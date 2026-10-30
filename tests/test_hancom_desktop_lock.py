# SPDX-License-Identifier: Apache-2.0
"""Public desktop serialization uses the worker's lock without touching Hancom."""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import pytest

from hwpx_automation.office.rendering import HancomBusy, hancom_desktop_lock, mac_session
from hwpx_automation.office.rendering.cli import _shared_desktop


@pytest.fixture
def lock_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "gui.lock"
    monkeypatch.setattr(mac_session, "_gui_lock_path", lambda: path)
    return path


def _other_process(path: Path) -> str:
    source = (
        "import sys\nfrom pathlib import Path\n"
        "from hwpx_automation.office.rendering import HancomBusy, hancom_desktop_lock, mac_session\n"
        "mac_session._gui_lock_path = lambda: Path(sys.argv[1])\n"
        "try:\n    with hancom_desktop_lock(wait=0.03):\n        print('acquired')\n"
        "except HancomBusy:\n    print('busy')\n"
    )
    result = subprocess.run([sys.executable, "-c", source, str(path)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows COM uses isolated processes, so this lock is a no-op")
def test_process_contention_reentrancy_and_release(lock_path: Path) -> None:
    with hancom_desktop_lock(wait=0):
        with hancom_desktop_lock(wait=0):
            with _shared_desktop("mac", 0):
                assert _other_process(lock_path) == "busy"
        assert _other_process(lock_path) == "busy"
    assert _other_process(lock_path) == "acquired"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX desktop serialization")
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


@pytest.mark.parametrize("wait", [-1.0, float("nan"), float("inf"), -float("inf")])
def test_wait_must_be_finite_and_non_negative(wait: float) -> None:
    with pytest.raises(ValueError, match="finite and non-negative"):
        with hancom_desktop_lock(wait=wait):
            pass


def test_windows_policy_is_noop_and_never_queries_a_posix_uid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    def forbidden() -> Path:
        raise AssertionError("Windows must not resolve the POSIX lock path")

    monkeypatch.setattr(mac_session, "_gui_lock_path", forbidden)
    with hancom_desktop_lock(wait=0):
        with hancom_desktop_lock(wait=0):
            pass
