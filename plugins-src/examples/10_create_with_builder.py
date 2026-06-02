#!/usr/bin/env python3
"""Create a layout-sensitive HWPX document with hwpx.builder."""

from __future__ import annotations

import base64
from pathlib import Path

from hwpx.builder import (
    Bullet,
    Document,
    Footer,
    Header,
    Heading,
    Image,
    Margins,
    Metadata,
    NumberedList,
    PageBreak,
    PageNumber,
    PageSize,
    Paragraph,
    Run,
    Section,
    Table,
)


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/axwAqkAAAAASUVORK5CYII="
)
OUTPUT = Path(__file__).resolve().parent / "out" / "10_builder_vertical_slice.hwpx"


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image_path = OUTPUT.parent / "10_builder_pixel.png"
    image_path.write_bytes(PNG_1X1)

    report = Document(
        metadata=Metadata(
            title="2026 AI 교육 운영계획",
            author="AI교육팀",
            organization="샘플학교",
        ),
        sections=[
            Section(
                page=PageSize.A4,
                margins=Margins(top_mm=20, right_mm=20, bottom_mm=20, left_mm=20),
                header=Header(
                    children=[
                        Paragraph(
                            align="right",
                            children=[
                                Run("샘플학교  -  ", bold=True, color="C00000"),
                                PageNumber(),
                            ],
                        )
                    ]
                ),
                footer=Footer(
                    children=[
                        Paragraph(align="center", children=[PageNumber(format="page/total")]),
                    ]
                ),
                children=[
                    Heading(level=1, text="추진 개요"),
                    Heading(level=2, text="세부 목표"),
                    Paragraph(
                        children=[
                            Run("AI 활용 수업을 "),
                            Run("전 학년", bold=True, color="1F5FBF", font="함초롬바탕", size=12),
                            Run("으로 확산한다."),
                        ]
                    ),
                    Bullet(items=["교원 연수", "수업 공개"], level=0),
                    NumberedList(items=["계획 수립", "수업 적용", "성과 점검"]),
                    Table(
                        header=["구분", "내용", "기한"],
                        rows=[
                            ["준비", "환경 점검", "3월"],
                            ["운영", "수업 적용", "4월"],
                        ],
                        column_widths=[2, 3, 1],
                        header_shading="EAF1FB",
                        merges=["A2:A3"],
                    ),
                    Image(image_path, width_mm=18, align="center", caption="샘플 이미지"),
                    PageBreak(),
                    Paragraph(text="다음 페이지 점검"),
                ],
            )
        ],
    ).save_to_path(OUTPUT)

    hard_gates = report.hard_gates
    required_gates = {
        "package_validation": "pass",
        "document_errors": "pass",
        "reopen": "pass",
    }
    failures = [
        f"{name}={hard_gates.get(name)!r}"
        for name, expected in required_gates.items()
        if hard_gates.get(name) != expected
    ]
    required_features = (
        "metadata",
        "page_setup",
        "header_footer",
        "page_number",
        "heading",
        "rich_run",
        "list",
        "table",
        "image",
        "page_break",
        "layout_sensitive",
    )
    failures.extend(
        f"feature_flags.{name}=false"
        for name in required_features
        if report.feature_flags.get(name) is not True
    )
    if report.visual_review_required is not True:
        failures.append("visual_review_required is not true")
    if failures:
        print("[ERR] builder report checks failed")
        for failure in failures:
            print(f" - {failure}")
        return 1

    print(f"[OK] wrote: {OUTPUT}")
    print(f"[OK] hard_gates={hard_gates}")
    print(f"[OK] visual_review_required={report.visual_review_required}")
    print(f"[OK] feature_flags={report.feature_flags}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
