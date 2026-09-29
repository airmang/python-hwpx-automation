# SPDX-License-Identifier: Apache-2.0
"""A document Hancom refuses to open must not leave its alert on the desktop.

Hancom answers some documents with a one-button alert ("파일이 손상되었습니다",
"파일을 읽거나 저장하는데 오류가 있습니다"). Left up, it blocks every later
render on that Mac, from any process. The Mac render script compares the
alert-like windows before and after opening the document, dismisses only an
alert that appeared after its own open, and reports ``HANCOM_REFUSED`` at
once instead of waiting for the timeout.

Nothing here talks to Hancom: the Python side runs against fake script output,
and the script's decision logic runs as plain AppleScript handlers over
hand-written window snapshots.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from hwpx_automation.office.rendering import mac_session, oracle
from hwpx_automation.office.rendering.worker import SerializedHancomWorker, WorkerJob

SCRIPT = Path(oracle.__file__).with_name("_render_hwpx_mac.applescript")
REFUSAL = "파일이 손상되었습니다."
TITLE = "한컴오피스 한글"
# What real Hancom asks during PDF export for a table with a broken cellSpan.
REPAIR = f"{TITLE}\n문서에 손상된 표가 있습니다.\n손상된 표를 복원할까요?"


# --------------------------------------------------------------------------- #
# MacHancomOracle: the script's refusal line becomes last_refusal
# --------------------------------------------------------------------------- #
def _scripted_oracle(monkeypatch: pytest.MonkeyPatch, stdout: str) -> oracle.MacHancomOracle:
    backend = oracle.MacHancomOracle()
    monkeypatch.setattr(backend, "available", lambda: True)

    def _run(cmd: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout, "")

    monkeypatch.setattr(backend, "_run_render_script", _run)
    return backend


def test_refusal_line_is_reported_as_last_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "in.hwpx"
    source.write_bytes(b"x")
    backend = _scripted_oracle(monkeypatch, f"ERR: HANCOM_REFUSED: {REFUSAL}\n")

    assert backend.render_pdf(str(source), str(tmp_path / "out.pdf")) is None
    assert backend.last_refusal == REFUSAL
    assert not list(tmp_path.glob("hwpx-render-*"))


def test_other_failures_and_the_next_render_clear_last_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "in.hwpx"
    source.write_bytes(b"x")
    backend = _scripted_oracle(monkeypatch, f"ERR: HANCOM_REFUSED: {REFUSAL}")
    backend.render_pdf(str(source), str(tmp_path / "out.pdf"))

    def _timeout(cmd: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, "ERR: document window did not open: x", "")

    monkeypatch.setattr(backend, "_run_render_script", _timeout)
    assert backend.render_pdf(str(source), str(tmp_path / "out.pdf")) is None
    assert backend.last_refusal is None


# --------------------------------------------------------------------------- #
# render-pdf: a refusal is its own error code, exit 1
# --------------------------------------------------------------------------- #
def test_render_pdf_reports_hancom_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hwpx import HwpxDocument

    from hwpx_automation.office.rendering import cli as render_cli

    source = tmp_path / "in.hwpx"
    HwpxDocument.new().save_to_path(str(source))

    class _Refusing(oracle.MacHancomOracle):
        def available(self) -> bool:
            return True

        def render_pdf(self, hwpx_path: str, out_pdf: str | None = None) -> str | None:
            self.last_refusal = REFUSAL
            return None

    monkeypatch.delenv("HWPX_ORACLE_STRUCTURAL_ONLY", raising=False)
    monkeypatch.setattr(oracle, "resolve_oracle", lambda **kwargs: _Refusing(**kwargs))
    monkeypatch.setattr(mac_session, "_gui_lock_path", lambda: tmp_path / "gui.lock")

    stdout, stderr = io.StringIO(), io.StringIO()
    code = render_cli.main(
        ["render-pdf", str(source), str(tmp_path / "out.pdf"), "--json"],
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 1
    payload = json.loads(stdout.getvalue().splitlines()[-1])
    assert payload["error"] == "hancom-refused"
    assert payload["backend"] == "mac"
    assert REFUSAL in payload["message"]


# --------------------------------------------------------------------------- #
# Render worker: a refusal is HANCOM_REFUSED and not retryable
# --------------------------------------------------------------------------- #
def test_mac_session_raises_a_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hwpx import HwpxDocument

    source = tmp_path / "in.hwpx"
    HwpxDocument.new().save_to_path(str(source))

    class _Oracle:
        last_refusal: str | None = None

        def render_pdf(self, hwpx_path: str, out_pdf: str | None = None) -> str | None:
            self.last_refusal = REFUSAL
            return None

    session = object.__new__(mac_session.MacHancomSession)
    session.oracle = _Oracle()  # type: ignore[assignment]
    monkeypatch.setattr(mac_session, "_gui_lock_path", lambda: tmp_path / "gui.lock")

    with pytest.raises(mac_session.HancomRefusedError) as caught:
        session.render_pdf(source, tmp_path / "out.pdf")
    assert REFUSAL in str(caught.value)
    assert caught.value.worker_reason == "HANCOM_REFUSED"


class _RefusingSession:
    real_hancom = True
    hancom_build = "Hancom test build"
    backend = "mac-gui-worker"

    def render_pdf(self, source: Path, target: Path) -> Path | None:
        raise mac_session.HancomRefusedError(REFUSAL)

    def abort(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_worker_reports_hancom_refused_without_retry(tmp_path: Path) -> None:
    source = tmp_path / "in.hwpx"
    source.write_bytes(b"refused-by-hancom")
    digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    worker = SerializedHancomWorker(
        tmp_path / "worker", session_factory=_RefusingSession, worker_version="test/1"
    )

    result = worker.render(WorkerJob("job-refused", source, digest, 72))

    assert result.status == "unverified"
    assert result.terminal_reason == "HANCOM_REFUSED"
    assert result.retryable is False


# --------------------------------------------------------------------------- #
# The script's decision logic, run as AppleScript over fake window snapshots
# --------------------------------------------------------------------------- #
needs_osascript = pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("osacompile") is None,
    reason="AppleScript handlers run only on macOS",
)


def _alert(sig: str, text: str, buttons: tuple[str, ...] = ("확인",)) -> str:
    names = ", ".join(f'"{name}"' for name in buttons)
    text = text.replace("\n", '" & linefeed & "')  # the title, then each static text
    return f'{{sig:"{sig}", txt:"{text}", btns:{{{names}}}}}'


@pytest.fixture(scope="module")
def compiled_script(tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("applescript") / "render.scpt"
    subprocess.run(["osacompile", "-o", str(target), str(SCRIPT)], check=True, timeout=60)
    return target


def _call(compiled: Path, expression: str, tmp_path: Path) -> str:
    driver = tmp_path / "driver.applescript"
    driver.write_text(
        f'set s to load script POSIX file "{compiled}"\n'
        f"tell s to return {expression}\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        ["osascript", str(driver)], capture_output=True, text=True, timeout=60, check=False
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


@needs_osascript
@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        # a refusal alert that was not there before the open is ours
        ("{}", [_alert("AXDialog|a", REFUSAL)], "1"),
        ("{}", [_alert("AXDialog|a", "파일을 읽거나 저장하는데 오류가 있습니다.")], "1"),
        # what Hancom raises after the broken-table repair prompt is cancelled
        ("{}", [_alert("AXDialog|c", f"{TITLE}\nPDF 파일을 저장하는데 오류가 있습니다.")], "1"),
        # the repair prompt itself is not a one-button refusal alert
        ("{}", [_alert("AXDialog|r", REPAIR, ("취소", "복원"))], "0"),
        # the same alert already up before the open belongs to someone else
        ('{"AXDialog|a"}', [_alert("AXDialog|a", REFUSAL)], "0"),
        # our own PDF save panel, or any alert without the refusal wording
        ("{}", [_alert("AXDialog|PDF로 저장하기", "PDF로 저장하기", ("저장", "취소"))], "0"),
        ("{}", [_alert("AXDialog|b", "문서를 저장하시겠습니까?")], "0"),
        # the wording alone is not enough: dismissing needs a lone 확인
        ("{}", [_alert("AXDialog|a", REFUSAL, ("확인", "취소"))], "0"),
        # two identical new alerts: which one is ours cannot be proved
        ("{}", [_alert("AXDialog|a", REFUSAL), _alert("AXDialog|a", REFUSAL)], "2"),
    ],
)
def test_only_an_alert_raised_after_the_open_counts(
    compiled_script: Path, tmp_path: Path, before: str, after: list[str], expected: str
) -> None:
    entries = "{" + ", ".join(after) + "}"
    got = _call(compiled_script, f"count of newRefusalAlerts({before}, {entries})", tmp_path)

    assert got == expected


@needs_osascript
def test_refusal_text_is_reported_on_one_line(compiled_script: Path, tmp_path: Path) -> None:
    got = _call(
        compiled_script,
        'refusalLine("" & linefeed & "파일이 손상되었습니다." & linefeed & "  다시 시도하세요. ")',
        tmp_path,
    )

    assert got == "파일이 손상되었습니다. / 다시 시도하세요."


# --------------------------------------------------------------------------- #
# The flow: snapshot before the open, watch while opening and exporting
# --------------------------------------------------------------------------- #
def test_flow_snapshots_before_opening_and_watches_both_waits() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    run = source[source.index("on run argv") : source.index("end run")]

    snapshot = run.index("set beforeSigs to sigsOf(alertSnapshot())")
    opening = run.index('do shell script "open -a "')
    assert snapshot < opening
    assert "waitForDocumentOrRefusal(inputBase, beforeSigs, timeoutSecs)" in run
    assert "waitForFileOrRefusal(outPdf, beforeSigs, timeoutSecs)" in run
    assert "HANCOM_REFUSED" in source


def test_dismissal_clicks_only_a_unique_match_and_only_its_ok_button() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    dismiss = source[source.index("on dismissAlert(") : source.index("end dismissAlert")]

    assert "click button dismissButton of target" in dismiss
    assert dismiss.count("click button") == 1
    assert "if target is not missing value then return false" in dismiss


def test_alert_entries_read_each_text_and_button_on_its_own() -> None:
    # On a real Hancom refusal alert (AXDialog "한컴오피스 한글", one static text,
    # one 확인 button) the bulk forms "value of static texts of w" and "name of
    # buttons of w" fail as a whole, so the wording and the button went unread and
    # no alert ever counted as a refusal (#143). Read element by element.
    source = SCRIPT.read_text(encoding="utf-8")
    entry = source[source.index("on alertEntryOf(") : source.index("end alertEntryOf")]

    assert "value of static texts of w" not in entry
    assert "name of buttons of w" not in entry
    assert "repeat with t in (static texts of w)" in entry
    assert "(value of t) as string" in entry
    assert "repeat with b in (buttons of w)" in entry
    assert "(name of b) as string" in entry


def test_python_side_parses_the_script_refusal_line() -> None:
    marker = "ERR: HANCOM_REFUSED: "
    assert marker in SCRIPT.read_text(encoding="utf-8")
    assert marker.strip() in Path(oracle.__file__).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# The broken-table repair prompt: answered 취소, never 복원, then a refusal
# --------------------------------------------------------------------------- #
@needs_osascript
@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        # a new repair prompt is ours, whatever order its buttons come in
        ("{}", [_alert("AXDialog|r", REPAIR, ("취소", "복원"))], "1"),
        ("{}", [_alert("AXDialog|r", REPAIR, ("복원", "취소"))], "1"),
        # the same prompt already up before the open belongs to someone else
        ('{"AXDialog|r"}', [_alert("AXDialog|r", REPAIR, ("취소", "복원"))], "0"),
        # the buttons must be exactly 취소 and 복원
        ("{}", [_alert("AXDialog|r", REPAIR, ("취소",))], "0"),
        ("{}", [_alert("AXDialog|r", REPAIR, ("확인", "복원"))], "0"),
        ("{}", [_alert("AXDialog|r", REPAIR, ("취소", "복원", "확인"))], "0"),
        # and the wording must ask to repair
        ("{}", [_alert("AXDialog|s", "문서를 저장하시겠습니까?", ("취소", "복원"))], "0"),
        # a refusal alert is not a repair prompt
        ("{}", [_alert("AXDialog|a", REFUSAL)], "0"),
        # two identical new prompts: which one is ours cannot be proved
        (
            "{}",
            [
                _alert("AXDialog|r", REPAIR, ("취소", "복원")),
                _alert("AXDialog|r", REPAIR, ("취소", "복원")),
            ],
            "2",
        ),
    ],
)
def test_only_a_new_repair_prompt_counts(
    compiled_script: Path, tmp_path: Path, before: str, after: list[str], expected: str
) -> None:
    entries = "{" + ", ".join(after) + "}"
    got = _call(compiled_script, f"count of newRepairPrompts({before}, {entries})", tmp_path)

    assert got == expected


def test_repair_prompt_is_cancelled_and_never_restored() -> None:
    # 복원 would render a table Hancom rewrote, not the document given, so the
    # only button ever clicked on the prompt is 취소.
    source = SCRIPT.read_text(encoding="utf-8")
    cancel = source[source.index("on cancelRepairPrompt(") : source.index("end cancelRepairPrompt")]

    assert 'property repairCancelButton : "취소"' in source
    assert "click button repairCancelButton of target" in cancel
    assert cancel.count("click") == 1
    assert "if target is not missing value then return false" in cancel
    for line in source.splitlines():
        if "click" in line and not line.strip().startswith("--"):
            assert "복원" not in line and "repairAcceptButton" not in line, line
    # Return presses a dialog's default button, which on the prompt may be 복원:
    # the retried Return is held back while a repair prompt of ours is up.
    run = source[source.index("on run argv") : source.index("end run")]
    first = run.index("key code 36 -- Return")
    retry = run.index("key code 36", first + 1)
    guard = run.index("newRepairPrompts(beforeSigs, alertSnapshot())) is 0", first)
    assert guard < retry


def test_repair_prompt_ends_the_render_as_refused_and_clears_what_follows() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    result = source[source.index("on refusalResult(") : source.index("end refusalResult")]

    cancelled = result.index("cancelRepairPrompt(sig of item 1 of prompts)")
    follow_up = result.index("dismissFollowUpAlerts(beforeSigs, followUpSecs)")
    assert cancelled < follow_up
    assert '"ERR: HANCOM_REFUSED: " & refusalLine(txt of item 1 of prompts)' in result
    assert "(prompt left up: more than one matched)" in result
    # the follow-up alert is a one-button refusal alert, dismissed only when
    # unique and new, for a bounded while
    assert '"PDF 파일을 저장하는데 오류"' in source
    follow = source[
        source.index("on dismissFollowUpAlerts(") : source.index("end dismissFollowUpAlerts")
    ]
    assert "repeat (secs * 2) times" in follow
    assert "newRefusalAlerts(beforeSigs, alertSnapshot())" in follow
    assert "if (count of found) is 1 then dismissAlert(sig of item 1 of found)" in follow
    assert "property followUpSecs : 5" in source

