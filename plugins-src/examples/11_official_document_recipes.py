#!/usr/bin/env python3
"""Create official-document recipe examples and verify open safety."""

from __future__ import annotations

from pathlib import Path

from hwpx import (
    create_document_from_plan,
    inspect_official_document_style,
    validate_document_plan,
    validate_editor_open_safety,
)


OUTPUT_DIR = Path(__file__).resolve().parent / "out" / "11_official_document_recipes"


def _base_plan(title: str, organization: str, blocks: list[dict]) -> dict:
    return {
        "schemaVersion": "hwpx.document_plan.v2",
        "preset": "government_report",
        "title": title,
        "metadata": {
            "title": title,
            "author": "행정지원팀",
            "organization": organization,
        },
        "sections": [{"blocks": blocks}],
    }


def official_letter_external() -> dict:
    return _base_plan(
        "AI 활용 교육 협의회 참석 요청",
        "샘플교육지원청",
        [
            {"type": "approval_box"},
            {"type": "heading", "level": 1, "text": "1. 관련"},
            {"type": "paragraph", "text": "가. 미래교육과-1234(2026. 6. 1.)호"},
            {"type": "heading", "level": 1, "text": "2. 요청 사항"},
            {"type": "paragraph", "text": "가. 협의회 참석자를 2026. 6. 11.까지 제출하여 주시기 바랍니다."},
            {"type": "paragraph", "text": "붙임 1. 참석자 명단 서식 1부."},
            {"type": "paragraph", "text": "끝."},
        ],
    )


def official_letter_internal() -> dict:
    return _base_plan(
        "AI 교육 운영 점검 계획 보고",
        "샘플초등학교",
        [
            {"type": "approval_box", "labels": ["기안", "검토", "결재"], "delegated": "전결"},
            {"type": "heading", "level": 1, "text": "1. 점검 개요"},
            {"type": "paragraph", "text": "가. 점검 일자: 2026. 6. 11."},
            {"type": "paragraph", "text": "나. 점검 대상: AI 교육실 및 관련 기자재"},
            {"type": "heading", "level": 1, "text": "2. 조치 계획"},
            {"type": "paragraph", "text": "가. 점검 결과를 취합하여 개선 사항을 보고하겠습니다."},
            {"type": "paragraph", "text": "끝."},
        ],
    )


def family_notice() -> dict:
    return _base_plan(
        "AI 활용 수업 공개 가정통신문",
        "샘플초등학교",
        [
            {"type": "heading", "level": 1, "text": "1. 안내 사항"},
            {"type": "paragraph", "text": "가. 공개 수업은 2026. 6. 11. 10:00에 실시합니다."},
            {"type": "paragraph", "text": "나. 참석을 희망하시는 보호자는 담임교사에게 회신해 주시기 바랍니다."},
            {"type": "heading", "level": 1, "text": "2. 협조 요청"},
            {"type": "paragraph", "text": "가. 원활한 운영을 위해 시작 10분 전까지 입실해 주시기 바랍니다."},
            {"type": "paragraph", "text": "끝."},
        ],
    )


def meeting_minutes() -> dict:
    return _base_plan(
        "AI 교육 협의회 회의록",
        "샘플교육지원청",
        [
            {"type": "approval_box"},
            {"type": "heading", "level": 1, "text": "1. 회의 개요"},
            {"type": "paragraph", "text": "가. 일시: 2026. 6. 11. 14:00"},
            {"type": "paragraph", "text": "나. 참석자: 미래교육과 담당자 및 학교 업무 담당자"},
            {"type": "heading", "level": 1, "text": "2. 주요 논의"},
            {"type": "paragraph", "text": "가. AI 교육실 활용률 제고 방안을 협의하였습니다."},
            {"type": "paragraph", "text": "끝."},
        ],
    )


def purchase_request() -> dict:
    return _base_plan(
        "AI 교육 기자재 구입 품의",
        "샘플초등학교",
        [
            {"type": "approval_box"},
            {"type": "heading", "level": 1, "text": "1. 구입 목적"},
            {"type": "paragraph", "text": "가. AI 활용 수업 운영에 필요한 기자재를 확보하고자 합니다."},
            {"type": "heading", "level": 1, "text": "2. 소요 예산"},
            {"type": "paragraph", "text": "가. 금액: 1,250,000원"},
            {"type": "paragraph", "text": "붙임 1. 견적서 1부."},
            {"type": "paragraph", "text": "끝."},
        ],
    )


RECIPES = {
    "official-letter-external": official_letter_external,
    "official-letter-internal": official_letter_internal,
    "family-notice": family_notice,
    "meeting-minutes": meeting_minutes,
    "purchase-request": purchase_request,
}


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    for slug, factory in RECIPES.items():
        plan = factory()
        validation = validate_document_plan(plan)
        if not validation.ok:
            failures.append(f"{slug}: validation failed {validation.to_dict()['issues']}")
            continue
        target = OUTPUT_DIR / f"{slug}.hwpx"
        document = create_document_from_plan(plan)
        try:
            document.save_to_path(target)
        finally:
            document.close()
        open_safety = validate_editor_open_safety(target)
        style = inspect_official_document_style(target)
        if not open_safety.ok:
            failures.append(f"{slug}: openSafety failed {open_safety.summary}")
        if not style["pass"]:
            failures.append(f"{slug}: style lint failed {style['violations']}")
        print(f"[OK] {slug}: openSafety={open_safety.ok} style={style['pass']} path={target}")

    if failures:
        print("[ERR] official document recipe checks failed")
        for failure in failures:
            print(f" - {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
