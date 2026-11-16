from __future__ import annotations

from pathlib import Path

from hwpx.document import HwpxDocument
from hwpx.tools.package_validator import validate_editor_open_safety
from hwpx_automation import server
from hwpx_automation.fastmcp_adapter import snapshot_runtime_tools


def test_doc_diff_tools_are_exposed() -> None:
    names = set(snapshot_runtime_tools(server.mcp))

    assert {
        "doc_diff",
        "create_comparison_table_document",
        "inspect_reference_consistency",
    }.issubset(names)


def test_doc_diff_from_paragraphs() -> None:
    result = server.doc_diff(
        old_paragraphs=["제1조 목적", "제2조 예산"],
        new_paragraphs=["제1조 목적", "제2조 예산 변경", "제3조 시행"],
    )

    assert result["summary"]["counts"]["changed"] == 1
    assert result["summary"]["counts"]["added"] == 1


def test_create_comparison_table_document_returns_open_safety(tmp_path: Path) -> None:
    target = tmp_path / "comparison.hwpx"
    result = server.create_comparison_table_document(
        str(target),
        old_paragraphs=["제1조 목적", "제2조 예산"],
        new_paragraphs=["제1조 목적", "제2조 예산 변경"],
        include_equal=False,
    )

    assert result["created"] is True
    assert result["verification"]["openSafety"]["ok"] is True
    assert validate_editor_open_safety(target).ok is True


def test_inspect_reference_consistency_from_file_returns_revision(tmp_path: Path) -> None:
    target = tmp_path / "references.hwpx"
    doc = HwpxDocument.new()
    doc.add_paragraph("붙임 2 참조")
    doc.add_paragraph("표 1. 예산")
    doc.add_paragraph("표 3. 누락")
    doc.add_paragraph("붙임 1. 세부계획서 1부.")
    doc.save(target)
    doc.close()

    result = server.inspect_reference_consistency(filename=str(target))

    assert result["pass"] is False
    assert result["document_revision"].startswith("sha256:")
    rules = {violation["rule"] for violation in result["violations"]}
    assert "attachment-reference" in rules
    assert "table-numbering" in rules
