from __future__ import annotations

import base64
from pathlib import Path

from hwpx.document import HwpxDocument
from hwpx.tools.package_validator import validate_editor_open_safety
from hwpx_automation import server
from hwpx_automation.fastmcp_adapter import snapshot_runtime_tools


def _reference_doc(path: Path) -> None:
    document = HwpxDocument.new()
    # Hancom's own landscape form: the paper's portrait size with
    # landscape="NARROWLY", which Hancom turns. python-hwpx 6.5 stored
    # orientation="LANDSCAPE" as an unknown value that Hancom drew portrait.
    document.page.set_size(width=36000, height=72000, orientation="NARROWLY")
    document.page.set_margins(left=7000, right=5000, top=3000, bottom=3000, header=1500, footer=1600, gutter=1000)
    document.add_paragraph("{{student}} 안내")
    table = document.add_table(2, 3, width=30000)
    table.set_column_widths([2, 1, 1])
    table.set_cell_text(0, 0, "구분")
    table.set_cell_text(0, 1, "내용")
    table.set_cell_text(0, 2, "비고")
    table.set_cell_text(1, 0, "A")
    table.set_cell_text(1, 1, "${teacher}")
    table.set_cell_text(1, 2, "확인")
    document.save_to_path(path)
    document.close()


def test_style_profile_tools_are_exposed() -> None:
    names = set(snapshot_runtime_tools(server.mcp))

    assert {
        "extract_style_profile",
        "apply_style_profile_to_plan",
        "compare_style_profiles",
        "register_template",
        "list_templates",
        "describe_template",
    }.issubset(names)


def test_style_profile_apply_create_and_compare(tmp_path: Path) -> None:
    reference = tmp_path / "reference.hwpx"
    target = tmp_path / "target.hwpx"
    _reference_doc(reference)

    profile = server.extract_style_profile(str(reference))
    applied = server.apply_style_profile_to_plan(
        {
            "schemaVersion": "hwpx.document_plan.v2",
            "title": "서식 이식",
            "sections": [
                {
                    "blocks": [
                        {"type": "heading", "level": 1, "text": "서식 이식"},
                        {
                            "type": "table",
                            "header": ["구분", "내용", "비고"],
                            "rows": [["A", "본문", "확인"]],
                        },
                    ]
                }
            ],
        },
        style_profile=profile,
    )
    created = server.create_document_from_plan(str(target), applied["document_plan"])
    compared = server.compare_style_profiles(reference_profile=profile, candidate_filename=str(target))

    assert applied["document_plan"]["sections"][0]["page"]["orientation"] == "LANDSCAPE"
    assert created["verification"]["openSafety"]["ok"] is True
    assert validate_editor_open_safety(target).ok is True
    assert compared["pass"] is True


def test_template_registry_roundtrip_and_missing_placeholder_report(tmp_path: Path) -> None:
    reference = tmp_path / "template.hwpx"
    registry = tmp_path / "registry.json"
    _reference_doc(reference)

    registered = server.register_template("notice", str(reference), registry_path=str(registry), tags=["school"])
    listed = server.list_templates(registry_path=str(registry))
    described = server.describe_template("notice", registry_path=str(registry), values={"student": "김하나"})

    assert registered["placeholderKeys"] == ["student", "teacher"]
    assert listed["templates"][0]["name"] == "notice"
    assert described["placeholderReport"]["missingKeys"] == ["teacher"]


def test_hwpx_extract_json_format_detail_is_opt_in(tmp_path: Path) -> None:
    target = tmp_path / "format-detail.hwpx"
    _reference_doc(target)
    payload = base64.b64encode(target.read_bytes()).decode("ascii")

    basic = server.hwpx_extract_json(hwpx_base64=payload)
    detailed = server.hwpx_extract_json(hwpx_base64=payload, format_detail=True)

    first_basic = basic["doc"]["sections"][0]["paragraphs"][0]
    first_detailed = detailed["doc"]["sections"][0]["paragraphs"][0]
    assert "format" not in first_basic
    assert "format_detail" not in basic["meta"]
    assert first_detailed["format"]["runs"]
    assert detailed["doc"]["tables"][0]["format"]["cells"]
    assert detailed["meta"]["format_detail"] is True
