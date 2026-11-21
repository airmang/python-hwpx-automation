# SPDX-License-Identifier: Apache-2.0
"""Application document-plan composition for old/new comparisons."""

from __future__ import annotations

from typing import Any

from hwpx.tools.doc_diff import doc_diff


def build_comparison_table_plan(
    old_source: Any,
    new_source: Any,
    *,
    title: str = "신구대조표",
    include_equal: bool = True,
) -> dict[str, Any]:
    """Return a plan-v2 document containing an old/new comparison table."""

    report = doc_diff(old_source, new_source)
    rows = [
        [
            _change_label(change["tag"]),
            change.get("old_text") or "",
            change.get("new_text") or "",
        ]
        for change in report["changes"]
        if include_equal or change["tag"] != "equal"
    ]
    if not rows:
        rows = [["동일", "", ""]]
    return {
        "schemaVersion": "hwpx.document_plan.v2",
        "preset": "government_report",
        "title": title,
        "sections": [
            {
                "blocks": [
                    {"type": "heading", "level": 1, "text": title},
                    {
                        "type": "table",
                        "header": ["구분", "구", "신"],
                        "rows": rows,
                        "columnWidths": [1, 4, 4],
                        "headerShading": "EAF1FB",
                    },
                ]
            }
        ],
    }


def _change_label(tag: str) -> str:
    return {
        "equal": "동일",
        "added": "추가",
        "removed": "삭제",
        "changed": "변경",
    }.get(tag, tag)


__all__ = ["build_comparison_table_plan"]
