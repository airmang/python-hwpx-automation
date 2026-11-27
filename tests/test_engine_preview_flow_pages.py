"""Flow pages (pages drawn as approximate flow) keep their columns, their paper height and their margins.

- A flow page with more than one column stacks each column in its own box, at the engine's column
  width and gap, holding what the engine sets in that column; a one-column flow page is as before.
- A flow page box is as high as its paper. What the flow stacks past the body's foot is moved by the
  page's script into the overflow band under the box; the footer stands on the box's foot.
- Page numbers show the number of the page they are drawn on, in the engine's page order.

All documents are made in the tests; every test also runs the checks of ``preview_text_cover``.
"""

import re
from collections import Counter
from dataclasses import replace

import pytest
from hwpx import HwpxDocument, experimental
from lxml import html

from hwpx_automation.preview import layout_preview, render_layout_preview
from preview_flow import tables_flow  # noqa: F401
from preview_text_cover import every_engine_preview_shows_the_text  # noqa: F401

pytestmark = pytest.mark.skipif(
    "AreaPlacement" not in getattr(experimental, "__all__", ()), reason="needs the core area placement API",
)

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
MM = 7200 / 25.4


def _mm(element, name: str) -> float:
    found = re.search(rf"(?:^|;)\s*{re.escape(name)}:\s*(-?[\d.]+)mm", element.get("style") or "")
    assert found, f"{name} missing in {element.get('style')}"
    return float(found.group(1))


def _limitations(preview) -> dict[tuple[str, str], int]:
    return {(item["kind"], item["reason"]): item["count"] for item in preview.as_dict()["limitations"]}


def _long_body(document: HwpxDocument, count: int = 60) -> None:
    for index in range(count):
        document.add_paragraph(f"본문 문단 {index} " + "글자 " * 20)


def _two_column_document() -> HwpxDocument:
    document = HwpxDocument.new()
    document.page.set_columns(2, same_gap=1500)
    _long_body(document, 45)
    document.add_paragraph("").add_table(2, 2).cell(0, 0).text = "흐르는 표"  # drawn flowing: the page flows
    return document


@pytest.mark.usefixtures("tables_flow")
def test_a_two_column_flow_page_stacks_each_column_in_its_own_box() -> None:
    payload = _two_column_document().to_bytes()
    layout = experimental.estimate_layout(payload)
    flow_pages = [
        index for index, fragment in enumerate(render_layout_preview(payload).page_fragments)
        if 'data-layout-mode="flow"' in fragment
    ]
    page_number = flow_pages[0]
    placement = layout.pages[page_number]
    area, = placement.column_areas
    assert len(area.widths) == 2 and area.gap == 1500

    page = html.fromstring(render_layout_preview(payload).page_fragments[page_number])

    row, = page.xpath("./div[@class='hwpx-engine-flow']/div[@class='hwpx-engine-column-area']")
    columns = row.xpath("./div[@class='hwpx-engine-column']")
    assert [column.get("data-column") for column in columns] == ["0", "1"]
    assert [_mm(column, "width") for column in columns] == pytest.approx([w / MM for w in area.widths], abs=0.006)
    assert _mm(columns[1], "margin-left") == pytest.approx(area.gap / MM, abs=0.006)
    engine = Counter(
        line.position.column for paragraph in layout.paragraphs for line in paragraph.lines
        if line.position.page == page_number and not line.hidden and line.text is not None
    )
    assert engine[0] and engine[1]  # the engine sets lines in both columns
    for column in columns:
        lines = column.xpath(".//div[@class='hwpx-engine-line']")
        assert len(lines) == engine[int(column.get("data-column"))]
        assert {line.get("data-column") for line in lines} == {column.get("data-column")}
    # A line's offset is taken from its own column's left edge.
    first_right = columns[1].xpath("./div[@class='hwpx-engine-line']")[0]
    placed = next(line for paragraph in layout.paragraphs for line in paragraph.lines
                  if line.position.page == page_number and line.position.column == 1)
    assert _mm(first_right, "--hwpx-line-offset") == pytest.approx(placed.x / MM, abs=0.006)


@pytest.mark.usefixtures("tables_flow")
def test_a_column_starts_at_its_first_line_when_the_engine_sets_it_lower(monkeypatch) -> None:
    payload = _two_column_document().to_bytes()
    layout = experimental.estimate_layout(payload)
    page_number = next(
        index for index, fragment in enumerate(render_layout_preview(payload).page_fragments)
        if 'data-layout-mode="flow"' in fragment
    )
    lowered = 5000  # as if something wider than the first column stood across both above it

    def lower(paragraph):
        return replace(paragraph, lines=tuple(
            replace(line, top=line.top + lowered)
            if line.position.page == page_number and line.position.column == 1 else line
            for line in paragraph.lines
        ))

    moved = replace(layout, paragraphs=tuple(lower(paragraph) for paragraph in layout.paragraphs))
    monkeypatch.setattr(experimental, "estimate_layout", lambda document: moved)

    page = html.fromstring(render_layout_preview(payload).page_fragments[page_number])

    left, right = page.xpath(".//div[@class='hwpx-engine-column']")
    lead, = right.xpath("./div[@class='hwpx-engine-column-lead']")
    assert lead.getparent().index(lead) == 0
    first = min(line.top for paragraph in moved.paragraphs for line in paragraph.lines
                if line.position.page == page_number and line.position.column == 1)
    area = moved.pages[page_number].column_areas[0]
    assert _mm(lead, "height") == pytest.approx((first - max(area.top, moved.pages[page_number].body[1])) / MM,
                                                abs=0.006)
    assert not left.xpath("./div[@class='hwpx-engine-column-lead']")  # its first line stands at the top


@pytest.mark.usefixtures("tables_flow")
def test_a_one_column_flow_page_has_no_column_boxes() -> None:
    document = HwpxDocument.new()
    document.add_paragraph("표 앞 문단")
    document.add_paragraph("").add_table(2, 2)
    page = html.fromstring(render_layout_preview(document.to_bytes()).page_fragments[0])

    assert page.get("data-layout-mode") == "flow"
    assert not page.xpath(".//div[@class='hwpx-engine-column-area' or @class='hwpx-engine-column']")


@pytest.mark.usefixtures("tables_flow")
def test_a_flow_page_keeps_its_paper_height_and_its_footer_on_the_foot() -> None:
    document = HwpxDocument.new()
    document.page.set_header(text="머리말의 글")
    document.page.set_footer(text="꼬리말의 글")
    document.add_paragraph("표 앞 문단")
    document.add_paragraph("").add_table(2, 2)
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)

    preview = render_layout_preview(payload)

    page = html.fromstring(preview.page_fragments[0])
    assert page.get("data-layout-mode") == "flow"
    paper = layout.pages[0].paper_height / MM
    assert _mm(page, "min-height") == pytest.approx(paper, abs=0.006)
    assert _mm(page, "--hwpx-paper-height") == pytest.approx(paper, abs=0.006)
    footer, = page.xpath(".//div[@class='hwpx-area-layer'][@data-area-kind='footer']")
    assert footer.getparent().get("class") == "hwpx-area-foot"
    header, = page.xpath(".//div[@class='hwpx-area-layer'][@data-area-kind='header']")
    assert header.getparent().get("class") == "hwpx-engine-flow"  # a header keeps its place from the top
    assert ".hwpx-area-foot { position: absolute; left: 0; right: 0; bottom: 0; " in preview.html
    # The overflow band is under the body, empty and hidden until the script moves into it what overflows.
    band, = page.xpath("./div[@class='hwpx-engine-spill']")
    assert band.get("hidden") is not None and not "".join(band.itertext()).strip()
    assert band.getprevious().get("class") == "hwpx-engine-flow"
    assert "hwpx-engine-spill-flow" in preview.html and "function spill(page)" in preview.html
    assert "function splitRows(item, foot)" in preview.html


def test_a_page_number_in_a_footer_shows_the_number_of_its_page() -> None:
    document = HwpxDocument.new()
    document.page.set_page_number()
    _long_body(document)
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)
    assert layout.estimate.pages > 1

    preview = render_layout_preview(payload)

    for number, fragment in enumerate(preview.page_fragments):
        page = html.fromstring(fragment)
        shown = page.xpath(".//*[@data-area-kind='footer']//span[@class='hwpx-page-number-text']")
        # Shown by the style sheet, not as page text (Hangul lists no text for a page number).
        assert [span.get("data-number-text") for span in shown] == [str(number + 1)]
        assert not "".join(span.text_content() for span in shown)


def _page_number_control(document: HwpxDocument, **attributes: str) -> None:
    """A page number control (``hp:ctrl/hp:pageNum``) in the first paragraph."""
    run = document.sections[0].element.find(f"{HP}p/{HP}run")
    control = run.makeelement(f"{HP}ctrl", {})
    control.append(control.makeelement(f"{HP}pageNum", attributes))
    run.append(control)


def test_a_page_number_control_stands_in_the_footer_margin_of_every_page() -> None:
    document = HwpxDocument.new()
    _page_number_control(document, pos="BOTTOM_CENTER", formatType="ROMAN_SMALL", sideChar="-")
    _long_body(document)
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)
    assert layout.estimate.pages > 1

    preview = render_layout_preview(payload)

    margin = int(document.sections[0].element.find(f".//{HP}pagePr/{HP}margin").get("footer"))
    for number, fragment in enumerate(preview.page_fragments):
        mark, = html.fromstring(fragment).xpath(".//div[@class='hwpx-page-number']")
        # Shown by the style sheet, not as page text (Hangul lists no text for a page number control).
        assert mark.get("data-number-text") == f"- {['i', 'ii', 'iii', 'iv', 'v'][number]} -"
        assert not mark.text_content()
        assert mark.get("data-approx") == "page-number"
        left, top, width, height = layout.pages[number].body
        assert _mm(mark, "top") == pytest.approx((top + height) / MM, abs=0.006)
        assert _mm(mark, "height") == pytest.approx(margin / MM, abs=0.006)
        assert _mm(mark, "left") == pytest.approx(left / MM, abs=0.006)
    limits = _limitations(preview)
    assert limits["page-number", layout_preview._PAGE_NUMBER_PLACE[1]] == len(preview.pages)
    assert ":is(.hwpx-page-number, .hwpx-page-number-text)::before { content: attr(data-number-text); }" \
        in preview.html


def test_a_new_page_number_restarts_the_count_and_a_hidden_one_is_not_drawn() -> None:
    document = HwpxDocument.new()
    _page_number_control(document, pos="TOP_RIGHT", formatType="DIGIT")
    _long_body(document, 90)
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)
    assert layout.estimate.pages >= 3
    second = next(placed.paragraph for placed in layout.paragraphs
                  if placed.lines and placed.lines[0].position.page == 1)
    document.page.add_number_restart(second, number=7)
    payload = document.to_bytes()
    assert experimental.estimate_layout(payload).estimate.pages == layout.estimate.pages

    preview = render_layout_preview(payload)

    shown = [[mark.get("data-number-text")
              for mark in html.fromstring(fragment).xpath(".//div[@class='hwpx-page-number']")]
             for fragment in preview.page_fragments]
    assert shown[:3] == [["1"], ["7"], ["8"]]
    mark = html.fromstring(preview.page_fragments[0]).xpath(".//div[@class='hwpx-page-number']")[0]
    assert "justify-content: flex-end" in mark.get("style")  # at the right, in the header margin
    assert _mm(mark, "top") < layout.pages[0].body[1] / MM


@pytest.mark.parametrize(("value", "style", "text"), [
    (3, "DIGIT", "3"), (4, "ROMAN_CAPITAL", "IV"), (9, "ROMAN_SMALL", "ix"), (2, "LATIN_CAPITAL", "B"),
    (3, "HANGUL_SYLLABLE", "다"), (2, "CIRCLED_DIGIT", "②"), (10, "IDEOGRAPH", "十"), (None, None, None),
])
def test_page_numbers_are_written_in_the_file_s_number_style(value, style, text) -> None:
    issues: Counter[tuple[str, str]] = Counter()
    if value is None:  # a style not written here is drawn in digits, counted
        assert layout_preview._number_text(5, "DECAGON_CIRCLE", issues) == "5"
        assert issues[layout_preview._NUMBER_STYLE_UNREAD] == 1
        return
    assert layout_preview._number_text(value, style, issues) == text and not issues
