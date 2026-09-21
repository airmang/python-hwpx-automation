from __future__ import annotations

import hashlib
from pathlib import Path

from hwpx.tools.package_validator import validate_package
from hwpx.tools.validator import validate_document

import hwpx_automation.server as server
from hwpx_automation.fastmcp_adapter import snapshot_runtime_tools


def _government_plan() -> dict:
    return {
        "schemaVersion": "hwpx.document_plan.v1",
        "title": "2026년 AI 활용 교육 추진 보고",
        "metadata": {
            "organization": "샘플교육지원청",
            "author": "미래교육과",
            "document_type": "government_report",
        },
        "blocks": [
            {"type": "heading", "level": 1, "text": "Ⅰ. 추진 개요"},
            {
                "type": "paragraph",
                "text": "본 보고서는 AI 활용 교육 추진 현황과 향후 조치 계획을 요약한다.",
            },
            {
                "type": "bullets",
                "items": [
                    "□ 주요 성과를 정량 지표 중심으로 정리",
                    "○ 학교 현장 적용 사례 및 확산 계획 포함",
                    "※ 예산 집행 및 일정 리스크를 별도 관리",
                ],
            },
            {"type": "heading", "level": 1, "text": "Ⅱ. 세부 추진 현황"},
            {
                "type": "table",
                "caption": "AI 활용 교육 추진 현황",
                "columns": [
                    {"key": "area", "label": "구분", "widthWeight": 1},
                    {"key": "count", "label": "실적", "widthWeight": 1},
                    {"key": "note", "label": "비고", "widthWeight": 2},
                ],
                "rows": [
                    {"area": "교원 연수", "count": "128명", "note": "기초·심화 과정 운영"},
                    {"area": "학생 프로젝트", "count": "24팀", "note": "탐구 결과 공유회 예정"},
                ],
            },
        ],
        "qualityGates": {
            "validatePackage": True,
            "validateDocument": True,
            "reopen": True,
            "minNonEmptyParagraphs": 5,
            "minTableCount": 1,
            "requiredText": ["추진 개요", "세부 추진 현황"],
            "visualReviewRequired": True,
        },
    }


def _broken_plan() -> dict:
    plan = _government_plan()
    plan["blocks"][4]["rows"] = ["not-a-row"]
    return plan


def _comparable_create_payload(payload: dict) -> dict:
    comparable = dict(payload)
    comparable.pop("filename", None)
    if "quality" in comparable:
        quality = dict(comparable["quality"])
        quality.pop("source_content_hash", None)
        comparable["quality"] = quality
    if "verification" in comparable:
        verification = comparable["verification"]
        open_safety = verification["openSafety"]
        comparable["verification"] = {
            "ok": verification["ok"],
            "summary": verification["summary"],
            "openSafety": {
                "ok": open_safety["ok"],
                "validatePackage": open_safety["validatePackage"]["ok"],
                "validateDocument": open_safety["validateDocument"]["ok"],
                "reopen": open_safety["reopen"]["ok"],
            },
        }
    return comparable


def test_government_report_tool_is_exposed() -> None:
    names = set(snapshot_runtime_tools(server.mcp))

    assert {
        "create_government_report_document",
        "compute_report_value",
        "parse_government_report_text",
    }.issubset(names)


def test_create_government_report_document_matches_direct_document_plan_call(
    tmp_path: Path,
) -> None:
    wrapper_destination = tmp_path / "gov-wrapper.hwpx"
    direct_destination = tmp_path / "gov-direct.hwpx"

    wrapper_result = server.create_government_report_document(
        str(wrapper_destination),
        _government_plan(),
    )
    direct_result = server.create_document_from_plan(
        str(direct_destination),
        _government_plan(),
        style_preset="government_report",
        quality_profile="government_report",
    )

    assert wrapper_result["created"] is True
    assert wrapper_result["style_preset"] == "government_report"
    assert wrapper_result["quality_profile"] == "government_report"
    assert wrapper_result["quality"]["source_content_hash"] == (
        "sha256:" + hashlib.sha256(wrapper_destination.read_bytes()).hexdigest()
    )
    assert direct_result["quality"]["source_content_hash"] == (
        "sha256:" + hashlib.sha256(direct_destination.read_bytes()).hexdigest()
    )
    assert _comparable_create_payload(wrapper_result) == _comparable_create_payload(direct_result)
    assert validate_package(wrapper_destination).ok
    assert validate_document(wrapper_destination).ok


def test_create_government_report_document_returns_repair_hints_for_invalid_plan(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "invalid-government-report.hwpx"

    result = server.create_government_report_document(str(destination), _broken_plan())

    assert result["created"] is False
    assert result["handoff_status"] == "needs_revision"
    assert result["next_tool"] == "validate_document_plan"
    assert result["plan_validation"]["ok"] is False
    assert any(hint["path"] == "blocks[4].rows[0]" for hint in result["plan_validation"]["repairHints"])
    assert not destination.exists()


def test_compute_report_value_delegates_to_report_utils() -> None:
    assert server.compute_report_value("krw_hangul", [123456789]) == {
        "operation": "krw_hangul",
        "value": "일억 이천삼백사십오만 육천칠백팔십구원",
        "warnings": [],
    }
    assert server.compute_report_value("commas", [1234567])["value"] == "1,234,567"
    assert server.compute_report_value("age", ["2000-06-04", {"today": "2026-06-03"}])[
        "value"
    ] == 25
    assert server.compute_report_value("delta", [-2500])["value"] == "△2,500"
    assert server.compute_report_value("delta_percent", [110, 100])["value"] == "+10.0%"
    assert server.compute_report_value("ratios", [25, 200])["value"] == 12.5
    assert server.compute_report_value("date", ["2026. 6. 3."])["value"] == "2026-06-03"


def test_compute_report_value_reports_invalid_operation_without_eval() -> None:
    result = server.compute_report_value("__import__('os').system('echo nope')", [1])

    assert result["operation"].startswith("__import__")
    assert result["value"] is None
    assert result["warnings"]


def test_parse_government_report_text_returns_validated_document_plan() -> None:
    result = server.parse_government_report_text(
        "Ⅰ. 추진 개요\n□ 주요 성과\n○ 세부 과제\n\n구분\t실적\n교원 연수\t128명",
        title="AI 활용 교육 추진 보고",
    )

    assert result["document_plan"]["schemaVersion"] == "hwpx.document_plan.v2"
    assert result["document_plan"]["title"] == "AI 활용 교육 추진 보고"
    assert result["plan_validation"]["ok"] is True
    assert result["can_create"] is True
    assert result["next_tool"] == "create_government_report_document"
