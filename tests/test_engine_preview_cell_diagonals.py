"""Cell diagonals of the engine-placed HTML preview: drawn across the cell's box as the border fill gives them."""

import io
from zipfile import ZipFile

import pytest
from hwpx import HwpxDocument, experimental
from lxml import etree, html
from preview_text_cover import every_engine_preview_shows_the_text  # noqa: F401

from hwpx_automation.preview import layout_preview, render_layout_preview

pytestmark = pytest.mark.skipif(
    not hasattr(experimental, "estimate_layout"), reason="needs the core placement API",
)

RISING = ("0", "100%", "100%", "0")  # a slash: bottom left corner to top right
FALLING = ("0", "0", "100%", "100%")  # a back slash: top left corner to bottom right
BESIDE = ("table-cell", "cell diagonal is drawn as its centre line: the slanted lines beside it are not drawn")
BENT = ("table-cell", "cell diagonal is drawn straight: its bend or counter direction is not drawn")
STYLE = ("table-cell", "cell diagonal line style is drawn solid")
CENTRE = ("table-cell", "cell centre line is drawn with the diagonal's line")


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


def _border_fill(header, fill_id: str):
    found, = header.xpath(f".//*[local-name()='borderFill'][@id='{fill_id}']")
    return found


def _child(border_fill, name: str):
    found, = [node for node in border_fill if etree.QName(node).localname == name]
    return found


def _limitations(preview) -> dict[tuple[str, str], int]:
    return {(item["kind"], item["reason"]): item["count"] for item in preview.as_dict()["limitations"]}


def _diagonals(cell) -> list[tuple[tuple[str, str, str, str], str]]:
    """The lines a drawn cell's diagonal SVG holds: their ends and style."""
    found = cell.xpath("./svg[@class='hwpx-cell-diagonal']")
    if not found:
        return []
    svg, = found
    return [(tuple(line.get(name) for name in ("x1", "y1", "x2", "y2")), line.get("style")) for line in svg]


@pytest.fixture(params=["coordinates", "flow"])
def drawn(request, monkeypatch) -> str:
    """Cells drawn at the engine's coordinates, and drawn as the flowing rows of a flow page."""
    if request.param == "flow":
        monkeypatch.setattr(layout_preview, "_drawable_at_coordinates", lambda table, objects=None, placements=None: False)
    return request.param


def _cells(fragment: str, drawn: str) -> list:
    page = html.fromstring(fragment)
    cells = page.xpath(".//td" if drawn == "flow" else ".//div[@class='hwpx-engine-cell']")
    assert cells and page.get("data-layout-mode") == ("flow" if drawn == "flow" else "positioned")
    return cells


def _table_with_fills(count: int) -> tuple[HwpxDocument, list[str]]:
    """A one-row table of *count* cells, each with a border fill of its own (ids returned in order)."""
    document = HwpxDocument.new()
    table = document.add_paragraph("").add_table(1, count)
    fills = []
    for column in range(count):
        table.cell(0, column).text = f"칸 {column + 1}"
        fill = document.styles.ensure_border_fill(border_color=f"#10203{column}")
        table.cell(0, column).element.set("borderFillIDRef", fill)
        fills.append(fill)
    return document, fills


def test_a_slash_and_a_back_slash_cross_their_cells_with_the_files_line(drawn) -> None:
    document, (slash, back, both, _plain) = _table_with_fills(4)

    def diagonals(header) -> None:
        for fill, tags in ((slash, ("slash",)), (back, ("backSlash",)), (both, ("slash", "backSlash"))):
            node = _border_fill(header, fill)
            for tag in tags:
                _child(node, tag).set("type", "CENTER")
            _child(node, "diagonal").attrib.update({"type": "SOLID", "width": "0.4 mm", "color": "#C00000"})

    preview = render_layout_preview(_with_header(document.to_bytes(), diagonals))

    cells = _cells(preview.page_fragments[0], drawn)
    stroke = "stroke: #C00000; stroke-width: max(1px, 0.4mm)"
    assert [_diagonals(cell) for cell in cells] == [
        [(RISING, stroke)], [(FALLING, stroke)], [(RISING, stroke), (FALLING, stroke)], [],
    ]
    if drawn == "flow":  # the cell is the box the diagonals span
        assert ["position: relative" in cell.get("style") for cell in cells] == [True, True, True, False]
    assert ".hwpx-cell-diagonal { position: absolute; inset: 0; width: 100%; height: 100%;" in preview.html
    assert [cell.text_content() for cell in cells] == ["칸 1", "칸 2", "칸 3", "칸 4"]
    assert not any("diagonal" in reason or "centre line" in reason for _, reason in _limitations(preview))


def test_a_slash_without_a_diagonal_line_draws_nothing() -> None:
    document, (missing, none) = _table_with_fills(2)

    def no_line(header) -> None:
        for fill in (missing, none):
            _child(_border_fill(header, fill), "slash").set("type", "CENTER")
        diagonal = _child(_border_fill(header, missing), "diagonal")
        diagonal.getparent().remove(diagonal)
        _child(_border_fill(header, none), "diagonal").set("type", "NONE")

    preview = render_layout_preview(_with_header(document.to_bytes(), no_line))

    assert "hwpx-cell-diagonal\"" not in preview.html.split("</style>", 1)[1]
    assert not any("diagonal" in reason for _, reason in _limitations(preview))


def test_diagonals_drawn_otherwise_than_the_file_says_are_named(drawn) -> None:
    document, (beside, bent, dashed, centre) = _table_with_fills(4)

    def kinds(header) -> None:
        _child(_border_fill(header, beside), "slash").set("type", "ALL")
        _child(_border_fill(header, bent), "backSlash").attrib.update({"type": "CENTER", "Crooked": "1"})
        _child(_border_fill(header, dashed), "slash").set("type", "CENTER")
        _child(_border_fill(header, dashed), "diagonal").set("type", "DASH")
        _border_fill(header, centre).set("centerLine", "CROSS")

    preview = render_layout_preview(_with_header(document.to_bytes(), kinds))

    ends = [[line[0] for line in _diagonals(cell)] for cell in _cells(preview.page_fragments[0], drawn)]
    assert ends == [
        [RISING], [FALLING], [RISING], [("50%", "0", "50%", "100%"), ("0", "50%", "100%", "50%")],
    ]
    limitations = _limitations(preview)
    assert {key: limitations[key] for key in (BESIDE, BENT, STYLE, CENTRE)} == {BESIDE: 1, BENT: 1, STYLE: 1, CENTRE: 1}
    assert preview.fidelity_tier == "partial-engine-estimated-pagination"


def test_a_declined_document_draws_no_diagonal(monkeypatch) -> None:
    document, (slash,) = _table_with_fills(1)
    payload = _with_header(
        document.to_bytes(), lambda header: _child(_border_fill(header, slash), "slash").set("type", "CENTER"),
    )
    monkeypatch.setattr(experimental, "estimate_layout", None)

    preview = render_layout_preview(payload)

    assert preview.fidelity_tier.startswith("text-approx-pagination")
    assert 'class="hwpx-cell-diagonal"' not in preview.html
    assert "position: relative" not in html.fromstring(preview.html).xpath(".//td")[0].get("style")


def test_a_header_table_draws_its_cell_diagonals() -> None:
    document = HwpxDocument.new()
    document.page.set_header(text="표를 담은 머리말")
    node = next(node for node in document.sections[0].element.iter() if node.tag.endswith("}header"))
    for number in range(20):
        document.add_paragraph(f"본문 문단 {number + 1}")
    table = document.add_paragraph("").add_table(1, 2)  # moved into the header's paragraph
    table.cell(0, 0).text = "쪽 번호 칸"
    fill = document.styles.ensure_border_fill(border_color="#102030")
    table.cell(0, 0).element.set("borderFillIDRef", fill)
    node.find(".//{*}p/{*}run").append(table.element)
    payload = _with_header(
        document.to_bytes(), lambda header: _child(_border_fill(header, fill), "slash").set("type", "CENTER"),
    )
    if any(area.page is None for area in experimental.estimate_layout(payload).areas):
        pytest.skip("the engine gives this header no page")

    preview = render_layout_preview(payload)

    for fragment in preview.page_fragments:
        # at the engine's place in the header's layer, or drawn whole in its room on a core without its rows
        first, second = html.fromstring(fragment).xpath(
            ".//div[@data-area-kind='header']//*[self::td or self::div[@class='hwpx-engine-cell']]")
        assert [line[0] for line in _diagonals(first)] == [RISING] and not _diagonals(second)
