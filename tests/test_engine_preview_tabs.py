"""The text after a tab starts where the engine places it (``LinePlacement.tabs``, ``TableCellLinePlacement.tabs``),
however wide the browser draws the text before it; a tab's fill runs from where the engine starts the tab. All
documents are made in the tests."""

import re
from dataclasses import replace

import pytest
from hwpx import HwpxDocument, experimental
from lxml import html
from preview_text_cover import every_engine_preview_shows_the_text  # noqa: F401

from hwpx_automation.preview import render_layout_preview

pytestmark = pytest.mark.skipif(
    "tabs" not in getattr(getattr(experimental, "LinePlacement", None), "__dataclass_fields__", {}),
    reason="needs the core's tab places",
)

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
MM = 7200 / 25.4
UNGIVEN = "text after a tab stands where the browser's tab width puts it"


def _mm(element, name: str) -> float:
    found = re.search(rf"(?:^|;)\s*{re.escape(name)}:\s*(-?[\d.]+)mm", element.get("style") or "")
    assert found, f"{name} missing in {element.get('style')}"
    return float(found.group(1))


def _limitations(preview) -> dict[tuple[str, str], int]:
    return {(item["kind"], item["reason"]): item["count"] for item in preview.as_dict()["limitations"]}


def _tabbed(document: HwpxDocument, align: str = "LEFT") -> str:
    """A paragraph format with a left stop at 40 mm filled with dots and a right stop at 100 mm."""
    tab = document.styles.ensure_tab_definition(tab_stops=[
        {"pos_mm": 40, "type": "LEFT", "leader": "DOT"}, {"pos_mm": 100, "type": "RIGHT"},
    ])
    return document.styles.ensure_paragraph_format(tab_pr_id_ref=tab, alignment=align)


def _pieces(line) -> dict[str, object]:
    return {piece.get("data-tab"): piece for piece in line.xpath("./span[@class='hwpx-tab-frame']/span")
            if piece.get("data-tab") is not None}


def _body_document(align: str = "LEFT") -> HwpxDocument:
    document = HwpxDocument.new()
    document.add_paragraph("첫 문단")
    document.add_paragraph("가나다\t라마\t바사아", para_pr_id_ref=_tabbed(document, align))
    document.add_paragraph("끝 문단")
    return document


def _tab_line(layout):
    return next(line for placed in layout.paragraphs for line in placed.lines if "\t" in (line.text or ""))


@pytest.mark.parametrize("align", ["LEFT", "JUSTIFY"])
def test_text_after_each_tab_starts_at_the_engines_place_and_a_fill_spans_the_tab(align: str) -> None:
    payload = _body_document(align).to_bytes()
    line = _tab_line(experimental.estimate_layout(payload))
    first, second = line.tabs
    assert None not in (first.x, first.start, second.x, second.start) and first.leader == "DOT"

    preview = render_layout_preview(payload)

    assert preview.fidelity_tier == "engine-estimated-pagination" and not preview.limitations
    drawn, = html.fromstring(preview.page_fragments[0]).xpath(".//div[@data-tabs='2']")
    pieces = _pieces(drawn)
    assert set(pieces) == {"0", "1", "2"} and pieces["0"].get("style") in (None, "")  # from the line's left edge
    assert _mm(pieces["1"], "left") == pytest.approx((first.x - line.x) / MM, abs=0.006)
    assert _mm(pieces["2"], "left") == pytest.approx((second.x - line.x) / MM, abs=0.006)
    assert [piece.text_content() for piece in pieces.values()] == ["가나다", "라마", "바사아"]
    fill, = drawn.xpath(".//span[@class='hwpx-tab-leader']")  # the right stop has no fill
    assert fill.get("data-leader") == "DOT" and "dotted" in fill.get("style")
    assert _mm(fill, "left") == pytest.approx((first.start - line.x) / MM, abs=0.006)
    assert _mm(fill, "width") == pytest.approx((first.x - first.start) / MM, abs=0.006)
    assert "text-align: left" in drawn.get("style")


def test_a_line_set_right_ends_its_first_piece_where_the_engine_starts_the_tab() -> None:
    payload = _body_document("RIGHT").to_bytes()
    line = _tab_line(experimental.estimate_layout(payload))

    preview = render_layout_preview(payload)

    drawn, = html.fromstring(preview.page_fragments[0]).xpath(".//div[@data-tabs='2']")
    first = _pieces(drawn)["0"]
    found = re.search(r"right: calc\(100% - (-?[\d.]+)mm\)", first.get("style"))
    assert found and float(found.group(1)) == pytest.approx((line.tabs[0].start - line.x) / MM, abs=0.006)


def test_a_tab_the_engine_does_not_place_keeps_the_browsers_width_and_is_counted(monkeypatch) -> None:
    payload = _body_document().to_bytes()
    layout = experimental.estimate_layout(payload)
    reason = "a made-up reason the tab is not placed"
    unplaced = replace(layout, paragraphs=tuple(
        replace(placed, lines=tuple(
            replace(line, tabs=tuple(replace(tab, x=None, unavailable=(reason,)) for tab in line.tabs))
            for line in placed.lines
        ))
        for placed in layout.paragraphs
    ))
    monkeypatch.setattr(experimental, "estimate_layout", lambda document: unplaced)

    preview = render_layout_preview(payload)

    page = html.fromstring(preview.page_fragments[0])
    assert not page.xpath(".//*[@data-tabs]") and not page.xpath(".//span[@class='hwpx-tab-frame']")
    assert _limitations(preview) == {("tab", f"{UNGIVEN}: {reason}"): 2}


def test_cell_and_header_lines_cut_at_their_tabs() -> None:
    document = HwpxDocument.new()
    para = _tabbed(document)
    document.page.set_header(text="머리\t말")
    header = next(node for node in document.sections[0].element.iter() if node.tag == f"{HP}header")
    for paragraph in header.iter(f"{HP}p"):
        paragraph.set("paraPrIDRef", para)
    table = document.add_paragraph("").add_table(1, 1)
    table.cell(0, 0).text = "칸\t안"
    table.cell(0, 0).paragraphs[0].element.set("paraPrIDRef", para)
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)
    cell_line, = [line for table in layout.tables for row in table.rows for cell in row.cells for line in cell.lines
                  if "\t" in (line.text or "")]
    area_line, = [line for area in layout.areas for line in area.lines if "\t" in (line.text or "")]
    assert cell_line.tabs[0].x is not None and area_line.tabs[0].x is not None

    preview = render_layout_preview(payload)

    page = html.fromstring(preview.page_fragments[0])
    for css_class, line in (("hwpx-engine-cell-line", cell_line), ("hwpx-engine-area-line", area_line)):
        drawn, = page.xpath(f".//div[@class='{css_class}'][@data-tabs='1']")
        assert _mm(_pieces(drawn)["1"], "left") == pytest.approx((line.tabs[0].x - line.x) / MM, abs=0.006)
    assert not [item for item in _limitations(preview) if item[0] == "tab"]
