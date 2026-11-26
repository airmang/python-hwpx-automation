"""Exercise engine page placement through the HTML preview entry point."""

import io
import re
from base64 import b64decode
from zipfile import ZipFile

import pytest
from hwpx import HwpxDocument, experimental
from lxml import etree, html

from hwpx_automation.preview import render_layout_preview

HH = "{http://www.hancom.co.kr/hwpml/2011/head}"


@pytest.mark.parametrize("mode", ["pages", "long"])
def test_the_preview_uses_engine_pages_and_text_ranges(mode: str) -> None:
    estimate_layout = getattr(experimental, "estimate_layout", None)
    if estimate_layout is None:
        pytest.skip("needs the core placement API")
    document = HwpxDocument.new()
    document.add_paragraph("엔진이 끊는 여러 줄의 문장 🙂 " * 400)
    payload = document.to_bytes()
    layout = estimate_layout(payload)

    preview = render_layout_preview(payload, mode=mode)

    assert len(preview.pages) == layout.estimate.pages > 1
    assert preview.fidelity_tier == "engine-estimated-pagination"
    for index, fragment in enumerate(preview.page_fragments):
        expected = [
            (line.text_start, line.text_end)
            for paragraph in layout.paragraphs
            for line in paragraph.lines if line.position.page == index and not line.hidden
        ]
        actual = re.findall(r'data-text-start="(\d+)" data-text-end="(\d+)"', fragment)
        assert [(int(start), int(end)) for start, end in actual] == expected
    assert "white-space: pre;" in preview.html
    assert not preview.limitations


@pytest.mark.parametrize("mode", ["pages", "long"])
def test_declined_estimate_keeps_legacy_page_fragments(mode: str, monkeypatch) -> None:
    if not hasattr(experimental, "estimate_layout"):
        pytest.skip("needs the core placement API")
    document = HwpxDocument.new()
    document.add_paragraph("첫 페이지")
    document.add_paragraph("다음 페이지").element.set("pageBreak", "1")
    output = io.BytesIO()
    with ZipFile(io.BytesIO(document.to_bytes())) as source, ZipFile(output, "w") as target:
        for member in source.namelist():
            data = source.read(member)
            if member == "Contents/header.xml":
                header = etree.fromstring(data)
                compatible = header.find(f"{HH}compatibleDocument")
                if compatible is None:
                    compatible = etree.SubElement(header, f"{HH}compatibleDocument")
                compatible.set("targetProgram", "MS_WORD")
                data = etree.tostring(header)
            target.writestr(member, data)
    payload = output.getvalue()

    preview = render_layout_preview(payload, mode=mode)
    monkeypatch.setattr(experimental, "estimate_layout", None)
    legacy = render_layout_preview(payload, mode=mode)

    assert preview.fidelity_tier == "text-approx-pagination"
    assert preview.pages == legacy.pages
    assert preview.page_fragments == legacy.page_fragments
    assert any("MS Word" in warning for warning in preview.warnings)


@pytest.mark.parametrize("mode", ["pages", "long"])
def test_only_the_page_with_an_unplaced_table_flows_in_document_order(mode: str) -> None:
    estimate_layout = getattr(experimental, "estimate_layout", None)
    if estimate_layout is None:
        pytest.skip("needs the core placement API")
    document = HwpxDocument.new()
    document.add_paragraph("표 앞 문단")
    table = document.add_paragraph("").add_table(3, 2)
    table.cell(0, 0).text = "표 내용"
    document.add_paragraph("표 뒤 문단")
    document.add_paragraph("다음 쪽 문단").element.set("pageBreak", "1")
    payload = document.to_bytes()

    preview = render_layout_preview(payload, mode=mode)

    assert len(preview.pages) == estimate_layout(payload).estimate.pages == 2
    assert preview.fidelity_tier == "partial-engine-estimated-pagination"
    flow, positioned = map(html.fromstring, preview.page_fragments)
    assert flow.get("data-layout-mode") == "flow"
    assert positioned.get("data-layout-mode") == "positioned"
    assert not flow.xpath(".//aside")
    body = flow.find("div[@class='hwpx-engine-flow']")
    assert body is not None
    table_markup, = body.findall("table")
    assert "표 내용" in table_markup.text_content()
    text = body.text_content()
    assert text.index("표 앞 문단") < text.index("표 내용") < text.index("표 뒤 문단")
    assert positioned.find("div[@class='hwpx-engine-canvas']") is not None
    actual_ranges = [(line.get("data-text-start"), line.get("data-text-end"))
                     for line in body.findall("div[@class='hwpx-engine-line']")]
    expected_ranges = [
        (str(line.text_start), str(line.text_end))
        for paragraph in estimate_layout(payload).paragraphs for line in paragraph.lines
        if line.position.page == 0 and not line.hidden and line.text is not None
    ]
    assert actual_ranges == expected_ranges
    assert any(item["kind"] == "table" for item in preview.as_dict()["limitations"])
    assert any(item["kind"] == "page-flow" and item["count"] == 1 for item in preview.as_dict()["limitations"])


def test_table_rows_follow_the_engine_across_pages_and_repeat_headers() -> None:
    if "TablePlacement" not in experimental.__all__:
        pytest.skip("needs the core table placement API")
    document = HwpxDocument.new()
    table = document.add_paragraph("").add_table(52, 2)
    table.element.find("{*}pos").set("treatAsChar", "0")
    table.element.attrib.update({"pageBreak": "TABLE", "repeatHeader": "1"})
    for row in range(52):
        table.cell(row, 0).text = f"확인 {row + 1}"
    table.cell(0, 0).element.set("header", "1")
    table.cell(0, 1).element.set("header", "1")
    payload = document.to_bytes()

    preview = render_layout_preview(payload)
    table_placement, = experimental.estimate_layout(payload).tables

    for page, fragment in enumerate(preview.page_fragments):
        elements = html.fromstring(fragment).xpath(".//tr[@data-engine-row]")
        observed = [(int(row.get("data-engine-row")), row.get("data-engine-repeated") == "1") for row in elements]
        expected = [(row.row, row.repeated) for row in table_placement.rows if row.page == page]
        assert observed == expected and observed


def test_engine_line_renders_each_original_run_style() -> None:
    if "TablePlacement" not in experimental.__all__:
        pytest.skip("needs the core run placement API")
    doc = HwpxDocument.new()
    paragraph = doc.add_paragraph("기본 🙂")
    paragraph.add_run("강조", bold=True, italic=True, underline=True, color="#CC0000", size=18)
    paragraph.add_run("마침")

    preview = render_layout_preview(doc.to_bytes())
    page = html.fromstring(preview.page_fragments[0])
    line, = [item for item in page.xpath(".//div[@class='hwpx-engine-line']") if item.text_content()]
    plain, styled, tail = line.findall("span")
    assert [plain.text, styled.text, tail.text] == ["기본 🙂", "강조", "마침"]
    assert all(piece in styled.get("style") for piece in (
        "font-size: 18.00pt", "color: #CC0000", "font-weight: bold",
        "font-style: italic", "text-decoration-line: underline",
    ))


def test_supported_embedded_picture_and_shape_overlap_the_engine_page() -> None:
    if "ObjectPlacement" not in experimental.__all__:
        pytest.skip("needs the core object placement API")
    doc = HwpxDocument.new()
    paragraph = doc.add_paragraph("그림과 도형이 겹치는 글")
    png = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/qFUAAAAASUVORK5CYII=")
    picture = paragraph.add_picture(doc.media.add_image(png, "png"), width=6000, height=4000)
    shape = doc.shapes.add_rectangle(6000, 4000, paragraph=paragraph, treat_as_char=False)
    for element, wrap in ((picture.element, "BEHIND_TEXT"), (shape.element, "IN_FRONT_OF_TEXT")):
        element.set("textWrap", wrap)
        element.find("{*}pos").attrib.update({
            "treatAsChar": "0", "flowWithText": "0", "horzRelTo": "PAPER", "vertRelTo": "PAPER",
            "horzAlign": "LEFT", "vertAlign": "TOP", "horzOffset": "8504", "vertOffset": "10000",
        })

    preview = render_layout_preview(doc.to_bytes())
    page = html.fromstring(preview.page_fragments[0])
    behind, = page.xpath(".//*[@data-overlay='behind']")
    front, = page.xpath(".//*[@data-overlay='front']")
    assert behind.find("img").get("src").startswith("data:image/png;base64,")
    assert "hwpx-shape-outline" in front.get("class")
    assert "left: 30.00mm" in behind.get("style")
    assert "top: 35.28mm" in front.get("style")
