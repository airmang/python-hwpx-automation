# SPDX-License-Identifier: Apache-2.0
"""The automation template analyzer delegates format reading to core (#176).

``hwpx.tools.template_analyzer`` is the one implementation. These tests pin
that the automation import path hands out core's objects, that the cell
geometry is core's *effective* margin, that the page is reported as Hancom
draws it, and that the CLI keeps its schema options and output order.

The effective-margin expectations need core 6.7.0 (``cell_margins_of``) and
the drawn-page expectations core 6.6.0 (``_drawn_page_size``); on an older
core those cases are skipped and the parity case still holds.
"""

from __future__ import annotations

import dataclasses
import io
import json
import re
import zipfile
from pathlib import Path

import hwpx.oxml.table_sizes as core_table_sizes
import hwpx.tools.template_analyzer as core_template
import pytest
from hwpx import HwpxDocument

import hwpx_automation.office.authoring.template_analyzer as template_analyzer

_SECTION = "Contents/section0.xml"
_HAS_EFFECTIVE_MARGINS = hasattr(core_table_sizes, "cell_margins_of")
_SIDES = ("left", "right", "top", "bottom")


def _margin(tag: str, values: dict[str, str] | None) -> str:
    if values is None:
        return ""
    attrs = " ".join(f'{side}="{values[side]}"' for side in _SIDES if side in values)
    return f"<hp:{tag} {attrs}/>"


def _cell(col: int, has_margin: str | None, own: dict[str, str] | None, inner: str = "") -> str:
    flag = "" if has_margin is None else f' hasMargin="{has_margin}"'
    return (
        f'<hp:tc borderFillIDRef="3"{flag}><hp:subList vertAlign="CENTER">'
        f'<hp:p paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0"><hp:t>c{col}</hp:t>{inner}</hp:run></hp:p>'
        f'</hp:subList><hp:cellAddr colAddr="{col}" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
        f'<hp:cellSz width="1000" height="282"/>{_margin("cellMargin", own)}</hp:tc>'
    )


def _table(table_margin: dict[str, str] | None, cells: list[str]) -> str:
    return (
        f'<hp:tbl id="7" rowCnt="1" colCnt="{len(cells)}" cellSpacing="0" borderFillIDRef="3">'
        '<hp:sz width="2000" height="282"/>'
        f'{_margin("inMargin", table_margin)}<hp:tr>{"".join(cells)}</hp:tr></hp:tbl>'
    )


def _template(tmp_path: Path, table_xml: str, *, landscape: str | None = "WIDELY") -> Path:
    doc = HwpxDocument.new()
    doc.add_table(1, 1)
    source = doc.to_bytes()
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source)) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename == _SECTION:
                text = data.decode("utf-8")
                text = re.sub(r"<hp:tbl\b.*?</hp:tbl>", lambda _m: table_xml, text, count=1, flags=re.DOTALL)
                attr = "" if landscape is None else f' landscape="{landscape}"'
                text = re.sub(r'<hp:pagePr landscape="[A-Z]+"', f"<hp:pagePr{attr}", text, count=1)
                data = text.encode("utf-8")
            dst.writestr(info, data)
    path = tmp_path / "template.hwpx"
    path.write_bytes(out.getvalue())
    return path


TABLE = {"left": "100", "right": "100", "top": "20", "bottom": "20"}
OWN = {"left": "900", "right": "900", "top": "90", "bottom": "90"}

# (hasMargin, table inMargin, cell cellMargin, expected effective margin)
MARGIN_CASES = [
    ("0", TABLE, OWN, TABLE),
    ("false", TABLE, OWN, TABLE),
    (None, TABLE, OWN, TABLE),  # absent: OWPML default is false
    ("1", TABLE, OWN, OWN),
    ("true", TABLE, OWN, OWN),
    ("1", TABLE, None, TABLE),  # on, but the cell has none: falls back
    ("0", None, OWN, OWN),  # off, but the table has none: falls back
    ("0", None, None, dict.fromkeys(_SIDES, "0")),
    ("0", {"left": "abc", "right": "-5", "top": "", "bottom": "7"}, OWN, {"left": "0", "right": "-5", "top": "0", "bottom": "7"}),
]


def test_the_automation_path_hands_out_cores_objects() -> None:
    for name in template_analyzer.__all__:
        if name in {"main", "template_analysis_agent_schema"}:
            continue
        assert getattr(template_analyzer, name) is getattr(core_template, name), name
    assert template_analyzer.TEMPLATE_ANALYSIS_SCHEMA_VERSION == core_template.TEMPLATE_ANALYSIS_SCHEMA_VERSION


@pytest.mark.parametrize(("has_margin", "table_margin", "own", "expected"), MARGIN_CASES)
def test_cell_margin_is_the_effective_margin(
    tmp_path: Path,
    has_margin: str | None,
    table_margin: dict[str, str] | None,
    own: dict[str, str] | None,
    expected: dict[str, str],
) -> None:
    path = _template(tmp_path, _table(table_margin, [_cell(0, has_margin, own)]))

    analysis = template_analyzer.analyze_template(path)

    assert dataclasses.asdict(analysis) == dataclasses.asdict(core_template.analyze_template(path))
    if not _HAS_EFFECTIVE_MARGINS:
        pytest.skip("installed python-hwpx predates effective cell margins (6.7.0)")
    (table,) = analysis.table_summaries
    assert table.cells[0].margin == {side: int(expected[side]) for side in _SIDES}


def test_a_nested_cell_reads_its_own_tables_margin(tmp_path: Path) -> None:
    inner = _table({"left": "33", "right": "33", "top": "3", "bottom": "3"}, [_cell(0, "0", OWN)])
    outer = _table(TABLE, [_cell(0, "0", OWN, inner=f"<hp:ctrl/>{inner}")])
    path = _template(tmp_path, outer)

    analysis = template_analyzer.analyze_template(path)

    assert dataclasses.asdict(analysis) == dataclasses.asdict(core_template.analyze_template(path))
    if not _HAS_EFFECTIVE_MARGINS:
        pytest.skip("installed python-hwpx predates effective cell margins (6.7.0)")
    margins = sorted(cell.margin["left"] for table in analysis.table_summaries for cell in table.cells)
    assert margins == [33, 100]


@pytest.mark.parametrize(
    ("landscape", "drawn"),
    [("WIDELY", (59528, 84186)), ("NARROWLY", (84186, 59528)), (None, (84186, 59528))],
)
def test_page_size_is_reported_as_drawn(tmp_path: Path, landscape: str | None, drawn: tuple[int, int]) -> None:
    if not hasattr(__import__("hwpx.oxml.section_format", fromlist=["_"]), "_drawn_page_size"):
        pytest.skip("installed python-hwpx predates drawn page sizes (6.6.0)")
    path = _template(tmp_path, _table(TABLE, [_cell(0, "0", OWN)]), landscape=landscape)

    (layout, *_rest) = template_analyzer.analyze_template(path).section_layouts

    assert (layout.page_width, layout.page_height) == drawn
    assert layout.computed_body_width == drawn[0] - 8504 - 8504


def _run_cli(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    status = template_analyzer.main(argv)
    return status, capsys.readouterr().out


def test_cli_schema_only_prints_just_the_schema(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _template(tmp_path, _table(TABLE, [_cell(0, "0", OWN)]))
    status, out = _run_cli([str(path), "--schema-json"], capsys)
    assert status == 0
    assert json.loads(out) == template_analyzer.template_analysis_agent_schema()


def test_cli_schema_only_also_writes_the_requested_schema_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _template(tmp_path, _table(TABLE, [_cell(0, "0", OWN)]))
    schema_file = tmp_path / "output" / "schema.json"

    status, out = _run_cli(
        [str(path), "--schema-json", "--output-schema-json", str(schema_file)], capsys
    )

    assert status == 0
    assert json.loads(out) == template_analyzer.template_analysis_agent_schema()
    assert json.loads(schema_file.read_text(encoding="utf-8")) == json.loads(out)


def test_cli_keeps_json_then_schema_then_extracted_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _template(tmp_path, _table(TABLE, [_cell(0, "0", OWN)]))
    header = tmp_path / "out" / "header.xml"
    schema_file = tmp_path / "out" / "schema.json"

    status, out = _run_cli(
        [str(path), "--json", "--schema-json", "--output-schema-json", str(schema_file), "--extract-header", str(header)],
        capsys,
    )

    assert status == 0
    analysis_end = out.index("\n}\n") + 3
    analysis = json.loads(out[:analysis_end])
    assert analysis["schema_version"] == core_template.TEMPLATE_ANALYSIS_SCHEMA_VERSION
    rest = out[analysis_end:]
    schema_end = rest.index("\n}\n") + 3
    assert json.loads(rest[:schema_end]) == template_analyzer.template_analysis_agent_schema()
    assert rest[schema_end:].splitlines() == [f"extracted: {header}"]
    assert json.loads(schema_file.read_text(encoding="utf-8"))["schemaVersion"] == (
        template_analyzer.TEMPLATE_ANALYSIS_AGENT_SCHEMA_VERSION
    )
    assert header.is_file()


def test_cli_reports_a_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    status, out = _run_cli([str(tmp_path / "missing.hwpx"), "--schema-json"], capsys)
    assert status == 1 and out.startswith("ERROR: file not found")
    status, out = _run_cli([str(tmp_path / "missing.hwpx"), "--json"], capsys)
    assert status == 1 and out.startswith("ERROR: file not found")
