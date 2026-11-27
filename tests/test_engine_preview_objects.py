"""Objects, groups, text boxes, headers and footers drawn at the engine's places on pages at coordinates.

A drawn box is right when its page, place and size are the engine's (to the millimetre rounding of the
markup); its look is not compared. What the engine does not place is drawn at an approximate place and
counted, and a page flows only for an object that may take room the engine's lines do not show.
Every test also runs the checks of ``preview_text_cover`` (all text shown, no overlap drawn wrongly).
"""

import re
from base64 import b64decode
from dataclasses import replace

import pytest
from hwpx import HwpxDocument, experimental
from hwpx.objects import ContainerMember
from lxml import html
from preview_overlap import drawn_wrongly, overlaps
from preview_text_cover import every_engine_preview_shows_the_text  # noqa: F401

from hwpx_automation.preview import render_layout_preview

pytestmark = pytest.mark.skipif(
    "AreaPlacement" not in getattr(experimental, "__all__", ())
    or "lines" not in getattr(getattr(experimental, "ObjectPlacement", None), "__dataclass_fields__", {}),
    reason="needs the core object, text box and area placement API",
)

PIXEL = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/qFUAAAAASUVORK5CYII=")
MM = 7200 / 25.4


def _limitations(preview) -> dict[tuple[str, str], int]:
    return {(item["kind"], item["reason"]): item["count"] for item in preview.as_dict()["limitations"]}


def _mm(element, name: str) -> float:
    found = re.search(rf"(?:^|;)\s*{re.escape(name)}:\s*(-?[\d.]+)mm", element.get("style") or "")
    assert found, f"{name} missing in {element.get('style')}"
    return float(found.group(1))


def _assert_engine_box(element, placed, origin=(0, 0)) -> None:
    """The element's box is the engine's rectangle (paper-relative, less *origin*), to the markup's rounding."""
    for name, value in (("left", placed.x - origin[0]), ("top", placed.top - origin[1]),
                        ("width", placed.width), ("height", placed.height)):
        assert _mm(element, name) == pytest.approx(value / MM, abs=0.006), name


def _modes(preview) -> list[str]:
    return [html.fromstring(fragment).get("data-layout-mode") for fragment in preview.page_fragments]


def _preview_with(monkeypatch, payload: bytes, layout):
    monkeypatch.setattr(experimental, "estimate_layout", lambda document: layout)
    return render_layout_preview(payload)


def _shapes_document() -> HwpxDocument:
    document = HwpxDocument.new()
    holder = document.add_paragraph("글상자를 단 문단")
    box = document.shapes.add_rectangle(
        14000, 6000, paragraph=holder, treat_as_char=False, fill_color="#FFEEAA", line_color="#2244CC",
        line_width_mm=0.5,
    )
    box.set_draw_text("글상자 안의 글")
    box.element.set("textWrap", "TOP_AND_BOTTOM")
    line = document.shapes.add_line(0, 0, 20000, 0, paragraph=document.add_paragraph("선을 단 문단"),
                                    treat_as_char=False)
    line.element.set("textWrap", "TOP_AND_BOTTOM")
    document.shapes.add_ellipse(5000, 3000, paragraph=document.add_paragraph("타원 "), treat_as_char=True)
    document.shapes.add_equation("a over b", paragraph=document.add_paragraph("수식 "))
    document.add_paragraph("그림 ").add_picture(document.media.add_image(PIXEL, "png"), width=6000, height=4000)
    return document


def test_shapes_text_boxes_equations_and_pictures_stand_in_their_engine_boxes() -> None:
    payload = _shapes_document().to_bytes()
    layout = experimental.estimate_layout(payload)

    preview = render_layout_preview(payload)

    assert _modes(preview) == ["positioned"] and preview.fidelity_tier == "engine-estimated-pagination"
    page = html.fromstring(preview.page_fragments[0])
    drawn = page.xpath("./div/div[contains(@class, 'hwpx-placed-object')]")
    assert [item.get("data-object-kind") for item in drawn] == ["shape", "shape", "shape", "equation", "picture"]
    for item, placed in zip(drawn, layout.objects):
        _assert_engine_box(item, placed)
    box, line, ellipse, equation, picture = drawn
    # The file's line colour and width, and its fill as one colour.
    assert "border: 0.50mm solid #2244CC" in box.get("style") and "background: #FFEEAA" in box.get("style")
    # The text box's lines stand at the engine's places in the box.
    text_line, = box.xpath("./div[@class='hwpx-engine-cell-line']")
    engine_line, = layout.objects[0].lines
    assert text_line.text_content() == "글상자 안의 글"
    assert _mm(text_line, "top") == pytest.approx(engine_line.top / MM, abs=0.006)
    assert _mm(text_line, "left") == pytest.approx(engine_line.x / MM, abs=0.006)
    # A line is drawn through its two ends; an ellipse is round.
    assert line.xpath(".//*[local-name()='polyline']") and "border-radius: 50%" in ellipse.get("style")
    assert equation.xpath(".//*[local-name()='math']") and picture.find("img") is not None
    assert line.get("data-wrap") == "TOP_AND_BOTTOM" and picture.get("data-wrap") == "AS_CHARACTER"
    found = overlaps(preview.page_fragments)
    assert found["objects"] == 5 and found["box-line pairs"] == 0 and not drawn_wrongly(found)


def test_a_form_object_is_a_counted_marker_in_its_box() -> None:
    document = HwpxDocument.new()
    document.fields.add_check_box("동의", paragraph=document.add_paragraph("양식 개체 "))
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)
    if not layout.objects or layout.objects[0].x is None:
        pytest.skip("the engine gives this form object no place")

    preview = render_layout_preview(payload)

    item, = html.fromstring(preview.page_fragments[0]).xpath(".//div[@data-object-kind='checkBtn']")
    _assert_engine_box(item, layout.objects[0])
    assert "⟦" in item.text_content()
    assert _limitations(preview)["checkBtn", "object is shown as a placeholder"] == 1


def test_group_members_stand_at_their_places_in_the_group_box() -> None:
    document = HwpxDocument.new()
    document.add_paragraph("묶음 앞 문단")
    group = document.shapes.add_container([
        ContainerMember.rect(0, 0, 8000, 4000, fill_color="#DDEEFF"),
        ContainerMember.text_box(9000, 1000, 9000, 5000, "묶음 안 글상자"),
        ContainerMember.line(0, 6000, 18000, 6000),
    ], paragraph=document.add_paragraph("묶음 문단 "), treat_as_char=False)
    group.element.set("textWrap", "TOP_AND_BOTTOM")
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)
    outer, *members = layout.objects
    assert None not in (outer.x, outer.top) and all(member.x is not None for member in members)

    preview = render_layout_preview(payload)

    assert _modes(preview) == ["positioned"]
    page = html.fromstring(preview.page_fragments[0])
    box, = page.xpath(".//div[contains(@class, 'hwpx-group')]")
    _assert_engine_box(box, outer)
    drawn = box.xpath("./div[contains(@class, 'hwpx-placed-object')]")
    assert len(drawn) == len(members) == 3
    for item, member in zip(drawn, members):
        _assert_engine_box(item, member, origin=(outer.x, outer.top))
    assert drawn[1].xpath("./div[@class='hwpx-engine-cell-line']")[0].text_content() == "묶음 안 글상자"
    assert not drawn_wrongly(overlaps(preview.page_fragments))


def test_a_group_member_without_a_place_stands_at_the_group_corner_and_is_counted(monkeypatch) -> None:
    document = HwpxDocument.new()
    group = document.shapes.add_container([
        ContainerMember.rect(0, 0, 8000, 4000), ContainerMember.text_box(9000, 0, 9000, 4000, "자리 없는 부재"),
    ], paragraph=document.add_paragraph("묶음 문단 "), treat_as_char=False)
    group.element.set("textWrap", "TOP_AND_BOTTOM")
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)
    outer, first, second = layout.objects
    unplaced = replace(second, x=None, top=None, unavailable=("a member of a group: test",))

    preview = _preview_with(monkeypatch, payload, replace(layout, objects=(outer, first, unplaced)))

    assert _modes(preview) == ["positioned"]
    member, = html.fromstring(preview.page_fragments[0]).xpath(".//div[@data-approx='place']")
    assert "자리 없는 부재" in member.text_content()
    assert _limitations(preview)["shape", "a member of a group without a place is drawn at the group's top left"] == 1


def _first_page_objects(layout, **changes):
    return tuple(replace(placed, **changes) for placed in layout.objects)


def test_an_object_set_as_a_character_without_a_place_keeps_the_page_at_coordinates(monkeypatch) -> None:
    """The rule: a sized object set as a character whose paragraph has a line on its page is in that
    line's height already -- the page stays at coordinates and the object stands on that line."""
    document = HwpxDocument.new()
    document.add_paragraph("앞 문단")
    picture = document.add_paragraph("").add_picture(document.media.add_image(PIXEL, "png"), width=6000, height=4000)
    document.add_paragraph("뒤 문단")
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)
    placed, = layout.objects
    assert placed.wrap == "AS_CHARACTER" and placed.x is not None
    reason = "object set as a character: where it stands on its line is not laid out"

    preview = _preview_with(monkeypatch, payload, replace(
        layout, objects=_first_page_objects(layout, x=None, top=None, unavailable=(reason,)),
    ))

    assert _modes(preview) == ["positioned"]
    item, = html.fromstring(preview.page_fragments[0]).xpath(".//div[@data-object-kind='picture']")
    assert item.get("data-approx") == "place"
    holder, = [line for paragraph in layout.paragraphs if paragraph.paragraph == 1 for line in paragraph.lines]
    assert _mm(item, "top") == pytest.approx((holder.top + holder.height - placed.height) / MM, abs=0.006)
    assert _mm(item, "width") == pytest.approx(placed.width / MM, abs=0.006)
    limits = _limitations(preview)
    assert limits["picture", reason] == 1
    assert limits["picture", "object set as a character is drawn at an approximate place on its line"] == 1
    assert ("page-flow", "vertical placement is approximate and may exceed the engine body") not in limits
    del picture


def test_an_object_in_front_of_the_text_without_a_place_keeps_the_page_at_coordinates(monkeypatch) -> None:
    document = HwpxDocument.new()
    shape = document.shapes.add_rectangle(6000, 4000, paragraph=document.add_paragraph("글 앞 도형 문단"),
                                          treat_as_char=False)
    shape.element.set("textWrap", "IN_FRONT_OF_TEXT")
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)

    preview = _preview_with(monkeypatch, payload, replace(
        layout, objects=_first_page_objects(layout, x=None, top=None, unavailable=("object origin not measured",)),
    ))

    assert _modes(preview) == ["positioned"]
    item, = html.fromstring(preview.page_fragments[0]).xpath(".//div[@data-object-kind='shape']")
    assert item.get("data-overlay") == "front" and item.get("data-approx") == "place"
    assert _limitations(preview)["shape", "object in front of or behind the text is drawn at an approximate place"] == 1


def test_an_object_that_takes_room_without_a_place_makes_its_page_flow(monkeypatch) -> None:
    """Wrapped above and below (or square), an object without a place may push the text: the page flows."""
    document = HwpxDocument.new()
    shape = document.shapes.add_rectangle(6000, 4000, paragraph=document.add_paragraph("위아래 도형 문단"),
                                          treat_as_char=False)
    shape.element.set("textWrap", "TOP_AND_BOTTOM")
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)

    preview = _preview_with(monkeypatch, payload, replace(
        layout, objects=_first_page_objects(layout, x=None, top=None, unavailable=("object origin not measured",)),
    ))

    assert _modes(preview) == ["flow"]
    assert _limitations(preview)["shape", "object origin not measured"] == 1


def test_an_object_set_as_a_character_without_a_size_makes_its_page_flow(monkeypatch) -> None:
    document = HwpxDocument.new()
    document.add_paragraph("").add_picture(document.media.add_image(PIXEL, "png"), width=6000, height=4000)
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)

    preview = _preview_with(monkeypatch, payload, replace(layout, objects=_first_page_objects(
        layout, x=None, top=None, width=None, height=None, unavailable=("object size not measured",),
    )))

    assert _modes(preview) == ["flow"]


def _long_body(document: HwpxDocument, count: int = 60) -> None:
    for index in range(count):
        document.add_paragraph(f"본문 문단 {index} " + "글자 " * 20)


def test_headers_and_footers_stand_on_every_page_in_their_rooms_not_in_the_body() -> None:
    document = HwpxDocument.new()
    document.page.set_header(text="머리말의 글")
    document.page.set_footer(text="꼬리말의 글")
    _long_body(document)
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)
    assert layout.estimate.pages > 1

    preview = render_layout_preview(payload)

    assert set(_modes(preview)) == {"positioned"} and preview.fidelity_tier == "engine-estimated-pagination"
    for number, fragment in enumerate(preview.page_fragments):
        page = html.fromstring(fragment)
        for kind in ("header", "footer"):
            placed, = [area for area in layout.areas if area.kind == kind and area.page == number]
            line, = page.xpath(f".//div[@class='hwpx-area-layer'][@data-area-kind='{kind}']/div")
            assert line.text_content() == ("머리말의 글" if kind == "header" else "꼬리말의 글")
            assert _mm(line, "top") == pytest.approx(placed.lines[0].top / MM, abs=0.006)
            assert _mm(line, "left") == pytest.approx(placed.x / MM, abs=0.006)
        # Nothing of a header or footer stands among the body's lines.
        assert not page.xpath(".//p[@data-area-kind]")
    found = overlaps(preview.page_fragments)
    assert found["area-lines"] == 2 * len(preview.pages) and not drawn_wrongly(found)


def test_a_header_on_a_flow_page_stands_in_its_room_and_takes_no_body_room(monkeypatch) -> None:
    document = HwpxDocument.new()
    document.page.set_header(text="머리말의 글")
    shape = document.shapes.add_rectangle(6000, 4000, paragraph=document.add_paragraph("위아래 도형 문단"),
                                          treat_as_char=False)
    shape.element.set("textWrap", "TOP_AND_BOTTOM")
    document.add_paragraph("뒤 문단")
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)
    flowing = replace(layout, objects=_first_page_objects(layout, x=None, top=None, unavailable=("test",)))

    preview = _preview_with(monkeypatch, payload, flowing)

    assert _modes(preview) == ["flow"]
    page = html.fromstring(preview.page_fragments[0])
    layer, = page.xpath(".//div[@class='hwpx-area-layer']")
    assert layer.getparent().get("class") == "hwpx-engine-flow"
    # The header stands absolutely, on the paper: it takes no room among the flowing body lines.
    assert ".hwpx-area-layer { position: absolute;" in preview.html
    assert "머리말의 글" in layer.text_content()


def test_a_header_for_odd_pages_only_stands_in_the_first_page_header_margin() -> None:
    document = HwpxDocument.new()
    document.page.set_header(text="홀수 쪽 머리말", page_type="ODD")
    _long_body(document)
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)
    area, = layout.areas
    assert area.page is None and area.unavailable

    preview = render_layout_preview(payload)

    assert set(_modes(preview)) == {"positioned"}
    rooms = [html.fromstring(fragment).xpath(".//div[contains(@class, 'hwpx-area-room')]")
             for fragment in preview.page_fragments]
    assert [len(found) for found in rooms] == [1] + [0] * (len(rooms) - 1)
    room, = rooms[0]
    assert room.get("data-approx") == "area" and "홀수 쪽 머리말" in room.text_content()
    body = layout.pages[0].body
    margin = int(document.sections[0].element.find(".//{*}pagePr/{*}margin").get("header"))
    assert _mm(room, "top") == pytest.approx((body[1] - margin) / MM, abs=0.006)
    assert _mm(room, "height") == pytest.approx(margin / MM, abs=0.006)
    limits = _limitations(preview)
    assert limits["header", "area without a page is drawn in the margin of its paragraph's page"] == 1
    assert limits["header", area.unavailable[0]] == 1


def test_a_header_holding_a_table_is_drawn_whole_in_its_room_on_every_page() -> None:
    document = HwpxDocument.new()
    document.page.set_header(text="표를 담은 머리말")
    node = next(node for node in document.sections[0].element.iter() if node.tag.endswith("}header"))
    _long_body(document, 40)
    table = document.add_paragraph("").add_table(1, 2)  # moved into the header's paragraph
    table.cell(0, 0).text = "머리말 표 칸"
    node.find(".//{*}p/{*}run").append(table.element)
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)
    if any(area.page is None for area in layout.areas):
        pytest.skip("the engine gives this header no page")

    preview = render_layout_preview(payload)

    assert set(_modes(preview)) == {"positioned"}
    for number, fragment in enumerate(preview.page_fragments):
        room, = html.fromstring(fragment).xpath(".//div[contains(@class, 'hwpx-area-room')]")
        placed, = [area for area in layout.areas if area.page == number]
        _assert_engine_box(room, placed)
        assert "머리말 표 칸" in room.text_content() and room.find(".//table") is not None
    assert _limitations(preview)["header", "area is drawn whole in its room: its lines do not give all it holds"] \
        == len(preview.pages)


def test_a_picture_in_a_table_cell_with_its_rectangle_keeps_the_table_at_coordinates(monkeypatch) -> None:
    document = HwpxDocument.new()
    table = document.add_paragraph("").add_table(1, 2)
    table.cell(0, 0).text = "그림 옆 칸"
    cell = table.cell(0, 1)
    cell.text = ""
    cell.paragraphs[0].add_picture(document.media.add_image(PIXEL, "png"), width=6000, height=4000)
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)
    placed, = layout.objects
    if None in (placed.x, placed.top):
        # A cell python-hwpx wrote keeps no saved lines: the engine gives its picture line no x, as a
        # document Hangul saved would have. The line and the picture are given theirs here.
        table_placement = layout.tables[0]
        row = table_placement.rows[0]
        right = next(part for part in row.cells if part.column == 1)
        line, = right.lines
        right = replace(right, unavailable=(), lines=(replace(
            line, x=510, width=right.width - 1020, text="", text_start=0, text_end=1, source="test"),))
        row = replace(row, cells=tuple(right if part.column == 1 else part for part in row.cells))
        placed = replace(placed, x=layout.pages[0].body[0] + row.x + right.x + 510, top=row.top + line.top,
                         unavailable=())
        layout = replace(layout, objects=(placed,), tables=(replace(table_placement, rows=(row,)),))
        monkeypatch.setattr(experimental, "estimate_layout", lambda document: layout)

    preview = render_layout_preview(payload)

    assert _modes(preview) == ["positioned"]
    page = html.fromstring(preview.page_fragments[0])
    assert page.xpath(".//div[@class='hwpx-engine-table']") and not page.xpath(".//table")
    item, = page.xpath(".//div[@data-object-kind='picture']")
    _assert_engine_box(item, placed)
    assert "그림 옆 칸" in page.text_content()
    assert ("table", "table content uses approximate flow within engine row pages") not in _limitations(preview)
