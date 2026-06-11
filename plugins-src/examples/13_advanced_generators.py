#!/usr/bin/env python3
"""Create P8 advanced generator examples and verify open safety."""

from __future__ import annotations

import base64
from pathlib import Path

from hwpx import (
    build_image_grid,
    build_meeting_nameplates,
    build_organization_chart,
    create_document_from_plan,
    validate_document_plan,
    validate_editor_open_safety,
)


OUTPUT_DIR = Path(__file__).resolve().parent / "out" / "13_advanced_generators"
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/axwAqkAAAAASUVORK5CYII="
)


def _write_sample_images() -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    image_a = OUTPUT_DIR / "site-before.png"
    image_b = OUTPUT_DIR / "site-after.png"
    image_a.write_bytes(PNG_1X1)
    image_b.write_bytes(PNG_1X1)
    return image_a, image_b


def _save_plan(name: str, plan: dict) -> Path:
    validation = validate_document_plan(plan)
    if not validation.ok:
        raise RuntimeError(f"{name} plan failed validation: {validation.to_dict()['issues']}")
    target = OUTPUT_DIR / f"{name}.hwpx"
    document = create_document_from_plan(plan)
    try:
        document.save_to_path(target)
    finally:
        document.close()
    open_safety = validate_editor_open_safety(target)
    if not open_safety.ok:
        raise RuntimeError(f"{name} openSafety failed: {open_safety.summary}")
    print(f"[OK] {name}: openSafety={open_safety.ok} path={target}")
    return target


def photo_sheet_plan() -> dict:
    image_a, image_b = _write_sample_images()
    return {
        "schemaVersion": "hwpx.document_plan.v2",
        "preset": "government_report",
        "title": "현장 사진대지",
        "sections": [
            {
                "blocks": [
                    {"type": "heading", "level": 1, "text": "현장 사진대지"},
                    build_image_grid(
                        [
                            {"path": str(image_a), "caption": "개선 전 현장"},
                            {"path": str(image_b), "caption": "개선 후 현장"},
                        ],
                        columns=2,
                        image_width_mm=22,
                    ),
                ]
            }
        ],
    }


def nameplate_plan() -> dict:
    return {
        "schemaVersion": "hwpx.document_plan.v2",
        "preset": "government_report",
        "title": "회의 명패",
        "sections": [
            {
                "blocks": [
                    {"type": "heading", "level": 1, "text": "회의 명패"},
                    build_meeting_nameplates(["김하나", "이두리", "박세진", "최네모"], columns=2),
                ]
            }
        ],
    }


def organization_chart_plan() -> dict:
    return {
        "schemaVersion": "hwpx.document_plan.v2",
        "preset": "government_report",
        "title": "운영 조직도",
        "sections": [
            {
                "blocks": [
                    {"type": "heading", "level": 1, "text": "운영 조직도"},
                    build_organization_chart(
                        {
                            "name": "위원장",
                            "children": [
                                {"name": "기획팀", "children": [{"name": "교육과정"}, {"name": "예산"}]},
                                {"name": "운영팀", "children": [{"name": "시설"}, {"name": "홍보"}]},
                            ],
                        },
                        max_depth=3,
                    ),
                ]
            }
        ],
    }


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _save_plan("photo-sheet", photo_sheet_plan())
    _save_plan("meeting-nameplates", nameplate_plan())
    _save_plan("organization-chart", organization_chart_plan())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
