"""Numbers and bullets, and what the overlap check sees on flow pages and in header rooms.

- A numbered, outline or bullet paragraph shows its label before its first line, in the body, in a
  cell (drawn at coordinates or flowing) -- python-hwpx's count (``ListLabels``), each counted as
  drawn at an approximate place. The engine's own label, where its line carries one, wins.
- The text cover check counts labels: a label left out is missing text.
- A header drawn whole sets its paragraphs at the engine's tops in its room; a paragraph showing only
  tables at its top draws no empty line before them.
- A flow page in columns sets what the engine puts first and wider than its column across the columns,
  above their boxes; a table the engine sets above its paragraph's line stands before that line.
- The overlap check measures header rooms whose content runs out of them, and flow pages.

All documents are made in the tests; every test also runs the checks of ``preview_text_cover``.
"""

import re
from collections import Counter
from dataclasses import replace
from typing import Any

import pytest
from hwpx import HwpxDocument, experimental
from hwpx.tools.exporter import ListLabels
from lxml import etree, html
from preview_flow import tables_flow  # noqa: F401
from preview_overlap import drawn_wrongly, page_overlaps
from preview_text_cover import every_engine_preview_shows_the_text, missing_characters  # noqa: F401

from hwpx_automation.preview import layout_preview, render_layout_preview

pytestmark = pytest.mark.skipif(
    "AreaPlacement" not in getattr(experimental, "__all__", ()), reason="needs the core area placement API",
)

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
LABEL = re.compile(r'<span class="hwpx-paragraph-label"[^>]*>([^<]*)</span>')
ROOM = ("paragraph-label", "number or bullet is drawn at its paragraph's first line: its place and room are approximate")


def _limitations(preview: Any) -> dict[tuple[str, str], int]:
    return {(item["kind"], item["reason"]): item["count"] for item in preview.as_dict()["limitations"]}


def _listed() -> tuple[HwpxDocument, list[Any]]:
    document = HwpxDocument.new()
    numbered = [document.add_paragraph(f"항목 {index}") for index in range(3)]
    document.styles.apply_list_format(paragraphs=numbered, kind="number")
    bullet = document.add_paragraph("점 항목")
    document.styles.apply_list_format(paragraph=bullet, kind="bullet")
    cell = document.add_paragraph("").add_table(1, 1).cell(0, 0)
    cell.text = "칸 항목"
    document.styles.apply_list_format(paragraph=cell.paragraphs[0], kind="number")
    return document, [*numbered, bullet, cell.paragraphs[0]]


@pytest.mark.parametrize("flowing", [False, True], ids=["at-coordinates", "flowing"])
def test_numbered_and_bullet_paragraphs_show_their_labels_in_the_body_and_in_cells(
    flowing: bool, request: pytest.FixtureRequest,
) -> None:
    if flowing:
        request.getfixturevalue("tables_flow")
    document, paragraphs = _listed()
    expected = [ListLabels(document).label(paragraph) for paragraph in paragraphs]
    assert all(expected)

    preview = render_layout_preview(document.to_bytes())

    assert LABEL.findall("".join(preview.page_fragments)) == [html_escape(label) for label in expected]
    assert _limitations(preview)[ROOM] == len(paragraphs)  # each labelled paragraph once
    assert preview.fidelity_tier == "partial-engine-estimated-pagination"


def html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def test_a_label_left_out_is_missing_text() -> None:
    document, paragraphs = _listed()
    preview = render_layout_preview(document.to_bytes())

    stripped = tuple(LABEL.sub("", fragment) for fragment in preview.page_fragments)

    labels = Counter("".join(ListLabels(document).label(paragraph) for paragraph in paragraphs))
    labels.pop(" ", None)
    assert missing_characters(document, stripped) == labels
    assert not missing_characters(document, preview.page_fragments)


class _Labelled:
    """An engine line carrying a label of its own (the engine's label field, ahead of the core)."""

    def __init__(self, line: Any, label: Any) -> None:
        self._line, self.label = line, label

    def __getattr__(self, name: str) -> Any:
        return getattr(self._line, name)


def test_the_engines_own_label_is_drawn_where_its_line_carries_one(monkeypatch: pytest.MonkeyPatch) -> None:
    document, paragraphs = _listed()
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)
    first = layout.paragraphs[0]
    # the same characters as the count's "1." (the text cover check counts those), in its own order
    own = type("Label", (), {"text": ".1", "char_pr_id_ref": "0"})()
    moved = replace(first, lines=tuple(_Labelled(line, own) if not index else line
                                       for index, line in enumerate(first.lines)))
    changed = replace(layout, paragraphs=(moved, *layout.paragraphs[1:]))
    monkeypatch.setattr(experimental, "estimate_layout", lambda source: changed)

    labels = LABEL.findall("".join(render_layout_preview(payload).page_fragments))

    assert labels[0] == ".1"
    assert labels[1:] == [ListLabels(document).label(paragraph) for paragraph in paragraphs[1:]]


def test_outside_the_engine_preview_a_paragraph_is_drawn_without_a_label() -> None:
    document, paragraphs = _listed()
    styles = layout_preview._collect_style_maps(document.oxml.headers[0].element)

    markup = layout_preview._render_paragraph(paragraphs[0].element, styles, layout_preview._ObjectCounter())

    assert "hwpx-paragraph-label" not in markup


def _header(*paragraphs: str) -> Any:
    return etree.fromstring(
        f'<hp:header xmlns:hp="{HP_NS}"><hp:subList>{"".join(paragraphs)}</hp:subList></hp:header>'
    )


_TABLE = (
    '<hp:tbl textWrap="TOP_AND_BOTTOM" rowCnt="1" colCnt="1"><hp:sz width="6000" height="1300"/>'
    '<hp:pos treatAsChar="{char}" vertRelTo="PARA" vertAlign="TOP" vertOffset="0"/>'
    '<hp:tr><hp:tc><hp:subList><hp:p><hp:run><hp:t>머리 칸</hp:t></hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl>'
)


@pytest.mark.parametrize("char", ["1", "0"], ids=["as-a-character", "at-the-paragraph-top"])
def test_a_header_drawn_whole_sets_its_paragraphs_at_the_engines_tops(char: str) -> None:
    area = _header(f'<hp:p><hp:run>{_TABLE.format(char=char)}</hp:run></hp:p>',
                   '<hp:p><hp:run><hp:t>머리 글</hp:t></hp:run></hp:p>')
    line = type("Line", (), {})
    first, second = line(), line()
    first.top, first.text_start, second.top, second.text_start = 4000, 0, 5500, 0
    styles = layout_preview._collect_style_maps(None)

    markup = layout_preview._area_whole(area, "header", (5000, 4000, 40000, 2800), styles,
                                        layout_preview._ObjectCounter(), lines=(first, second))

    room = html.fromstring(markup)
    blocks = room.xpath("./div[@class='hwpx-area-paragraph']")
    assert [block.get("style") for block in blocks] == ["top: 0.00mm", "top: 5.29mm"]
    assert [child.tag for child in blocks[0]] == ["table"]  # no empty line before the table
    page = html.fromstring(f'<section data-layout-mode="positioned">{markup}</section>')
    assert not drawn_wrongly(page_overlaps(html.tostring(page, encoding="unicode")))


def _positioned(room_content: str, room_height: float) -> str:
    return (
        '<section data-layout-mode="positioned"><div class="hwpx-engine-canvas">'
        f'<div class="hwpx-placed-object hwpx-area-room" data-area-kind="header" data-approx="area" '
        f'style="left: 20.00mm; top: 15.00mm; width: 170.00mm; height: {room_height:.2f}mm">{room_content}</div>'
        '<div class="hwpx-engine-line" style="left: 20.00mm; top: 25.00mm; width: 170.00mm; '
        '--hwpx-line-height: 5.00mm; font-size: 10.00pt">본문</div></div></section>'
    )


def test_the_overlap_check_sees_a_header_room_running_over_the_body() -> None:
    tall = ('<p class="hwpx-paragraph" style="line-height: 160%"><span style="font-size: 10.00pt">머리</span></p>'
            '<table class="hwpx-table"><tbody><tr><td style="min-height: 8.00mm">칸</td></tr></tbody></table>')

    over = page_overlaps(_positioned(tall, 10.0))
    fits = page_overlaps(_positioned(tall, 16.0))

    assert over["area-room-overflow-body"] == 1 and drawn_wrongly(over) == 1
    assert not drawn_wrongly(fits)


def _flow_page(header: str, columns: str) -> str:
    return (
        '<section data-layout-mode="flow" style="width:210.00mm;padding:25.00mm 20.00mm 25.00mm 20.00mm">'
        f'<div class="hwpx-engine-flow"><div class="hwpx-placed-object hwpx-area-room" data-area-kind="header" '
        f'data-approx="area" style="left: 20.00mm; top: 15.00mm; width: 170.00mm; height: 10.00mm">{header}</div>'
        f'<div class="hwpx-engine-column-area">{columns}</div></div></section>'
    )


def test_the_overlap_check_sees_a_flow_pages_header_below_the_body_top_and_a_table_over_a_column() -> None:
    short = '<p class="hwpx-paragraph" style="line-height: 160%"><span style="font-size: 10.00pt">머리</span></p>'
    tall = short * 3
    narrow = ('<div class="hwpx-engine-column" style="width: 80.00mm"><table class="hwpx-table" style="width: 80.00mm">'
              '<tr><td>표</td></tr></table></div>'
              '<div class="hwpx-engine-column" style="width: 80.00mm"><div class="hwpx-engine-line">글</div></div>')
    wide = narrow.replace('class="hwpx-table" style="width: 80.00mm"', 'class="hwpx-table" style="width: 170.00mm"')

    clean = page_overlaps(_flow_page(short, narrow))
    found = page_overlaps(_flow_page(tall, wide))

    assert clean["flow pages"] == 1 and not drawn_wrongly(clean)
    assert found["area-room-flow"] == 1 and found["column-spill"] == 1 and drawn_wrongly(found) == 2


@pytest.mark.usefixtures("tables_flow")
def test_a_table_wider_than_its_column_stands_across_a_flow_pages_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    document = HwpxDocument.new()
    document.page.set_columns(2, same_gap=1500)
    table = document.add_paragraph("").add_table(2, 3)
    table.cell(0, 0).text = "넓은 표"
    body_width = experimental.estimate_layout(document.to_bytes()).pages[0].body[2]
    table.element.find(f"{HP}sz").set("width", str(body_width))
    table.element.find(f"{HP}pos").set("treatAsChar", "0")
    table.element.set("textWrap", "TOP_AND_BOTTOM")
    for index in range(40):
        document.add_paragraph(f"본문 문단 {index} " + "글자 " * 15)
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)
    placed, = (found for found in layout.tables if found.paragraph == 0)
    foot = max(row.top + row.height for row in placed.rows)
    # As the engine sets it for a table at the paragraph's top with the text below: the line under the table.
    anchor = layout.paragraphs[0]
    lowered = replace(anchor, lines=tuple(replace(line, top=foot) for line in anchor.lines))
    moved = replace(layout, paragraphs=(lowered, *layout.paragraphs[1:]))
    monkeypatch.setattr(experimental, "estimate_layout", lambda source: moved)

    page = html.fromstring(render_layout_preview(payload).page_fragments[0])

    assert page.get("data-layout-mode") == "flow"
    across, = page.xpath("./div[@class='hwpx-engine-flow']/div[@class='hwpx-engine-column-across']")
    assert across.xpath("./table[@data-engine-table]")
    assert not page.xpath(".//div[@class='hwpx-engine-column']//table[@data-engine-table]")
    assert across.getnext().get("class") == "hwpx-engine-column-area"  # the columns start under it
    assert not drawn_wrongly(page_overlaps(html.tostring(page, encoding="unicode")))


@pytest.mark.usefixtures("tables_flow")
def test_a_table_the_engine_sets_above_its_paragraphs_line_stands_before_it(monkeypatch: pytest.MonkeyPatch) -> None:
    document = HwpxDocument.new()
    table = document.add_paragraph("표를 담은 문단").add_table(2, 2)
    table.element.find(f"{HP}pos").set("treatAsChar", "0")
    table.element.set("textWrap", "TOP_AND_BOTTOM")
    document.add_paragraph("뒤 문단")
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)
    placed, = layout.tables
    foot = max(row.top + row.height for row in placed.rows)
    anchor = layout.paragraphs[0]
    lowered = replace(anchor, lines=tuple(replace(line, top=foot) for line in anchor.lines))
    monkeypatch.setattr(experimental, "estimate_layout",
                        lambda source: replace(layout, paragraphs=(lowered, *layout.paragraphs[1:])))

    page = html.fromstring(render_layout_preview(payload).page_fragments[0])

    body, = page.xpath("./div[@class='hwpx-engine-flow']")
    assert [child.tag if child.tag == "table" else child.get("class") for child in body][:2] == [
        "table", "hwpx-engine-line"]
