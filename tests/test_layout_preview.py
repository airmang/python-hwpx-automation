# SPDX-License-Identifier: Apache-2.0
"""Layout preview (moved from python-hwpx tests/test_layout_preview.py and the
preview cases of test_cell_margins.py, test_page_orientation.py and
test_export_text_boxes.py)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from hwpx.document import HwpxDocument
from hwpx.oxml.namespaces import HP

from hwpx_automation.preview import render_layout_preview
from hwpx_automation.preview.layout_preview import _fmt_mm, _hwp_to_mm
from preview_flow import tables_flow  # noqa: F401


CORPUS = Path(__file__).parent / "fixtures" / "moved" / "misc"
MANIFEST = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))


def _sample_ids() -> list[str]:
    return [sample["file"] for sample in MANIFEST["samples"]]


def test_layout_preview_renders_page_box_and_margins() -> None:
    preview = render_layout_preview(CORPUS / "reader_writer__PageSize_Margin.hwpx")

    # The sample is a landscape B4 page: NARROWLY with the portrait size.
    page = preview.pages[0]
    assert page.width_mm > 350
    assert page.height_mm > 250
    assert page.margins_mm["left"] == pytest.approx(30.0, abs=0.2)
    assert page.margins_mm["top"] == pytest.approx(20.0, abs=0.2)
    assert "hwpx-preview-page" in preview.html
    assert "padding:" in preview.html


@pytest.mark.usefixtures("tables_flow")
def test_layout_preview_renders_table_geometry_and_borders() -> None:
    preview = render_layout_preview(CORPUS / "reader_writer__SimpleTable.hwpx")

    assert '<table class="hwpx-table"' in preview.html
    assert 'colspan="2"' in preview.html
    assert 'rowspan="2"' in preview.html
    assert "border-left:" in preview.html
    assert "width:" in preview.html
    assert preview.pages[0].table_count == 1


def test_layout_preview_long_mode_uses_single_page_box() -> None:
    preview = render_layout_preview(
        CORPUS / "reader_writer__SimpleTable.hwpx",
        mode="long",
    )

    assert preview.mode == "long"
    assert preview.as_dict()["pageCount"] == 1


@pytest.mark.parametrize("sample", _sample_ids())
def test_hwpxlib_corpus_layout_preview_does_not_crash(sample: str) -> None:
    preview = render_layout_preview(CORPUS / sample)

    assert preview.html.startswith("<!DOCTYPE html>")
    assert preview.as_dict()["pageCount"] == len(preview.pages)


def test_layout_preview_rejects_an_unknown_mode() -> None:
    with pytest.raises(ValueError):
        render_layout_preview(CORPUS / "reader_writer__SimpleTable.hwpx", mode="grid")


# --- from test_cell_margins.py ------------------------------------------------

_TABLE_MARGIN = (100, 200, 300, 400)
_CELL_MARGIN = (1, 2, 3, 4)


def _set_box(element, left: int, right: int, top: int, bottom: int) -> None:
    for name, value in (("left", left), ("right", right), ("top", top), ("bottom", bottom)):
        element.set(name, str(value))


def _cell_with_two_margins(has_margin: str | None):
    doc = HwpxDocument.new()
    table = doc.add_table(1, 1)
    cell = table.cell(0, 0)
    _set_box(table.element.find(f"{HP}inMargin"), *_TABLE_MARGIN)
    _set_box(cell.element.find(f"{HP}cellMargin"), *_CELL_MARGIN)
    if has_margin is None:
        cell.element.attrib.pop("hasMargin", None)
    else:
        cell.element.set("hasMargin", has_margin)
    return doc, table, cell


_RULE_CASES = [("0", _TABLE_MARGIN), (None, _TABLE_MARGIN), ("1", _CELL_MARGIN)]


@pytest.mark.usefixtures("tables_flow")
@pytest.mark.parametrize(("has_margin", "expected"), _RULE_CASES)
def test_the_layout_preview_pads_cells_with_the_effective_margins(has_margin, expected) -> None:
    doc, _, _ = _cell_with_two_margins(has_margin)
    buffer = io.BytesIO()
    doc.save(buffer)

    left, right, top, bottom = (_fmt_mm(_hwp_to_mm(value)) for value in expected)
    assert f"padding:{top} {right} {bottom} {left}" in render_layout_preview(
        buffer.getvalue()
    ).html.replace(": ", ":")


# --- from test_page_orientation.py ---------------------------------------------


def test_a_landscape_page_previews_wider_than_tall(tmp_path: Path) -> None:
    document = HwpxDocument.new()
    document.page.setup(paper_size="A4", orientation="LANDSCAPE", margin_left_mm=20, margin_right_mm=20)
    document.add_table(1, 2)
    path = tmp_path / "landscape.hwpx"
    document.save(path)

    page = render_layout_preview(path).pages[0]
    assert page.width_mm > page.height_mm


# --- from test_export_text_boxes.py --------------------------------------------


def _text_box_document() -> HwpxDocument:
    document = HwpxDocument.new(empty_first_line=True)
    document.add_paragraph("앞 문단")
    holder = document.add_paragraph("상자 담은 문단")
    document.shapes.add_rectangle(paragraph=holder).set_draw_text("상자 글")
    holder.add_table(1, 1).cell(0, 0).text = "같은 문단의 칸"
    document.add_paragraph("뒤 문단")
    return document


def test_a_text_box_in_a_table_cell_shows_once_in_the_preview() -> None:
    document = HwpxDocument.new(empty_first_line=True)
    cell = document.add_table(1, 1).cell(0, 0)
    cell.text = "칸 글"
    document.shapes.add_rectangle(paragraph=cell.paragraphs[0]).set_draw_text("칸상자글")

    html = render_layout_preview(document.to_bytes()).html

    assert html.count("칸상자글") == 1
    assert html.count("칸 글") == 1


def test_the_preview_writes_the_box_text_next_to_the_shape_marker() -> None:
    html = render_layout_preview(_text_box_document().to_bytes()).html

    marker = html.index("⟦도형⟧")
    assert html.index('<span class="hwpx-shape-text">상자 글</span>') > marker
