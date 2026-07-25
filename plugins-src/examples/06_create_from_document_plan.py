#!/usr/bin/env python3
"""Create a valid HWPX from a declarative document-plan JSON."""

from __future__ import annotations

from pathlib import Path

from hwpx_mcp_server.office.authoring import create_document_from_plan, inspect_document_authoring_quality, validate_document_plan


def main() -> None:
    output_path = Path(__file__).resolve().parent / "out" / "06_document_plan.hwpx"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    document_plan = {
        "schemaVersion": "hwpx.document_plan.v1",
        "title": "2026 AI Education Operating Plan",
        "subtitle": "Generated from hwpx.document_plan.v1",
        "metadata": {
            "organization": "Sample School",
            "author": "AI Education Team",
            "date": "2026-05-09",
        },
        "blocks": [
            {"type": "heading", "level": 1, "text": "Executive Summary"},
            {
                "type": "paragraph",
                "text": "This document was generated through the public python-hwpx document-plan API.",
            },
            {
                "type": "bullets",
                "items": [
                    "Normalize natural-language requests into a compact JSON plan.",
                    "Generate HWPX without direct OWPML editing.",
                    "Return validation evidence before handoff.",
                ],
            },
            {"type": "heading", "level": 2, "text": "Budget"},
            {
                "type": "table",
                "caption": "Budget Plan",
                "columns": [
                    {"key": "item", "label": "Item", "widthWeight": 2},
                    {"key": "amount", "label": "Amount", "widthWeight": 1},
                    {"key": "note", "label": "Note", "widthWeight": 2},
                ],
                "rows": [
                    {
                        "item": "AI devices",
                        "amount": "5,000,000 KRW",
                        "note": "Laptop and classroom equipment",
                    },
                    {
                        "item": "Teacher training",
                        "amount": "1,000,000 KRW",
                        "note": "Workshops and coaching",
                    },
                ],
            },
        ],
        "qualityGates": {
            "validatePackage": True,
            "validateDocument": True,
            "reopen": True,
            "minNonEmptyParagraphs": 4,
            "visualReviewRequired": True,
        },
    }

    validation = validate_document_plan(document_plan)
    if not validation.ok:
        payload = validation.to_dict()
        print("[ERR] document plan failed validation")
        for issue in payload["issues"]:
            print(
                "[ISSUE] "
                f"{issue['severity']} {issue['code']} at {issue['path']}: "
                f"{issue['message']}"
            )
        for hint in payload["repairHints"]:
            print(
                "[HINT] "
                f"{hint['action']} {hint['path']} ({hint['code']}): "
                f"{hint['message']}"
            )
        raise SystemExit(1)

    doc = create_document_from_plan(document_plan)
    try:
        doc.save_to_path(output_path)
    finally:
        doc.close()

    report = inspect_document_authoring_quality(output_path, plan=document_plan)
    print(f"[OK] wrote: {output_path}")
    print(f"[OK] pass={report['pass']} visual_review_required={report['visual_review_required']}")
    print(f"[OK] package={report['validation']['validate_package']['ok']}")
    print(f"[OK] document={report['validation']['validate_document']['ok']}")


if __name__ == "__main__":
    main()
