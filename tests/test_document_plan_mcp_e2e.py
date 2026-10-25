from __future__ import annotations

from pathlib import Path

import hwpx_automation.server as server
from hwpx.tools.package_validator import validate_package
from hwpx.tools.validator import validate_document
from hwpx_automation.fastmcp_adapter import snapshot_runtime_tools


def _plan() -> dict:
    return {
        "schemaVersion": "hwpx.document_plan.v1",
        "title": "2026 AI Education Operating Plan",
        "subtitle": "MCP document-plan smoke",
        "metadata": {
            "organization": "Sample School",
            "author": "AI Education Team",
        },
        "blocks": [
            {"type": "heading", "level": 1, "text": "Executive Summary"},
            {
                "type": "paragraph",
                "text": "This HWPX was generated from a declarative plan through MCP.",
            },
            {
                "type": "bullets",
                "items": ["Validate before handoff.", "Keep visual review explicit."],
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
                    }
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


def _broken_plan() -> dict:
    plan = _plan()
    plan["blocks"][4]["rows"] = ["bad"]
    return plan


def _operating_plan() -> dict:
    return {
        "schemaVersion": "hwpx.document_plan.v1",
        "title": "2026 AI 중점학교 운영계획서",
        "subtitle": "MCP operating-plan profile smoke",
        "metadata": {
            "organization": "샘플고등학교",
            "author": "AI교육기획팀",
            "date": "2026-05-14",
            "document_type": "operating_plan",
        },
        "blocks": [
            {"type": "heading", "level": 1, "text": "Ⅰ. 신청 목적"},
            {
                "type": "paragraph",
                "text": "본 계획은 학교의 AI·디지털 기반 수업 역량을 강화하고 학생 맞춤형 학습 경험을 확대하기 위한 운영 방향을 제시한다.",
            },
            {"type": "heading", "level": 2, "text": "AI 중점학교 운영 목표"},
            {
                "type": "bullets",
                "items": [
                    "책임 있는 AI 활용 체계를 마련한다.",
                    "학생의 AI 리터러시와 비판적 사고 역량을 강화한다.",
                    "수업, 평가, 기록을 연계한 맞춤형 피드백 구조를 정착시킨다.",
                ],
            },
            {"type": "heading", "level": 1, "text": "Ⅱ. 운영 계획"},
            {
                "type": "paragraph",
                "text": "정규 수업, 교원 연수, 학생 프로젝트를 연계하여 학기별 실행 과제를 운영한다.",
            },
            {
                "type": "table",
                "caption": "추진 일정",
                "columns": [
                    {"key": "phase", "label": "단계", "widthWeight": 1},
                    {"key": "period", "label": "기간", "widthWeight": 1},
                    {"key": "activity", "label": "세부 추진 내용", "widthWeight": 3},
                    {"key": "owner", "label": "담당", "widthWeight": 1},
                ],
                "rows": [
                    {"phase": "준비", "period": "3월", "activity": "운영 계획 공유 및 협의회 구성", "owner": "운영팀"},
                    {"phase": "운영", "period": "4월~11월", "activity": "AI 활용 수업, 프로젝트, 교원 연수 운영", "owner": "교과협의회"},
                    {"phase": "평가", "period": "12월~2월", "activity": "성과 분석, 사례 공유, 차년도 개선안 수립", "owner": "평가팀"},
                ],
            },
            {"type": "heading", "level": 1, "text": "Ⅲ. 추진 일정 및 사업비 사용 계획"},
            {
                "type": "table",
                "caption": "사업비 사용 계획",
                "columns": [
                    {"key": "item", "label": "항목", "widthWeight": 2},
                    {"key": "amount", "label": "금액", "widthWeight": 1},
                    {"key": "ratio", "label": "비율(%)", "widthWeight": 1},
                    {"key": "basis", "label": "산출근거", "widthWeight": 3},
                ],
                "rows": [
                    {"item": "교육 운영비", "amount": "4,000,000원", "ratio": "50", "basis": "수업 자료 제작, 학생 프로젝트 재료비"},
                    {"item": "교원 연수비", "amount": "1,000,000원", "ratio": "12.5", "basis": "AI 활용 수업 설계 연수 운영"},
                    {"item": "자산 취득비", "amount": "3,000,000원", "ratio": "37.5", "basis": "AI 교육 전용 교구 및 실습 장비"},
                ],
            },
            {"type": "heading", "level": 1, "text": "Ⅳ. 교육과정 편제표"},
            {
                "type": "paragraph",
                "text": "세부 교육과정 편제표는 학교 자율 양식으로 별도 첨부하고, 본문에는 운영 방향과 연계 과목을 요약한다.",
            },
            {"type": "heading", "level": 1, "text": "Ⅴ. 기대 효과 및 성과 관리"},
            {
                "type": "bullets",
                "items": [
                    "AI 활용 수업 공개와 수업 나눔을 통해 교원 실행 역량을 높인다.",
                    "학생 산출물, 참여도, 만족도 자료를 종합하여 성과를 관리한다.",
                    "차년도 교육과정 편성과 예산 계획에 운영 결과를 반영한다.",
                ],
            },
            {"type": "heading", "level": 1, "text": "Ⅵ. 제출 및 확인"},
            {
                "type": "paragraph",
                "text": "본 운영계획서는 학교 구성원의 검토를 거쳐 제출하며, 선정 이후 세부 실행 계획과 증빙 자료를 보완한다.",
            },
        ],
        "qualityGates": {
            "validatePackage": True,
            "validateDocument": True,
            "reopen": True,
            "minNonEmptyParagraphs": 12,
            "minTableCount": 2,
            "requiredText": ["Ⅰ. 신청 목적", "Ⅱ. 운영 계획", "사업비 사용 계획", "기대 효과"],
            "visualReviewRequired": True,
        },
    }


def _sparse_operating_plan() -> dict:
    return {
        "schemaVersion": "hwpx.document_plan.v1",
        "title": "2026 AI 중점학교 운영계획서",
        "metadata": {"organization": "샘플고등학교", "document_type": "operating_plan"},
        "blocks": [
            {"type": "heading", "level": 1, "text": "Ⅰ. 신청 목적"},
            {"type": "paragraph", "text": "작성 필요: 학교 상황에 맞게 입력하세요."},
            {
                "type": "table",
                "caption": "사업비 사용 계획",
                "columns": [{"key": "item", "label": "항목"}, {"key": "amount", "label": "금액"}],
                "rows": [{"item": "TODO", "amount": ""}],
            },
        ],
        "qualityGates": {
            "validatePackage": True,
            "validateDocument": True,
            "reopen": True,
            "minNonEmptyParagraphs": 3,
            "visualReviewRequired": True,
        },
    }


def test_document_plan_tools_are_exposed() -> None:
    names = set(snapshot_runtime_tools(server.mcp))

    assert {
        "analyze_document_plan",
        "markdown_to_document_plan",
        "validate_document_plan",
        "create_document_from_plan",
        "inspect_document_authoring_quality",
        "inspect_operating_plan_quality",
    }.issubset(names)


def test_validate_document_plan_is_non_mutating(tmp_path: Path) -> None:
    destination = tmp_path / "not-created.hwpx"

    result = server.validate_document_plan(_plan())

    assert result["ok"] is True
    assert result["can_create"] is True
    assert result["normalizedPlan"]["schemaVersion"] == "hwpx.document_plan.v1"
    assert result["next_tool"] == "create_document_from_plan"
    assert not destination.exists()


def test_validate_document_plan_reports_recovery_fields_for_invalid_plan(tmp_path: Path) -> None:
    destination = tmp_path / "invalid-plan.hwpx"

    result = server.validate_document_plan(_broken_plan())

    assert result["ok"] is False
    assert result["can_create"] is False
    assert result["next_tool"] == "validate_document_plan"
    assert result["next_action"].startswith("repair document_plan")
    assert any(issue["code"] == "invalid_table_row" for issue in result["issues"])
    assert any(hint["path"] == "blocks[4].rows[0]" for hint in result["repairHints"])

    create_result = server.create_document_from_plan(str(destination), _broken_plan())

    assert create_result["created"] is False
    assert create_result["plan_validation"]["ok"] is False
    assert any(
        issue["path"] == "blocks[4].rows[0]"
        for issue in create_result["plan_validation"]["issues"]
    )
    assert not destination.exists()


def test_analyze_document_plan_previews_operating_plan_quality_without_writing(tmp_path: Path) -> None:
    destination = tmp_path / "analyzed-only.hwpx"

    result = server.analyze_document_plan(
        _operating_plan(),
        destination_filename=str(destination),
        quality_profile="operating_plan",
    )

    assert result["ok"] is True
    assert result["mutated"] is False
    assert result["can_create"] is True
    assert result["next_tool"] == "create_document_from_plan"
    assert result["normalizedPlan"]["schemaVersion"] == "hwpx.document_plan.v1"
    assert result["quality_preview"]["pass"] is True
    assert result["quality_preview"]["profiles"]["operating_plan"]["pass"] is True
    assert result["handoff_status"] == "ready"
    assert not destination.exists()


def test_validate_document_plan_allows_recoverable_style_warning() -> None:
    plan = _plan()
    plan["blocks"][1]["style"] = "hero"

    result = server.validate_document_plan(plan)

    assert result["ok"] is True
    assert result["can_create"] is True
    assert any(
        issue["code"] == "unknown_style_token" and issue["severity"] == "warning"
        for issue in result["issues"]
    )
    assert any(hint["action"] == "review" for hint in result["repairHints"])


def test_create_document_from_plan_creates_valid_handoff_file(tmp_path: Path) -> None:
    destination = tmp_path / "agent-plan.hwpx"

    result = server.create_document_from_plan(str(destination), _plan())

    assert result["created"] is True
    assert result["quality"]["pass"] is True
    assert result["quality"]["validation"]["reopened"] is True
    assert result["quality"]["validation"]["validate_package"]["ok"] is True
    assert result["quality"]["validation"]["validate_document"]["ok"] is True
    assert result["verification"]["openSafety"]["ok"] is True
    assert result["quality"]["visual_review_required"] is True
    assert validate_package(destination).ok
    assert validate_document(destination).ok

    text = server.get_document_text(str(destination))["text"]
    assert "2026 AI Education Operating Plan" in text
    assert "generated from a declarative plan through MCP" in text
    assert "AI devices" in text

    budget_table = server.get_table_text(str(destination), 1)["data"]
    assert budget_table[0] == ["Item", "Amount", "Note"]
    assert budget_table[1][0] == "AI devices"

    outline = server.get_document_outline(str(destination))["outline"]
    levels_by_text = {item["text"]: item["level"] for item in outline}
    assert levels_by_text["Executive Summary"] == 1
    assert levels_by_text["Budget"] == 2
    assert set(levels_by_text) == {"Executive Summary", "Budget"}


def test_table_cell_styles_paint_one_body_cell_below_the_header(tmp_path: Path) -> None:
    import zipfile

    from lxml import etree

    plan = _plan()
    plan["blocks"][4]["cellStyles"] = [
        {"row": 0, "column": "amount", "fillColor": "fff2cc", "textColor": "#c00000"}
    ]
    validation = server.validate_document_plan(plan)
    assert validation["can_create"] is True
    assert validation["normalizedPlan"]["blocks"][4]["cellStyles"] == [
        {"row": 0, "column": "amount", "fillColor": "#FFF2CC", "textColor": "#C00000"}
    ]
    destination = tmp_path / "cell-styles.hwpx"
    assert server.create_document_from_plan(str(destination), plan)["created"] is True
    assert validate_package(destination).ok
    assert validate_document(destination).ok

    hh = "{http://www.hancom.co.kr/hwpml/2011/head}"
    hc = "{http://www.hancom.co.kr/hwpml/2011/core}"
    hp = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
    with zipfile.ZipFile(destination) as package:
        header = etree.fromstring(package.read("Contents/header.xml"))
        section = etree.fromstring(package.read("Contents/section0.xml"))
    faces = {}
    for fill in header.iter(f"{hh}borderFill"):
        brush = fill.find(f".//{hc}winBrush")
        faces[fill.get("id")] = brush.get("faceColor") if brush is not None else None
    text_colors = {char.get("id"): char.get("textColor") for char in header.iter(f"{hh}charPr")}
    budget = next(
        table for table in section.iter(f"{hp}tbl") if "AI devices" in "".join(table.itertext())
    )
    rows = [list(row.iter(f"{hp}tc")) for row in budget.iter(f"{hp}tr")]
    painted = {
        (row_index, col_index)
        for row_index, row in enumerate(rows)
        for col_index, cell in enumerate(row)
        if faces[cell.get("borderFillIDRef")] == "#FFF2CC"
    }
    assert painted == {(1, 1)}
    assert {text_colors[run.get("charPrIDRef")] for run in rows[1][1].iter(f"{hp}run")} == {"#C00000"}
    assert {text_colors[run.get("charPrIDRef")] for run in rows[1][0].iter(f"{hp}run")} != {"#C00000"}


def test_validate_document_plan_refuses_cell_styles_it_cannot_place() -> None:
    plan = _plan()
    plan["blocks"][4]["cellStyles"] = [
        {"row": 1, "column": "amount", "fillColor": "#FFF2CC"},
        {"row": 0, "column": "price", "fillColor": "#FFF2CC"},
        {"row": 0, "column": "amount", "fillColor": "yellow"},
        {"row": 0, "column": "amount"},
    ]

    result = server.validate_document_plan(plan)

    assert result["can_create"] is False
    codes = {issue["path"]: issue["code"] for issue in result["issues"]}
    assert codes["blocks[4].cellStyles[0].row"] == "invalid_cell_style_row"
    assert codes["blocks[4].cellStyles[1].column"] == "invalid_cell_style_column"
    assert codes["blocks[4].cellStyles[2].fillColor"] == "invalid_cell_style_color"
    assert codes["blocks[4].cellStyles[3]"] == "missing_cell_style_color"


def test_create_document_from_plan_returns_operating_plan_profile_and_handoff_status(tmp_path: Path) -> None:
    destination = tmp_path / "operating-plan.hwpx"

    result = server.create_document_from_plan(
        str(destination),
        _operating_plan(),
        quality_profile="operating_plan",
    )

    assert result["created"] is True
    assert result["handoff_status"] == "ready"
    assert result["next_action"].startswith("structural handoff is ready")
    assert result["quality"]["pass"] is True
    assert result["quality"]["profiles"]["operating_plan"]["pass"] is True
    assert result["quality"]["profiles"]["operating_plan"]["score"] >= 4.0
    assert result["verification"]["openSafety"]["ok"] is True
    assert validate_package(destination).ok
    assert validate_document(destination).ok

    text = server.get_document_text(str(destination))["text"]
    assert "2026 AI 중점학교 운영계획서" in text
    assert "성과 관리" in text

    schedule_table = server.get_table_text(str(destination), 1)["data"]
    assert schedule_table[0] == ["단계", "기간", "세부 추진 내용", "담당"]

    profile = server.inspect_operating_plan_quality(str(destination), _operating_plan())
    assert profile["pass"] is True


def test_sparse_operating_plan_is_created_but_marked_needs_revision(tmp_path: Path) -> None:
    destination = tmp_path / "sparse-operating-plan.hwpx"

    result = server.create_document_from_plan(
        str(destination),
        _sparse_operating_plan(),
        quality_profile="operating_plan",
    )

    assert result["created"] is True
    assert destination.exists()
    assert result["handoff_status"] == "needs_revision"
    assert result["quality"]["pass"] is False
    profile = result["quality"]["profiles"]["operating_plan"]
    assert profile["pass"] is False
    assert any("schedule_table" in gap for gap in profile["gaps"])
    assert any(hint["dimension"] == "placeholder_residue" for hint in profile["repair_hints"])
    assert result["next_action"].startswith("review quality.gaps")


def test_document_plan_jsonrpc_tool_call(mcp_server_factory, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    destination = workspace / "rpc-plan.hwpx"
    client = mcp_server_factory(cwd=workspace)

    create_result = client.call_tool(
        "create_document_from_plan",
        {
            "filename": str(destination),
            "document_plan": _operating_plan(),
            "quality_profile": "operating_plan",
        },
    )
    payload = client.parse_tool_result_payload(create_result)

    assert isinstance(payload, dict)
    assert payload["created"] is True
    assert payload["handoff_status"] == "ready"
    assert payload["quality"]["pass"] is True
    assert payload["quality"]["profiles"]["operating_plan"]["pass"] is True
    assert destination.exists()

    read_result = client.call_tool("get_document_text", {"filename": str(destination)})
    read_payload = client.parse_tool_result_payload(read_result)

    assert isinstance(read_payload, dict)
    assert "2026 AI 중점학교 운영계획서" in read_payload["text"]


def test_document_plan_jsonrpc_tools_list_exposes_sanitized_profile_arguments(mcp_server_factory, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    client = mcp_server_factory(cwd=workspace)

    tools = {tool["name"]: tool for tool in client.list_tools()}

    assert "analyze_document_plan" in tools
    assert "inspect_operating_plan_quality" in tools
    create_schema = tools["create_document_from_plan"]["inputSchema"]
    inspect_schema = tools["inspect_document_authoring_quality"]["inputSchema"]
    analyze_schema = tools["analyze_document_plan"]["inputSchema"]
    for schema in (create_schema, inspect_schema, analyze_schema):
        assert schema["type"] == "object"
        assert "quality_profile" in schema["properties"]
        assert "$defs" not in schema
        assert "$ref" not in schema
