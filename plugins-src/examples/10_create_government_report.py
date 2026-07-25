#!/usr/bin/env python3
"""Create a government-report style HWPX from a document-plan v2."""

from __future__ import annotations

from pathlib import Path

from hwpx import HwpxDocument
from hwpx_automation.office.authoring import create_document_from_plan, inspect_document_authoring_quality, validate_document_plan
from hwpx.tools.report_utils import (
    calculate_ratios,
    format_krw_hangul,
    format_number_commas,
)


OUTPUT = Path(__file__).resolve().parent / "out" / "10_government_report.hwpx"


def government_report_plan() -> dict:
    total_budget = 12_500_000
    executed_budget = 8_750_000
    execution_ratio = calculate_ratios(executed_budget, total_budget)
    return {
        "schemaVersion": "hwpx.document_plan.v2",
        "preset": "government_report",
        "title": "2026년 AI 활용 교육 추진 현황 보고",
        "metadata": {
            "title": "2026년 AI 활용 교육 추진 현황 보고",
            "author": "미래교육과",
            "organization": "샘플교육지원청",
        },
        "visualReviewRequired": True,
        "sections": [
            {
                "blocks": [
                    {"type": "heading", "level": 1, "text": "Ⅰ. 추진 개요"},
                    {
                        "type": "paragraph",
                        "text": "AI 활용 교육 사업의 추진 실적, 예산 집행 현황, 향후 조치 계획을 보고드림.",
                    },
                    {
                        "type": "bullets",
                        "style": "square",
                        "items": [
                            "주요 성과: 교원 연수 및 학생 프로젝트 운영 확대",
                            "현장 확산: 우수 사례 공유회와 수업 공개 연계",
                        ],
                    },
                    {
                        "type": "bullets",
                        "style": "circle",
                        "items": [
                            "교원 연수 128명 이수",
                            "학생 프로젝트 24팀 운영",
                        ],
                    },
                    {
                        "type": "bullets",
                        "style": "note",
                        "items": ["세부 예산 집행 증빙은 별첨 자료로 관리"],
                    },
                    {"type": "heading", "level": 1, "text": "Ⅱ. 세부 추진 현황"},
                    {
                        "type": "table",
                        "tableProfile": "government",
                        "caption": "AI 활용 교육 추진 현황",
                        "unit": "단위: 명, 팀",
                        "header": ["구분", "실적", "비고"],
                        "rows": [
                            ["교원 연수", "128", "기초·심화 과정 운영"],
                            ["학생 프로젝트", "24", "탐구 결과 공유회 예정"],
                        ],
                    },
                    {"type": "heading", "level": 1, "text": "Ⅲ. 예산 집행 현황"},
                    {
                        "type": "table",
                        "tableProfile": "government",
                        "caption": "예산 집행 현황",
                        "unit": "단위: 원, %",
                        "header": ["총예산", "집행액", "집행률", "한글 표기"],
                        "rows": [
                            [
                                format_number_commas(total_budget),
                                format_number_commas(executed_budget),
                                f"{execution_ratio:.1f}",
                                format_krw_hangul(executed_budget),
                            ]
                        ],
                    },
                    {"type": "heading", "level": 1, "text": "Ⅳ. 향후 조치 계획"},
                    {
                        "type": "paragraph",
                        "text": "성과 공유회 이후 보완 수요를 반영하여 차년도 운영 계획과 예산 배분안을 확정할 예정임.",
                    },
                ]
            }
        ],
    }


def main() -> int:
    plan = government_report_plan()
    validation = validate_document_plan(plan)
    if not validation.ok:
        print("validation_ok=False")
        for issue in validation.to_dict()["issues"]:
            print(f"issue={issue['code']} path={issue['path']}")
        return 1

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document = create_document_from_plan(plan)
    try:
        document.save_to_path(OUTPUT)
    finally:
        document.close()

    report = inspect_document_authoring_quality(
        OUTPUT,
        plan=plan,
        quality_profile="government_report",
    )
    reopened = HwpxDocument.open(OUTPUT)
    try:
        text = reopened.export_text()
    finally:
        reopened.close()

    checks = [
        (report["pass"] is True, "authoring quality did not pass"),
        (report["validation"]["reopened"] is True, "reopen validation failed"),
        ("AI 활용 교육 추진 현황" in text, "report title missing"),
        (
            plan["sections"][0]["blocks"][8]["unit"] == "단위: 원, %",
            "government table unit missing from plan",
        ),
        ("팔백칠십오만원" in text, "KRW Hangul value missing"),
    ]
    failures = [message for passed, message in checks if not passed]
    if failures:
        print("[ERR] government report checks failed")
        for failure in failures:
            print(f" - {failure}")
        return 1

    print(f"[OK] wrote: {OUTPUT}")
    print(f"[OK] quality_pass={report['pass']}")
    print(f"[OK] visual_review_required={report['visual_review_required']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
