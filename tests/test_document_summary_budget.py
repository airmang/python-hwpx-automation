from __future__ import annotations
import json
from pathlib import Path
from hwpx import HwpxDocument
from hwpx_automation import server
from hwpx_automation.utils.read_budget import bound_document_summary, SUMMARY_MAX_CHARS


def test_large_summary_has_bounded_revision_bound_continuation(tmp_path: Path):
    source = Path(__file__).parent / "fixtures/edit-fidelity/sample1.hwpx"
    target = tmp_path / "many-paragraphs.hwpx"
    with HwpxDocument.open(source) as document:
        for i in range(80):
            document.sections[0].add_paragraph(f"항목 {i}: " + "긴 설명 " * 300)
        document.save_to_path(target, mode="patch", fallback="error")
    full = server.get_document_map(str(target), detail="full")
    summary = server.get_document_map(str(target), detail="summary")
    assert len(json.dumps(summary, ensure_ascii=False)) <= SUMMARY_MAX_CHARS
    assert summary["truncated"] is True
    assert summary["targetSelectionComplete"] is False
    assert summary["summaryCoverage"]["paragraphs"] == full["info"]["paragraphs"]
    assert len(summary["anchors"]["paragraphs"]) < full["info"]["paragraphs"]
    assert "truncated" not in full
    root = server.get_document_node(**summary["continuation"]["arguments"])
    assert root["revision"] == summary["document_revision"]
    section = server.get_document_node(
        str(target),
        path="/section[1]",
        depth=1,
        child_limit=24,
        expected_revision=summary["document_revision"],
    )
    assert section["coverage"]["truncatedChildren"] > 0
    omitted = server.get_document_node(
        str(target),
        path="/section[1]/paragraph[40]",
        depth=0,
        expected_revision=summary["document_revision"],
    )
    assert omitted.get("kind") == "paragraph", omitted
    assert omitted["summary"]["text"].startswith("항목")


def test_budget_keeps_counts_and_marks_partial_selection():
    payload = {
        "filename": "test.hwpx",
        "document_revision": "sha256:" + "1" * 64,
        "info": {"paragraphs": 100, "tables": 100, "sections": 1},
        "outline": [],
        "sections": [],
        "tables": {"count": 100, "tables": []},
        "anchors": {"paragraphs": [], "tables": [], "figures": []},
        "formFields": {
            "fields": [
                {"id": str(i), "name": "동일 라벨", "value": "가" * 5000}
                for i in range(100)
            ]
        },
    }
    result = bound_document_summary(payload)
    assert len(json.dumps(result, ensure_ascii=False)) <= SUMMARY_MAX_CHARS
    assert result["summaryCoverage"]["formFields"] == 100
    assert len(result["formFields"]["fields"]) <= 24
    assert result["targetSelectionComplete"] is False
    assert result["truncated"] is True
    assert len(payload["formFields"]["fields"][0]["value"]) == 5000


def test_small_summary_is_complete_as_preview_only():
    result = bound_document_summary(
        {
            "filename": "x.hwpx",
            "document_revision": "sha256:" + "1" * 64,
            "info": {"paragraphs": 1, "tables": 0, "sections": 1},
            "outline": [],
            "anchors": {},
            "formFields": {"fields": []},
        }
    )
    assert result["truncated"] is False
    assert result["targetSelectionComplete"] is False
