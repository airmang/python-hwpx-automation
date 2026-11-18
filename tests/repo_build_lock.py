# SPDX-License-Identifier: Apache-2.0
"""One ``python -m build`` of the repository root at a time, across pytest-xdist workers.

A build in the root writes ``build/`` and ``src/*.egg-info``, and the wheel-contents test removes
``build/`` before it builds. Two workers doing that at once broke one another's build (the full run
failed one of them, a different one each time). The lock is a file created exclusively in the
temporary directory, named after the checkout; a lock left by a killed run is taken over after
``STALE_SECONDS``.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STALE_SECONDS = 900.0
_LOCK = Path(tempfile.gettempdir()) / (
    "hwpx-automation-build-" + hashlib.sha256(str(ROOT).encode("utf-8")).hexdigest()[:12] + ".lock"
)


@contextmanager
def repo_build_lock(timeout: float = 1800.0) -> Iterator[None]:
    deadline = time.monotonic() + timeout
    while True:
        try:
            handle = os.open(_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - _LOCK.stat().st_mtime > STALE_SECONDS:
                    _LOCK.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() > deadline:
                raise TimeoutError(f"repository build lock still held: {_LOCK}") from None
            time.sleep(0.5)
            continue
        os.write(handle, str(os.getpid()).encode("ascii"))
        os.close(handle)
        break
    try:
        yield
    finally:
        _LOCK.unlink(missing_ok=True)
