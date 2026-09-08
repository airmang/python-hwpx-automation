from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

from hwpx_automation.office.rendering.mac_session import _OwnedMacOracle
from hwpx_automation.office.rendering.oracle import MacHancomOracle


def test_abort_only_terminates_owned_subprocess():
    oracle = _OwnedMacOracle(timeout=10)
    errors = []
    def render():
        try:
            oracle._run_render_script([sys.executable, '-c', 'import time; time.sleep(30)'], 10)
        except OSError as exc:
            errors.append(exc)
    thread = threading.Thread(target=render)
    thread.start()
    deadline = time.monotonic() + 2
    while oracle.process is None and time.monotonic() < deadline:
        time.sleep(.01)
    assert oracle.process is not None
    owned = oracle.process
    oracle.abort()
    thread.join(2)
    assert not thread.is_alive() and owned.poll() is not None and errors
    assert oracle.process is None


def test_failure_does_not_overwrite_caller_target_or_staged_name(tmp_path, monkeypatch):
    source = tmp_path / 'original.hwpx'
    target = tmp_path / 'output.pdf'
    collision = tmp_path / 'output.hwpx'
    source.write_bytes(b'original')
    target.write_bytes(b'prior-verified-pdf')
    collision.write_bytes(b'user-document')
    oracle = MacHancomOracle()
    monkeypatch.setattr(oracle, 'available', lambda: True)
    def failed(cmd, timeout):
        assert Path(cmd[2]) != collision
        Path(cmd[3]).write_bytes(b'%PDF-stream-without-trailer')
        return subprocess.CompletedProcess(cmd, 0, 'ERR: export failed', '')
    monkeypatch.setattr(oracle, '_run_render_script', failed)
    assert oracle.render_pdf(str(source), str(target)) is None
    assert target.read_bytes() == b'prior-verified-pdf'
    assert collision.read_bytes() == b'user-document'
    assert source.read_bytes() == b'original'
    assert not list(tmp_path.glob('hwpx-render-*'))
