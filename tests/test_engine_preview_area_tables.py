"""Tables a header or footer holds on its lines (``AreaPlacement.tables``) are drawn at the engine's place on
every page the area is drawn on, once: the body does not draw them again. All documents are made in the tests."""

import re
from dataclasses import replace

import pytest
from hwpx import HwpxDocument, experimental
from lxml import etree, html
from preview_text_cover import every_engine_preview_shows_the_text  # noqa: F401

from hwpx_automation.preview import render_layout_preview

pytestmark = pytest.mark.skipif(
    "tables" not in getattr(getattr(experimental, "AreaPlacement", None), "__dataclass_fields__", {}),
    reason="needs the core's header and footer table rows",
)

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
MM = 7200 / 25.4
CELL_TEXT = "영역 표 칸"
TOP_APPROXIMATE = "table's top is not measured: it stands in the area's room at the area's vertical alignment"


def _mm(element, name: str) -> float:
    found = re.search(rf"(?:^|;)\s*{re.escape(name)}:\s*(-?[\d.]+)mm", element.get("style") or "")
    assert found, f"{name} missing in {element.get('style')}"
    return float(found.group(1))


def _limitations(preview) -> dict[tuple[str, str], int]:
    return {(item["kind"], item["reason"]): item["count"] for item in preview.as_dict()["limitations"]}


def _document(kind: str) -> HwpxDocument:
    """Two pages of body; the *kind* area holds only a one-row table set as a character, a page number in its
    second cell."""
    document = HwpxDocument.new()
    (document.page.set_header if kind == "header" else document.page.set_footer)(text="자리")
    area = next(node for node in document.sections[0].element.iter() if node.tag == f"{HP}{kind}")
    for index in range(40):
        document.add_paragraph(f"본문 문단 {index} " + "글자 " * 20)
    table = document.add_paragraph("").add_table(1, 2)
    table.cell(0, 0).text = CELL_TEXT
    run = table.cell(0, 1).paragraphs[0].element.find(f"{HP}run")
    number = etree.SubElement(etree.SubElement(run, f"{HP}ctrl"), f"{HP}autoNum", {"num": "1", "numType": "PAGE"})
    etree.SubElement(number, f"{HP}autoNumFormat",
                     {"type": "DIGIT", "userChar": "", "prefixChar": "", "suffixChar": "", "supscript": "0"})
    holder = area.find(f".//{HP}p/{HP}run")
    for text in holder.findall(f"{HP}t"):
        holder.remove(text)
    holder.append(table.element)
    return document


@pytest.mark.parametrize("kind", ["header", "footer"])
def test_an_area_table_stands_at_the_engines_place_on_every_page_with_its_page_number(kind: str) -> None:
    payload = _document(kind).to_bytes()
    layout = experimental.estimate_layout(payload)

    preview = render_layout_preview(payload)

    assert len(preview.page_fragments) == len(layout.pages) > 1
    assert preview.fidelity_tier == "engine-estimated-pagination" and not preview.limitations
    for number, fragment in enumerate(preview.page_fragments):
        page = html.fromstring(fragment)
        assert page.get("data-layout-mode") == "positioned"
        placed, = [area for area in layout.areas if area.page == number]
        row, = placed.tables[0].rows
        drawn, = page.xpath(f".//div[@class='hwpx-area-layer'][@data-area-kind='{kind}']"
                            "/div[@class='hwpx-engine-table']")
        assert _mm(drawn, "left") == pytest.approx((placed.x + row.x) / MM, abs=0.006)
        assert _mm(drawn, "top") == pytest.approx(row.top / MM, abs=0.006)
        assert page.text_content().count(CELL_TEXT) == 1  # once: not again in the body or a room
        assert not page.xpath(".//div[contains(@class, 'hwpx-area-room')]") and not page.xpath(".//table")
        shown = drawn.xpath(".//span[@class='hwpx-page-number-text']/@data-number-text")
        assert shown == [str(number + 1)]


def test_an_area_table_without_a_top_stands_at_the_rooms_foot_as_the_area_is_set(monkeypatch) -> None:
    document = _document("footer")
    footer = next(node for node in document.sections[0].element.iter() if node.tag == f"{HP}footer")
    footer.find(f"{HP}subList").set("vertAlign", "BOTTOM")
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)
    untopped = replace(layout, areas=tuple(
        replace(area, tables=tuple(replace(table, rows=tuple(replace(row, top=None) for row in table.rows))
                                   for table in area.tables))
        for area in layout.areas
    ))
    monkeypatch.setattr(experimental, "estimate_layout", lambda document: untopped)

    preview = render_layout_preview(payload)

    for number, fragment in enumerate(preview.page_fragments):
        placed, = [area for area in layout.areas if area.page == number]
        row, = placed.tables[0].rows
        drawn, = html.fromstring(fragment).xpath(".//div[@class='hwpx-area-layer']/div[@class='hwpx-engine-table']")
        assert _mm(drawn, "left") == pytest.approx((placed.x + row.x) / MM, abs=0.006)  # the engine's x
        assert _mm(drawn, "top") == pytest.approx((placed.top + placed.height - row.height) / MM, abs=0.006)
    assert _limitations(preview) == {("footer", TOP_APPROXIMATE): len(preview.pages)}


BOX_TEXT = "칸 안 글상자 글"
HOLDS = ("a table in it holds an object, a table or a caption the engine gives no place with the area: "
         "the area is shown whole")


def test_an_area_table_whose_cell_holds_a_text_box_is_drawn_whole_with_the_box_text() -> None:
    """A header's 2x3 table set as a character, its first cell a character and a rectangle set as a character
    holding text: the engine gives the cell line its character only and the rectangle no place, so the table
    is not drawn at coordinates (its rectangle and the text in it would vanish) but with the area drawn whole."""
    document = HwpxDocument.new()
    document.page.set_header(text="자리")
    area = next(node for node in document.sections[0].element.iter() if node.tag == f"{HP}header")
    for index in range(40):
        document.add_paragraph(f"본문 문단 {index} " + "글자 " * 20)
    table = document.add_paragraph("").add_table(2, 3)
    table.cell(0, 0).text = "가"
    box = document.shapes.add_rectangle(4000, 1500, paragraph=table.cell(0, 0).paragraphs[0], treat_as_char=True)
    box.set_draw_text(BOX_TEXT)
    table.cell(1, 2).text = CELL_TEXT
    holder = area.find(f".//{HP}p/{HP}run")
    for text in holder.findall(f"{HP}t"):
        holder.remove(text)
    holder.append(table.element)
    margin = next(document.sections[0].element.iter(f"{HP}margin"))
    margin.set("header", "14000")  # a room the table fits in
    margin.set("top", "16000")
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)
    # The engine places the table's rows with the header, its first cell's line holding the character only.
    assert all(placed.tables and all(row.top is not None for row in placed.tables[0].rows) for placed in layout.areas)

    preview = render_layout_preview(payload)  # every character shown (preview_text_cover)

    assert len(preview.page_fragments) == len(layout.pages) > 1
    for fragment in preview.page_fragments:
        page = html.fromstring(fragment)
        assert not page.xpath(".//div[@class='hwpx-area-layer']/div[@class='hwpx-engine-table']")
        room, = page.xpath(".//div[contains(@class, 'hwpx-area-room')]")
        assert BOX_TEXT in room.text_content() and CELL_TEXT in room.text_content()
    assert _limitations(preview)["header", HOLDS] == len(preview.pages)


def test_an_area_table_the_engine_does_not_place_is_drawn_whole_in_the_room(monkeypatch) -> None:
    payload = _document("header").to_bytes()
    layout = experimental.estimate_layout(payload)
    unplaced = replace(layout, areas=tuple(
        replace(area, tables=tuple(replace(table, rows=(), unavailable=("not placed",)) for table in area.tables))
        for area in layout.areas
    ))
    monkeypatch.setattr(experimental, "estimate_layout", lambda document: unplaced)

    preview = render_layout_preview(payload)

    for fragment in preview.page_fragments:
        page = html.fromstring(fragment)
        room, = page.xpath(".//div[contains(@class, 'hwpx-area-room')]")
        assert room.find(".//table") is not None and CELL_TEXT in room.text_content()
        assert not page.xpath(".//div[@class='hwpx-area-layer']/div[@class='hwpx-engine-table']")
        assert page.text_content().count(CELL_TEXT) == 1
    assert _limitations(preview)["header", "area is drawn whole in its room: its lines do not give all it holds"] \
        == len(preview.pages)
