# SPDX-License-Identifier: Apache-2.0
"""Owned, cancellable Mac GUI adapter for the existing serialized worker."""
from __future__ import annotations

import os
import plistlib
import subprocess
import tempfile
import threading
from pathlib import Path

from .oracle import MacHancomOracle


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
        import fcntl
        lock = Path(tempfile.gettempdir()) / f"hwpx-hancom-gui-{os.getuid()}.lock"
        with lock.open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("MAC_GUI_BUSY") from None
            try:
                result = self.oracle.render_pdf(str(source), str(target))
                return Path(result) if result else None
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def abort(self) -> None:
        self.oracle.abort()

    def close(self) -> None:
        self.abort()
