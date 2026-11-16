from __future__ import annotations

from pathlib import Path

from hwpx.document import HwpxDocument
from hwpx_automation import server
from hwpx_automation.fastmcp_adapter import snapshot_runtime_tools


def test_official_document_style_tool_is_exposed() -> None:
    names = set(snapshot_runtime_tools(server.mcp))

    assert "inspect_official_document_style" in names


def test_inspect_official_document_style_from_paragraphs() -> None:
    result = server.inspect_official_document_style(
        paragraphs=[
            "1. 추진 개요",
            "1) 세부 추진",
            "일시 : 2026-06-11",
            "붙임: 세부계획서",
            "본문 끝.",
        ]
    )

    assert result["pass"] is False
    rules = {violation["rule"] for violation in result["violations"]}
    assert "item-marker-hierarchy" in rules
    assert "date-notation" in rules
    assert "attachment-notation" in rules
    assert all(violation["suggestion"] for violation in result["violations"])


def test_inspect_official_document_style_from_file_returns_revision(tmp_path: Path) -> None:
    target = tmp_path / "official.hwpx"
    doc = HwpxDocument.new()
    doc.add_paragraph("1. 추진 개요")
    doc.add_paragraph("가. 기본 방향")
    doc.add_paragraph("일시: 2026. 6. 11.")
    doc.add_paragraph("끝.")
    doc.save(target)
    doc.close()

    result = server.inspect_official_document_style(filename=str(target))

    assert result["pass"] is True
    assert result["document_revision"].startswith("sha256:")
    assert result["documentWarnings"] == []
