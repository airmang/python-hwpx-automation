# SPDX-License-Identifier: Apache-2.0
"""A byte-preserving write leaves no hidden copy of the document beside it.

``apply_table_ops``, ``apply_body_ops``, ``apply_evalplan_fill`` and ``apply_form_fill(plan=)``
keep the output's bytes from before in a sidecar (``.hwpx-mixed-form-recovery-…``) while they
write, so a write that fails half way can be put back. That copy is for the write only:

* a call that changed nothing (a refusal) leaves the folder as it was, however often it is made;
* a call that succeeded leaves the document and, where the rule says so, its ``.bak``;
* a write that failed and was put back leaves the folder as it was;
* the copy stays in one case -- the output no longer holds its bytes from before -- and then the
  result or the error names it;
* a copy that cannot be removed does not fail the call, and the result or the error names it.

Synthetic documents only.
"""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import mcp.types as mcp_types
import pytest
from test_mixed_form_mcp import _build_fixture, _plan

import hwpx_automation.mixed_form as mixed_form
import hwpx_automation.server as server
import hwpx_automation.workspace as workspace_module
from hwpx_automation.upstream import HwpxDocument

PREFIX = ".hwpx-mixed-form-recovery-"
FILL = [{"op": "fill_cell", "tableIndex": 0, "row": 1, "col": 1, "text": "v"}]
NO_SUCH_TABLE = [{"op": "fill_cell", "tableIndex": 9, "row": 0, "col": 0, "text": "v"}]
NO_SUCH_PARAGRAPH = [{"op": "set_paragraph_text", "index": 99, "text": "v"}]
NO_SUCH_TEXT = [{"op": "replace_text", "find": "OMEGA", "replace": "v"}]
REPLACE = [{"op": "replace_text", "find": "ALPHA", "replace": "DELTA"}]


def _document(path: Path) -> Path:
    with HwpxDocument.new() as document:
        document.sections[0].paragraphs[0].text = "ALPHA synthetic line one"
        document.add_paragraph("BETA synthetic line two")
        table = document.add_paragraph("GAMMA synthetic line three").add_table(2, 2)
        table.rows[0].cells[0].text = "label"
        document.save(path)
    return path


def _folder(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A folder holding the document a call edits and another document a call may name as output."""

    folder = tmp_path / "documents"
    folder.mkdir()
    document = _document(folder / "form.hwpx")
    other = _document(folder / "other.hwpx")
    (folder / "review.md").write_text("# synthetic review\n", encoding="utf-8")
    return folder, document, other


def _names(folder: Path) -> list[str]:
    return sorted(entry.name for entry in folder.iterdir())


def _contents(folder: Path) -> dict[str, bytes]:
    return {entry.name: entry.read_bytes() for entry in folder.iterdir()}


def _copies(folder: Path) -> list[Path]:
    return sorted(entry for entry in folder.iterdir() if entry.name.startswith(PREFIX))


def _run(call: Callable[[], Any]) -> tuple[Any, BaseException | None]:
    try:
        return call(), None
    except Exception as error:  # the refusal itself is what the test is about
        return None, error


def _mcp(name: str, arguments: dict[str, Any]) -> Any:
    request = SimpleNamespace(params=SimpleNamespace(name=name, arguments=arguments))
    return asyncio.run(server._strict_call_tool_handler(request))


def _note(result: dict[str, Any]) -> Any:
    return result["verificationReceipt"]["rollbackPreservation"].get("recoveryCopy")


# -- (1) a refusal changes nothing, in the document or in its folder ---------------------------------

_REFUSALS: dict[str, Callable[[Path, Path, Path], Any]] = {
    "apply_table_ops: no such table": lambda folder, document, other: server.apply_table_ops(
        str(document), NO_SUCH_TABLE
    ),
    "apply_table_ops(output=another document): no such table": (
        lambda folder, document, other: server.apply_table_ops(
            str(document), NO_SUCH_TABLE, output=str(other)
        )
    ),
    "apply_body_ops: no such paragraph": lambda folder, document, other: server.apply_body_ops(
        str(document), NO_SUCH_PARAGRAPH
    ),
    "apply_body_ops: text not found": lambda folder, document, other: server.apply_body_ops(
        str(document), NO_SUCH_TEXT
    ),
    "apply_body_ops(output=another document): text not found": (
        lambda folder, document, other: server.apply_body_ops(
            str(document), NO_SUCH_TEXT, output=str(other)
        )
    ),
    "apply_evalplan_fill: no such phase": lambda folder, document, other: server.apply_evalplan_fill(
        str(document), str(folder / "review.md"), phase="nope"
    ),
    "apply_evalplan_fill: no review file": lambda folder, document, other: server.apply_evalplan_fill(
        str(document), str(folder / "missing.md")
    ),
    "byte_preserving_patch: no such paragraph": (
        lambda folder, document, other: server.byte_preserving_patch(
            str(document),
            [{"sectionPath": "Contents/section0.xml", "paragraphIndex": 99, "text": "v"}],
        )
    ),
}


@pytest.mark.parametrize("label", list(_REFUSALS))
def test_a_refused_call_leaves_the_folder_as_it_was(tmp_path: Path, label: str) -> None:
    folder, document, other = _folder(tmp_path)
    before = _contents(folder)

    for _attempt in range(3):  # (3) nor does it pile up: three refusals, still nothing
        result, error = _run(lambda: _REFUSALS[label](folder, document, other))
        assert error is not None or result["ok"] is False, (label, result)
        assert _contents(folder) == before, (label, _names(folder))


@pytest.mark.parametrize("tool", ["apply_table_ops", "apply_body_ops"])
def test_a_refused_call_over_mcp_leaves_the_folder_as_it_was(tmp_path: Path, tool: str) -> None:
    folder, document, _other = _folder(tmp_path)
    before = _contents(folder)
    ops = NO_SUCH_TABLE if tool == "apply_table_ops" else NO_SUCH_PARAGRAPH

    for _attempt in range(3):
        refused = _mcp(tool, {"filename": str(document), "ops": ops})
        assert isinstance(refused, mcp_types.ErrorData), refused
        assert "recoveryCopy" not in (refused.data["error"].get("details") or {})
        assert _contents(folder) == before, _names(folder)


def test_a_refused_form_fill_plan_leaves_the_folder_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path  # the workspace root itself, as in test_mixed_form_mcp
    source, output = folder / "source.hwpx", folder / "output.hwpx"
    _build_fixture(source)
    _document(output)
    before = _contents(folder)

    def fail_before_publication(stage: str, index: int | None) -> None:
        if stage == "after_command" and index == 1:
            raise RuntimeError("injected failure before publication")

    monkeypatch.setattr(mixed_form, "_fault_injector_for_tests", fail_before_publication)
    for _attempt in range(3):
        result = server.apply_form_fill(plan=_plan(source, output))
        assert result["ok"] is False
        assert _contents(folder) == before, _names(folder)

    # A refusal the plan protocol makes on its own: one key, two different requests.
    monkeypatch.setattr(mixed_form, "_fault_injector_for_tests", None)
    request = _plan(source, output, key="refusal-leaves-no-copy")
    assert server.apply_form_fill(plan=request)["ok"] is True
    after_first = _contents(folder)
    conflict = copy.deepcopy(request)
    conflict["operations"][0]["value"] = "another value"
    for _attempt in range(3):
        result = server.apply_form_fill(plan=conflict)
        assert result["ok"] is False and result["error"]["code"] == "idempotency_conflict"
        assert _contents(folder) == after_first, _names(folder)


# -- (2) a call that succeeded leaves the document and its .bak, nothing else ------------------------

_SUCCESSES: dict[str, tuple[Callable[[Path, Path, Path], Any], list[str]]] = {
    "apply_table_ops in place": (
        lambda folder, document, other: server.apply_table_ops(str(document), FILL),
        [],
    ),
    "apply_table_ops(output=another document)": (
        lambda folder, document, other: server.apply_table_ops(str(document), FILL, output=str(other)),
        ["other.hwpx.bak"],
    ),
    "apply_table_ops(output=new name)": (
        lambda folder, document, other: server.apply_table_ops(
            str(document), FILL, output=str(folder / "new.hwpx")
        ),
        ["new.hwpx"],
    ),
    "apply_body_ops in place": (
        lambda folder, document, other: server.apply_body_ops(str(document), REPLACE),
        [],
    ),
    "apply_body_ops(output=another document)": (
        lambda folder, document, other: server.apply_body_ops(str(document), REPLACE, output=str(other)),
        ["other.hwpx.bak"],
    ),
}


@pytest.mark.parametrize("label", list(_SUCCESSES))
def test_a_successful_call_leaves_the_document_and_its_backup_only(tmp_path: Path, label: str) -> None:
    folder, document, other = _folder(tmp_path)
    before = _names(folder)
    call, added = _SUCCESSES[label]

    result = call(folder, document, other)

    assert result["ok"] is True
    assert _names(folder) == sorted(before + added)
    assert _note(result) is None


def test_a_successful_form_fill_plan_leaves_the_document_and_its_backup_only(tmp_path: Path) -> None:
    folder = tmp_path  # the workspace root itself, as in test_mixed_form_mcp
    source, output = folder / "source.hwpx", folder / "output.hwpx"
    _build_fixture(source)
    _document(output)
    before = _names(folder)

    result = server.apply_form_fill(plan=_plan(source, output))

    assert result["ok"] is True
    assert _copies(folder) == []
    assert set(_names(folder)) - set(before) <= {"output.hwpx.bak"}
    assert _note(result) is None


def test_a_successful_evalplan_fill_leaves_no_copy(tmp_path: Path) -> None:
    from test_evalplan_fill_mcp import BLANK, SYNTHETIC_MD

    if not BLANK.is_file():
        pytest.skip("python-hwpx evaluation-plan fixture is unavailable")
    folder = tmp_path / "documents"
    folder.mkdir()
    form = folder / "form.hwpx"
    form.write_bytes(BLANK.read_bytes())
    review = folder / "review.md"
    review.write_text(SYNTHETIC_MD, encoding="utf-8")
    before = _names(folder)

    result = server.apply_evalplan_fill(str(form), str(review))

    assert result["ok"] is True
    assert form.read_bytes() != BLANK.read_bytes()
    assert _names(folder) == before


# -- (4) a write that fails half way: the document is put back and the copy goes ---------------------


def _fail_publication_of(target: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The write of *target* itself fails (a full disk, a file another program holds open)."""

    original = workspace_module.WorkspaceResolver.atomic_publish_bytes

    def publish(self: Any, guard: Any, data: bytes, *, mode: int | None = None) -> Any:
        if guard.path == target:
            raise OSError("disk full")
        return original(self, guard, data, mode=mode)

    monkeypatch.setattr(workspace_module.WorkspaceResolver, "atomic_publish_bytes", publish)


@pytest.mark.parametrize("tool", ["apply_table_ops", "apply_body_ops"])
def test_a_write_that_cannot_replace_the_document_leaves_the_folder_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str
) -> None:
    folder, document, _other = _folder(tmp_path)
    before = _contents(folder)
    _fail_publication_of(document, monkeypatch)
    ops = FILL if tool == "apply_table_ops" else REPLACE

    with pytest.raises(OSError, match="disk full") as failed:
        getattr(server, tool)(str(document), ops)

    assert _contents(folder) == before, _names(folder)
    assert getattr(failed.value, "hwpx_recovery_copy", None) is None


@pytest.mark.parametrize("outcome", ["raises", "reports a failure"])
def test_a_write_that_fails_after_replacing_the_document_puts_it_back_and_drops_the_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    folder, document, _other = _folder(tmp_path)
    before = _contents(folder)
    replaced: list[bytes] = []

    def write_then_fail(*args: Any, **kwargs: Any) -> dict[str, Any]:
        publication = server._OPS.storage.atomic_publish_bytes(
            kwargs["output_guard"], b"half-written synthetic bytes"
        )
        kwargs["publication_sink"](publication)
        replaced.append(document.read_bytes())
        assert len(_copies(folder)) == 1  # while the write is under way the copy is there
        if outcome == "raises":
            raise RuntimeError("failed after the document was replaced")
        return {"ok": False, "changedParts": []}

    monkeypatch.setattr(server._OPS, "apply_table_ops", write_then_fail)

    result, error = _run(lambda: server.apply_table_ops(str(document), FILL))

    assert replaced == [b"half-written synthetic bytes"]
    assert _contents(folder) == before, _names(folder)
    if outcome == "raises":
        assert isinstance(error, RuntimeError)
        assert getattr(error, "hwpx_recovery_copy", None) is None
    else:
        assert result["ok"] is False and result["rolledBack"] is True
        assert _note(result) is None


def test_a_form_fill_plan_that_fails_after_replacing_the_output_puts_it_back_and_drops_the_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path  # the workspace root itself, as in test_mixed_form_mcp
    source, output = folder / "source.hwpx", folder / "output.hwpx"
    _build_fixture(source)
    _document(output)
    before = _contents(folder)
    original_diff = mixed_form._member_diff

    def reject_candidate(*args: Any, **kwargs: Any) -> dict[str, Any]:
        report = original_diff(*args, **kwargs)
        report["ok"] = False
        return report

    monkeypatch.setattr(mixed_form, "_member_diff", reject_candidate)

    result = server.apply_form_fill(plan=_plan(source, output))

    assert result["ok"] is False and result["rolledBack"] is True
    assert _contents(folder) == before, _names(folder)
    assert _note(result) is None


# -- the one case the copy stays: the output no longer holds its bytes from before -------------------


def _write_then_lose_the_document(document: Path, external: Path) -> Callable[..., dict[str, Any]]:
    """The tool writes the document, then another program replaces it: nothing can be put back."""

    def write(*args: Any, **kwargs: Any) -> dict[str, Any]:
        publication = server._OPS.storage.atomic_publish_bytes(
            kwargs["output_guard"], b"candidate synthetic bytes"
        )
        kwargs["publication_sink"](publication)
        external.write_bytes(b"another program's synthetic bytes")
        external.replace(document)
        return {"ok": True, "changedParts": []}

    return write


def test_a_copy_that_is_the_only_way_back_stays_and_the_result_names_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder, document, _other = _folder(tmp_path)
    original = document.read_bytes()
    monkeypatch.setattr(
        server._OPS, "apply_table_ops", _write_then_lose_the_document(document, tmp_path / "external.hwpx")
    )

    result = server.apply_table_ops(str(document), FILL)

    assert result["ok"] is False and result["rolledBack"] is False
    assert document.read_bytes() == b"another program's synthetic bytes"
    (copy_,) = _copies(folder)
    assert copy_.read_bytes() == original
    assert _note(result) == {"filename": copy_.name, "reason": "output-changed"}


def test_a_copy_that_is_the_only_way_back_is_named_in_the_mcp_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder, document, _other = _folder(tmp_path)
    original = document.read_bytes()
    monkeypatch.setattr(
        server._OPS, "apply_table_ops", _write_then_lose_the_document(document, tmp_path / "external.hwpx")
    )

    refused = _mcp("apply_table_ops", {"filename": str(document), "ops": FILL})

    assert isinstance(refused, mcp_types.ErrorData), refused
    (copy_,) = _copies(folder)
    assert copy_.read_bytes() == original
    assert refused.data["error"]["details"]["recoveryCopy"] == {
        "filename": copy_.name,
        "reason": "output-changed",
    }
    assert copy_.name in refused.message
    assert str(folder) not in refused.message + str(refused.data)


def test_a_copy_kept_after_a_raised_failure_is_named_on_the_error_and_over_mcp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder, document, _other = _folder(tmp_path)
    original = document.read_bytes()
    external = tmp_path / "external.hwpx"
    publish = workspace_module.WorkspaceResolver.atomic_publish_bytes
    raced: list[bool] = []

    def publish_then_lose_the_claim(self: Any, guard: Any, data: bytes, *, mode: int | None = None) -> Any:
        publication = publish(self, guard, data, mode=mode)
        if guard.path == document and not raced:
            raced.append(True)
            external.write_bytes(b"another program's synthetic bytes")
            external.replace(document)
            raise workspace_module.WorkspacePathError(
                "simulated claim loss", code="WORKSPACE_PATH_CHANGED", reason="output_target_changed"
            )
        return publication

    monkeypatch.setattr(
        workspace_module.WorkspaceResolver, "atomic_publish_bytes", publish_then_lose_the_claim
    )

    with pytest.raises(workspace_module.WorkspacePathError, match="simulated claim loss") as failed:
        server.apply_table_ops(str(document), FILL)

    (copy_,) = _copies(folder)
    assert copy_.read_bytes() == original
    assert failed.value.hwpx_recovery_copy == {"filename": copy_.name, "reason": "output-changed"}

    # The same failure through the MCP handler: the error names the copy.
    copy_.unlink()
    document.write_bytes(original)
    raced.clear()
    refused = _mcp("apply_table_ops", {"filename": str(document), "ops": FILL})
    assert isinstance(refused, mcp_types.ErrorData), refused
    (copy_,) = _copies(folder)
    assert refused.data["errorCode"] == "WORKSPACE_PATH_CHANGED"
    assert refused.data["error"]["details"] == {
        "reason": "output_target_changed",
        "recoveryCopy": {"filename": copy_.name, "reason": "output-changed"},
    }
    assert copy_.name in refused.message


# -- (5) a copy that cannot be removed (Windows: another program holds it open) ----------------------


def _refuse_to_remove_copies(monkeypatch: pytest.MonkeyPatch) -> None:
    original = workspace_module.WorkspaceResolver.remove_output

    def remove(self: Any, guard: Any) -> None:
        if guard.path.name.startswith(PREFIX):
            raise PermissionError("the file is open in another program")
        original(self, guard)

    monkeypatch.setattr(workspace_module.WorkspaceResolver, "remove_output", remove)


def test_a_copy_that_cannot_be_removed_does_not_change_a_refusal_and_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder, document, _other = _folder(tmp_path)
    original = document.read_bytes()
    expected = server.apply_table_ops(str(document), NO_SUCH_TABLE)
    assert _copies(folder) == []
    _refuse_to_remove_copies(monkeypatch)

    result = server.apply_table_ops(str(document), NO_SUCH_TABLE)

    assert result["ok"] is False and result.get("error") == expected.get("error")
    assert document.read_bytes() == original
    (copy_,) = _copies(folder)
    assert _note(result) == {"filename": copy_.name, "reason": "not-removed"}

    refused = _mcp("apply_table_ops", {"filename": str(document), "ops": NO_SUCH_TABLE})
    assert isinstance(refused, mcp_types.ErrorData), refused
    named = refused.data["error"]["details"]["recoveryCopy"]
    assert named["reason"] == "not-removed" and named["filename"] in refused.message
    assert named["filename"] in {entry.name for entry in _copies(folder)}


@pytest.mark.parametrize("tool", ["apply_table_ops", "apply_form_fill"])
def test_a_copy_that_cannot_be_removed_does_not_fail_a_successful_write_and_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str
) -> None:
    folder = tmp_path  # the workspace root itself, as in test_mixed_form_mcp
    source, output = folder / "source.hwpx", folder / "output.hwpx"
    _build_fixture(source) if tool == "apply_form_fill" else _document(source)
    _document(output)
    original = output.read_bytes()
    _refuse_to_remove_copies(monkeypatch)

    if tool == "apply_form_fill":
        result = server.apply_form_fill(plan=_plan(source, output))
    else:
        result = server.apply_table_ops(str(source), FILL, output=str(output))

    assert result["ok"] is True and result["rolledBack"] is False
    assert output.read_bytes() != original
    (copy_,) = _copies(folder)
    assert copy_.read_bytes() == original
    assert _note(result) == {"filename": copy_.name, "reason": "not-removed"}
