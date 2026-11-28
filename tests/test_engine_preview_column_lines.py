"""The line between columns (``hp:colLine``, ``ColumnArea.separator``) on engine pages: in the middle of the gap,
from the column area's top to the next area's top or the body's foot, on pages at coordinates and flow pages alike."""

import re
from collections import Counter
from types import SimpleNamespace

import pytest
from hwpx import HwpxDocument, experimental
from lxml import html
from preview_flow import tables_flow  # noqa: F401
from preview_text_cover import every_engine_preview_shows_the_text  # noqa: F401

from hwpx_automation.preview import layout_preview, render_layout_preview

pytestmark = pytest.mark.skipif(
    "ColumnSeparator" not in getattr(experimental, "__all__", ()), reason="needs the core's column separator",
)

MM = 25.4 / 7200


def _mm(element, name: str) -> float:
    found = re.search(rf"(?:^|;)\s*{re.escape(name)}:\s*(-?[\d.]+)mm", element.get("style") or "")
    assert found, f"{name} missing in {element.get('style')}"
    return float(found.group(1))


def _limitations(preview) -> dict[tuple[str, str], int]:
    return {(item["kind"], item["reason"]): item["count"] for item in preview.as_dict()["limitations"]}


def _document(separator_type: str | None = "SOLID", paragraphs: int = 30, table: bool = False) -> HwpxDocument:
    document = HwpxDocument.new()
    document.page.set_columns(
        2, same_gap=1500,
        **({"separator_type": separator_type, "separator_width_mm": 0.4, "separator_color": "#C00000"}
           if separator_type else {}),
    )
    for index in range(paragraphs):
        document.add_paragraph(f"본문 문단 {index} " + "글자 " * 20)
    if table:
        document.add_paragraph("").add_table(2, 2).cell(0, 0).text = "흐르는 표"
    return document


def _lines(fragment: str) -> list:
    return html.fromstring(fragment).xpath(".//i[@class='hwpx-column-line']")


def _assert_in_the_gap(line, page, area) -> None:
    middle = page.body[0] + area.widths[0] + area.gaps[0] / 2
    assert _mm(line, "left") == pytest.approx(middle * MM, abs=0.006)
    assert _mm(line, "top") == pytest.approx(area.top * MM, abs=0.006)
    foot = page.body[1] + page.body[3]
    assert _mm(line, "height") == pytest.approx((foot - area.top) * MM, abs=0.006)
    assert "border-left: max(1px, 0.4mm) solid #C00000" in line.get("style")
    assert "translateX(-50%)" in line.get("style")


def test_a_column_line_stands_in_the_middle_of_the_gap_on_every_page() -> None:
    payload = _document().to_bytes()
    layout = experimental.estimate_layout(payload)

    preview = render_layout_preview(payload)

    assert len(preview.page_fragments) == len(layout.pages)
    for fragment, page in zip(preview.page_fragments, layout.pages, strict=True):
        area, = page.column_areas
        assert area.separator is not None and area.separator.type == "SOLID"
        line, = _lines(fragment)
        _assert_in_the_gap(line, page, area)
    assert not any(kind == "column-line" for kind, _ in _limitations(preview))
    assert ".hwpx-column-line { position: absolute; width: 0;" in preview.html


@pytest.mark.usefixtures("tables_flow")
def test_a_flow_page_draws_its_column_line_at_the_same_place() -> None:
    payload = _document(paragraphs=45, table=True).to_bytes()
    layout = experimental.estimate_layout(payload)

    preview = render_layout_preview(payload)

    flowing = [index for index, fragment in enumerate(preview.page_fragments) if 'data-layout-mode="flow"' in fragment]
    assert flowing
    for index in flowing:
        page = layout.pages[index]
        line, = _lines(preview.page_fragments[index])
        assert line.getparent().tag == "section"  # on the paper, not in a column's box
        _assert_in_the_gap(line, page, page.column_areas[0])


def test_no_column_line_without_a_separator() -> None:
    preview = render_layout_preview(_document(separator_type=None).to_bytes())

    assert not any(_lines(fragment) for fragment in preview.page_fragments)


def test_a_column_line_of_another_style_is_drawn_solid_and_named() -> None:
    preview = render_layout_preview(_document(separator_type="DASH").to_bytes())

    assert all(len(_lines(fragment)) == 1 for fragment in preview.page_fragments)
    assert _limitations(preview)["column-line", "column separator line style is drawn solid"] == len(preview.pages)


def _page(*areas) -> SimpleNamespace:
    return SimpleNamespace(page=0, body=(1000, 2000, 30000, 40000), column_areas=areas)


def _area(top: int, *, gap: int | None = 1000, gaps: tuple[int, ...] = (1000,), width_mm: float | None = 0.12):
    separator = SimpleNamespace(type="SOLID", width_mm=width_mm, color="#000000")
    return SimpleNamespace(top=top, widths=(14500, 14500), gap=gap, gaps=gaps, separator=separator)


def _row(top: int, height: int, *, column: int = 0, x: int = 0, width: int = 30000) -> SimpleNamespace:
    cell = SimpleNamespace(x=0, width=width)
    return SimpleNamespace(page=0, top=top, height=height, column=column, x=x, cells=(cell,))


def test_a_column_line_breaks_where_a_table_row_stands_across_the_gap_and_ends_at_the_next_area() -> None:
    page = _page(_area(2000), _area(30000))
    across = SimpleNamespace(rows=(_row(5000, 3000),))
    narrow = SimpleNamespace(rows=(_row(12000, 3000, width=14000),))  # in the first column only
    issues = Counter()

    markup = layout_preview._column_lines(page, issues, (across, narrow))

    lines = html.fromstring(f"<div>{markup}</div>").xpath("./i")
    # the first area: above the wide row, then on to the next area's top; the second: to the body's foot
    expected = [(0, 2000, 3000), (0, 8000, 22000), (1, 30000, 12000)]
    assert [int(line.get("data-column-area")) for line in lines] == [area for area, _, _ in expected]
    for line, (_, top, height) in zip(lines, expected, strict=True):
        assert _mm(line, "top") == pytest.approx(top * MM, abs=0.006)
        assert _mm(line, "height") == pytest.approx(height * MM, abs=0.006)
        assert _mm(line, "left") == pytest.approx((1000 + 14500 + 500) * MM, abs=0.006)
    assert not issues


def test_a_column_line_without_a_gap_or_width_is_named() -> None:
    issues = Counter()

    unspaced = layout_preview._column_lines(_page(_area(2000, gap=None, gaps=())), issues)
    thin = layout_preview._column_lines(_page(_area(2000, width_mm=None)), issues)

    assert unspaced == "" and "max(1px, 0mm)" in thin
    assert issues == {
        ("column-line", "column separator is not drawn: the gap between the columns is not given"): 1,
        ("column-line", "column separator width is not given: it is drawn a pixel wide"): 1,
    }
