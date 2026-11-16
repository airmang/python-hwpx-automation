from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

from hwpx.document import HwpxDocument
from hwpx.tools.package_validator import validate_editor_open_safety
from hwpx_automation import server
from hwpx_automation.fastmcp_adapter import snapshot_runtime_tools


def _template(path: Path) -> None:
    doc = HwpxDocument.new()
    doc.add_paragraph("{{student}} 상장")
    doc.add_paragraph("담임 ${teacher} / 학급 {{class_name}}")
    doc.save(path)
    doc.close()


def test_mail_merge_tools_are_exposed() -> None:
    names = set(snapshot_runtime_tools(server.mcp))

    assert {
        "inspect_mail_merge_placeholders",
        "mail_merge",
        "table_compute",
    }.issubset(names)


def test_mail_merge_returns_zip_and_open_safety_evidence(tmp_path: Path) -> None:
    template = tmp_path / "award-template.hwpx"
    _template(template)

    result = server.mail_merge(
        str(template),
        data_rows=[
            {"student": "김하나", "teacher": "이교사", "class_name": "1-1"},
            {"student": "박두리", "teacher": "최교사", "class_name": "1-2"},
        ],
        output_dir=str(tmp_path / "out"),
        filename_pattern="{index:03d}-{student}.hwpx",
        zip_filename=str(tmp_path / "awards.zip"),
    )

    assert result["ok"] is True
    assert result["openSafety"]["ok"] is True
    assert result["verification"]["openSafety"]["checkedCount"] == 2
    assert validate_editor_open_safety(result["rows"][0]["filename"]).ok is True
    with ZipFile(tmp_path / "awards.zip") as archive:
        assert sorted(archive.namelist()) == ["001-김하나.hwpx", "002-박두리.hwpx"]


def test_mail_merge_reports_missing_placeholders(tmp_path: Path) -> None:
    template = tmp_path / "notice-template.hwpx"
    _template(template)

    placeholders = server.inspect_mail_merge_placeholders(str(template))
    result = server.mail_merge(
        str(template),
        data_rows=[{"student": "김하나", "class_name": "1-1"}],
        output_dir=str(tmp_path / "missing"),
    )

    assert placeholders["keys"] == ["class_name", "student", "teacher"]
    assert result["ok"] is False
    assert result["rowsWithIssues"] == [1]
    assert result["rows"][0]["missingKeys"] == ["teacher"]
    assert result["rows"][0]["openSafety"]["ok"] is True


def test_mail_merge_hundred_rows_are_open_safe(tmp_path: Path) -> None:
    template = tmp_path / "bulk-template.hwpx"
    _template(template)
    rows = [
        {"student": f"학생{index:03d}", "teacher": "담임", "class_name": "3-1"}
        for index in range(1, 101)
    ]

    result = server.mail_merge(str(template), data_rows=rows, output_dir=str(tmp_path / "bulk"))

    assert result["createdCount"] == 100
    assert result["openSafety"]["ok"] is True
    assert all(row["openSafety"]["ok"] for row in result["rows"])


def test_table_compute_returns_computed_table_and_evidence() -> None:
    result = server.table_compute(
        {
            "type": "table",
            "columns": [
                {"key": "team", "label": "팀"},
                {"key": "name", "label": "항목"},
                {"key": "amount", "label": "금액"},
            ],
            "rows": [
                {"team": "A", "name": "x", "amount": "100"},
                {"team": "A", "name": "y", "amount": "200"},
                {"team": "B", "name": "z", "amount": "300"},
            ],
        },
        value_columns=["amount"],
        operations=["subtotal", "sum"],
        group_by="team",
        label_column="name",
    )

    assert result["computedTable"]["rows"][2]["name"] == "A 소계"
    assert result["computedTable"]["rows"][-1]["amount"] == "600"
    assert any(item["operation"] == "sum" for item in result["evidence"])
