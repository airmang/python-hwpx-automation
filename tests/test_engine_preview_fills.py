"""Cell and page fills of the engine-placed HTML preview: what is drawn, what is reduced and named."""

import io
from base64 import b64decode
from zipfile import ZipFile

import pytest
from hwpx import HwpxDocument, experimental
from lxml import etree, html

from hwpx_automation.preview import layout_preview, render_layout_preview
from preview_text_cover import every_engine_preview_shows_the_text  # noqa: F401

pytestmark = pytest.mark.skipif(
    not hasattr(experimental, "estimate_layout"), reason="needs the core placement API",
)

HC = "{http://www.hancom.co.kr/hwpml/2011/core}"
PIXEL = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/qFUAAAAASUVORK5CYII=")
GRADIENT = {
    "type": "LINEAR", "angle": 0, "centerX": 0, "centerY": 0, "step": 255, "colorNum": 2,
    "stepCenter": 50, "alpha": 0, "colors": ["#102040", "#305070"],
}


def _with_header(payload: bytes, change) -> bytes:
    output = io.BytesIO()
    with ZipFile(io.BytesIO(payload)) as source, ZipFile(output, "w") as target:
        for member in source.namelist():
            data = source.read(member)
            if member == "Contents/header.xml":
                header = etree.fromstring(data)
                change(header)
                data = etree.tostring(header)
            target.writestr(member, data)
    return output.getvalue()


def _limitations(preview) -> dict[tuple[str, str], int]:
    return {(item["kind"], item["reason"]): item["count"] for item in preview.as_dict()["limitations"]}


def _cells(fragment: str, drawn: str) -> list:
    """The cells of the page's tables: flowing rows' ``td``, or the boxes of a table at coordinates."""
    page = html.fromstring(fragment)
    cells = page.xpath(".//td" if drawn == "flow" else ".//div[@class='hwpx-engine-cell']")
    assert cells and page.get("data-layout-mode") == ("flow" if drawn == "flow" else "positioned")
    return cells


def _fill(cell) -> str:
    """The cell's background as drawn; a box at coordinates leaves out a transparent one."""
    style = cell.get("style")
    return style.split("background: ", 1)[1].split(";", 1)[0] if "background: " in style else "transparent"


@pytest.fixture(params=["coordinates", "flow"])
def drawn(request, monkeypatch) -> str:
    """Cells drawn at the engine's coordinates, and drawn as the flowing rows of a flow page."""
    if request.param == "flow":
        monkeypatch.setattr(layout_preview, "_drawable_at_coordinates", lambda table: False)
    return request.param


def test_a_dark_cell_fill_shows_under_text_in_the_page_colour(drawn) -> None:
    document = HwpxDocument.new()
    table = document.add_paragraph("").add_table(1, 2)
    label = table.cell(0, 0)
    label.text = ""
    label.paragraphs[0].add_run("이름표", color="#FFFFFF")
    table.cell(0, 1).text = "값"
    table.set_cell_shading(0, 0, "#1F2A44")

    preview = render_layout_preview(document.to_bytes())

    dark, plain = _cells(preview.page_fragments[0], drawn)
    assert _fill(dark) == "#1F2A44"
    text, = [span for span in dark.xpath(".//span") if span.text == "이름표"]
    assert "color: #FFFFFF" in text.get("style")
    assert _fill(plain) == "transparent"
    assert not any(kind == "table-cell" and "fill" in reason for kind, reason in _limitations(preview))


def test_pattern_gradient_and_picture_cell_fills_are_reduced_and_counted(monkeypatch, drawn) -> None:
    document = HwpxDocument.new()
    table = document.add_paragraph("").add_table(1, 5)
    table.set_cell_shading(0, 0, "#203050")
    pattern = table.cell(0, 0).element.get("borderFillIDRef")
    table.set_cell_shading(0, 4, "#405060")
    bare_pattern = table.cell(0, 4).element.get("borderFillIDRef")
    gradient = document.styles.ensure_border_fill(fill_gradient=GRADIENT)
    picture = document.styles.ensure_border_fill(fill_image=document.media.add_image(PIXEL, "png"))
    for column, fill in ((1, gradient), (2, gradient), (3, picture)):
        table.cell(0, column).element.set("borderFillIDRef", fill)

    def hatch(header) -> None:
        for fill in (pattern, bare_pattern):
            brush, = header.xpath(f".//*[local-name()='borderFill'][@id='{fill}']//*[local-name()='winBrush']")
            brush.set("hatchStyle", "CROSS")
        brush.set("faceColor", "none")  # the last one: lines only, no face colour

    payload = _with_header(document.to_bytes(), hatch)

    preview = render_layout_preview(payload)

    fills = [_fill(cell) for cell in _cells(preview.page_fragments[0], drawn)]
    # the pattern's face colour, the mean of the gradient's two stops, nothing for a picture or a bare pattern
    assert fills == ["#203050", "#203858", "#203858", "transparent", "transparent"]
    assert "url(" not in preview.html
    limitations = _limitations(preview)
    assert limitations["table-cell", "cell fill pattern or gradient is drawn as one colour"] == 3
    assert limitations["table-cell", "cell fill picture is not drawn"] == 1
    assert limitations["table-cell", "cell fill pattern is not drawn"] == 1
    # The approximate preview of a document the estimate does not answer draws fills as before.
    monkeypatch.setattr(experimental, "estimate_layout", None)
    legacy = [cell.get("style") for cell in html.fromstring(render_layout_preview(payload).html).xpath(".//td")]
    assert "background: #203050" in legacy[0] and "background: transparent" in legacy[1]


def _picture(document: HwpxDocument) -> dict[str, object]:
    return {"fill_image": document.media.add_image(PIXEL, "png")}


def _two_pages_with_a_page_fill(brush, kind: str = "BOTH") -> tuple[HwpxDocument, object]:
    """A two-page document whose page border fill of *kind* is *brush*; returns it and that entry."""
    document = HwpxDocument.new()
    document.add_paragraph("첫 쪽 글")
    document.add_paragraph("둘째 쪽 글").element.set("pageBreak", "1")
    fill = document.styles.ensure_border_fill(**(brush(document) if callable(brush) else brush))
    entry, = [node for node in document.sections[0].element.iter("{*}pageBorderFill") if node.get("type") == kind]
    entry.attrib.update({"borderFillIDRef": fill, "fillArea": "PAPER"})
    return document, entry


def _page_fills(preview) -> list[list[str]]:
    return [
        [fill.get("style") for fill in html.fromstring(fragment).xpath(".//div[@class='hwpx-page-fill']")]
        for fragment in preview.page_fragments
    ]


def test_a_page_fill_picture_over_the_paper_is_drawn_behind_every_page() -> None:
    document, _ = _two_pages_with_a_page_fill(_picture)
    payload = document.to_bytes()
    paper_height = experimental.estimate_layout(payload).pages[0].paper_height

    preview = render_layout_preview(payload)

    assert preview.fidelity_tier == "engine-estimated-pagination" and not preview.limitations
    for fragment, (style,) in zip(preview.page_fragments, _page_fills(preview), strict=True):
        assert style.startswith("background-image: url(data:image/png;base64,iVBORw0KGgo")
        assert style.endswith(f"background-size: 100% {paper_height / 7200 * 25.4:.2f}mm")
        fill, = html.fromstring(fragment).xpath(".//div[@class='hwpx-page-fill']")
        assert fill.getparent().get("class") == "hwpx-engine-canvas"
    assert ".hwpx-page-fill { position: absolute; inset: 0; z-index: -1;" in preview.html


def test_a_page_fill_colour_follows_the_first_page_setting() -> None:
    document, _ = _two_pages_with_a_page_fill({"fill_color": "#102040"})
    assert _page_fills(render_layout_preview(document.to_bytes())) == [["background-color: #102040"]] * 2

    document, entry = _two_pages_with_a_page_fill({"fill_color": "#102040"})
    entry.getparent().find("{*}visibility").set("fill", "HIDE_FIRST")
    preview = render_layout_preview(document.to_bytes())

    assert _page_fills(preview) == [[], ["background-color: #102040"]]
    assert not preview.limitations


@pytest.mark.parametrize(
    ("brush", "kind", "area", "drawn", "reason"),
    [
        ({"fill_color": "#102040"}, "BOTH", "PAGE", [],
         "page fill over an area other than the whole paper is not drawn"),
        ({"fill_gradient": GRADIENT}, "BOTH", "PAPER", ["background-color: #203858"],
         "page fill pattern or gradient is drawn as one colour"),
        ({"fill_image": "an-item-the-document-does-not-hold"}, "BOTH", "PAPER", [],
         "page fill picture is not drawn"),
        ({"fill_color": "#102040"}, "ODD", "PAPER", [],
         "page fill set for odd or even pages only is not drawn"),
    ],
)
def test_a_page_fill_that_is_not_drawn_as_written_is_named(brush, kind, area, drawn, reason) -> None:
    document, entry = _two_pages_with_a_page_fill(brush, kind)
    entry.set("fillArea", area)

    preview = render_layout_preview(document.to_bytes())

    assert _page_fills(preview) == [drawn] * 2
    assert _limitations(preview) == {("page-fill", reason): 2}
    assert preview.fidelity_tier == "partial-engine-estimated-pagination"


@pytest.mark.parametrize(
    "change",
    [
        lambda header: [image.set("effect", "GRAY_SCALE") for image in header.iter(f"{HC}img")],
        lambda header: [image.set("bright", "70") for image in header.iter(f"{HC}img")],
        lambda header: [brush.set("mode", "TILE") for brush in header.iter(f"{HC}imgBrush")],
    ],
    ids=["effect", "brightness", "tiled"],
)
def test_a_page_fill_picture_with_an_effect_or_not_stretched_is_left_out(change) -> None:
    document, _ = _two_pages_with_a_page_fill(_picture)

    preview = render_layout_preview(_with_header(document.to_bytes(), change))

    assert _page_fills(preview) == [[], []]
    assert _limitations(preview) == {("page-fill", "page fill picture is not drawn"): 2}


def test_a_page_fill_pattern_without_a_face_colour_is_named() -> None:
    document, _ = _two_pages_with_a_page_fill({"fill_color": "#102040"})

    def lines_only(header) -> None:
        brush, = [node for node in header.iter(f"{HC}winBrush") if node.get("faceColor") == "#102040"]
        brush.attrib.update({"faceColor": "none", "hatchStyle": "CROSS"})

    preview = render_layout_preview(_with_header(document.to_bytes(), lines_only))

    assert _page_fills(preview) == [[], []]
    assert _limitations(preview) == {("page-fill", "page fill pattern is not drawn"): 2}


def test_page_fill_pictures_past_the_budget_are_left_out_and_named(monkeypatch) -> None:
    document, _ = _two_pages_with_a_page_fill(_picture)
    monkeypatch.setattr(layout_preview, "_PAGE_FILL_PICTURE_BUDGET", len(PIXEL) * 2 - 1)

    preview = render_layout_preview(document.to_bytes())

    assert _page_fills(preview) == [[], []]
    assert _limitations(preview) == {("page-fill", "page fill picture is not drawn"): 2}
