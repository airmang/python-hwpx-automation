"""v2 tool surface end-to-end tests."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from hwpx_automation.core.document import open_doc, save_doc
from hwpx_automation.fastmcp_adapter import snapshot_runtime_tools


PHASE1_TOOLS = {
    "create_document",
    "get_document_info",
    "get_document_text",
    "get_document_outline",
    "get_paragraph_text",
    "get_paragraphs_text",
    "find_text",
    "search_and_replace",
    "batch_replace",
    "repair_hwpx",
}

TABLE_NAVIGATION_TOOLS = {
    "get_table_map",
    "find_cell_by_label",
    "fill_by_path",
}

FORMAT_EDIT_TOOLS = {
    "set_paragraph_format",
    "set_page_setup",
    "set_header_footer",
    "set_page_number",
    "set_list_format",
}

FORM_FIELD_TOOLS = {
    "list_form_fields",
    "fill_form_field",
}

ADVANCED_TOOLS = {
    "package_parts",
    "package_get_xml",
    "package_get_text",
    "object_find_by_tag",
    "object_find_by_attr",
    "validate_structure",
    "lint_text_conventions",
}


@pytest.fixture()
def server_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("HWPX_MCP_ADVANCED", raising=False)
    import hwpx_automation.server as server

    return importlib.reload(server)


def test_default_toolset_exposes_phase1_and_hides_advanced(server_module) -> None:
    names = set(snapshot_runtime_tools(server_module.mcp))

    assert PHASE1_TOOLS.issubset(names)
    assert TABLE_NAVIGATION_TOOLS.issubset(names)
    assert FORMAT_EDIT_TOOLS.issubset(names)
    assert FORM_FIELD_TOOLS.issubset(names)
    assert names.isdisjoint(ADVANCED_TOOLS)


def test_advanced_toolset_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HWPX_MCP_ADVANCED", "1")
    import hwpx_automation.server as server

    try:
        reloaded = importlib.reload(server)
        names = set(snapshot_runtime_tools(reloaded.mcp))

        assert ADVANCED_TOOLS.issubset(names)
    finally:
        # 고급 도구를 켠 서버 모듈을 남기지 않는다(같은 일꾼의 뒤 시험이 기본 도구 목록을 본다).
        monkeypatch.undo()
        importlib.reload(server)


def test_year_rollover_batch_replace_flow(server_module, tmp_path: Path) -> None:
    target = tmp_path / "school_plan.hwpx"
    server_module.create_document(str(target))
    server_module.add_paragraph(str(target), "2025. 3. 1. ~ 2026. 2. 28.")

    result = server_module.batch_replace(
        str(target),
        [
            {"find": "2026", "replace": "2027"},
            {"find": "2025", "replace": "2026"},
        ],
    )
    text_result = server_module.get_document_text(str(target))

    assert result["total_replaced"] == 2
    assert "2026. 3. 1. ~ 2027. 2. 28." in text_result["text"]


def test_document_revision_changes_and_stale_write_is_rejected(server_module, tmp_path: Path) -> None:
    target = tmp_path / "revision.hwpx"
    server_module.create_document(str(target))
    first_info = server_module.get_document_info(str(target))
    first_revision = first_info["document_revision"]

    external_doc = open_doc(str(target))
    external_doc.add_paragraph("외부 변경")
    save_doc(external_doc, str(target))

    second_info = server_module.get_document_info(str(target))
    assert second_info["document_revision"] != first_revision

    stale = server_module.add_paragraph(
        str(target),
        "에이전트 변경",
        expected_revision=first_revision,
    )

    assert stale["ok"] is False
    assert stale["reason"] == "document revision mismatch"
    assert stale["document_revision"] == second_info["document_revision"]
    assert "Re-read" in stale["suggestion"]
    assert "에이전트 변경" not in server_module.get_document_text(str(target))["text"]


def test_expected_revision_is_backward_compatible_when_omitted(server_module, tmp_path: Path) -> None:
    target = tmp_path / "revision-omitted.hwpx"
    server_module.create_document(str(target))
    before = server_module.get_document_info(str(target))["document_revision"]

    result = server_module.add_paragraph(str(target), "기존 호출")

    assert result["paragraph_index"] >= 0
    assert result["document_revision"] != before
    assert "기존 호출" in server_module.get_document_text(str(target))["text"]


def test_lock_marker_warning_is_reported_on_read(server_module, tmp_path: Path) -> None:
    target = tmp_path / "locked.hwpx"
    server_module.create_document(str(target))
    lock_marker = target.with_name(f"~${target.name}")
    lock_marker.write_text("open elsewhere", encoding="utf-8")

    info = server_module.get_document_info(str(target))

    assert info["documentWarnings"]
    assert info["documentWarnings"][0]["code"] == "possible_document_lock"
    assert info["documentWarnings"][0]["path"] == str(lock_marker)


def test_default_max_chars_from_env(server_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "long.hwpx"
    server_module.create_document(str(target))
    server_module.add_paragraph(str(target), "A" * 500)
    monkeypatch.setenv("HWPX_MCP_MAX_CHARS", "60")

    result = server_module.get_document_text(str(target))

    assert result["truncated"] is True
    assert len(result["text"]) == 60


def test_table_navigation_tools_stay_filename_based(server_module) -> None:
    forbidden_keys = {"doc_id", "docId", "document", "path", "handleId", "sessionId", "session"}

    for tool_name in TABLE_NAVIGATION_TOOLS:
        schema = snapshot_runtime_tools(server_module.mcp)[tool_name].input_schema
        properties = set(schema.get("properties", {}))

        assert "filename" in properties
        assert properties.isdisjoint(forbidden_keys)


def test_form_field_tools_stay_filename_based(server_module) -> None:
    forbidden_keys = {"doc_id", "docId", "document", "path", "handleId", "sessionId", "session"}

    for tool_name in FORM_FIELD_TOOLS:
        schema = snapshot_runtime_tools(server_module.mcp)[tool_name].input_schema
        properties = set(schema.get("properties", {}))

        assert "filename" in properties
        assert properties.isdisjoint(forbidden_keys)
