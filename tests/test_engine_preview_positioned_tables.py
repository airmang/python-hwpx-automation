"""Tables the engine gives every coordinate are drawn at those coordinates on pages that leave the flow."""

import re
from base64 import b64decode

import pytest
from hwpx import HwpxDocument, experimental
from lxml import html
from preview_overlap import drawn_wrongly, overlaps, page_overlaps
from preview_text_cover import every_engine_preview_shows_the_text  # noqa: F401

from hwpx_automation.preview import layout_preview, render_layout_preview

pytestmark = pytest.mark.skipif(
    "TableRowPlacement" not in getattr(experimental, "__all__", ())
    or "x" not in getattr(experimental.TableRowPlacement, "__dataclass_fields__", {}),
    reason="needs the core's table origins and cell line tops",
)

PIXEL = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/qFUAAAAASUVORK5CYII=")
FLOWING = ("table", "table content uses approximate flow within engine row pages")
MM = 25.4 / 7200


def _mm(element, name: str) -> float:
    found = re.search(rf"(?:^|; ?){re.escape(name)}: ?(-?[\d.]+)mm", element.get("style"))
    assert found is not None, (name, element.get("style"))
    return float(found.group(1))


def _limitations(preview) -> dict[tuple[str, str], int]:
    return {(item["kind"], item["reason"]): item["count"] for item in preview.as_dict()["limitations"]}


def _column_left(page, column: int, top: int) -> int:
    area = [area for area in page.column_areas if area.top <= top][-1]
    return page.body[0] + sum(area.widths[:column]) + column * (area.gap or 0)


def _form_document() -> HwpxDocument:
    document = HwpxDocument.new()
    document.add_paragraph("표 위의 문단")
    table = document.add_paragraph("").add_table(3, 3)
    for row in range(3):
        for column in range(3):
            table.cell(row, column).text = f"칸 {row + 1}-{column + 1}"
    table.cell(1, 1).text = "여러 줄로 나뉘는 가운데 칸의 글 " * 5
    for column, vertical in enumerate(("TOP", "CENTER", "BOTTOM")):
        table.cell(2, column).element.find("{*}subList").set("vertAlign", vertical)
        table.cell(2, column).element.find("{*}cellSz").set("height", "6000")
    table.merge_cells(0, 0, 0, 1)
    document.add_paragraph("표 아래의 문단")
    return document


def test_a_table_with_every_coordinate_is_drawn_at_them_and_its_page_leaves_the_flow() -> None:
    payload = _form_document().to_bytes()
    layout = experimental.estimate_layout(payload)
    placed, = layout.tables

    preview = render_layout_preview(payload)

    page = html.fromstring(preview.page_fragments[0])
    assert page.get("data-layout-mode") == "positioned"
    assert not page.xpath(".//table")
    table, = page.xpath(".//div[@class='hwpx-engine-table']")
    left, top = _mm(table, "left"), _mm(table, "top")
    engine_page = layout.pages[0]
    shown = page.xpath(".//div[@class='hwpx-engine-cell']")
    expected = [(row, cell) for row in placed.rows for cell in row.cells]
    assert len(shown) == len(expected)
    for markup, (row, cell) in zip(shown, expected):
        assert (int(markup.get("data-engine-row")), int(markup.get("data-engine-column"))) == (row.row, cell.column)
        paper_x = _column_left(engine_page, row.column, row.top) + row.x + cell.x
        paper_top = row.top - row.table_offset + cell.top
        assert left + _mm(markup, "left") == pytest.approx(paper_x * MM, abs=0.011)
        assert top + _mm(markup, "top") == pytest.approx(paper_top * MM, abs=0.011)
        assert _mm(markup, "width") == pytest.approx(cell.width * MM, abs=0.006)
        assert _mm(markup, "height") == pytest.approx(cell.height * MM, abs=0.006)
        lines = markup.xpath("./div[@class='hwpx-engine-cell-line']")
        given = [line for line in cell.lines if line.text]
        assert [line.text_content() for line in lines] == [line.text for line in given]
        for drawn, line in zip(lines, given):  # the engine's tops, as the cell sets them (top, centre, foot)
            assert int(drawn.get("data-engine-top")) == line.top
            assert _mm(drawn, "top") == pytest.approx(line.top * MM, abs=0.006)
            assert _mm(drawn, "left") == pytest.approx(line.x * MM, abs=0.006)
            assert _mm(drawn, "line-height") == pytest.approx(line.height * MM, abs=0.006)
    merged = shown[0]
    assert _mm(merged, "width") == pytest.approx(sum(cell.width for cell in placed.rows[1].cells[:2]) * MM, abs=0.02)
    # A cell set at its centre or foot stands its line lower than one set at its top.
    foot_row = [markup for markup in shown if markup.get("data-engine-row") == "2"]
    tops = [_mm(markup.xpath("./div[@class='hwpx-engine-cell-line']")[0], "top") for markup in foot_row]
    assert tops[0] < tops[1] < tops[2]
    assert FLOWING not in _limitations(preview) and preview.fidelity_tier == "engine-estimated-pagination"
    found = page_overlaps(preview.page_fragments[0])
    assert found["tables"] == 1 and found["cell-line pairs"] > 0 and not drawn_wrongly(found)
    assert found["cell-lines"] == found["table-body"] == 0


def test_a_cell_border_stands_on_the_edge_and_fills_lie_under_borders_and_text() -> None:
    document = HwpxDocument.new()
    table = document.add_paragraph("").add_table(1, 2)
    table.cell(0, 0).text = "바탕 있는 칸"
    table.set_cell_shading(0, 0, "#1F2A44")
    table.cell(0, 1).text = "옆 칸"

    preview = render_layout_preview(document.to_bytes())

    first, second = html.fromstring(preview.page_fragments[0]).xpath(".//div[@class='hwpx-engine-cell']")
    assert "background: #1F2A44" in first.get("style") and "background" not in second.get("style")
    frame, = first.xpath("./i[@class='hwpx-cell-frame']")
    width = float(re.search(r"border-left: ([\d.]+)mm", frame.get("style")).group(1))
    assert _mm(frame, "left") == pytest.approx(-width / 2, abs=0.001)  # half out of the cell, half in
    assert ".hwpx-cell-frame { position: absolute; box-sizing: border-box; z-index: 1;" in preview.html
    assert ".hwpx-engine-cell > .hwpx-engine-cell-line { position: absolute; z-index: 2;" in preview.html
    assert "data-text-start]').forEach" in preview.html  # lines wider than their room are narrowed


def test_a_table_split_over_pages_is_drawn_at_coordinates_on_every_page_with_its_header_again() -> None:
    document = HwpxDocument.new()
    document.add_paragraph("나뉘는 표 앞의 문단")
    table = document.add_paragraph("").add_table(60, 2)
    table.element.find("{*}pos").set("treatAsChar", "0")
    table.element.attrib.update({"pageBreak": "CELL", "repeatHeader": "1"})
    for row in range(60):
        table.cell(row, 0).text = f"{row + 1}번 행"
        table.cell(row, 1).text = f"{row + 1}번 행의 내용"
    for column in range(2):
        table.cell(0, column).element.set("header", "1")
    payload = document.to_bytes()
    placed, = experimental.estimate_layout(payload).tables
    pages = sorted({row.page for row in placed.rows})
    assert len(pages) > 1 and any(row.repeated for row in placed.rows)

    preview = render_layout_preview(payload)

    for number in pages:
        page = html.fromstring(preview.page_fragments[number])
        assert page.get("data-layout-mode") == "positioned"
        cells = page.xpath(".//div[@class='hwpx-engine-cell']")
        assert [(int(cell.get("data-engine-row")), cell.get("data-engine-repeated")) for cell in cells] == [
            (row.row, str(int(row.repeated))) for row in placed.rows if row.page == number for _ in row.cells
        ]
    assert not drawn_wrongly(overlaps(preview.page_fragments))
    text = "".join(html.fromstring(fragment).text_content() for fragment in preview.page_fragments)
    assert all(len(re.findall(rf"(?<![0-9]){row}번 행의 내용", text)) == 1 for row in range(2, 61))


def _nested_document() -> HwpxDocument:
    document = HwpxDocument.new()
    document.add_paragraph("표 위의 문단")
    outer = document.add_paragraph("").add_table(2, 2)
    outer.cell(0, 0).text = "바깥 칸"
    outer.cell(1, 1).text = "안쪽 표를 담은 칸"
    inner = outer.cell(1, 1).add_paragraph("").add_table(2, 2)
    for row in range(2):
        for column in range(2):
            inner.cell(row, column).text = f"안 {row + 1}-{column + 1}"
    document.add_paragraph("표 아래의 문단")
    return document


@pytest.mark.skipif(not hasattr(getattr(experimental, "TableRowPlacement", None), "x"), reason="needs the core row left edge")
def test_a_table_alone_on_a_cell_line_is_drawn_at_the_engine_s_coordinates_inside_its_cell() -> None:
    payload = _nested_document().to_bytes()
    layout = experimental.estimate_layout(payload)
    outer, inner = layout.tables
    if any(row.top is None or row.x is None for row in inner.rows):
        pytest.skip("the core does not set this nested table at coordinates")

    preview = render_layout_preview(payload)

    page = html.fromstring(preview.page_fragments[0])
    assert page.get("data-layout-mode") == "positioned" and not page.xpath(".//table")
    drawn = {int(table.get("data-engine-table")): table for table in page.xpath(".//div[@class='hwpx-engine-table']")}
    assert sorted(drawn) == [outer.table, inner.table]
    engine_page = layout.pages[0]
    for row in inner.rows:
        for cell in row.cells:
            markup, = drawn[inner.table].xpath(
                f"./div[@data-engine-row='{row.row}'][@data-engine-column='{cell.column}']"
            )
            paper_x = _column_left(engine_page, row.column, row.top) + row.x + cell.x
            paper_top = row.top - row.table_offset + cell.top
            assert _mm(drawn[inner.table], "left") + _mm(markup, "left") == pytest.approx(paper_x * MM, abs=0.011)
            assert _mm(drawn[inner.table], "top") + _mm(markup, "top") == pytest.approx(paper_top * MM, abs=0.011)
            assert _mm(markup, "width") == pytest.approx(cell.width * MM, abs=0.006)
    # The inner table stands inside the outer cell holding it, under that cell's own line.
    holder = next(cell for row in outer.rows for cell in row.cells if cell.lines_with_tables)
    holder_box, = drawn[outer.table].xpath(
        f"./div[@data-engine-row='{holder.row}'][@data-engine-column='{holder.column}']"
    )
    left = _mm(drawn[outer.table], "left") + _mm(holder_box, "left")
    top = _mm(drawn[outer.table], "top") + _mm(holder_box, "top")
    assert left <= _mm(drawn[inner.table], "left") and top < _mm(drawn[inner.table], "top")
    assert _mm(drawn[inner.table], "left") + _mm(drawn[inner.table], "width") <= left + _mm(holder_box, "width") + 0.02
    assert FLOWING not in _limitations(preview)
    assert not drawn_wrongly(overlaps(preview.page_fragments))
    text = page.text_content()
    assert all(text.count(f"안 {row}-{column}") == 1 for row in (1, 2) for column in (1, 2))


@pytest.mark.parametrize("holds", ["caption", "table"])
def test_a_table_holding_what_cell_lines_do_not_give_flows_and_says_so(holds: str) -> None:
    document = HwpxDocument.new()
    table = document.add_paragraph("").add_table(2, 2)
    table.cell(0, 0).text = "글이 든 칸"
    if holds == "caption":
        table.set_caption("표의 캡션")
    else:  # a table in a cell not set as a character: the engine gives it no place in the cell
        inner = table.cell(1, 1).add_paragraph("").add_table(1, 1)
        inner.cell(0, 0).text = "안쪽 표"
        inner.element.find("{*}pos").set("treatAsChar", "0")

    preview = render_layout_preview(document.to_bytes())

    page = html.fromstring(preview.page_fragments[0])
    assert page.get("data-layout-mode") == "flow" and page.xpath(".//table[@data-engine-table='0']")
    assert not page.xpath(".//div[@class='hwpx-engine-table']")
    assert _limitations(preview)[FLOWING] == 1


def test_a_table_with_coordinates_on_a_flow_page_flows_and_is_counted_once(monkeypatch) -> None:
    # A table without rows the preview does not set over the page makes the page flow.
    monkeypatch.setattr(layout_preview, "_floating_table", lambda *arguments: None)
    document = HwpxDocument.new()
    first = document.add_paragraph("").add_table(2, 2)
    first.cell(0, 0).text = "좌표를 가진 표"
    floating = document.add_paragraph("").add_table(1, 1)  # in front of the text: the layout keeps no rows
    floating.element.find("{*}pos").set("treatAsChar", "0")
    floating.element.set("textWrap", "IN_FRONT_OF_TEXT")
    floating.cell(0, 0).text = "떠 있는 표"
    payload = document.to_bytes()
    placed, unplaced = experimental.estimate_layout(payload).tables
    assert placed.rows and placed.rows[0].top is not None and not unplaced.rows

    preview = render_layout_preview(payload)

    page = html.fromstring(preview.page_fragments[0])
    assert page.get("data-layout-mode") == "flow"
    assert page.xpath(".//table[@data-engine-table='0']") and not page.xpath(".//div[@class='hwpx-engine-table']")
    limitations = _limitations(preview)
    assert limitations[FLOWING] == 1
    assert limitations["table", "row and cell placement is unavailable"] == 1


def test_a_table_in_front_of_the_text_stands_over_the_page_at_its_offset_and_keeps_the_page_positioned() -> None:
    document = HwpxDocument.new()
    document.add_paragraph("표 위의 문단")
    holder = document.add_paragraph("떠 있는 표를 단 문단")
    floating = holder.add_table(2, 2)
    floating.element.find("{*}pos").attrib.update({
        "treatAsChar": "0", "vertRelTo": "PARA", "horzRelTo": "COLUMN", "vertAlign": "TOP", "horzAlign": "LEFT",
        "vertOffset": "1200", "horzOffset": "3000",
    })
    floating.element.set("textWrap", "IN_FRONT_OF_TEXT")
    for row in range(2):
        for column in range(2):
            floating.cell(row, column).text = f"떠 있는 칸 {row + 1}-{column + 1}"
    document.add_paragraph("표 아래의 문단")
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)
    placed, = layout.tables
    assert not placed.rows  # the layout gives a table in front of the text no rows

    preview = render_layout_preview(payload)

    page = html.fromstring(preview.page_fragments[0])
    assert page.get("data-layout-mode") == "positioned"
    box, = page.xpath(".//div[contains(@class, 'hwpx-floating-table')]")
    assert box.get("data-overlay") == "front" and box.get("data-approx") == "place"
    line = next(paragraph for paragraph in layout.paragraphs if paragraph.paragraph == placed.paragraph).lines[0]
    engine_page = layout.pages[0]
    assert _mm(box, "left") == pytest.approx((_column_left(engine_page, 0, line.top) + 3000) * MM, abs=0.006)
    assert _mm(box, "top") == pytest.approx((line.top + 1200) * MM, abs=0.006)
    assert [cell.text_content() for cell in box.xpath(".//td")] == [
        f"떠 있는 칸 {row}-{column}" for row in (1, 2) for column in (1, 2)
    ]
    assert _limitations(preview)["table", "table in front of or behind the text is drawn at an approximate place"] == 1
    # Over the text: no overlap is counted against it (the document sets it there).
    assert not drawn_wrongly(overlaps(preview.page_fragments))
    assert "function hang(page)" in preview.html
