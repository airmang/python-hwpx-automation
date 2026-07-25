#!/usr/bin/env python3
"""제안서/기획안 HWPX를 agent-first preset으로 생성하는 예제."""

from __future__ import annotations

from pathlib import Path

# Presets moved to the MCP owner in the 5.0 train; the skill routes here anyway.
from hwpx_automation.office.authoring.presets import (
    create_proposal_document,
    inspect_proposal_quality,
)


def main() -> None:
    output_path = Path(__file__).resolve().parent / "out" / "04_proposal.hwpx"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    proposal_spec = {
        "title": "AI 융합형 교육실 구축 제안서",
        "subtitle": "학생 맞춤형 디지털 학습 공간 구축 및 운영 계획",
        "organization": "샘플 고등학교",
        "author": "교육혁신팀",
        "date": "2026-05-06",
        "metadata": {"문서유형": "제안서", "검토단계": "초안"},
        "executive_summary": "AI 융합형 교육실을 구축하여 수업, 평가, 기록을 연결하는 학습 환경을 조성합니다.",
        "sections": [
            {"title": "추진 배경 및 문제 정의", "paragraphs": ["디지털 기반 수업은 확대되고 있으나 실습 공간과 운영 체계가 분리되어 있습니다."]},
            {"title": "제안 내용", "bullets": ["AI 실습 존과 협업 학습 존 구성", "교원 연수와 수업 적용 컨설팅 운영"]},
            {"title": "구축 및 운영 계획", "paragraphs": ["준비, 구축, 시범 운영, 확산의 네 단계로 추진합니다."]},
        ],
        "budget_items": [
            {"item": "기자재", "amount": "5,000,000원", "note": "노트북 및 주변기기"},
            {"item": "연수 운영", "amount": "1,000,000원", "note": "교원 워크숍"},
        ],
        "expected_outcomes": ["수업 참여도 향상", "학생별 피드백 강화", "AI 활용 프로젝트 성과 축적"],
        "closing": "본 제안서를 검토 후 승인 요청드립니다.",
    }

    doc = create_proposal_document(proposal_spec)
    try:
        doc.save_to_path(output_path)
    finally:
        doc.close()

    report = inspect_proposal_quality(output_path)
    print(f"[OK] wrote: {output_path}")
    print(f"[OK] rubric average: {report['rubric_average']} pass={report['pass']}")
    print(
        "[OK] sample match: "
        f"average={report['sample_match']['average']} "
        f"pass={report['sample_match']['pass']} "
        f"visual_review_required={report['visual_review_required']}"
    )


if __name__ == "__main__":
    main()
