# SPDX-License-Identifier: Apache-2.0
"""Reference consistency lint (moved from python-hwpx tests/test_doc_diff.py).

Only the reference-consistency cases moved; the paragraph-diff cases stay with
``hwpx.tools.doc_diff`` in python-hwpx.
"""

from __future__ import annotations

from pathlib import Path

from hwpx.document import HwpxDocument

from hwpx_automation.office.compliance import (
    REFERENCE_CONSISTENCY_REPORT_VERSION,
    inspect_reference_consistency,
)


def test_reference_consistency_passes_matching_references() -> None:
    report = inspect_reference_consistency(
        [
            "붙임 1 참조",
            "표 1. 예산 현황",
            "그림 1. 조직도",
            "붙임 1. 세부계획서 1부.",
        ]
    )

    assert report["report_version"] == REFERENCE_CONSISTENCY_REPORT_VERSION == "reference-consistency-v1"
    assert report["pass"] is True
    assert report["violations"] == []


def test_reference_consistency_detects_attachment_and_numbering_gaps() -> None:
    report = inspect_reference_consistency(
        [
            "붙임 2 참조",
            "표 1. 예산 현황",
            "표 3. 세부 현황",
            "그림 2. 조직도",
            "붙임 1. 세부계획서 1부.",
        ]
    )

    assert report["pass"] is False
    rules = {violation["rule"] for violation in report["violations"]}
    assert "attachment-reference" in rules
    assert "table-numbering" in rules
    assert "figure-numbering" in rules
    assert all(violation["suggestion"] for violation in report["violations"])


def test_reference_consistency_reads_a_document_plan_and_a_file(tmp_path: Path) -> None:
    plan = {
        "sections": [
            {
                "blocks": [
                    {"type": "paragraph", "text": "붙임 2 참조"},
                    {"type": "table", "rows": [["표 1", "현황"]]},
                    {"type": "paragraph", "text": "붙임 1. 세부계획서 1부."},
                ]
            }
        ]
    }
    from_plan = inspect_reference_consistency(plan)
    assert from_plan["summary"]["paragraph_count"] == 3
    assert [violation["rule"] for violation in from_plan["violations"]] == ["attachment-reference"]

    path = tmp_path / "refs.hwpx"
    document = HwpxDocument.new()
    for text in ("붙임 2 참조", "표 1 현황", "붙임 1. 세부계획서 1부."):
        document.add_paragraph(text)
    document.save_to_path(path)
    from_file = inspect_reference_consistency(path)
    assert from_file["violations"] == from_plan["violations"]
