"""Cells of tables the engine placed row by row: lines, tables inside, objects, split cells."""

import copy
import re
from base64 import b64decode
from types import SimpleNamespace

import pytest
from hwpx import HwpxDocument, experimental
from lxml import etree, html

from hwpx_automation.preview import layout_preview, render_layout_preview
from preview_text_cover import every_engine_preview_shows_the_text  # noqa: F401

pytestmark = pytest.mark.skipif(
    "TableCellPlacement" not in getattr(experimental, "__all__", ()), reason="needs the core table placement API",
)

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
PIXEL = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/qFUAAAAASUVORK5CYII=")
STACKED = ("table-cell", "cell lines stand at the file's line spacing, not at engine tops")
PLACEHOLDER = "object is shown as a placeholder"


def _limitations(preview) -> dict[tuple[str, str], int]:
    return {(item["kind"], item["reason"]): item["count"] for item in preview.as_dict()["limitations"]}


def _css(element, name: str) -> str | None:
    found = re.search(rf"(?:^|; ?){re.escape(name)}: ?([^;]+)", element.get("style"))
    return found.group(1) if found else None


def _mm(value: str | None) -> float:
    assert value is not None and value.endswith("mm")
    return float(value[:-2])


def _lines_of(cell) -> list:
    return cell.xpath("./div[@class='hwpx-engine-cell-line'][@data-text-start]")


def _needs_lines_with_tables() -> None:
    document = HwpxDocument.new()
    document.add_paragraph("").add_table(1, 1)
    cell = experimental.estimate_layout(document.to_bytes()).tables[0].rows[0].cells[0]
    if not hasattr(cell, "lines_with_tables"):
        pytest.skip("needs the core's lines of cells that hold tables")


# --- a) a table inside a cell stands at its place among the cell's lines


def test_a_table_in_a_cell_is_drawn_once_between_the_lines_around_it() -> None:
    _needs_lines_with_tables()
    document = HwpxDocument.new()
    table = document.add_paragraph("").add_table(2, 2)
    cell = table.cell(0, 0)
    cell.text = "안쪽 표 앞의 글"
    inner = cell.add_paragraph("").add_table(2, 2)
    for row in range(2):
        for column in range(2):
            inner.cell(row, column).text = f"안쪽 {row + 1}-{column + 1}"
    cell.add_paragraph("안쪽 표 뒤의 글")
    table.cell(0, 1).text = "옆 칸"

    preview = render_layout_preview(document.to_bytes())

    page = html.fromstring(preview.page_fragments[0])
    outer_cell = page.xpath(".//table[@data-engine-table='0']/tbody/tr[1]/td[1]")[0]
    before, host, after = outer_cell
    assert (before.text_content(), after.text_content()) == ("안쪽 표 앞의 글", "안쪽 표 뒤의 글")
    assert host.get("data-engine-host") == "1" and host.get("data-text-start") is None
    nested, = host
    assert nested.tag == "table" and nested.get("data-engine-table") == "1"
    assert [cell.text_content() for cell in nested.xpath(".//td")] == ["안쪽 1-1", "안쪽 1-2", "안쪽 2-1", "안쪽 2-2"]
    text = page.text_content()
    assert all(text.count(f"안쪽 {row}-{column}") == 1 for row in (1, 2) for column in (1, 2))
    assert not any("the cell holds tables" in reason for _, reason in _limitations(preview))


def test_a_table_late_in_a_split_cell_is_drawn_on_the_page_the_engine_sets_it() -> None:
    _needs_lines_with_tables()
    document = HwpxDocument.new()
    outer = document.add_paragraph("").add_table(1, 1)
    outer.element.find("{*}pos").set("treatAsChar", "0")
    outer.element.set("pageBreak", "CELL")
    cell = outer.cell(0, 0)
    cell.text = "첫 줄"
    for index in range(1, 46):
        cell.add_paragraph(f"앞쪽 {index}째 줄")
    inner = cell.add_paragraph("").add_table(1, 2)
    inner.cell(0, 0).text = "안쪽 표의 칸"
    for index in range(3):
        cell.add_paragraph(f"안쪽 표 뒤 {index + 1}째 줄")
    payload = document.to_bytes()
    placed = next(table for table in experimental.estimate_layout(payload).tables if table.table == 0)
    assert len({row.page for row in placed.rows}) == 2  # the cell goes on over a page end

    preview = render_layout_preview(payload)

    for row in placed.rows:
        page = html.fromstring(preview.page_fragments[row.page])
        cell_markup, = page.xpath(".//table[@data-engine-table='0']/tbody/tr/td")
        engine_lines = row.cells[0].lines_with_tables
        assert [line.text_content() for line in _lines_of(cell_markup)] == [
            line.text for line in engine_lines if not line.tables
        ]
        tables_here = sum(1 for line in engine_lines if line.tables)
        assert len(cell_markup.xpath(".//table")) == tables_here
        assert page.text_content().count("안쪽 표의 칸") == tables_here
    assert sum(fragment.count("안쪽 표의 칸") for fragment in preview.page_fragments) == 1


# --- b) cells of placed rows: alignment, row height, lines that never overlap


def _aligned_table() -> HwpxDocument:
    document = HwpxDocument.new()
    table = document.add_paragraph("").add_table(2, 3)
    for column, (horizontal, vertical) in enumerate((("LEFT", "TOP"), ("CENTER", "CENTER"), ("RIGHT", "BOTTOM"))):
        for row, text in enumerate(("여러 줄로 나뉘는 칸의 글 " * 6, "한 줄")):
            cell = table.cell(row, column)
            cell.text = text
            cell.paragraphs[0].alignment = horizontal
            cell.paragraphs[0].line_spacing = 130 + 40 * column
            cell.element.find("{*}subList").set("vertAlign", vertical)
    return document


def test_placed_cells_follow_the_paragraph_and_cell_alignment() -> None:
    preview = render_layout_preview(_aligned_table().to_bytes())

    first_row = html.fromstring(preview.page_fragments[0]).xpath(".//tr[@data-engine-row='0']/td")
    assert [_css(cell, "vertical-align") for cell in first_row] == ["top", "middle", "bottom"]
    assert [{_css(line, "text-align") for line in _lines_of(cell)} for cell in first_row] == [
        {None}, {"center"}, {"right"},
    ]
    # The cell margins stay the padding; only the half border the box takes comes off it.
    assert all(_css(cell, "padding-top").startswith("calc(") for cell in first_row)


def test_placed_cell_lines_take_the_engine_or_the_file_pitch_and_never_overlap() -> None:
    payload = _aligned_table().to_bytes()
    table, = experimental.estimate_layout(payload).tables
    row = table.rows[0]

    preview = render_layout_preview(payload)

    page = html.fromstring(preview.page_fragments[0])
    row_markup, = page.xpath(".//tr[@data-engine-row='0']")
    assert _mm(_css(row_markup, "height")) == pytest.approx(row.height / 7200 * 25.4, abs=0.006)
    stacked = 0
    for cell, placed in zip(row_markup.xpath("./td"), row.cells, strict=True):
        lines = _lines_of(cell)
        assert [line.text_content() for line in lines] == [line.text for line in placed.lines] and len(lines) > 2
        for markup, line, following in zip(lines, placed.lines, placed.lines[1:]):
            room = _mm(_css(markup, "height"))
            assert room >= _mm(_css(markup, "line-height"))  # the next line starts below this one
            if line.top is not None and following.top is not None:
                assert int(markup.get("data-engine-advance")) == following.top - line.top
                assert room == pytest.approx((following.top - line.top) / 7200 * 25.4, abs=0.006)
            else:
                assert markup.get("data-line-pitch") == "file" and markup.get("data-engine-advance") is None
        assert _css(lines[-1], "height") is None  # the cell's last line keeps its own height
        stacked += any(line.get("data-line-pitch") == "file" for line in lines)
    # 170 % and 210 % of a 1000-unit line: the file's spacing where the engine gives no tops.
    pitches = {
        _css(line, "height") for line in page.xpath(".//div[@data-line-pitch='file']")
        if line.getparent().getparent() is row_markup
    }
    assert pitches <= {"4.59mm", "6.00mm", "7.41mm"} and pitches
    assert _limitations(preview).get(STACKED, 0) == stacked > 0
    assert "data-text-start]').forEach" in preview.html  # lines wider than their cell are narrowed in the browser


@pytest.mark.parametrize(
    ("spacing", "following_paragraph", "expected"),
    [
        (("PERCENT", 160), 0, 1600),
        (("PERCENT", 50), 0, 1000),  # never less than the line: two lines cannot overlap
        (("FIXED", 2400), 0, 2400),
        (("FIXED", 300), 0, 1000),
        (("BETWEEN_LINES", 500), 0, 1500),
        (("AT_LEAST", 1800), 0, 1800),
        (("UNKNOWN", 7), 0, 1000),
        (("PERCENT", 160), 1, 1600 + 300 + 200),  # the spacing after this paragraph and before the next
    ],
)
def test_the_file_pitch_of_a_cell_line(spacing, following_paragraph, expected) -> None:
    line = SimpleNamespace(paragraph=0, top=None, height=1000)
    following = SimpleNamespace(paragraph=following_paragraph, top=None, height=1000)
    unit = 25.4 / 7200
    style = {"line_spacing": spacing, "margins_mm": {"bottom": 300 * unit, "top": 900 * unit}}
    next_style = {"margins_mm": {"top": 200 * unit, "bottom": 0.0}}

    room, engine = layout_preview._cell_line_room(line, following, style, next_style)

    assert engine is None and room == pytest.approx(expected * unit)
    assert layout_preview._cell_line_room(line, None, style, next_style) == (None, None)
    with_tops = layout_preview._cell_line_room(
        SimpleNamespace(paragraph=0, top=141, height=1000), SimpleNamespace(paragraph=0, top=1441, height=1000),
        style, next_style,
    )
    assert with_tops == (pytest.approx(1300 * unit), 1300)  # an engine top replaces the file's pitch


def test_columns_keep_their_widths_under_a_merged_first_row() -> None:
    document = HwpxDocument.new()
    table = document.add_paragraph("").add_table(2, 3)
    widths = (6000, 21000, 15520)
    for row in range(2):
        for column, width in enumerate(widths):
            table.cell(row, column).element.find("{*}cellSz").set("width", str(width))
    table.merge_cells(0, 0, 0, 2)
    table.cell(0, 0).text = "합친 첫 행"
    table.cell(1, 1).text = "넓은 칸"

    page = html.fromstring(render_layout_preview(document.to_bytes()).page_fragments[0])

    assert [column.get("style") for column in page.xpath(".//table/colgroup/col")] == [
        f"width:{width / 7200 * 25.4:.2f}mm" for width in widths
    ]


# --- c) nothing a cell holds vanishes


def test_objects_in_the_cells_of_a_placed_table_show_themselves_or_a_marker() -> None:
    document = HwpxDocument.new()
    document.add_paragraph("표 위 문단")
    table = document.add_paragraph("").add_table(1, 5)
    picture = table.cell(0, 0)
    picture.text = ""
    picture.paragraphs[0].add_picture(document.media.add_image(PIXEL, "png"), width=6000, height=4000)
    shape = table.cell(0, 1)
    shape.text = "도형이 든 칸"
    document.shapes.add_rectangle(5000, 3000, paragraph=shape.paragraphs[0], treat_as_char=True)
    equation = table.cell(0, 2)
    equation.text = "수식이 든 칸 "
    equation.paragraphs[0].add_equation("x^2 + y^2 = z^2")
    form = table.cell(0, 3)
    form.text = "선택 상자가 든 칸"
    sized = document.shapes.add_rectangle(1200, 1200, paragraph=form.paragraphs[0], treat_as_char=True).element
    box = etree.SubElement(sized.getparent(), f"{HP}checkBtn")  # a form object, with the rectangle's size and place
    box.extend(copy.deepcopy(sized.find(f"{HP}{name}")) for name in ("sz", "pos", "outMargin"))
    sized.getparent().remove(sized)
    floating = table.cell(0, 4)
    floating.text = "떠 있는 도형이 걸린 칸"
    document.shapes.add_rectangle(4000, 2000, paragraph=floating.paragraphs[0], treat_as_char=False)
    payload = document.to_bytes()
    placed, = experimental.estimate_layout(payload).tables
    assert placed.rows

    preview = render_layout_preview(payload)

    cells = html.fromstring(preview.page_fragments[0]).xpath(".//tr[@data-engine-row='0']/td")
    image, = cells[0].xpath(".//img[@class='hwpx-cell-picture']")
    assert image.get("src").startswith("data:image/png;base64,") and image.get("style") == "width: 21.17mm; height: 14.11mm"
    markers = [[marker.text for marker in cell.xpath(".//span[@class='hwpx-object-marker']")] for cell in cells]
    assert markers == [[], ["⟦도형⟧"], [], ["⟦체크 상자⟧"], ["⟦도형⟧"]]
    assert cells[2].xpath(".//*[contains(@class, 'hwpx-equation')]")
    texts = [cell.text_content() for cell in cells]
    for cell_text, own in zip(texts[1:], ("도형이 든 칸", "수식이 든 칸", "선택 상자가 든 칸", "떠 있는 도형이 걸린 칸")):
        assert cell_text.count(own) == 1
    limitations = _limitations(preview)
    assert limitations["shape", PLACEHOLDER] == 2 and limitations["checkBtn", PLACEHOLDER] == 1
    assert ("picture", PLACEHOLDER) not in limitations


def test_a_picture_without_bytes_a_browser_reads_is_a_counted_marker() -> None:
    document = HwpxDocument.new()
    table = document.add_paragraph("").add_table(1, 1)
    cell = table.cell(0, 0)
    cell.text = ""
    tiff = b"II*\x00" + bytes(16)  # a format the file may hold and this preview does not hand to a browser
    cell.paragraphs[0].add_picture(document.media.add_image(tiff, "tif"), width=6000, height=4000)

    preview = render_layout_preview(document.to_bytes())

    cell_markup, = html.fromstring(preview.page_fragments[0]).xpath(".//td")
    assert not cell_markup.xpath(".//img")
    assert [marker.text for marker in cell_markup.xpath(".//span[@class='hwpx-object-marker']")] == ["⟦그림 1⟧"]
    assert _limitations(preview)["picture", PLACEHOLDER] == 1


# --- d) a row split over pages


def _split_table() -> HwpxDocument:
    document = HwpxDocument.new()
    table = document.add_paragraph("").add_table(30, 3)
    table.element.find("{*}pos").set("treatAsChar", "0")
    table.element.attrib.update({"pageBreak": "CELL", "repeatHeader": "1"})
    for column, title in enumerate(("구분", "내용", "비고")):
        table.cell(0, column).text = title
        table.cell(0, column).element.set("header", "1")
    for row in range(1, 30):
        table.cell(row, 0).text = f"{row}번"
        table.cell(row, 1).text = f"{row}번 줄의 내용 " * (12 if row % 7 == 0 else 2)
    table.merge_cells(3, 2, 28, 2)
    merged = table.cell(3, 2)
    merged.text = "합친 칸의 1째 줄"
    for index in range(1, 40):
        merged.add_paragraph(f"합친 칸의 {index + 1}째 줄")
    return document


def test_the_later_part_of_a_split_merged_cell_shows_its_own_lines_only() -> None:
    payload = _split_table().to_bytes()
    table, = experimental.estimate_layout(payload).tables
    parts = [
        (row.page, cell) for row in table.rows for cell in row.cells
        if cell.column == 2 and cell.row_span > 1 and cell.lines
    ]
    assert len(parts) == 2 and parts[0][1].line_end == parts[1][1].line_start > 0  # one cell, on two pages

    preview = render_layout_preview(payload)

    shown = []
    for page, placed in parts:
        cell, = html.fromstring(preview.page_fragments[page]).xpath(".//td[@rowspan][.//div[@data-text-start]]")
        lines = [line.text_content() for line in _lines_of(cell)]
        assert lines == [line.text for line in placed.lines]
        shown += lines
        assert _css(cell, "vertical-align") == ("top" if placed.line_start else "middle")
    assert shown == [f"합친 칸의 {index + 1}째 줄" for index in range(40)]  # every line once, in order
    for page, fragment in enumerate(preview.page_fragments):
        rows = html.fromstring(fragment).xpath(".//tr[@data-engine-row]")
        assert [(int(row.get("data-engine-row")), row.get("data-engine-repeated")) for row in rows] == [
            (row.row, str(int(row.repeated))) for row in table.rows if row.page == page
        ]
    assert any(row.repeated for row in table.rows)  # the header row comes again on the second page, marked
    assert not any("이어지는" in fragment for fragment in preview.page_fragments)
