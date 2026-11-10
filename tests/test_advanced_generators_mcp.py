from __future__ import annotations

import base64
from pathlib import Path

from hwpx.tools.package_validator import validate_editor_open_safety
from hwpx_automation import server
from hwpx_automation.fastmcp_adapter import snapshot_runtime_tools


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_advanced_generator_tools_are_exposed() -> None:
    names = set(snapshot_runtime_tools(server.mcp))

    assert {
        "build_image_grid",
        "build_meeting_nameplates",
        "build_organization_chart",
    }.issubset(names)


def test_build_image_grid_returns_create_ready_plan(tmp_path: Path) -> None:
    image_path = tmp_path / "site.png"
    image_path.write_bytes(PNG_1X1)

    result = server.build_image_grid(
        [{"path": str(image_path), "caption": "현장 사진"}],
        columns=1,
        image_width_mm=20,
    )

    assert result["block"]["type"] == "image_grid"
    assert result["next_tool"] == "create_document_from_plan"
    validation = server.validate_document_plan(result["document_plan"])
    assert validation["ok"] is True

    target = tmp_path / "photo-grid.hwpx"
    created = server.create_document_from_plan(str(target), result["document_plan"])
    assert created["created"] is True
    assert created["verification"]["openSafety"]["ok"] is True
    assert validate_editor_open_safety(target).ok is True


def test_nameplate_and_org_chart_tools_return_table_blocks() -> None:
    nameplates = server.build_meeting_nameplates(["김하나", "이두리", "박세진"], columns=2)
    chart = server.build_organization_chart(
        {
            "name": "위원장",
            "children": [
                {"name": "기획팀", "children": [{"name": "교육과정"}]},
                {"name": "운영팀", "children": [{"name": "시설"}]},
            ],
        }
    )

    assert nameplates["block"]["type"] == "table"
    assert nameplates["block"]["rows"][0] == ["김하나", "이두리"]
    assert chart["block"]["type"] == "table"
    assert ["위원장", "기획팀", "교육과정"] in chart["block"]["rows"]
    assert server.validate_document_plan(chart["document_plan"])["ok"] is True
