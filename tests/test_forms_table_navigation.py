# SPDX-License-Identifier: Apache-2.0
"""Label-addressed cells: ``find_cell_by_label`` and ``fill_by_path``.

Moved with the code from python-hwpx (tests/test_table_navigation.py without the
table-map tests, which stay with ``doc.tables.map()``; the label tests of
tests/test_ns_tables.py; one test of tests/test_text_inline_elements.py).
"""

from __future__ import annotations

import io
import zipfile

import pytest

from hwpx import HwpxDocument
from hwpx_automation.forms import fill_by_path, find_cell_by_label


@pytest.mark.parametrize("direction,merge,label_at,target", [
    ("right", "A1:B1", (0, 0), (0, 2)),
    ("left", "B1:C1", (0, 1), (0, 0)),
    ("down", "A1:A2", (0, 0), (2, 0)),
    ("up", "A2:A3", (1, 0), (0, 0)),
])
def test_merged_label_is_unique_and_navigation_leaves_its_span(direction, merge, label_at, target):
    with HwpxDocument.new() as document:
        table = document.add_table(3, 3)
        document.tables.merge_cells(table, merge)
        table.cell(*label_at).text = "라벨"
        result = fill_by_path(document, {f"라벨 > {direction}": "값"})
        assert result["failed"] == []
        assert result["applied_count"] == 1
        assert (result["applied"][0]["row"], result["applied"][0]["col"]) == target
        assert table.cell(*target).text == "값"
        assert table.cell(*label_at).text == "라벨"


def test_two_distinct_merged_labels_are_still_ambiguous():
    with HwpxDocument.new() as document:
        table = document.add_table(2, 3)
        for row, region in [(0, "A1:B1"), (1, "A2:B2")]:
            document.tables.merge_cells(table, region)
            table.cell(row, 0).text = "라벨"
        assert find_cell_by_label(document, "라벨")["count"] == 2
        result = fill_by_path(document, {"라벨 > right": "값"})
        assert result["applied_count"] == 0
        assert result["failed"][0]["reason"] == "ambiguous label"


def test_fill_by_path_handles_unique_labels_in_a_single_table() -> None:
    document = HwpxDocument.new()
    document.add_paragraph("1. 기본 현황")
    table = document.add_table(2, 2)
    table.cell(0, 0).text = "성명:"
    table.cell(1, 0).text = "소속"

    result = fill_by_path(
        document,
        {
            "성명 > right": "홍길동",
            "소속 > right": "플랫폼팀",
        },
    )

    assert result["applied_count"] == 2
    assert result["failed_count"] == 0
    assert table.cell(0, 1).text == "홍길동"
    assert table.cell(1, 1).text == "플랫폼팀"


def test_find_cell_by_label_normalizes_trailing_colons() -> None:
    document = HwpxDocument.new()
    document.add_paragraph("기본 정보")
    table = document.add_table(1, 2)
    table.cell(0, 0).text = "성명:"

    result = find_cell_by_label(document, "성명")

    assert result["count"] == 1
    assert result["matches"][0]["table_index"] == 0
    assert result["matches"][0]["label_cell"] == {
        "row": 0,
        "col": 0,
        "text": "성명:",
    }
    assert result["matches"][0]["target_cell"] == {
        "row": 0,
        "col": 1,
        "text": "",
    }


def test_multiple_tables_with_the_same_label_return_all_matches_and_make_fill_ambiguous() -> None:
    document = HwpxDocument.new()
    document.add_paragraph("1. 신청인")
    first = document.add_table(1, 2)
    first.cell(0, 0).text = "성명"

    document.add_paragraph("2. 보호자")
    second = document.add_table(1, 2)
    second.cell(0, 0).text = "성명"

    matches = find_cell_by_label(document, "성명")
    fill_result = fill_by_path(document, {"성명 > right": "홍길동"})

    assert matches["count"] == 2
    assert [match["table_index"] for match in matches["matches"]] == [0, 1]
    assert fill_result["applied_count"] == 0
    assert fill_result["failed_count"] == 1
    assert fill_result["failed"][0] == {
        "path": "성명 > right",
        "reason": "ambiguous label",
        "candidates": [
            {"table_index": 0, "row": 0, "col": 0, "text": "성명", "selector": "성명[1]"},
            {"table_index": 1, "row": 0, "col": 0, "text": "성명", "selector": "성명[2]"},
        ],
    }
    assert first.cell(0, 1).text == ""
    assert second.cell(0, 1).text == ""


def test_out_of_bounds_candidates_are_skipped_and_reported_for_batch_fill() -> None:
    document = HwpxDocument.new()
    document.add_paragraph("경계 값")
    table = document.add_table(2, 2)
    table.cell(0, 1).text = "마지막열"
    table.cell(1, 0).text = "마지막행"

    right_matches = find_cell_by_label(document, "마지막열", direction="right")
    down_matches = find_cell_by_label(document, "마지막행", direction="down")
    fill_result = fill_by_path(
        document,
        {
            "마지막열 > right": "실패",
            "마지막행 > down": "실패",
        },
    )

    assert right_matches["count"] == 0
    assert down_matches["count"] == 0
    assert fill_result["applied_count"] == 0
    assert fill_result["failed_count"] == 2
    assert fill_result["failed"] == [
        {"path": "마지막열 > right", "reason": "navigation out of bounds"},
        {"path": "마지막행 > down", "reason": "navigation out of bounds"},
    ]


def test_fill_by_path_supports_multi_step_navigation() -> None:
    document = HwpxDocument.new()
    document.add_paragraph("정산표")
    table = document.add_table(3, 2)
    table.cell(0, 0).text = "합계"

    result = fill_by_path(document, {"합계 > down > right": "100"})

    assert result["applied"] == [
        {
            "path": "합계 > down > right",
            "table_index": 0,
            "row": 1,
            "col": 1,
            "value": "100",
        }
    ]
    assert result["failed"] == []
    assert table.cell(1, 1).text == "100"


def test_a_direction_other_than_right_or_down_is_refused() -> None:
    document = HwpxDocument.new()
    with pytest.raises(ValueError, match="direction"):
        find_cell_by_label(document, "성명", "left")  # type: ignore[arg-type]


def test_table_index_counts_tables_inside_cells_as_the_table_map_does() -> None:
    document = HwpxDocument.new()
    outer = document.add_table(1, 2)
    inner = outer.cell(0, 0).paragraphs[0].add_table(1, 2)
    inner.cell(0, 0).text = "안쪽"
    after = document.add_table(1, 2)
    after.cell(0, 0).text = "뒤쪽"

    mapped = [entry["table_index"] for entry in document.tables.map()["tables"]]
    assert mapped == [0, 1, 2]
    assert find_cell_by_label(document, "안쪽")["matches"][0]["table_index"] == 1
    assert find_cell_by_label(document, "뒤쪽")["matches"][0]["table_index"] == 2


# --- from tests/test_ns_tables.py ---------------------------------------------


@pytest.fixture()
def document() -> HwpxDocument:
    doc = HwpxDocument.new()
    doc.add_paragraph("본문")
    return doc


def test_find_cell_by_label_locates_the_neighbour(document: HwpxDocument) -> None:
    table = document.add_table(1, 2)
    table.set_cell_text(0, 0, "이름")
    found = find_cell_by_label(document, "이름")
    assert found["count"] == 1
    match = found["matches"][0]
    assert match["label_cell"]["col"] == 0
    assert match["target_cell"]["col"] == 1


def test_fill_by_path_writes_through_the_label_path(document: HwpxDocument) -> None:
    table = document.add_table(1, 2)
    table.set_cell_text(0, 0, "이름")
    # 경로 문법: ``라벨>방향`` — 방향이 없으면 채우지 않고 이유를 보고한다.
    result = fill_by_path(document, {"이름>right": "홍길동"})
    assert result["applied_count"] == 1, result
    assert table.cell(0, 1).text == "홍길동"

    missing_direction = fill_by_path(document, {"이름": "값"})
    assert missing_direction["applied_count"] == 0
    assert "direction" in missing_direction["failed"][0]["reason"]


def test_an_empty_mapping_is_a_no_op(document: HwpxDocument) -> None:
    result = fill_by_path(document, {})
    assert result["applied_count"] == 0 and result["failed_count"] == 0


# --- from tests/test_text_inline_elements.py ----------------------------------


def _document_with(t_xml: str) -> HwpxDocument:
    doc = HwpxDocument.new()
    doc.add_table(1, 2).set_cell_text(0, 0, "PLACEHOLDER")
    source = io.BytesIO(doc.to_bytes())
    out = io.BytesIO()
    with zipfile.ZipFile(source) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "Contents/section0.xml":
                data = data.decode("utf-8").replace("<hp:t>PLACEHOLDER</hp:t>", t_xml).encode("utf-8")
            zout.writestr(info, data, compress_type=zipfile.ZIP_STORED if info.filename == "mimetype" else zipfile.ZIP_DEFLATED)
    return HwpxDocument.open(io.BytesIO(out.getvalue()))


def test_a_spaced_form_label_is_found_by_its_letters() -> None:
    # Korean forms spread short labels with full-width spaces: "성<hp:fwSpace/>명".
    doc = _document_with('<hp:t>성<hp:fwSpace/>명</hp:t>')
    result = find_cell_by_label(doc, "성 명")
    assert result["count"] >= 1
