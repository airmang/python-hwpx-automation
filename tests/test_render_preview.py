# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from hwpx.document import HwpxDocument
from jsonschema import Draft202012Validator

from hwpx_automation import server
from hwpx_automation.tool_contract import bound_tool_registry


def test_render_preview_tool_is_bound_to_the_canonical_registry() -> None:
    binding = bound_tool_registry().by_name()["render_preview"]

    assert binding.function is server.render_preview
    assert "output_dir" in binding.input_schema["properties"]
    assert "max_pages" in binding.input_schema["properties"]
    assert binding.output_schema["title"] == "RenderPreviewOutput"
    assert binding.output_schema["required"] == [
        "schemaVersion",
        "status",
        "generatedAt",
        "sourcePath",
        "outputDir",
        "htmlPath",
        "manifestPath",
        "visualReviewPath",
        "mode",
        "pageCount",
        "pages",
        "screenshots",
        "screenshotEngine",
        "warnings",
        "suggestion",
    ]
    assert "content" not in binding.output_schema["properties"]


def test_render_preview_html_only_creates_manifest_and_visual_evidence(tmp_path: Path) -> None:
    source = tmp_path / "preview-source.hwpx"
    output_dir = tmp_path / "preview"
    document = HwpxDocument.new()
    document.add_paragraph("Preview title")
    document.save(source)

    call_result = server.render_preview(
        str(source),
        output_dir=str(output_dir),
        screenshot="off",
    )

    # render_preview now returns a CallToolResult so it can carry inline images;
    # the manifest lives in structuredContent and the JSON text content.
    result = call_result.structuredContent
    assert call_result.isError is False
    assert call_result.content[0].type == "text"
    assert result["status"] == "html_only"
    assert result["schemaVersion"] == "hwpx.render-preview.v1"
    assert result["pageCount"] >= 1
    assert result["pages"][0]["htmlPath"].endswith("page-001.html")
    assert result["screenshotEngine"]["requested"] is False
    # html_only -> no screenshots -> no inline image blocks
    assert all(block.type != "image" for block in call_result.content)
    assert not list(
        Draft202012Validator(
            bound_tool_registry().by_name()["render_preview"].output_schema
        ).iter_errors(result)
    )

    html_path = Path(result["htmlPath"])
    manifest_path = Path(result["manifestPath"])
    visual_review_path = Path(result["visualReviewPath"])
    assert html_path.exists()
    assert manifest_path.exists()
    assert visual_review_path.exists()
    assert "hwpx-preview-page" in html_path.read_text(encoding="utf-8")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "html_only"
    visual_review = json.loads(visual_review_path.read_text(encoding="utf-8"))
    assert visual_review["schemaVersion"] == "hwpx.visual-review.v1"
    assert visual_review["summary"]["layout_preview_status"] == "html_only"
