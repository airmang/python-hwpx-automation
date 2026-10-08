# SPDX-License-Identifier: Apache-2.0
"""A Windows render that outlives its timeout must not leave its Hancom running.

Hancom runs as a COM server, not as a child of the PowerShell backend, so
ending the backend at the timeout left ``Hwp.exe -Automation`` running, often
with a dialog open, and every later timed-out render added one more (#151).
The backend now records its own Hancom (PID and start time) right after it
creates the COM object, and the oracle ends that process, and only while both
still match, when the run times out.

Nothing here starts or stops a process: ``subprocess.run`` is a fake.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from hwpx_automation.office.rendering.oracle import WindowsComOracle

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "src" / "hwpx_automation" / "office" / "rendering" / "_render_hwpx.ps1"
)
_STARTED = "2026-09-30T05:00:00.1234567Z"


def _backend(calls: list[list[str]], *, record: Any = None, finish: bool = False) -> Any:
    """Play the backend: optionally name its Hancom, then time out (or finish)."""

    def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(cmd)
        if "-Jobs" not in cmd:  # the follow-up that ends the recorded Hancom
            return subprocess.CompletedProcess(cmd, 0, b"", b"")
        if record is not None:
            Path(cmd[cmd.index("-PidPath") + 1]).write_text(json.dumps(record), encoding="utf-8-sig")
        if not finish:
            raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout") or 0)
        jobs = json.loads(Path(cmd[cmd.index("-Jobs") + 1]).read_text(encoding="utf-8"))
        result = [{"src": job["src"], "pdf": job.get("out") or job["pdf"], "opened": True,
                   "saved": False, "error": None, "registered": False} for job in jobs]
        Path(cmd[cmd.index("-ResultPath") + 1]).write_text(json.dumps(result), encoding="utf-8-sig")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    return run


@pytest.fixture
def source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(WindowsComOracle, "available", lambda self: True)
    path = tmp_path / "in.hwpx"
    path.write_bytes(b"x")
    return path


def test_a_timed_out_render_ends_its_own_hancom(
    monkeypatch: pytest.MonkeyPatch, source: Path, tmp_path: Path
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _backend(calls, record={"pid": 4242, "started": _STARTED}))

    assert WindowsComOracle().render_pdf(str(source), str(tmp_path / "out.pdf")) is None

    render, end = calls
    assert "-PidPath" in render
    script = end[end.index("-Command") + 1]
    assert "Get-Process -Id 4242" in script and "Stop-Process -Id 4242 -Force" in script
    assert "ProcessName -eq 'Hwp'" in script
    assert f"-eq '{_STARTED}'" in script


def test_a_timed_out_refresh_ends_its_own_hancom_too(
    monkeypatch: pytest.MonkeyPatch, source: Path
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _backend(calls, record={"pid": 77, "started": _STARTED}))

    assert WindowsComOracle().refresh_document(str(source)) is False
    assert len(calls) == 2 and "Stop-Process -Id 77 -Force" in calls[1][-1]
    assert source.read_bytes() == b"x"


@pytest.mark.parametrize(
    "record",
    [
        None,  # the backend never named its Hancom
        {"pid": 4242, "started": "x'; Remove-Item -Recurse C:\\; '"},
        {"pid": "4242; Stop-Process -Name explorer", "started": _STARTED},
        {"pid": 0, "started": _STARTED},
        {"started": _STARTED},
    ],
    ids=["no-record", "odd-start-time", "odd-pid", "zero-pid", "no-pid"],
)
def test_without_a_trustworthy_record_nothing_is_ended(
    monkeypatch: pytest.MonkeyPatch, source: Path, tmp_path: Path, record: Any
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _backend(calls, record=record))

    assert WindowsComOracle().render_pdf(str(source), str(tmp_path / "out.pdf")) is None
    assert len(calls) == 1


def test_a_render_that_finishes_ends_nothing(
    monkeypatch: pytest.MonkeyPatch, source: Path, tmp_path: Path
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        subprocess, "run", _backend(calls, record={"pid": 4242, "started": _STARTED}, finish=True)
    )

    assert WindowsComOracle().render_pdf(str(source), str(tmp_path / "out.pdf")) is None
    assert len(calls) == 1


def test_the_backend_names_only_an_automation_hancom_it_started() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    assert "[string] $PidPath" in script
    assert '-match "-Automation"' in script
    created = script.index('New-Object -ComObject "HWPFrame.HwpObject"')
    assert script.index("$before = @(Get-Process -Name Hwp") < created < script.index("Write-OwnHancom -Before")
