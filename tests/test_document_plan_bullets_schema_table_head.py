# SPDX-License-Identifier: Apache-2.0
"""Document plans: nested bullets, the schema's top-level blocks, and the header row of a table with
a look of its own (automation #215, #214).

- #215: a bullets item ``{"text": ..., "children": [...]}`` was written as its Python form
  (``{'text': ...}``) and the plan validated; a v2 plan in the shape ``get_document_plan_schema()``
  describes (top-level ``blocks``) was refused (``sections must be a non-empty list``).
- #214: a v2 table that gives ``headerShading``, ``columnWidths`` or ``merges`` lost the table look's
  header row (not bold, ``JUSTIFY``, ``repeatHeader="0"``) and had equal columns.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile

import pytest

from hwpx_automation.office.authoring import (
    BuilderTable,
    create_document_from_plan,
    get_document_plan_schema,
    validate_document_plan,
)

V1 = "hwpx.document_plan.v1"
V2 = "hwpx.document_plan.v2"
NS = {
    "hh": "http://www.hancom.co.kr/hwpml/2011/head",
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hc": "http://www.hancom.co.kr/hwpml/2011/core",
}
NESTED = [
    "Top one",
    {"text": "Parent item", "children": ["Child A", {"text": "Child B", "children": ["Grandchild"]}]},
    "Top two",
]
TABLE = {
    "type": "table",
    "header": ["Kind", "Status", "Meaning"],
    "rows": [["Alpha", "a longer status line that needs room", "base"], ["Beta", "short", "small"]],
}


def _bytes(plan: dict) -> bytes:
    document = create_document_from_plan(plan)
    try:
        return document.to_bytes()
    finally:
        document.close()


def _parts(data: bytes) -> tuple[ET.Element, ET.Element]:
    package = zipfile.ZipFile(io.BytesIO(data))
    return (
        ET.fromstring(package.read("Contents/header.xml")),
        ET.fromstring(package.read("Contents/section0.xml")),
    )


def _list_paragraphs(data: bytes) -> list[tuple[str, str | None, int]]:
    """(text, list level of its bullet head, left margin) of each bullet paragraph."""

    header, section = _parts(data)
    shapes = {shape.get("id"): shape for shape in header.iter(f"{{{NS['hh']}}}paraPr")}
    found = []
    for paragraph in section.iter(f"{{{NS['hp']}}}p"):
        text = "".join(t.text or "" for t in paragraph.iter(f"{{{NS['hp']}}}t"))
        shape = shapes[paragraph.get("paraPrIDRef")]
        heading = shape.find("hh:heading", NS)
        if not text or heading is None or heading.get("type") != "BULLET":
            continue
        left = shape.find(".//hc:left", NS)
        found.append((text, heading.get("level"), int(left.get("value")) if left is not None else 0))
    return found


def _all_text(data: bytes) -> str:
    _header, section = _parts(data)
    return "".join(t.text or "" for t in section.iter(f"{{{NS['hp']}}}t"))


def _first_table(data: bytes) -> dict:
    header, section = _parts(data)
    fills = {fill.get("id"): fill for fill in header.iter(f"{{{NS['hh']}}}borderFill")}
    chars = {char.get("id"): char for char in header.iter(f"{{{NS['hh']}}}charPr")}
    shapes = {shape.get("id"): shape for shape in header.iter(f"{{{NS['hh']}}}paraPr")}
    table = next(section.iter(f"{{{NS['hp']}}}tbl"))
    head_cells = table.find("hp:tr", NS).findall("hp:tc", NS)
    heads = []
    for cell in head_cells:
        brush = fills[cell.get("borderFillIDRef")].find(".//hc:winBrush", NS)
        paragraph = cell.find(".//hp:p", NS)
        runs = [run for run in paragraph.findall("hp:run", NS) if run.find("hp:t", NS) is not None]
        heads.append(
            {
                "fill": brush.get("faceColor") if brush is not None else None,
                "bold": all(chars[run.get("charPrIDRef")].find("hh:bold", NS) is not None for run in runs),
                "align": shapes[paragraph.get("paraPrIDRef")].find("hh:align", NS).get("horizontal"),
                "is_header": cell.get("header"),
            }
        )
    return {
        "repeatHeader": table.get("repeatHeader"),
        "widths": [int(cell.find("hp:cellSz", NS).get("width")) for cell in head_cells],
        "heads": heads,
    }


# --------------------------------------------------------------------------- #215: plan shape


def test_schema_shaped_v2_plan_with_top_level_blocks_is_created() -> None:
    schema = get_document_plan_schema()
    assert schema["required"] == ["schemaVersion", "blocks"]
    plan = {
        "schemaVersion": V2,
        "blocks": [{"type": "heading", "level": 1, "text": "Plan heading"}, {"type": "paragraph", "text": "Body line"}],
    }

    report = validate_document_plan(plan)

    assert report.ok, report.errors
    text = _all_text(_bytes(plan))
    assert "Plan heading" in text and "Body line" in text


def test_top_level_blocks_and_sections_together_are_refused() -> None:
    plan = {
        "schemaVersion": V2,
        "blocks": [{"type": "paragraph", "text": "first"}],
        "sections": [{"blocks": [{"type": "paragraph", "text": "second"}]}],
    }

    report = validate_document_plan(plan)

    assert not report.ok
    assert [issue.code for issue in report.issues] == ["conflicting_plan_body"]
    with pytest.raises(ValueError, match="both given"):
        create_document_from_plan(plan)


def test_v2_plan_without_blocks_or_sections_still_names_both_ways() -> None:
    report = validate_document_plan({"schemaVersion": V2})

    assert not report.ok
    assert report.issues[0].code == "missing_sections"
    assert "top level" in report.issues[0].suggestion


# --------------------------------------------------------------------------- #215: nested bullets


@pytest.mark.parametrize(
    "plan",
    [
        {"schemaVersion": V2, "sections": [{"blocks": [{"type": "bullets", "items": NESTED}]}]},
        {"schemaVersion": V2, "blocks": [{"type": "bullets", "items": NESTED}]},
        {"schemaVersion": V1, "title": "Nested", "blocks": [{"type": "bullets", "items": NESTED}]},
    ],
    ids=["v2-sections", "v2-top-level", "v1"],
)
def test_nested_bullets_are_written_as_list_levels(plan: dict) -> None:
    assert validate_document_plan(plan).ok

    data = _bytes(plan)

    assert "{'text'" not in _all_text(data)
    found = _list_paragraphs(data)
    assert [(text, level) for text, level, _left in found] == [
        ("Top one", "0"),
        ("Parent item", "0"),
        ("Child A", "1"),
        ("Child B", "1"),
        ("Grandchild", "2"),
        ("Top two", "0"),
    ]
    left = {text: margin for text, _level, margin in found}
    assert left["Top one"] < left["Child A"] < left["Grandchild"]
    assert left["Child A"] == left["Child B"]


def test_nested_bullets_in_the_report_look_are_a_list_in_a_list() -> None:
    plan = {
        "schemaVersion": V1,
        "title": "Nested",
        "metadata": {"document_type": "보고서"},
        "blocks": [{"type": "bullets", "items": NESTED}],
    }

    found = _list_paragraphs(_bytes(plan))

    assert [(text, level) for text, level, _left in found] == [
        ("Top one", "0"),
        ("Parent item", "0"),
        ("Child A", "1"),
        ("Child B", "1"),
        ("Grandchild", "2"),
        ("Top two", "0"),
    ]


def test_nested_bullets_in_a_profile_are_body_paragraphs_in_reading_order() -> None:
    plan = {
        "schemaVersion": V1,
        "title": "Nested",
        "metadata": {"document_type": "공문"},
        "blocks": [{"type": "bullets", "items": NESTED}],
    }

    text = _all_text(_bytes(plan))

    assert "{'text'" not in text
    positions = [text.index(item) for item in ("Top one", "Parent item", "Child A", "Child B", "Grandchild", "Top two")]
    assert positions == sorted(positions)


@pytest.mark.parametrize("version", [V1, V2])
@pytest.mark.parametrize(
    ("item", "code", "path"),
    [
        (None, "unsupported_bullet_item", "items[1]"),
        (["a list"], "unsupported_bullet_item", "items[1]"),
        ({"children": ["no text"]}, "unsupported_bullet_item", "items[1].text"),
        ({"text": "t", "children": "not a list"}, "unsupported_bullet_item", "items[1].children"),
    ],
)
def test_a_bullet_item_the_document_cannot_hold_is_refused(version: str, item: object, code: str, path: str) -> None:
    block = {"type": "bullets", "items": ["fine", item]}
    plan = (
        {"schemaVersion": V1, "title": "T", "blocks": [block]}
        if version == V1
        else {"schemaVersion": V2, "blocks": [block]}
    )

    report = validate_document_plan(plan)

    assert not report.ok
    assert any(issue.code == code and issue.path.endswith(path) for issue in report.issues)
    with pytest.raises(ValueError):
        create_document_from_plan(plan)


def test_bullets_nest_at_most_ten_deep() -> None:
    item: object = "deepest"
    for depth in range(10):
        item = {"text": f"level {10 - depth}", "children": [item]}

    report = validate_document_plan({"schemaVersion": V2, "blocks": [{"type": "bullets", "items": [item]}]})

    assert [issue.code for issue in report.issues] == ["bullet_too_deep"]


def test_extra_fields_of_a_bullet_item_are_named_not_written() -> None:
    plan = {"schemaVersion": V2, "blocks": [{"type": "bullets", "items": [{"text": "kept", "bold": True}]}]}

    report = validate_document_plan(plan)

    assert report.ok
    assert [(issue.code, issue.severity) for issue in report.issues] == [("ignored_bullet_item_fields", "warning")]
    assert "kept" in _all_text(_bytes(plan))


def test_a_numbered_list_item_that_is_not_text_is_refused() -> None:
    plan = {"schemaVersion": V2, "blocks": [{"type": "numbered_list", "items": ["one", {"text": "two"}]}]}

    report = validate_document_plan(plan)

    assert [issue.code for issue in report.issues] == ["unsupported_list_item"]


# --------------------------------------------------------------------------- #214: table header row


@pytest.mark.parametrize(
    ("given", "fill"),
    [
        ({}, "#DFE6F7"),
        ({"headerShading": "#D9E2F3"}, "#D9E2F3"),
        ({"columnWidths": [1, 3, 2]}, "#DFE6F7"),
        ({"merges": ["A2:A3"]}, "#DFE6F7"),
    ],
    ids=["no-look", "headerShading", "columnWidths", "merges"],
)
def test_a_v2_table_keeps_the_header_row_rule_with_a_look_of_its_own(given: dict, fill: str) -> None:
    plan = {"schemaVersion": V2, "blocks": [dict(TABLE, **given)]}

    table = _first_table(_bytes(plan))

    assert table["repeatHeader"] == "1"
    for head in table["heads"]:
        assert head == {"fill": fill, "bold": True, "align": "CENTER", "is_header": "1"}


def test_given_column_widths_stay_and_widths_not_given_follow_the_text() -> None:
    given = _first_table(_bytes({"schemaVersion": V2, "blocks": [dict(TABLE, columnWidths=[1, 3, 2])]}))
    shaded = _first_table(_bytes({"schemaVersion": V2, "blocks": [dict(TABLE, headerShading="#D9E2F3")]}))

    assert abs(given["widths"][1] - 3 * given["widths"][0]) <= 2  # rounding
    assert len(set(shaded["widths"])) == 3  # not shared alike
    assert shaded["widths"][1] == max(shaded["widths"])  # the column of long text is the widest


def test_a_v1_table_with_widths_of_its_own_repeats_its_header_row() -> None:
    plan = {
        "schemaVersion": V1,
        "title": "T",
        "blocks": [
            {
                "type": "table",
                "columns": [{"key": "a", "label": "Kind", "widthWeight": 1}, {"key": "b", "label": "Status", "widthWeight": 3}],
                "rows": [{"a": "x", "b": "y"}, {"a": "z", "b": "w"}],
            }
        ],
    }

    table = _first_table(_bytes(plan))

    assert table["repeatHeader"] == "1"
    assert all(head["bold"] and head["align"] == "CENTER" and head["is_header"] == "1" for head in table["heads"])
    assert abs(table["widths"][1] - 3 * table["widths"][0]) <= 2  # rounding


def test_an_approval_box_keeps_its_own_look() -> None:
    plan = {"schemaVersion": V2, "blocks": [{"type": "approval_box", "labels": ["Draft", "Review", "Sign"]}]}

    table = _first_table(_bytes(plan))

    assert table["repeatHeader"] == "0"
    assert not any(head["bold"] for head in table["heads"])


def test_a_plan_table_seeds_the_ids_the_public_table_did() -> None:
    from hwpx_automation.office.authoring import _PlanBuilderTable

    fields = {"header": ("a",), "rows": (("b",),), "column_widths": (1,)}

    assert repr(_PlanBuilderTable(**fields)) == repr(BuilderTable(**fields))


@pytest.mark.parametrize("version", [V1, V2])
def test_table_profile_government_draws_the_default_table(version: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    if version == V1:
        block = {"type": "table", "columns": [{"key": "a", "label": "Kind"}], "rows": [{"a": "x"}]}
        plan = {"schemaVersion": V1, "title": "T", "blocks": [block]}
        government = {"schemaVersion": V1, "title": "T", "blocks": [dict(block, tableProfile="government")]}
        # v1 ids are seeded from the plan itself, so only the table is compared.
        assert _first_table(_bytes(government)) == _first_table(_bytes(plan))
    else:
        plan = {"schemaVersion": V2, "blocks": [dict(TABLE)]}
        government = {"schemaVersion": V2, "blocks": [dict(TABLE, tableProfile="government")]}
        assert _bytes(government) == _bytes(plan)
    unknown = dict(government)
    unknown["blocks"] = [dict(government["blocks"][0], tableProfile="fancy")]
    assert [issue.code for issue in validate_document_plan(unknown).issues] == ["unknown_table_profile"]
