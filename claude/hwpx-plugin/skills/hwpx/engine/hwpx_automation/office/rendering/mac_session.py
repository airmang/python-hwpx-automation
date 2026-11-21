# SPDX-License-Identifier: Apache-2.0
"""Owned, cancellable Mac GUI adapter for the existing serialized worker."""
from __future__ import annotations

import math
import os
import plistlib
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .oracle import MacHancomOracle


def _gui_lock_path() -> Path:
    """The per-user lock serializing the shared Mac desktop across processes."""

    return Path(tempfile.gettempdir()) / f"hwpx-hancom-gui-{os.getuid()}.lock"


class HancomBusy(TimeoutError):
    """The shared Hancom desktop was not available within the requested wait."""

    worker_reason = "MAC_GUI_BUSY"


_DESKTOP_PID = os.getpid()
_DESKTOP_THREADS = threading.RLock()
_DESKTOP_LOCAL = threading.local()


def _desktop_thread_state() -> tuple[threading.RLock, threading.local]:
    # A fork must not inherit the parent's recursion depth or locked mutex.
    global _DESKTOP_PID, _DESKTOP_THREADS, _DESKTOP_LOCAL
    if _DESKTOP_PID != os.getpid():
        _DESKTOP_PID = os.getpid()
        _DESKTOP_THREADS = threading.RLock()
        _DESKTOP_LOCAL = threading.local()
    return _DESKTOP_THREADS, _DESKTOP_LOCAL


@contextmanager
def hancom_desktop_lock(wait: float = 0.0) -> Iterator[None]:
    """Serialize use of the shared Mac desktop, reentrantly in one thread.

    ``wait`` is a finite, non-negative number of seconds, including both
    thread and cross-process contention. Timeout raises :class:`HancomBusy`.
    The worker and CLI use this same per-user POSIX flock. On Windows this
    is explicitly a no-op: COM renders own separate Hancom processes.
    """
    if not math.isfinite(wait) or wait < 0:
        raise ValueError("wait must be finite and non-negative")
    if sys.platform == "win32":
        yield
        return
    import fcntl

    deadline = time.monotonic() + wait
    owner_pid = os.getpid()
    mutex, local = _desktop_thread_state()
    if not mutex.acquire(timeout=min(wait, threading.TIMEOUT_MAX)):
        raise HancomBusy(f"MAC_GUI_BUSY: Hancom desktop remained busy for {wait:g}s")
    try:
        if getattr(local, "held", False):
            yield
            return
        with _gui_lock_path().open("a") as handle:
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise HancomBusy(f"MAC_GUI_BUSY: Hancom desktop remained busy for {wait:g}s") from None
                    time.sleep(min(0.05, remaining))
            local.held = True
            try:
                yield
            finally:
                # A fork shares this open-file description. Explicit unlock
                # in its child would release the parent's still-owned flock.
                if os.getpid() == owner_pid:
                    local.held = False
                    fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        if os.getpid() == owner_pid:
            mutex.release()


class HancomRefusedError(RuntimeError):
    """Hancom refused to open the document; its alert was dismissed.

    Retrying the same bytes gets the same answer, so the worker reports it as
    ``HANCOM_REFUSED`` and does not mark it retryable.
    """

    worker_reason = "HANCOM_REFUSED"


class HancomHungError(RuntimeError):
    """The render produced no PDF while Hancom stayed busy and did not answer.

    Every later render fails the same way until the user restarts Hancom, so
    the worker reports it as ``HANCOM_HUNG`` and does not mark it retryable.
    Hancom is never killed here: it is the user's application.
    """

    worker_reason = "HANCOM_HUNG"


class _OwnedMacOracle(MacHancomOracle):
    def __init__(self, *, timeout: float) -> None:
        super().__init__(timeout=timeout, budget_seconds=timeout)
        self.guard = threading.Lock()
        self.process: subprocess.Popen[str] | None = None
        self.cancelled = threading.Event()

    def _run_render_script(self, cmd: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        with self.guard:
            if self.cancelled.is_set():
                raise OSError("render cancelled before launch")
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.process = process
        try:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise
            if self.cancelled.is_set():
                raise OSError("render cancelled")
            return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
        finally:
            with self.guard:
                self.process = None

    def _hancom_hung(self, deadline: float | None) -> str | None:
        # A cancelled render ended because we killed our own osascript; Hancom's
        # CPU says nothing about that, and the worker is waiting on this thread.
        if self.cancelled.is_set():
            return None
        return super()._hancom_hung(deadline)

    def abort(self) -> None:
        self.cancelled.set()
        with self.guard:
            if self.process is not None and self.process.poll() is None:
                self.process.kill()  # our osascript only; never the user's app


class MacHancomSession:
    real_hancom = True
    backend = "mac-gui-worker"

    def __init__(self, *, timeout_seconds: float = 120) -> None:
        self.oracle = _OwnedMacOracle(timeout=timeout_seconds)
        app = self.oracle._app_path()
        if app is None or not self.oracle.available():
            raise RuntimeError("MAC_HANCOM_UNAVAILABLE")
        with (Path(app) / "Contents/Info.plist").open("rb") as handle:
            info = plistlib.load(handle)
        version, build = info.get("CFBundleShortVersionString"), info.get("CFBundleVersion")
        if not version or not build:
            raise RuntimeError("MAC_HANCOM_BUILD_UNKNOWN")
        self.hancom_build = f"{version} ({build})"

    def render_pdf(self, source: Path, target: Path) -> Path | None:
        from hwpx_automation.workflow.render_queue import inspect_hwpx
        inspect_hwpx(source.read_bytes(), filename=source.name, principal_id="local-worker")
        # The Mac desktop is shared even across worker roots/processes. flock
        # lives until the rendering/owned cleanup exits, including watchdogs.
        with hancom_desktop_lock(wait=0):
            result = self.oracle.render_pdf(str(source), str(target))
            if not result and self.oracle.last_refusal is not None:
                raise HancomRefusedError(self.oracle.last_refusal)
            if not result and getattr(self.oracle, "last_hang", None) is not None:
                raise HancomHungError(self.oracle.last_hang)
            return Path(result) if result else None

    def abort(self) -> None:
        self.oracle.abort()

    def close(self) -> None:
        self.abort()
