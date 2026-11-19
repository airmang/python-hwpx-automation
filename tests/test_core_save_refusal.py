# SPDX-License-Identifier: Apache-2.0
"""python-hwpx 7.0 save refusals reach the caller as DOCUMENT_SAVE_FAILED with the engine's code."""

from __future__ import annotations

import asyncio
import os
import stat
import warnings
import zipfile
from pathlib import Path
from types import SimpleNamespace

import mcp.types as mcp_types
import pytest
from hwpx import HwpxDocument

from hwpx_automation import server
from hwpx_automation.errors import CORE_SAVE_REFUSALS, core_save_refusal_payload
from hwpx_automation.hwpx_ops import HwpxOperationError, HwpxOps
from hwpx_automation.runtime import _classified_error_payload


def _unanchored_memo_error() -> BaseException:
    doc = HwpxDocument.new()
    doc.add_paragraph("본문")
    doc.notes.add_memo("걸지 않은 메모")
    with pytest.raises(Exception) as refused:
        doc.to_bytes()
    return refused.value


def test_an_unanchored_memo_save_is_a_document_save_failure() -> None:
    error = _unanchored_memo_error()
    assert getattr(error, "code", None) == "note-memo-unanchored"
    payload = _classified_error_payload(error)
    assert payload["code"] == "DOCUMENT_SAVE_FAILED"
    assert payload["details"] == {"coreCode": "note-memo-unanchored"}
    assert payload["message"] == CORE_SAVE_REFUSALS["note-memo-unanchored"]


def test_other_errors_are_not_save_refusals() -> None:
    assert core_save_refusal_payload(ValueError("x")) is None
    error = ValueError("x")
    error.code = "style-not-found"  # type: ignore[attr-defined]
    assert core_save_refusal_payload(error) is None


def test_ops_save_failure_carries_the_core_code(tmp_path: Path) -> None:
    target = tmp_path / "out.hwpx"
    doc = HwpxDocument.new()
    doc.add_paragraph("본문")
    doc.notes.add_memo("걸지 않은 메모")
    ops = HwpxOps(base_directory=tmp_path)
    with pytest.raises(HwpxOperationError) as refused:
        ops._services.save._save_document(doc, target)
    assert refused.value.code == "DOCUMENT_SAVE_FAILED"
    assert (refused.value.details or {}).get("coreCode") == "note-memo-unanchored"


# -- an archive python-hwpx will not write back: one entry name twice (python-hwpx #794, #799) ---------


def _archive_with_one_name_twice(path: Path) -> Path:
    document = HwpxDocument.new()
    document.add_paragraph("본문 가나다")
    document.add_table(2, 2).cell(0, 0).text = "이름"
    clean = path.with_name("clean.hwpx")
    document.save(clean)
    with zipfile.ZipFile(clean) as source, zipfile.ZipFile(path, "w") as target:
        for info in source.infolist():
            data = source.read(info)
            target.writestr(info, data)
            if info.filename == "Contents/section0.xml":
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)  # zipfile: duplicate name
                    # By name, so the second entry has a record of its own: the same ZipInfo written
                    # twice makes two directory entries of one record, which Python 3.10 and 3.11
                    # read as a broken ZIP.
                    target.writestr(info.filename, data)
    return path


def _mcp_error(name: str, arguments: dict) -> dict:
    request = SimpleNamespace(params=SimpleNamespace(name=name, arguments=arguments))
    result = asyncio.run(server._strict_call_tool_handler(request))
    assert isinstance(result, mcp_types.ErrorData), result
    return result.data


_TOOLS_THAT_WRITE = {
    "apply_table_ops dry run": ("apply_table_ops", lambda source, out: {"filename": source, "ops": [], "dry_run": True}),
    "apply_table_ops": ("apply_table_ops", lambda source, out: {"filename": source, "ops": [], "output": out}),
    "apply_body_ops": ("apply_body_ops", lambda source, out: {"filename": source, "ops": [], "output": out}),
    "search_and_replace": (
        "search_and_replace",
        lambda source, out: {"filename": source, "find_text": "가나다", "replace_text": "라마바"},
    ),
    "set_table_cell_text": (
        "set_table_cell_text",
        lambda source, out: {"filename": source, "table_index": 0, "row": 0, "col": 0, "text": "X"},
    ),
    "byte_preserving_patch": (
        "byte_preserving_patch",
        lambda source, out: {
            "filename": source,
            "output": out,
            "patches": [{"sectionPath": "Contents/section0.xml", "paragraphIndex": 0, "text": "X"}],
        },
    ),
}


@pytest.mark.parametrize("label", list(_TOOLS_THAT_WRITE))
def test_a_repeated_entry_name_reaches_mcp_as_a_save_refusal(tmp_path: Path, label: str) -> None:
    """Not TOOL_EXECUTION_FAILED (internal) and not INVALID_ARGUMENT: the arguments are fine and the
    server did not break -- the file cannot be written back, and the client is told so."""

    source = _archive_with_one_name_twice(tmp_path / "twice.hwpx")
    before = source.read_bytes()
    name, arguments = _TOOLS_THAT_WRITE[label]

    data = _mcp_error(name, arguments(str(source), str(tmp_path / "out.hwpx")))

    assert data["errorCode"] == "DOCUMENT_SAVE_FAILED"
    assert data["error"]["category"] == "document"
    assert data["error"]["details"] == {"coreCode": "save-duplicate-entry-names"}
    assert data["error"]["message"] == CORE_SAVE_REFUSALS["save-duplicate-entry-names"]
    assert source.read_bytes() == before and not (tmp_path / "out.hwpx").exists()


@pytest.mark.parametrize("dry_run", [True, False])
def test_an_edit_plan_step_refused_as_a_save_keeps_its_code_and_step(tmp_path: Path, dry_run: bool) -> None:
    source = _archive_with_one_name_twice(tmp_path / "twice.hwpx")
    plan = {
        "schemaVersion": "hwpx.edit-plan/v1",
        "source": str(source),
        "output": str(tmp_path / "out.hwpx"),
        "steps": [
            {
                "id": "s1",
                "op": "paragraph_patch",
                "args": {"patches": [{"sectionPath": "Contents/section0.xml", "paragraphIndex": 0, "text": "X"}]},
            }
        ],
    }

    data = _mcp_error("run_edit_plan", {"plan": plan, "dry_run": dry_run})

    assert data["errorCode"] == "DOCUMENT_SAVE_FAILED"
    assert data["error"]["details"] == {"coreCode": "save-duplicate-entry-names", "failedStepId": "s1"}
    assert not (tmp_path / "out.hwpx").exists()


@pytest.mark.parametrize("tool", ["apply_table_ops", "apply_body_ops"])
@pytest.mark.parametrize("read_only_folder", [False, True])
def test_a_refused_dry_run_writes_nothing_beside_the_document(
    tmp_path: Path, tool: str, read_only_folder: bool
) -> None:
    """A dry run publishes nothing, so a refusal has nothing to recover: no recovery sidecar is left in
    the document's folder, and a folder that cannot be written to still gets the real refusal (it
    used to be PERMISSION_DENIED, from trying to write the sidecar)."""

    if read_only_folder and (os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0)):
        pytest.skip("a folder's read-only bit does not stop writes here")
    folder = tmp_path / "documents"
    folder.mkdir()
    source = _archive_with_one_name_twice(folder / "twice.hwpx")
    before = sorted(entry.name for entry in folder.iterdir())
    if read_only_folder:
        folder.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        data = _mcp_error(tool, {"filename": str(source), "ops": [], "dry_run": True})
    finally:
        folder.chmod(stat.S_IRWXU)

    assert data["errorCode"] == "DOCUMENT_SAVE_FAILED"
    assert data["error"]["details"] == {"coreCode": "save-duplicate-entry-names"}
    assert sorted(entry.name for entry in folder.iterdir()) == before
