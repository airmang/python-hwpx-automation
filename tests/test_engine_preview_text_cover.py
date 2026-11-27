"""Nothing the document holds vanishes from the engine preview, whatever the engine leaves out.

Every test here (and every engine preview test) also runs the check of ``preview_text_cover``:
the pages show all the characters of the document. The engine's gaps are made by taking
values out of a real layout before the preview reads it.
"""

from base64 import b64decode
from dataclasses import replace

import pytest
from hwpx import HwpxDocument, experimental
from lxml import html

from hwpx_automation.preview import render_layout_preview
from preview_text_cover import every_engine_preview_shows_the_text, missing_characters  # noqa: F401

pytestmark = pytest.mark.skipif(
    "TableCellPlacement" not in getattr(experimental, "__all__", ()), reason="needs the core table placement API",
)

PIXEL = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/qFUAAAAASUVORK5CYII=")
WHOLE = ("table-cell", "cell paragraph is drawn whole: the engine's lines do not give all its text")


def _limitations(preview) -> dict[tuple[str, str], int]:
    return {(item["kind"], item["reason"]): item["count"] for item in preview.as_dict()["limitations"]}


def _preview_with(monkeypatch, payload: bytes, layout) -> object:
    """The preview of *payload* when the engine answers *layout*."""
    monkeypatch.setattr(experimental, "estimate_layout", lambda document: layout)
    return render_layout_preview(payload)


def _text(preview) -> str:
    return "".join(html.fromstring(fragment).text_content() for fragment in preview.page_fragments)


def _three_paragraph_cell() -> bytes:
    document = HwpxDocument.new()
    table = document.add_paragraph("").add_table(2, 2)
    cell = table.cell(0, 0)
    cell.text = "칸의 첫 문단"
    cell.add_paragraph("칸의 둘째 문단은 두 줄로 나뉠 만큼 길게 쓴 글이다 " * 2)
    cell.add_paragraph("칸의 셋째 문단")
    table.cell(0, 1).text = "옆 칸의 글"
    table.cell(1, 0).text = "아래 칸의 글"
    return document.to_bytes()


def _change_cell(layout, column: int, change):
    """*layout* with ``change(cell)`` in place of the first row's cell of *column* (``None`` takes it out)."""
    table = layout.tables[0]
    row = table.rows[0]
    cells = tuple(
        changed for cell in row.cells
        if (changed := change(cell) if cell.column == column else cell) is not None
    )
    return replace(layout, tables=(replace(table, rows=(replace(row, cells=cells), *table.rows[1:])), *layout.tables[1:]))


@pytest.mark.parametrize(
    ("gap", "counted"),
    [
        (lambda cell: replace(cell, lines=tuple(line for line in cell.lines if line.paragraph != 1)), WHOLE),
        (lambda cell: replace(cell, lines=cell.lines[:2]), WHOLE),
        (lambda cell: replace(cell, lines=tuple(replace(line, text=None, runs=()) if line.paragraph == 1 else line
                                                 for line in cell.lines)), WHOLE),
        (lambda cell: replace(cell, lines=()), None),
        (lambda cell: None, ("table-cell", "cell the engine placed in no row is drawn after the table's placed rows")),
    ],
    ids=["a paragraph without a line", "lines stop early", "a line without its text", "no line at all", "in no row"],
)
def test_what_the_engine_leaves_out_of_a_cell_is_still_drawn_once(monkeypatch, gap, counted) -> None:
    payload = _three_paragraph_cell()
    layout = _change_cell(experimental.estimate_layout(payload), 0, gap)

    preview = _preview_with(monkeypatch, payload, layout)

    text = _text(preview)
    for piece in ("칸의 첫 문단", "칸의 셋째 문단", "옆 칸의 글", "아래 칸의 글"):
        assert text.count(piece) == 1
    assert text.count("칸의 둘째 문단은") == 2  # the paragraph says it twice, and is drawn once
    if counted is not None:
        assert _limitations(preview)[counted] >= 1
    assert preview.fidelity_tier == "partial-engine-estimated-pagination"


def test_text_on_the_line_of_a_table_in_a_cell_is_shown_with_the_table() -> None:
    document = HwpxDocument.new()
    table = document.add_paragraph("").add_table(1, 2)
    cell = table.cell(0, 0)
    cell.text = "표와 같은 문단의 글"
    inner = cell.paragraphs[0].add_table(1, 1)
    inner.cell(0, 0).text = "안쪽 표의 글"
    cell.add_paragraph("다음 문단")

    preview = render_layout_preview(document.to_bytes())

    text = _text(preview)
    assert [text.count(piece) for piece in ("표와 같은 문단의 글", "안쪽 표의 글", "다음 문단")] == [1, 1, 1]
    assert len(html.fromstring(preview.page_fragments[0]).xpath(".//table")) == 2


def _split_merged_cell() -> bytes:
    document = HwpxDocument.new()
    table = document.add_paragraph("").add_table(30, 2)
    table.element.find("{*}pos").set("treatAsChar", "0")
    table.element.set("pageBreak", "CELL")
    for row in range(30):
        table.cell(row, 0).text = f"{row + 1}번 줄의 내용 " * 3
    table.merge_cells(0, 1, 29, 1)
    merged = table.cell(0, 1)
    merged.text = "합친 칸의 1째 줄"
    for index in range(1, 50):
        merged.add_paragraph(f"합친 칸의 {index + 1}째 줄")
    return document.to_bytes()


def test_a_split_cell_without_engine_lines_is_drawn_whole_in_its_first_part(monkeypatch) -> None:
    payload = _split_merged_cell()
    layout = experimental.estimate_layout(payload)
    table = layout.tables[0]
    assert len({row.page for row in table.rows}) == 2
    rows = tuple(
        replace(row, cells=tuple(replace(cell, lines=()) if cell.column == 1 else cell for cell in row.cells))
        for row in table.rows
    )

    preview = _preview_with(monkeypatch, payload, replace(layout, tables=(replace(table, rows=rows),)))

    first, second = (html.fromstring(fragment).text_content() for fragment in preview.page_fragments)
    assert all(first.count(f"합친 칸의 {index + 1}째 줄") == 1 for index in range(50))
    assert "합친 칸의" not in second and "이어지는 칸의 줄 위치 미확인" in second


def test_a_body_paragraph_the_engine_lines_do_not_cover_is_drawn_whole(monkeypatch) -> None:
    document = HwpxDocument.new()
    document.add_paragraph("앞 문단")
    document.add_paragraph("엔진의 줄이 다 담지 못한 문단의 글 " * 6)
    document.add_paragraph("뒤 문단")
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)
    cut = layout.paragraphs[1]
    assert len(cut.lines) > 1
    short = replace(cut, lines=(*cut.lines[:-1], replace(cut.lines[-1], text="", runs=())))

    preview = _preview_with(
        monkeypatch, payload, replace(layout, paragraphs=(layout.paragraphs[0], short, *layout.paragraphs[2:])),
    )

    assert _text(preview).count("엔진의 줄이 다 담지 못한 문단의 글") == 6
    assert _limitations(preview)["paragraph", "engine lines do not give all the paragraph's text"] == 1


def test_a_body_paragraph_the_engine_lists_nowhere_is_still_shown(monkeypatch) -> None:
    document = HwpxDocument.new()
    document.add_paragraph("엔진이 놓은 문단")
    document.add_paragraph("엔진이 어디에도 놓지 않은 문단")
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)

    preview = _preview_with(monkeypatch, payload, replace(layout, paragraphs=layout.paragraphs[:1]))

    assert _text(preview).count("엔진이 어디에도 놓지 않은 문단") == 1
    reason = "paragraph the engine places nowhere is shown on its section's first page"
    assert _limitations(preview)["paragraph", reason] == 1


def test_a_note_whose_lines_do_not_give_all_its_text_is_shown_whole(monkeypatch) -> None:
    document = HwpxDocument.new()
    paragraph = document.add_paragraph("각주가 달린 문단")
    document.notes.add_footnote("각주의 글 " * 30, paragraph=paragraph)
    payload = document.to_bytes()
    layout = experimental.estimate_layout(payload)
    note, = layout.areas
    assert len(note.lines) > 1 and all(line.text for line in note.lines)

    preview = _preview_with(monkeypatch, payload, replace(layout, areas=(replace(note, lines=note.lines[:1]),)))

    assert _text(preview).count("각주의 글") == 30
    assert _limitations(preview)["footNote", "area lines do not give all its text: the area is shown whole"] == 1


def test_captions_of_pictures_and_shapes_are_shown_in_the_body_and_in_cells() -> None:
    document = HwpxDocument.new()
    picture = document.add_paragraph("그림이 든 문단").add_picture(document.media.add_image(PIXEL, "png"), width=6000, height=4000)
    picture.set_caption("본문 그림의 캡션")
    table = document.add_paragraph("").add_table(1, 1)
    cell = table.cell(0, 0)
    cell.text = ""
    inside = cell.paragraphs[0].add_picture(document.media.add_image(PIXEL, "png"), width=3000, height=2000)
    inside.set_caption("칸 안 그림의 캡션", side="BOTTOM")
    shape = document.shapes.add_rectangle(5000, 3000, paragraph=document.add_paragraph("도형 문단"), treat_as_char=False)
    shape.set_caption("도형의 캡션")

    preview = render_layout_preview(document.to_bytes())

    page = html.fromstring(preview.page_fragments[0])
    captions = [caption.text_content() for caption in page.xpath(".//*[contains(@class, 'hwpx-object-caption')]")]
    assert sorted(captions) == ["도형의 캡션", "본문 그림의 캡션", "칸 안 그림의 캡션"]
    assert all(_text(preview).count(caption) == 1 for caption in captions)  # not inside the shape as well
    assert page.xpath(".//td//*[contains(@class, 'hwpx-object-caption')]")[0].text_content() == "칸 안 그림의 캡션"
    limitations = _limitations(preview)
    assert limitations["picture", "caption placement is unavailable"] == 1
    assert limitations["shape", "caption placement is unavailable"] == 1


def test_a_caption_of_a_placed_object_is_drawn_at_the_object_and_keeps_the_page_positioned() -> None:
    document = HwpxDocument.new()
    paragraph = document.add_paragraph("자리를 받은 그림이 걸린 문단")
    picture = paragraph.add_picture(document.media.add_image(PIXEL, "png"), width=6000, height=4000)
    picture.element.set("textWrap", "BEHIND_TEXT")
    picture.element.find("{*}pos").attrib.update({
        "treatAsChar": "0", "flowWithText": "0", "horzRelTo": "PAPER", "vertRelTo": "PAPER",
        "horzAlign": "LEFT", "vertAlign": "TOP", "horzOffset": "8504", "vertOffset": "20000",
    })
    picture.set_caption("자리를 받은 그림의 캡션", side="BOTTOM")
    payload = document.to_bytes()
    placed, = experimental.estimate_layout(payload).objects
    if None in (placed.x, placed.top, placed.width, placed.height):
        pytest.skip("the engine does not place this picture")

    preview = render_layout_preview(payload)

    page = html.fromstring(preview.page_fragments[0])
    assert page.get("data-layout-mode") == "positioned"
    caption, = page.xpath(".//div[contains(@class, 'hwpx-object-caption')]")
    assert caption.text_content() == "자리를 받은 그림의 캡션" and caption.get("data-overlay") == "behind"
    below = (placed.top + placed.height) / 7200 * 25.4
    assert f"top: {below:.2f}mm" in caption.get("style") and f"left: {placed.x / 7200 * 25.4:.2f}mm" in caption.get("style")
    assert _limitations(preview) == {("picture", "caption placement is unavailable"): 1}


def test_a_memo_is_not_page_text_and_is_not_drawn() -> None:
    """Hangul keeps a memo off the page (its text is in a ``MEMO`` field and ``hp:memogroup``)."""
    document = HwpxDocument.new()
    paragraph = document.add_paragraph("메모가 걸린 문단")
    document.notes.add_memo("쪽에 보이지 않는 메모", paragraph=paragraph)
    table = document.add_paragraph("").add_table(1, 1)
    table.cell(0, 0).text = "메모가 걸린 칸"
    document.notes.add_memo("칸에 건 메모", paragraph=table.cell(0, 0).paragraphs[0])
    payload = document.to_bytes()
    assert payload.count("쪽에 보이지 않는 메모".encode()) == 0  # the parts are compressed: read them through the document
    opened = HwpxDocument.open(payload)
    held = "".join("".join(node.itertext()) for node in opened.sections[0].element.iter("{*}t"))
    assert "쪽에 보이지 않는 메모" in held and "칸에 건 메모" in held

    preview = render_layout_preview(payload)

    text = _text(preview)
    assert "메모가 걸린 문단" in text and "메모가 걸린 칸" in text
    assert "보이지 않는 메모" not in text and "칸에 건 메모" not in text
    assert not missing_characters(opened, preview.page_fragments)
