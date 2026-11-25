# SPDX-License-Identifier: Apache-2.0
"""Public desktop serialization uses the worker's lock without touching Hancom.

The same per-user lock serializes the Mac GUI desktop (POSIX flock) and, on
Windows, every COM run (``msvcrt`` byte lock): a COM client can attach to the
automation Hancom another one started and close it with ``Quit()``. Nothing
here starts Hancom: PowerShell is a fake and only the lock is exercised.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from hwpx_automation.office.rendering import HancomBusy, hancom_desktop_lock, mac_session, oracle, worker
from hwpx_automation.office.rendering.cli import _shared_desktop
from hwpx_automation.office.rendering.oracle import WindowsComOracle

# The suite points every test at its own lock file; keep the real resolver
# (and the real subprocess.run, which some tests below replace) for the tests
# that check them.
_REAL_LOCK_PATH = oracle._gui_lock_path
_RUN = subprocess.run
_BUSY_CODE = "HANCOM_DESKTOP_BUSY" if sys.platform == "win32" else "MAC_GUI_BUSY"


@pytest.fixture
def lock_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "gui.lock"
    monkeypatch.setattr(oracle, "_gui_lock_path", lambda: path)
    return path


def _other_process(path: Path) -> str:
    source = (
        "import sys\nfrom pathlib import Path\n"
        "from hwpx_automation.office.rendering import HancomBusy, hancom_desktop_lock, oracle\n"
        "oracle._gui_lock_path = lambda: Path(sys.argv[1])\n"
        "try:\n    with hancom_desktop_lock(wait=0.03):\n        print('acquired')\n"
        "except HancomBusy:\n    print('busy')\n"
    )
    result = _RUN(
        [sys.executable, "-c", source, str(path)], check=False, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _holding_process(path: Path, seconds: float) -> subprocess.Popen[str]:
    """Start a process that holds the lock for ``seconds``; returns once it holds it."""

    source = (
        "import sys, time\nfrom pathlib import Path\n"
        "from hwpx_automation.office.rendering import hancom_desktop_lock, oracle\n"
        "oracle._gui_lock_path = lambda: Path(sys.argv[1])\n"
        "with hancom_desktop_lock(wait=10):\n"
        "    print('held', flush=True)\n"
        "    time.sleep(float(sys.argv[2]))\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", source, str(path), str(seconds)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    assert process.stdout is not None
    line = process.stdout.readline().strip()
    if line != "held":
        process.kill()
        _, stderr = process.communicate(timeout=10)
        raise AssertionError(f"holder did not take the lock: {line!r} {stderr}")
    return process


class _ThreadHolder:
    """Hold the lock in another thread of this process until released."""

    def __init__(self) -> None:
        self.held = threading.Event()
        self.release = threading.Event()
        self.thread = threading.Thread(target=self._hold, daemon=True)

    def _hold(self) -> None:
        with hancom_desktop_lock(wait=5):
            self.held.set()
            self.release.wait(30)

    def __enter__(self) -> None:
        self.thread.start()
        assert self.held.wait(10)

    def __exit__(self, *_exc: object) -> None:
        self.release.set()
        self.thread.join(10)
        assert not self.thread.is_alive()


# --- the lock itself, on every platform --------------------------------------


def test_process_contention_reentrancy_and_release(lock_path: Path) -> None:
    with hancom_desktop_lock(wait=0):
        with hancom_desktop_lock(wait=0):
            with _shared_desktop("mac", 0):
                with _shared_desktop("windows", 0):
                    assert _other_process(lock_path) == "busy"
        assert _other_process(lock_path) == "busy"
    assert _other_process(lock_path) == "acquired"


def test_other_threads_time_out_and_an_exception_releases_the_lock(lock_path: Path) -> None:
    caught: list[Exception] = []

    def contend() -> None:
        try:
            with hancom_desktop_lock(wait=0.01):
                pass
        except HancomBusy as exc:
            caught.append(exc)

    with pytest.raises(RuntimeError, match="render failed"):
        with hancom_desktop_lock(wait=0):
            thread = threading.Thread(target=contend)
            thread.start()
            thread.join(timeout=2)
            assert not thread.is_alive()
            assert len(caught) == 1
            raise RuntimeError("render failed")
    assert _other_process(lock_path) == "acquired"


def test_a_second_process_waits_its_turn_then_enters(lock_path: Path) -> None:
    holder = _holding_process(lock_path, 0.8)
    try:
        started = time.monotonic()
        with hancom_desktop_lock(wait=20):
            waited = time.monotonic() - started
            assert holder.wait(timeout=20) == 0
    finally:
        if holder.poll() is None:
            holder.kill()
        holder.communicate(timeout=10)
    assert 0.4 <= waited < 20


def test_a_second_process_that_waits_too_little_gets_busy(lock_path: Path) -> None:
    holder = _holding_process(lock_path, 3)
    try:
        started = time.monotonic()
        with pytest.raises(HancomBusy) as caught:
            with hancom_desktop_lock(wait=0.3):
                pass
        waited = time.monotonic() - started
    finally:
        holder.kill()
        holder.communicate(timeout=10)
    assert 0.25 <= waited < 2.5
    assert str(caught.value).startswith(f"{_BUSY_CODE}: ")
    assert caught.value.worker_reason == _BUSY_CODE
    assert isinstance(caught.value, TimeoutError)


def test_a_waiting_thread_enters_once_the_holder_leaves(lock_path: Path) -> None:
    holder = _ThreadHolder()
    with holder:
        timer = threading.Timer(0.5, holder.release.set)
        timer.start()
        started = time.monotonic()
        with hancom_desktop_lock(wait=10):
            waited = time.monotonic() - started
        timer.cancel()
    assert 0.3 <= waited < 10


def test_a_child_started_under_the_lock_does_not_keep_it(lock_path: Path) -> None:
    # PowerShell (and the Hancom it starts) outlive nothing of the lock: the
    # handle is not inherited, so the lock ends with the holder's context.
    with hancom_desktop_lock(wait=0):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert _other_process(lock_path) == "acquired"
    finally:
        child.kill()
        child.wait(timeout=10)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires a real POSIX fork")
@pytest.mark.parametrize("child_reenters", [False, True])
def test_forked_child_unwinding_the_inherited_context_does_not_unlock_parent(
    lock_path: Path, child_reenters: bool
) -> None:
    child = False
    child_completed = False
    try:
        with hancom_desktop_lock(wait=0):
            pid = os.fork()
            if pid == 0:
                child = True
                if child_reenters:
                    with pytest.raises(HancomBusy):
                        with hancom_desktop_lock(wait=0):
                            pass
            else:
                _, status = os.waitpid(pid, 0)
                assert os.waitstatus_to_exitcode(status) == 0
                assert _other_process(lock_path) == "busy"
        child_completed = True
    finally:
        # The child must unwind the inherited with before exiting, but must
        # never continue into pytest's own test/fixture cleanup machinery.
        if child:
            os._exit(0 if child_completed else 1)
    assert _other_process(lock_path) == "acquired"


@pytest.mark.parametrize("wait", [-1.0, float("nan"), float("inf"), -float("inf")])
def test_wait_must_be_finite_and_non_negative(wait: float) -> None:
    with pytest.raises(ValueError, match="finite and non-negative"):
        with hancom_desktop_lock(wait=wait):
            pass


@pytest.mark.parametrize(
    ("platform", "code"), [("darwin", "MAC_GUI_BUSY"), ("win32", "HANCOM_DESKTOP_BUSY")]
)
def test_busy_names_its_platform_and_keeps_the_mac_code(
    monkeypatch: pytest.MonkeyPatch, platform: str, code: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    error = oracle._busy(2.5)
    assert isinstance(error, HancomBusy) and isinstance(error, TimeoutError)
    assert str(error) == f"{code}: Hancom desktop remained busy for 2.5s"
    assert error.worker_reason == code
    assert HancomBusy.worker_reason == "MAC_GUI_BUSY"


def test_mac_session_keeps_publishing_the_lock() -> None:
    # The lock moved next to the COM backend that takes it; its published
    # names (and the path helper hwpx-school calls) stay importable here.
    assert mac_session.HancomBusy is HancomBusy is oracle.HancomBusy
    assert mac_session.hancom_desktop_lock is hancom_desktop_lock is oracle.hancom_desktop_lock
    assert mac_session._gui_lock_path is _REAL_LOCK_PATH


# --- where the lock file lives -------------------------------------------------


def _no_uid() -> int:
    raise AssertionError("Windows must not resolve a POSIX uid")


def test_windows_lock_is_per_user_under_local_app_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(os, "getuid", _no_uid, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("TEMP", str(tmp_path / "elsewhere"))
    monkeypatch.setenv("USERNAME", "합성:사용자")

    assert _REAL_LOCK_PATH() == tmp_path / "hwpx-automation" / "hwpx-hancom-gui-합성_사용자.lock"

    monkeypatch.setenv("USERNAME", " . ")
    assert _REAL_LOCK_PATH().name == "hwpx-hancom-gui-user.lock"


def test_windows_lock_falls_back_to_the_user_temporary_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(os, "getuid", _no_uid, raising=False)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setenv("USERNAME", "synthetic")
    for missing in (None, "", "relative", str(tmp_path / "absent")):
        if missing is None:
            monkeypatch.delenv("LOCALAPPDATA", raising=False)
        else:
            monkeypatch.setenv("LOCALAPPDATA", missing)
        assert _REAL_LOCK_PATH() == tmp_path / "hwpx-hancom-gui-synthetic.lock"


@pytest.mark.skipif(sys.platform == "win32", reason="the POSIX lock path")
def test_posix_lock_path_is_unchanged() -> None:
    assert _REAL_LOCK_PATH() == Path(tempfile.gettempdir()) / f"hwpx-hancom-gui-{os.getuid()}.lock"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows creates the lock folder")
def test_windows_creates_the_lock_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "new" / "hwpx-hancom-gui-synthetic.lock"
    monkeypatch.setattr(oracle, "_gui_lock_path", lambda: path)
    with hancom_desktop_lock(wait=0):
        assert path.is_file()
        assert _other_process(path) == "busy"
    assert _other_process(path) == "acquired"


# --- Windows COM runs take their turn ------------------------------------------


_PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


@pytest.fixture
def com(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(WindowsComOracle, "available", lambda self: True)


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "in" / "doc.hwpx"
    path.parent.mkdir()
    path.write_bytes(b"PK synthetic")
    return path


def test_a_com_render_holds_the_desktop_while_powershell_runs(
    com: None, lock_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    probes: list[str] = []

    def run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        probes.append(_other_process(lock_path))
        jobs = json.loads(Path(cmd[cmd.index("-Jobs") + 1]).read_text(encoding="utf-8"))
        Path(jobs[0]["pdf"]).write_bytes(_PDF)
        result = {"src": jobs[0]["src"], "pdf": jobs[0]["pdf"], "saved": True}
        Path(cmd[cmd.index("-ResultPath") + 1]).write_text(json.dumps(result), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", run)
    source, out = _source(tmp_path), tmp_path / "out.pdf"

    assert WindowsComOracle(timeout=30).render_pdf(str(source), str(out)) == str(out)
    assert probes == ["busy"]
    assert _other_process(lock_path) == "acquired"


def test_a_com_run_reentered_by_its_holder_does_not_wait(
    com: None, lock_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[float] = []

    def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(kwargs["timeout"])
        return subprocess.CompletedProcess(cmd, 1, b"", b"")

    monkeypatch.setattr(subprocess, "run", run)
    with hancom_desktop_lock(wait=0):  # as render-pdf and the worker hold it
        started = time.monotonic()
        assert WindowsComOracle(timeout=30).render_pdf(str(_source(tmp_path)), str(tmp_path / "o.pdf")) is None
        assert time.monotonic() - started < 5
    assert len(calls) == 1 and 0 < calls[0] <= 90


def test_a_com_run_that_never_gets_the_desktop_starts_no_powershell(
    com: None, lock_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("PowerShell started while another run held the desktop")

    monkeypatch.setattr(subprocess, "run", run)
    source, out = _source(tmp_path), tmp_path / "out.pdf"
    oracle = WindowsComOracle(timeout=30, budget_seconds=0.4)
    with _ThreadHolder():
        started = time.monotonic()
        assert oracle.render_pdf(str(source), str(out)) is None
        assert oracle.refresh_document(str(source)) is False
        entries = oracle.open_check_many([str(source)])
        waited = time.monotonic() - started
    assert waited < 10
    assert not out.exists()
    assert entries[0]["opened"] is None and entries[0]["status"] == "unverified"
    assert str(entries[0]["error"]).startswith("HANCOM_DESKTOP_BUSY:")


def test_an_open_check_holds_the_desktop_while_powershell_runs(
    com: None, lock_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    probes: list[str] = []

    def run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        probes.append(_other_process(lock_path))
        return subprocess.CompletedProcess(cmd, 1, b"", b"")

    monkeypatch.setattr(subprocess, "run", run)
    WindowsComOracle(timeout=30).open_check_many([str(_source(tmp_path))])
    assert probes == ["busy"]


# --- the render worker's Windows session -----------------------------------------


class _FakePopen:
    probes: ClassVar[list[str]] = []
    lock: ClassVar[Path | None] = None

    def __init__(self, command: list[str], **_kwargs: Any) -> None:
        assert self.lock is not None
        type(self).probes.append(_other_process(self.lock))
        jobs = json.loads(Path(command[command.index("-Jobs") + 1]).read_text(encoding="utf-8"))
        Path(jobs[0]["pdf"]).write_bytes(_PDF)

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def poll(self) -> int:
        return 0


@pytest.fixture
def fake_powershell(lock_path: Path, monkeypatch: pytest.MonkeyPatch) -> type[_FakePopen]:
    monkeypatch.setattr(_FakePopen, "probes", [])
    monkeypatch.setattr(_FakePopen, "lock", lock_path)
    monkeypatch.setattr(
        worker,
        "subprocess",
        SimpleNamespace(Popen=_FakePopen, DEVNULL=subprocess.DEVNULL, TimeoutExpired=subprocess.TimeoutExpired),
    )
    return _FakePopen


def test_the_windows_worker_session_holds_the_desktop(
    fake_powershell: type[_FakePopen], tmp_path: Path
) -> None:
    session = worker.PowerShellHancomSession(hancom_build="synthetic", powershell="powershell")
    source, target = _source(tmp_path), tmp_path / "work" / "out.pdf"

    assert session.render_pdf(source, target) == target
    assert fake_powershell.probes == ["busy"]


def test_a_busy_desktop_fails_the_windows_worker_job_without_powershell(
    fake_powershell: type[_FakePopen], tmp_path: Path
) -> None:
    session = worker.PowerShellHancomSession(hancom_build="synthetic", powershell="powershell")
    runner = worker.SerializedHancomWorker(
        tmp_path / "root", session_factory=lambda: session, worker_version="test", timeout_seconds=20
    )
    source = _source(tmp_path)
    job = worker.WorkerJob("job-1", source, worker.sha256_file(source))
    with _ThreadHolder():
        result = runner.render(job)
    assert result.status != "succeeded"
    assert result.terminal_reason == _BUSY_CODE
    assert fake_powershell.probes == []
