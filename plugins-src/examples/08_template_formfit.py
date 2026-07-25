#!/usr/bin/env python
"""Create a template-preserving form-fit HWPX from a small baseline.

호환(DEPRECATED — 5.0 경계 확정, 동작 유지·제거는 다음 major) 회귀 자산: 새 양식
채움 작업은 canonical analyze_form_fill → apply_form_fill → verify_form_fill
경로를 사용한다 (references/workflows-forms.md, examples/08_mcp_canonical_form_fill.md).
이 스크립트는 기존 template-formfit baseline 자동화의 quickcheck
게이트(--template-formfit)로 유지된다.
"""

from __future__ import annotations

from pathlib import Path

from hwpx import HwpxDocument
from hwpx_mcp_server.office.form_fill import analyze_template_formfit, apply_template_formfit

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "out"
TEMPLATE = OUTPUT_DIR / "08_template_formfit_template.hwpx"
DESTINATION = OUTPUT_DIR / "08_template_formfit_filled.hwpx"


def build_template(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = HwpxDocument.new()
    try:
        doc.paragraphs[0].text = "AI 융합형 교육실 구축·운영 계획서"
        doc.add_paragraph("학 교 명 :")
        doc.add_paragraph("1. 추진 배경 및 목적")
        doc.add_paragraph("작성 필요: 추진 배경을 입력하세요.")
        doc.add_paragraph("Ⅶ 추진 일정")
        doc.add_paragraph("TODO")
        doc.add_paragraph("대상 공간 사진")
        doc.save_to_path(path)
    finally:
        doc.close()


def main() -> None:
    baseline = {
        "schemaVersion": "hwpx.template-formfit.baseline.v1",
        "baselineId": "skill-template-formfit-example",
        "locatorPolicy": {
            "residualMarkers": {
                "blockOutsideVisualReview": True,
                "patterns": ["작성 필요", "TODO", "□□□□", "○○"],
            }
        },
        "scalarFields": [
            {
                "id": "school.name",
                "locator": {"kind": "scalar-line", "anchor": "학 교 명 :"},
                "sourcePath": "school.name",
            }
        ],
        "regionMappings": [
            {
                "id": "overview.background_purpose",
                "anchor": "1. 추진 배경 및 목적",
                "kind": "section-region",
                "sourcePath": "sections.background_purpose",
                "required": True,
            },
            {
                "id": "schedule.timeline",
                "anchor": "Ⅶ 추진 일정",
                "kind": "table-region",
                "sourcePath": "sections.timeline.rows[]",
                "required": True,
                "columns": ["월", "추진 내용"],
            },
        ],
        "visualReviewRegions": [{"id": "photos", "anchor": "대상 공간 사진"}],
    }
    content = {
        "school": {"name": "광교고등학교"},
        "sections": {
            "background_purpose": [
                "AI 융합형 교육실 구축으로 학생 맞춤형 탐구 수업을 확대한다.",
                "교원 공동 설계와 지역 연계를 통해 지속 가능한 운영 체계를 만든다.",
            ],
            "timeline": {
                "rows": [
                    {"월": "3월", "추진 내용": "운영 협의체 구성"},
                    {"월": "4월", "추진 내용": "공간 설계 및 기자재 선정"},
                ]
            },
        },
    }

    build_template(TEMPLATE)
    analysis = analyze_template_formfit(
        TEMPLATE,
        baseline=baseline,
        content=content,
        destination=DESTINATION,
    )
    if analysis["unresolved_count"]:
        raise SystemExit(f"unresolved targets: {analysis['unresolved']}")

    result = apply_template_formfit(analysis=analysis, confirm=True)
    if result["handoff_status"] != "ready":
        raise SystemExit(f"handoff not ready: {result}")

    print(f"output={DESTINATION}")
    print(f"source_preserved={result['source']['preserved']}")
    print(f"package={result['validation']['validate_package']['ok']}")
    print(f"document={result['validation']['validate_document']['ok']}")
    print(f"visual_review_required={result['visual_review_required']}")


if __name__ == "__main__":
    main()
