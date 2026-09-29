# SPDX-License-Identifier: Apache-2.0
"""A Hancom that hangs must be named as hung, not as one more failed render.

When Hancom's main thread is stuck (no windows, one core at 100%), the Mac
render waits out its timeout and every later render does the same. After a
render that ended without a PDF and without a refusal, the process is sampled
with ``ps``: a Hancom that stays busy across every sample is reported as
``hancom-hung`` by ``render-pdf`` and ``HANCOM_HUNG`` by the render worker, with
a message to restart Hancom. Hancom itself is never signalled.

Nothing here reads the real process table: ``pgrep``/``ps`` are fakes.
"""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import time
from pathlib import Path

import pytest

from hwpx_automation.office.rendering import mac_session, oracle
from hwpx_automation.office.rendering.worker import SerializedHancomWorker, WorkerJob

PID = 4242


class _ProcessTable:
    """Answers ``pgrep``/``ps`` like macOS would, from a script of CPU readings."""

    def __init__(self, pids: str, cpu: list[str]) -> None:
        self.pids = pids
        self.cpu = list(cpu)
        self.commands: list[list[str]] = []

    def __call__(self, cmd: list[str]) -> str:
        self.commands.append(cmd)
        if cmd[0] == "pgrep":
            return self.pids
        if cmd[0] == "ps":
            return self.cpu.pop(0) if self.cpu else ""
        raise AssertionError(f"unexpected command {cmd}")


BUSY = ("4242\n", [" 99.8\n", "100.0\n", " 99.1\n", " 98.7\n"])
IDLE = ("4242\n", ["  0.3\n"])
MISSING = ("", [])


@pytest.fixture
def table(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> _ProcessTable:
    pids, cpu = request.param
    fake = _ProcessTable(pids, cpu)
    monkeypatch.delenv("HWPX_ORACLE_STRUCTURAL_ONLY", raising=False)
    monkeypatch.setattr(oracle, "_probe", fake)
    monkeypatch.setattr(oracle, "_HUNG_SAMPLE_INTERVAL", 0.0)
    return fake


# --------------------------------------------------------------------------- #
# The probe
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("table", [BUSY], indirect=True)
def test_hancom_busy_in_every_sample_is_hung(table: _ProcessTable) -> None:
    naps: list[float] = []

    hang = oracle._busy_mac_hancom(sleep=naps.append)

    assert hang is not None
    assert f"pid {PID}" in hang
    assert len(naps) == oracle._HUNG_SAMPLES - 1
    # only read, never signalled
    assert {cmd[0] for cmd in table.commands} == {"pgrep", "ps"}
    assert table.commands[0] == ["pgrep", "-f", "Hancom Office HWP.app/Contents/MacOS"]
    assert table.commands[1] == ["ps", "-o", "%cpu=", "-p", str(PID)]


@pytest.mark.parametrize(
    "table",
    [
        IDLE,
        MISSING,
        # busy for a moment, then idle: Hancom is working, not stuck
        ("4242\n", ["99.0", "97.0", "12.0"]),
        # the process went away while being sampled
        ("4242\n", ["99.0", ""]),
    ],
    indirect=True,
)
def test_idle_briefly_busy_or_missing_hancom_is_not_hung(table: _ProcessTable) -> None:
    assert oracle._busy_mac_hancom(sleep=lambda _: None) is None


def test_structural_only_never_looks_for_hancom(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HWPX_ORACLE_STRUCTURAL_ONLY", "1")

    def _unexpected(cmd: list[str]) -> str:
        raise AssertionError(cmd)

    monkeypatch.setattr(oracle, "_probe", _unexpected)

    assert oracle._busy_mac_hancom(sleep=lambda _: None) is None


# --------------------------------------------------------------------------- #
# MacHancomOracle: only a render with no PDF and no refusal is probed
# --------------------------------------------------------------------------- #
def _scripted_oracle(monkeypatch: pytest.MonkeyPatch, stdout: str) -> oracle.MacHancomOracle:
    backend = oracle.MacHancomOracle()
    monkeypatch.setattr(backend, "available", lambda: True)

    def _run(cmd: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout, "")

    monkeypatch.setattr(backend, "_run_render_script", _run)
    return backend


@pytest.mark.parametrize("table", [BUSY], indirect=True)
def test_a_failed_render_with_hancom_busy_sets_last_hang(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, table: _ProcessTable
) -> None:
    source = tmp_path / "in.hwpx"
    source.write_bytes(b"x")
    backend = _scripted_oracle(monkeypatch, "ERR: document window did not open: x\n")

    assert backend.render_pdf(str(source), str(tmp_path / "out.pdf")) is None
    assert backend.last_hang is not None and f"pid {PID}" in backend.last_hang
    assert backend.last_refusal is None


@pytest.mark.parametrize("table", [BUSY], indirect=True)
def test_a_refusal_is_not_probed_and_the_next_render_clears_last_hang(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, table: _ProcessTable
) -> None:
    source = tmp_path / "in.hwpx"
    source.write_bytes(b"x")
    backend = _scripted_oracle(monkeypatch, "ERR: HANCOM_REFUSED: 파일이 손상되었습니다.\n")
    backend.last_hang = "left over"

    assert backend.render_pdf(str(source), str(tmp_path / "out.pdf")) is None
    assert backend.last_refusal == "파일이 손상되었습니다."
    assert backend.last_hang is None
    assert table.commands == []


def test_a_cancelled_owned_render_is_not_probed(monkeypatch: pytest.MonkeyPatch) -> None:
    def _unexpected(cmd: list[str]) -> str:
        raise AssertionError(cmd)

    monkeypatch.delenv("HWPX_ORACLE_STRUCTURAL_ONLY", raising=False)
    monkeypatch.setattr(oracle, "_probe", _unexpected)
    owned = mac_session._OwnedMacOracle(timeout=10)
    owned.abort()

    assert owned._hancom_hung(None) is None


# --------------------------------------------------------------------------- #
# The probe stays inside the caller's budget
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("table", [BUSY], indirect=True)
def test_the_probe_never_samples_past_the_deadline(
    table: _ProcessTable, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(oracle, "_HUNG_SAMPLE_INTERVAL", 1.0)
    naps: list[float] = []

    hang = oracle._busy_mac_hancom(sleep=naps.append, deadline=time.monotonic() + 0.5)

    assert hang is None  # not proven hung in the time left
    assert naps == []


def test_a_budget_bound_render_leaves_room_for_the_probe() -> None:
    room = oracle._hang_probe_seconds()
    now = time.monotonic()

    # no budget, or a budget with room to spare: the render keeps its wait
    assert oracle._leave_room_for_hang_probe(360.0, None) == 360.0
    assert oracle._leave_room_for_hang_probe(360.0, now + 1000.0) == 360.0
    # the budget bounds the wait: the probe's room comes out of it
    shortened = oracle._leave_room_for_hang_probe(120.0, now + 120.0)
    assert shortened <= 120.0 - room + 0.5
    assert shortened > room
    # a budget too small to share stays whole with the render
    assert oracle._leave_room_for_hang_probe(10.0, now + 10.0) == 10.0


@pytest.mark.parametrize("table", [BUSY], indirect=True)
def test_a_budget_bound_render_still_reports_a_hang_within_the_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, table: _ProcessTable
) -> None:
    source = tmp_path / "in.hwpx"
    source.write_bytes(b"x")
    backend = oracle.MacHancomOracle(timeout=60.0, budget_seconds=60.0)
    monkeypatch.setattr(backend, "available", lambda: True)
    waits: list[float] = []

    def _cut_off(cmd: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        waits.append(timeout)
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(backend, "_run_render_script", _cut_off)
    monkeypatch.setattr(backend, "_close_owned_document", lambda script, name: None)

    assert backend.render_pdf(str(source), str(tmp_path / "out.pdf")) is None
    assert waits and waits[0] <= 60.0 - oracle._hang_probe_seconds() + 0.5
    assert backend.last_hang is not None


# --------------------------------------------------------------------------- #
# render-pdf: hancom-hung when busy, render-failed otherwise
# --------------------------------------------------------------------------- #
def _render_pdf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[int, dict[str, object]]:
    from hwpx import HwpxDocument

    from hwpx_automation.office.rendering import cli as render_cli

    source = tmp_path / "in.hwpx"
    HwpxDocument.new().save_to_path(str(source))

    class _Stuck(oracle.MacHancomOracle):
        def available(self) -> bool:
            return True

        def _run_render_script(
            self, cmd: list[str], timeout: float
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(cmd, 0, "ERR: document window did not open: x\n", "")

    monkeypatch.setattr(oracle, "resolve_oracle", lambda **kwargs: _Stuck(**kwargs))
    monkeypatch.setattr(mac_session, "_gui_lock_path", lambda: tmp_path / "gui.lock")
    stdout, stderr = io.StringIO(), io.StringIO()
    code = render_cli.main(
        ["render-pdf", str(source), str(tmp_path / "out.pdf"), "--json"],
        stdout=stdout,
        stderr=stderr,
    )
    return code, json.loads(stdout.getvalue().splitlines()[-1])


@pytest.mark.parametrize("table", [BUSY], indirect=True)
def test_render_pdf_reports_hancom_hung(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, table: _ProcessTable
) -> None:
    code, payload = _render_pdf(tmp_path, monkeypatch)

    assert code == 1
    assert payload["error"] == "hancom-hung"
    assert payload["backend"] == "mac"
    assert "restart Hancom" in str(payload["message"])
    assert {cmd[0] for cmd in table.commands} == {"pgrep", "ps"}


@pytest.mark.parametrize("table", [IDLE, MISSING], indirect=True)
def test_render_pdf_without_a_busy_hancom_stays_render_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, table: _ProcessTable
) -> None:
    code, payload = _render_pdf(tmp_path, monkeypatch)

    assert code == 1
    assert payload["error"] == "render-failed"


# --------------------------------------------------------------------------- #
# Render worker: HANCOM_HUNG, not retryable
# --------------------------------------------------------------------------- #
def test_mac_session_raises_a_hang(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hwpx import HwpxDocument

    source = tmp_path / "in.hwpx"
    HwpxDocument.new().save_to_path(str(source))

    class _Oracle:
        last_refusal: str | None = None
        last_hang: str | None = None

        def render_pdf(self, hwpx_path: str, out_pdf: str | None = None) -> str | None:
            self.last_hang = "Hancom Office HWP (pid 4242) stayed at 99% CPU"
            return None

    session = object.__new__(mac_session.MacHancomSession)
    session.oracle = _Oracle()  # type: ignore[assignment]
    monkeypatch.setattr(mac_session, "_gui_lock_path", lambda: tmp_path / "gui.lock")

    with pytest.raises(mac_session.HancomHungError) as caught:
        session.render_pdf(source, tmp_path / "out.pdf")
    assert "pid 4242" in str(caught.value)
    assert caught.value.worker_reason == "HANCOM_HUNG"


class _HungSession:
    real_hancom = True
    hancom_build = "Hancom test build"
    backend = "mac-gui-worker"

    def render_pdf(self, source: Path, target: Path) -> Path | None:
        raise mac_session.HancomHungError("stayed at 99% CPU")

    def abort(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_worker_reports_hancom_hung_without_retry(tmp_path: Path) -> None:
    source = tmp_path / "in.hwpx"
    source.write_bytes(b"hancom-is-stuck")
    digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    worker = SerializedHancomWorker(
        tmp_path / "worker", session_factory=_HungSession, worker_version="test/1"
    )

    result = worker.render(WorkerJob("job-hung", source, digest, 72))

    assert result.status == "unverified"
    assert result.terminal_reason == "HANCOM_HUNG"
    assert result.retryable is False
