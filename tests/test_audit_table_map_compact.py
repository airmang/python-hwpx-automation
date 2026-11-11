# SPDX-License-Identifier: Apache-2.0
"""Audit EFF-16: ``get_table_map`` lists real cells once and bounds its size.

The map carried text, paragraphs and a location object for every logical grid
slot, a merged cell repeated for each slot it covers: 3.1 MB for a 131 KB form.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from hwpx import HwpxDocument

from hwpx_automation.core.content import get_table_map_in_doc
from hwpx_automation.server import get_table_map


def _document(path: Path, *, long_text: str = "") -> None:
    doc = HwpxDocument.new()
    doc.paragraphs[0].runs[0].text = "신청서"
    holder = doc.add_paragraph("")
    table = holder.add_table(4, 4)
    for row in range(4):
        for col in range(4):
            table.set_cell_text(row, col, f"R{row}C{col}")
    table.merge_cells(0, 0, 0, 3)  # one wide title cell
    table.merge_cells(1, 0, 2, 0)  # a tall label cell
    if long_text:
        table.set_cell_text(3, 3, long_text)
    inner_host = table.cell(3, 0).paragraphs[0]
    inner = inner_host.add_table(1, 2)
    inner.set_cell_text(0, 0, "안쪽 A")
    inner.set_cell_text(0, 1, "안쪽 B")
    doc.save_to_path(str(path))
    doc.close()


def _slots(full_table: dict) -> dict[tuple[int, int], str]:
    return {(cell["row"], cell["col"]): cell["text"] for cell in full_table["cells"]}


def test_compact_map_covers_every_slot_exactly_once(tmp_path: Path) -> None:
    target = tmp_path / "form.hwpx"
    _document(target)
    doc = HwpxDocument.open(str(target))
    try:
        full = get_table_map_in_doc(doc)  # in-process default stays the full shape
        compact = get_table_map_in_doc(doc, detail="compact")
    finally:
        doc.close()

    assert [t["table_index"] for t in compact["tables"]] == [t["table_index"] for t in full["tables"]]
    assert compact["count"] == full["count"] == 2  # outer table and the nested one
    for full_table, compact_table in zip(full["tables"], compact["tables"]):
        slots = _slots(full_table)
        covered: set[tuple[int, int]] = set()
        for cell in compact_table["cells"]:
            for row in range(cell["row"], cell["row"] + cell.get("row_span", 1)):
                for col in range(cell["col"], cell["col"] + cell.get("col_span", 1)):
                    assert (row, col) not in covered
                    covered.add((row, col))
                    assert slots[(row, col)] == cell["text"]
        assert covered == set(slots)
        assert compact_table["cell_count"] == len(compact_table["cells"])
        assert "location" not in compact_table["cells"][0]
        assert "paragraphs" not in compact_table["cells"][0]

    outer = compact["tables"][0]
    spans = {(c["row"], c["col"]): (c.get("row_span", 1), c.get("col_span", 1)) for c in outer["cells"]}
    assert spans[(0, 0)] == (1, 4)
    assert spans[(1, 0)] == (2, 1)
    assert outer["merged_cell_count"] == 2
    assert outer["cell_count"] == 16 - 3 - 1
    assert len(full["tables"][0]["cells"]) == 16


def test_tool_default_is_compact_and_full_is_the_previous_shape(tmp_path: Path) -> None:
    target = tmp_path / "form.hwpx"
    _document(target)

    default = get_table_map(str(target))
    full = get_table_map(str(target), detail="full")

    assert default["detail"] == "compact"
    assert default["cell_location"]["kind"] == "table_cell"
    assert "document_revision" in default
    assert "detail" not in full
    assert set(full["tables"][0]["cells"][0]) == {"row", "col", "text", "paragraphs", "location"}
    assert len(json.dumps(default, ensure_ascii=False)) < len(json.dumps(full, ensure_ascii=False))

    one = get_table_map(str(target), table_index=1)
    assert one["count"] == 1 and one["table_count"] == 2
    assert one["tables"][0]["table_index"] == 1
    assert [cell["text"] for cell in one["tables"][0]["cells"]] == ["안쪽 A", "안쪽 B"]


def test_text_preview_is_bounded_and_reports_the_full_length(tmp_path: Path) -> None:
    target = tmp_path / "form.hwpx"
    long_text = "가" * 500
    _document(target, long_text=long_text)

    result = get_table_map(str(target), text_preview_chars=20)

    cell = next(c for c in result["tables"][0]["cells"] if (c["row"], c["col"]) == (3, 3))
    assert cell["text"] == "가" * 20
    assert cell["text_length"] == 500
    short = next(c for c in result["tables"][0]["cells"] if (c["row"], c["col"]) == (3, 1))
    assert "text_length" not in short


def test_total_size_is_bounded_and_omissions_are_reported(tmp_path: Path) -> None:
    target = tmp_path / "big.hwpx"
    doc = HwpxDocument.new()
    for _ in range(3):
        table = doc.add_paragraph("").add_table(20, 10)
        for row in range(20):
            for col in range(10):
                table.set_cell_text(row, col, f"값 {row}-{col} " + "글" * 30)
    doc.save_to_path(str(target))
    doc.close()

    limited = get_table_map(str(target), max_chars=8000)

    body = {k: v for k, v in limited.items() if k not in {"document_revision", "documentWarnings"}}
    assert len(json.dumps(body, ensure_ascii=False)) <= 8000 + 1500  # fixed envelope only
    assert limited["truncated"] is True
    assert limited["tables_with_omitted_cells"]
    for table in limited["tables"]:
        assert table["cell_count"] == 200  # the real size is always reported
        assert len(table["cells"]) + table.get("cells_omitted", 0) == 200
    assert "get_table_map(table_index=N)" in limited["next_action"]

    unlimited = get_table_map(str(target), max_chars=10_000_000)
    assert "truncated" not in unlimited
    assert all(len(t["cells"]) == 200 for t in unlimited["tables"])


def test_invalid_arguments_are_refused(tmp_path: Path) -> None:
    target = tmp_path / "form.hwpx"
    _document(target)
    doc = HwpxDocument.open(str(target))
    try:
        with pytest.raises(ValueError, match="detail must be one of"):
            get_table_map_in_doc(doc, detail="tiny")
        with pytest.raises(ValueError, match="table_index"):
            get_table_map_in_doc(doc, detail="compact", table_index=9)
    finally:
        doc.close()


def test_compact_location_template_drives_text_lookup(tmp_path: Path) -> None:
    from hwpx_automation.server import get_paragraph_text

    target = tmp_path / "form.hwpx"
    _document(target)
    result = get_table_map(str(target))
    cell = next(c for c in result["tables"][0]["cells"] if (c["row"], c["col"]) == (2, 2))
    location = dict(result["cell_paragraph_location"])
    location.update(table_index=result["tables"][0]["table_index"], row=cell["row"], col=cell["col"])

    assert get_paragraph_text(str(target), location=location)["text"] == cell["text"] == "R2C2"
