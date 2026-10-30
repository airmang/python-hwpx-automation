# SPDX-License-Identifier: Apache-2.0
"""Refresh refuses only its own alerts; all observations here are fake."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from hwpx_automation.office.rendering import oracle
from test_mac_render_refusal import _alert, _call

SCRIPT = Path(oracle.__file__).with_name("_refresh_hwpx_mac.applescript")
RENDER_SCRIPT = Path(oracle.__file__).with_name("_render_hwpx_mac.applescript")
REFUSAL = "파일이 손상되었습니다. OK is not a success marker here."
NEEDS_APPLESCRIPT = pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("osacompile") is None,
    reason="pure AppleScript handlers require the macOS language runtime",
)


def test_refresh_reports_refusal_and_clears_it_on_the_next_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "input.hwpx"
    source.write_bytes(b"original")
    backend = oracle.MacHancomOracle()
    monkeypatch.setattr(backend, "available", lambda: True)
    answers = [f"ERR: HANCOM_REFUSED: {REFUSAL}", "ERR: window did not open"]

    def run(*args, **kwargs):
        before = source.stat().st_mtime_ns
        os.utime(source, ns=(before, before + 1_000_000))
        return subprocess.CompletedProcess(args[0], 0, answers.pop(0), "")

    monkeypatch.setattr(oracle.subprocess, "run", run)
    assert backend.refresh_document(str(source)) is False
    assert backend.last_refusal == REFUSAL
    assert backend.refresh_document(str(source)) is False
    assert backend.last_refusal is None
    assert source.read_bytes() == b"original"


@pytest.mark.parametrize(("status", "answer", "expected"), [(0, "OK\n", True), (1, "OK", False), (0, "ERR: not OK", False)])
def test_refresh_requires_a_successful_exact_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int, answer: str, expected: bool
) -> None:
    source = tmp_path / "input.hwpx"
    source.write_bytes(b"original")
    backend = oracle.MacHancomOracle()
    monkeypatch.setattr(backend, "available", lambda: True)

    def run(*args, **kwargs):
        before = source.stat().st_mtime_ns
        os.utime(source, ns=(before, before + 1_000_000))
        return subprocess.CompletedProcess(args[0], status, answer, "")

    monkeypatch.setattr(oracle.subprocess, "run", run)
    assert backend.refresh_document(str(source)) is expected


def test_refresh_snapshots_before_open_and_preserves_the_canonical_guard_handlers() -> None:
    source = oracle._mac_script_source(SCRIPT.name)
    run = source[source.index("on run argv") : source.index("end run")]
    assert run.index("set beforeSigs to sigsOf(alertSnapshot())") < run.index('do shell script "open -a "')
    assert "waitForDocumentOrRefusal(inputBase, beforeSigs, timeoutSecs)" in run
    assert "refusalResult(beforeSigs)" in run
    guard = SCRIPT.with_name("_hancom_alerts_mac.applescript").read_text(encoding="utf-8")
    for name in (SCRIPT.name, RENDER_SCRIPT.name):
        assembled = oracle._mac_script_source(name)
        assert guard in assembled
        assert assembled.count("on alertSnapshot()") == 1


def test_assembled_script_survives_until_owned_cleanup_then_is_removed() -> None:
    with pytest.raises(RuntimeError, match="timeout cleanup"):
        with oracle._mac_script_file(SCRIPT.name) as script:
            assert script.read_text(encoding="utf-8") == oracle._mac_script_source(SCRIPT.name)
            folder = script.parent
            raise RuntimeError("timeout cleanup")
    assert not folder.exists()


@NEEDS_APPLESCRIPT
@pytest.mark.parametrize(
    ("before", "entries", "clicked"),
    [
        ("{}", [_alert("AXDialog|ours", "파일이 손상되었습니다.")], 1),
        ('{"AXDialog|ours"}', [_alert("AXDialog|ours", "파일이 손상되었습니다.")], 0),
        ("{}", [_alert("AXDialog|a", "파일이 손상되었습니다."), _alert("AXDialog|b", "파일이 손상되었습니다.")], 0),
        ("{}", [_alert("AXDialog|a", "파일이 손상되었습니다.", ("확인", "취소"))], 0),
    ],
)
def test_only_a_unique_new_refusal_is_dismissed(
    tmp_path: Path, before: str, entries: list[str], clicked: int
) -> None:
    source = oracle._mac_script_source(SCRIPT.name)
    start = source.index("on alertSnapshot()")
    end = source.index("end alertSnapshot", start) + len("end alertSnapshot")
    source = source[:start] + 'on alertSnapshot()\nreturn fakeEntries\nend alertSnapshot' + source[end:]
    start = source.index("on dismissAlert(theSig)")
    end = source.index("end dismissAlert", start) + len("end dismissAlert")
    source = source[:start] + 'on dismissAlert(theSig)\nset end of dismissedSigs to theSig\nreturn true\nend dismissAlert' + source[end:]
    source = "property fakeEntries : {" + ", ".join(entries) + "}\nproperty dismissedSigs : {}\non dismissedCount()\nreturn count of dismissedSigs\nend dismissedCount\n" + source
    script = tmp_path / "fake.applescript"
    script.write_text(source, encoding="utf-8")
    compiled = tmp_path / "fake.scpt"
    result = subprocess.run(["osacompile", "-o", str(compiled), str(script)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    answer = _call(compiled, f'refusalResult({before}) & "|" & dismissedCount()', tmp_path)
    assert answer.endswith(f"|{clicked}")
    if clicked:
        assert answer.startswith("ERR: HANCOM_REFUSED:")
