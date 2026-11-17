from __future__ import annotations

from pathlib import Path

import hwpx_automation.server as server


def test_markdown_to_document_plan_builds_valid_plan() -> None:
    markdown = """# 2026 Operating Plan

Intro paragraph.

## Tasks

- Validate before handoff.
- Keep review explicit.

| Item | Amount |
| --- | --- |
| Devices | 100 |
"""

    result = server.markdown_to_document_plan(
        markdown,
        metadata={"author": "Agent"},
    )

    plan = result["document_plan"]
    assert result["ok"] is True
    assert result["can_create"] is True
    assert result["next_tool"] == "create_document_from_plan"
    assert plan["title"] == "2026 Operating Plan"
    assert plan["metadata"]["author"] == "Agent"
    assert [block["type"] for block in plan["blocks"]] == [
        "paragraph",
        "heading",
        "bullets",
        "table",
    ]
    assert plan["blocks"][3]["columns"][0]["label"] == "Item"
    assert plan["blocks"][3]["rows"][0]["col2"] == "100"
    assert result["normalizedPlan"]["schemaVersion"] == "hwpx.document_plan.v1"


def test_markdown_to_document_plan_warns_for_lossy_markdown_shapes() -> None:
    markdown = """#### Deep Section

1. First
2. Second
"""

    result = server.markdown_to_document_plan(markdown)

    assert result["ok"] is True
    assert result["document_plan"]["title"] == "Deep Section"
    assert result["document_plan"]["blocks"][0] == {
        "type": "heading",
        "level": 3,
        "text": "Deep Section",
    }
    assert any("clamped" in warning for warning in result["warnings"])
    assert any("Ordered Markdown lists" in warning for warning in result["warnings"])


def test_markdown_to_document_plan_reads_inline_marks_like_from_markdown() -> None:
    result = server.markdown_to_document_plan(
        "# Notes\n\nPlain **bold part** and *slanted* `code` [site](https://example.org).\n\n"
        "- item with **bold**\n"
    )

    blocks = result["document_plan"]["blocks"]
    assert blocks[0] == {
        "type": "paragraph",
        "text": "Plain bold part and slanted code site(https://example.org).",
        "runs": [
            {"text": "Plain "},
            {"text": "bold part", "bold": True},
            {"text": " and slanted code site(https://example.org)."},
        ],
    }
    assert blocks[1] == {"type": "bullets", "items": ["item with bold"]}
    assert not any("**" in str(block) for block in blocks)
    warnings = " ".join(result["warnings"])
    assert "italic" in warnings and "inline code" in warnings and "links" in warnings
    assert "list item" in warnings


def test_markdown_document_plan_can_create_hwpx(tmp_path: Path) -> None:
    target = tmp_path / "from_markdown.hwpx"
    result = server.markdown_to_document_plan(
        "# Project Report\n\nOverview paragraph.\n\n| Name | Value |\n| --- | --- |\n| A | 1 |"
    )

    create_result = server.create_document_from_plan(str(target), result["document_plan"])

    assert create_result["created"] is True
    assert target.exists()
    extracted = server.document_to_markdown(str(target))
    assert "Project Report" in extracted["markdown"]
    assert "Name" in extracted["markdown"]
    assert "Value" in extracted["markdown"]
    assert "| A | 1 |" in extracted["markdown"]


def test_heading_with_its_own_number_is_not_numbered_again(tmp_path: Path) -> None:
    from hwpx import HwpxDocument

    target = tmp_path / "numbered.hwpx"
    plan = server.markdown_to_document_plan("# Report\n\n## 1. Overview\n\nText.\n\n## Details\n\nMore.")
    server.create_document_from_plan(str(target), plan["document_plan"])

    with HwpxDocument.open(target) as doc:
        heads = {
            paragraph.text: doc.styles.paragraph_property(paragraph.para_pr_id_ref).heading
            for paragraph in doc.paragraphs
            if paragraph.text in {"1. Overview", "Details"}
        }
    # The writer's "1." stays and the outline draws no second number; an unnumbered heading keeps it.
    assert heads["1. Overview"].type == "NONE"
    assert heads["Details"].type == "OUTLINE"
