"""Exercise engine page placement through the HTML preview entry point."""

import io
import re
import warnings
from base64 import b64decode
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from hwpx import HwpxDocument, experimental
from lxml import etree, html

from hwpx_automation.preview import layout_preview, render_layout_preview
from preview_flow import tables_flow  # noqa: F401
from preview_text_cover import every_engine_preview_shows_the_text  # noqa: F401

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


@pytest.mark.usefixtures("tables_flow")
@pytest.mark.parametrize("mode", ["pages", "long"])
def test_only_the_page_with_a_flowing_table_flows_in_document_order(mode: str) -> None:
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
    table_markup, = body.xpath(".//table")
    # The table is placed as a character: it stands in its paragraph's own (empty) line.
    assert table_markup.getparent().get("data-engine-host") == "1"
    assert table_markup.getparent().getparent() is body
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


def _same_text_on_two_pages(document: HwpxDocument) -> None:
    """The same paragraphs twice, the second time from a new page."""

    def body() -> object:
        made = [
            document.add_paragraph("두 쪽에 똑같이 놓이는 여러 줄 문단 " * 12),
            document.add_paragraph("한 줄 문단"),
            document.add_paragraph("줄 간격과 문단 위 간격을 바꾼 문단 " * 8),
            document.add_paragraph("끝 문단"),
        ]
        for paragraph, (line_spacing, before) in zip(made, ((160, 0), (160, 0), (220, 14), (130, 6))):
            paragraph.line_spacing = line_spacing
            paragraph.spacing_before_pt = before
        return made[0]

    body()
    body().element.set("pageBreak", "1")


@pytest.mark.usefixtures("tables_flow")
def test_flow_lines_take_the_engine_advance_of_a_positioned_page() -> None:
    estimate_layout = getattr(experimental, "estimate_layout", None)
    if estimate_layout is None:
        pytest.skip("needs the core placement API")
    document = HwpxDocument.new()
    _same_text_on_two_pages(document)
    document.add_paragraph("").add_table(2, 2)  # drawn flowing (tables_flow): the second page flows
    payload = document.to_bytes()

    preview = render_layout_preview(payload)

    positioned, flow = map(html.fromstring, preview.page_fragments)
    assert (positioned.get("data-layout-mode"), flow.get("data-layout-mode")) == ("positioned", "flow")
    first_page = positioned.xpath(".//div[@class='hwpx-engine-line']")
    second_page = flow.xpath("./div[@class='hwpx-engine-flow']/div[@class='hwpx-engine-line']")
    *text_lines, host = second_page
    assert [line.text_content() for line in text_lines] == [line.text_content() for line in first_page]
    engine_tops = [
        line.top for paragraph in estimate_layout(payload).paragraphs for line in paragraph.lines
        if line.position.page == 0
    ]
    pitch = [below - above for above, below in zip(engine_tops, engine_tops[1:])]
    assert len(set(pitch)) > 1  # line spacing and paragraph spacing are in it
    # Every line but the page's last stands the engine's distance above the next one ...
    assert [int(line.get("data-engine-advance")) for line in text_lines[:-1]] == pitch
    assert text_lines[-1].get("data-engine-advance") is not None  # ... the table's line included
    # ... and that is the pitch the positioned page draws the same paragraphs at.
    tops_mm = [float(re.search(r"(?<![\w-])top: ([\d.]+)mm", line.get("style")).group(1)) for line in first_page]
    advances_mm = [
        float(re.search(r"--hwpx-line-advance: ([\d.]+)mm", line.get("style")).group(1)) for line in text_lines[:-1]
    ]
    assert advances_mm == pytest.approx([below - above for above, below in zip(tops_mm, tops_mm[1:])], abs=0.011)
    assert ".hwpx-engine-flow [data-engine-advance] { height: var(--hwpx-line-advance);" in preview.html
    # The page's last line has no next line: it keeps its own height.
    assert host.get("data-engine-advance") is None and host.get("data-engine-host") == "1"
    assert not positioned.xpath(".//*[@data-engine-advance]")


@pytest.mark.usefixtures("tables_flow")
def test_a_flow_line_before_a_floating_table_keeps_its_own_height() -> None:
    if not hasattr(experimental, "estimate_layout"):
        pytest.skip("needs the core placement API")
    document = HwpxDocument.new()
    document.add_paragraph("표 앞 문단")
    table = document.add_paragraph("").add_table(2, 2)
    table.element.find("{*}pos").set("treatAsChar", "0")
    document.add_paragraph("표 뒤 문단")

    page = html.fromstring(render_layout_preview(document.to_bytes()).page_fragments[0])

    body, = page.xpath("./div[@class='hwpx-engine-flow']")
    before, anchor, table_markup, after = body
    assert (before.get("class"), anchor.get("class"), table_markup.tag) == ("hwpx-engine-line",) * 2 + ("table",)
    assert before.get("data-engine-advance") is not None  # the next line follows it
    # The table takes room the engine's line tops do not describe: no advance is made up.
    assert anchor.get("data-engine-advance") is None and anchor.get("data-engine-host") is None
    assert after.get("data-engine-advance") is None  # the page's last line


def test_rows_take_the_engine_height_or_else_the_authored_cell_height(monkeypatch) -> None:
    if "TablePlacement" not in experimental.__all__:
        pytest.skip("needs the core table placement API")
    document = HwpxDocument.new()
    for wrap in ("TOP_AND_BOTTOM", "IN_FRONT_OF_TEXT"):  # the layout path keeps no rows for the second
        table = document.add_paragraph("").add_table(3, 2)
        table.element.find("{*}pos").set("treatAsChar", "0")
        table.element.set("textWrap", wrap)
        for index, cell in enumerate(table.element.iter("{*}tc")):
            cell.find("{*}cellSz").set("height", "5000" if index < 2 else "2500")
    payload = document.to_bytes()
    placed, unplaced = experimental.estimate_layout(payload).tables
    assert [row.height for row in placed.rows] == [5000, 2500, 2500] and not unplaced.rows

    preview = render_layout_preview(payload)

    engine_table, authored_table = html.fromstring(preview.page_fragments[0]).xpath(".//table")
    heights = ["height:17.64mm", "height:8.82mm", "height:8.82mm"]
    assert [(row.get("data-row-height"), row.get("style")) for row in engine_table.xpath(".//tr")] == [
        (None, height) for height in heights
    ]
    assert [(row.get("data-row-height"), row.get("style")) for row in authored_table.xpath(".//tr")] == [
        ("authored", height) for height in heights
    ]
    assert {
        "kind": "table-row", "reason": "row height is the authored cell height, not an engine value", "count": 3,
    } in preview.as_dict()["limitations"]
    # The approximate preview of a document the estimate does not answer is drawn as before.
    monkeypatch.setattr(experimental, "estimate_layout", None)
    assert "data-row-height" not in render_layout_preview(payload).html


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
        markup = html.fromstring(fragment)
        assert markup.get("data-layout-mode") == "positioned"  # every row and cell has its coordinates
        cells = markup.xpath(".//div[@class='hwpx-engine-cell']")
        observed = list(dict.fromkeys(
            (int(cell.get("data-engine-row")), cell.get("data-engine-repeated") == "1") for cell in cells
        ))
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


def _saved_as_hwp(tmp_path, text: str):
    document = HwpxDocument.new()
    document.add_paragraph(text)
    path = tmp_path / "made.hwp"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # writing .hwp is experimental and says so
        document.save(str(path))
    return path


def test_the_preview_reads_the_parts_python_hwpx_opened(tmp_path, monkeypatch) -> None:
    if not hasattr(experimental, "estimate_layout"):
        pytest.skip("needs the core placement API")
    hwp = _saved_as_hwp(tmp_path, "한글 5.0 형식으로 저장한 문단")  # no package for zipfile; python-hwpx opens it
    document = HwpxDocument.new()
    document.add_paragraph("꾸러미로 저장한 문단")
    monkeypatch.setattr(layout_preview, "_read_package_parts", lambda source: pytest.fail("read a second time"))

    for source, text in ((hwp, "한글 5.0 형식"), (hwp.read_bytes(), "한글 5.0 형식"), (document.to_bytes(), "꾸러미로")):
        preview = render_layout_preview(source)
        assert preview.fidelity_tier == "engine-estimated-pagination" and len(preview.pages) == 1
        assert text in preview.html


def test_what_an_hwp_source_lost_in_conversion_is_named(tmp_path, monkeypatch) -> None:
    if not hasattr(experimental, "estimate_layout"):
        pytest.skip("needs the core placement API")
    hwp = _saved_as_hwp(tmp_path, "변환해서 읽는 문단")
    report = SimpleNamespace(unconverted={"chart": 2}, dropped={"script": 1})
    monkeypatch.setattr(HwpxDocument, "conversion_report", property(lambda self: report))

    preview = render_layout_preview(hwp)

    assert preview.fidelity_tier == "partial-engine-estimated-pagination"
    assert [item.as_dict() for item in preview.limitations] == [
        {"kind": "hwp-conversion", "reason": "chart is not converted into the previewed document", "count": 2},
        {"kind": "hwp-conversion", "reason": "script has no HWPX form and is left out", "count": 1},
    ]


@pytest.mark.parametrize("source", [b"not a package at all", b""])
def test_a_source_nothing_reads_raises_as_it_did(source: bytes, tmp_path) -> None:
    path = tmp_path / "plain.hwpx"
    path.write_bytes(source)
    for given in (source, path, str(path)):
        with pytest.raises(ValueError, match=r"^unable to read HWPX package: File is not a zip file$"):
            render_layout_preview(given)
    with pytest.raises(ValueError, match=r"^unable to read HWPX package: \[Errno 2\]"):
        render_layout_preview(tmp_path / "missing.hwpx")


def test_a_package_python_hwpx_refuses_keeps_its_approximate_preview(monkeypatch) -> None:
    if not hasattr(experimental, "estimate_layout"):
        pytest.skip("needs the core placement API")
    document = HwpxDocument.new()
    document.add_paragraph("첫 쪽")
    document.add_paragraph("다음 쪽").element.set("pageBreak", "1")
    output = io.BytesIO()
    with ZipFile(io.BytesIO(document.to_bytes())) as source, ZipFile(output, "w") as target:
        for member in source.namelist():
            if member != "mimetype":  # python-hwpx does not open a package without it
                target.writestr(member, source.read(member))
    payload = output.getvalue()

    preview = render_layout_preview(payload)
    monkeypatch.setattr(experimental, "estimate_layout", None)
    legacy = render_layout_preview(payload)

    assert preview.fidelity_tier == "text-approx-pagination"
    assert preview.warnings == ("layout estimate unavailable: HwpxStructureError",)
    assert (preview.pages, preview.page_fragments) == (legacy.pages, legacy.page_fragments)
    assert len(preview.pages) == 2
