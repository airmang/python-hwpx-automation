# SPDX-License-Identifier: Apache-2.0
"""Markdown and HTML export tests gathered from python-hwpx test files that also test what stays there.

Each block names the python-hwpx test file it came from. The tests read a document; the 6.x
exporters also took the bytes of a package, so the tests that built a bare package now build
a document around the same section XML (``_payload_doc``).
"""

from __future__ import annotations

import io
import re
import zipfile

import pytest

from hwpx import HwpxDocument
from hwpx.errors import HwpxTypeError
from hwpx_automation.markdown import to_html, to_markdown
from hwpx_automation.markdown._export import export_markdown as rich_markdown
from hwpx_automation.markdown._plain_export import export_html, export_markdown

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"

_SEC_OPEN = (
    "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
    "<hs:sec xmlns:hp='http://www.hancom.co.kr/hwpml/2011/paragraph'"
    " xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section'>"
)


def _payload_doc(body: str) -> HwpxDocument:
    """A document whose only section is *body* (``hp:p`` … elements), in a blank package."""

    source = io.BytesIO(HwpxDocument.new().to_bytes())
    out = io.BytesIO()
    with zipfile.ZipFile(source) as zin, zipfile.ZipFile(out, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "Contents/section0.xml":
                data = (_SEC_OPEN + body + "</hs:sec>").encode("utf-8")
            zout.writestr(info, data)
    return HwpxDocument.open(io.BytesIO(out.getvalue()))


def _reopened(doc: HwpxDocument) -> HwpxDocument:
    buffer = io.BytesIO()
    doc.save_to_stream(buffer)
    return HwpxDocument.open(buffer.getvalue())


# ── tests/test_exporter_table_text.py ─────────────────────────────────────


def _p(*items: str) -> str:
    return "<hp:p><hp:run>" + "".join(items) + "</hp:run></hp:p>"


def _t(text: str) -> str:
    return f"<hp:t>{text}</hp:t>"


def _cell(*paragraphs: str) -> str:
    return "<hp:tc><hp:subList>" + "".join(paragraphs) + "</hp:subList></hp:tc>"


def _table(*rows: list[str]) -> str:
    return "<hp:tbl>" + "".join("<hp:tr>" + "".join(row) + "</hp:tr>" for row in rows) + "</hp:tbl>"


def _sub_list(*paragraphs: str) -> str:
    return "<hp:subList>" + "".join(paragraphs) + "</hp:subList>"


def test_a_nested_table_is_written_once() -> None:
    inner = _table([_cell(_p(_t("inner")))])
    doc = _payload_doc(_p(_table([_cell(_p(_t("outer"))), _cell(_p(inner))])))

    assert export_html(doc, full_document=False).count("inner") == 1
    assert export_markdown(doc).count("inner") == 1


def test_a_nested_table_made_with_the_api_is_written_once() -> None:
    doc = HwpxDocument.new()
    table = doc.add_table(1, 2)
    table.cell(0, 0).text = "outer"
    table.cell(0, 1).add_table(1, 1).cell(0, 0).text = "inner"

    assert to_markdown(doc).count("inner") == 1
    assert to_html(doc, full_document=False).count("inner") == 1


def test_note_and_memo_text_stays_out_of_cell_text() -> None:
    memo = "<hp:ctrl><hp:fieldBegin id='7' type='MEMO'>" + _sub_list(_p(_t("memo body"))) + "</hp:fieldBegin></hp:ctrl>"
    memo_end = "<hp:ctrl><hp:fieldEnd beginIDRef='7'/></hp:ctrl>"
    footnote = "<hp:ctrl><hp:footNote>" + _sub_list(_p(_t("note body"))) + "</hp:footNote></hp:ctrl>"
    endnote = "<hp:ctrl><hp:endNote>" + _sub_list(_p(_t("end body"))) + "</hp:endNote></hp:ctrl>"
    cell_paragraph = _p(memo, _t("cell text"), memo_end, footnote, endnote)
    body_paragraph = _p(memo, _t("body text"), memo_end, footnote, endnote)
    doc = _payload_doc(body_paragraph + _p(_table([_cell(cell_paragraph)])))

    for exported in (export_html(doc, full_document=False), export_markdown(doc)):
        assert "memo body" not in exported
        assert "note body" not in exported
        assert "end body" not in exported


def test_header_and_footer_tables_are_not_body_text() -> None:
    header = "<hp:ctrl><hp:header id='1'>" + _sub_list(_p(_table([_cell(_p(_t("header cell")))]))) + "</hp:header></hp:ctrl>"
    footer = "<hp:ctrl><hp:footer id='2'>" + _sub_list(_p(_table([_cell(_p(_t("footer cell")))]))) + "</hp:footer></hp:ctrl>"
    doc = _payload_doc(_p(header, footer, _t("body")))

    assert "header cell" not in export_html(doc, full_document=False)
    assert "footer cell" not in export_markdown(doc)


def test_markdown_table_cells_stay_on_one_line() -> None:
    doc = _payload_doc(_p(_table(
        [_cell(_p(_t("head"))), _cell(_p(_t("a|b")))],
        [_cell(_p(_t("first")), _p(_t("second"))), _cell(_p(_t("x")))],
    )))

    assert export_markdown(doc).splitlines() == [
        "| head | a\\|b |",
        "| --- | --- |",
        "| first<br>second | x |",
    ]


def test_markdown_keeps_every_cell_under_a_merged_first_row() -> None:
    doc = HwpxDocument.new()
    table = doc.add_table(3, 3)
    for row in range(3):
        for col in range(3):
            if row or not col:  # the cells the merge covers stay blank
                table.cell(row, col).text = f"r{row}c{col}"
    doc.tables.merge_cells(table, "A1:C1")

    lines = to_markdown(doc).splitlines()[-4:]

    assert lines == [
        "| r0c0 |  |  |",
        "| --- | --- | --- |",
        "| r1c0 | r1c1 | r1c2 |",
        "| r2c0 | r2c1 | r2c2 |",
    ]


def test_markdown_places_cells_at_their_grid_address() -> None:
    def addressed(row: int, col: int, text: str, col_span: int = 1) -> str:
        return (
            "<hp:tc><hp:subList>" + _p(_t(text)) + "</hp:subList>"
            f"<hp:cellAddr colAddr='{col}' rowAddr='{row}'/>"
            f"<hp:cellSpan colSpan='{col_span}' rowSpan='1'/></hp:tc>"
        )

    doc = _payload_doc(_p(_table(
        [addressed(0, 0, "a"), addressed(0, 1, "b"), addressed(0, 2, "c")],
        [addressed(1, 0, "wide", col_span=2), addressed(1, 2, "right")],
    )))

    assert export_markdown(doc).splitlines() == [
        "| a | b | c |",
        "| --- | --- | --- |",
        "| wide |  | right |",
    ]


# ── tests/test_hp_tab_support.py ──────────────────────────────────────────


def test_exporters_render_hp_tab_text() -> None:
    doc = _payload_doc(
        "  <hp:p><hp:run><hp:t>left</hp:t><hp:tab/><hp:t>right</hp:t></hp:run></hp:p>"
        "  <hp:p><hp:run><hp:t>ctrl</hp:t><hp:ctrl id='tab'/><hp:t>path</hp:t></hp:run></hp:p>"
    )

    assert "<p>left\tright</p>" in export_html(doc, full_document=False)
    assert "left\tright" in export_markdown(doc)


# ── tests/test_export_list_labels.py ──────────────────────────────────────


def _numbered(count: int) -> HwpxDocument:
    document = HwpxDocument.new(empty_first_line=True)
    for index in range(1, count + 1):
        document.add_paragraph(f"항목{index}")
    document.styles.apply_list_format(paragraph_indexes=list(range(1, count + 1)), kind="number")
    return document


def _numbered_with_a_numbered_cell() -> HwpxDocument:
    document = _numbered(1)
    list_style = document.paragraphs[1].element.get("paraPrIDRef")
    cell = document.add_table(1, 1).cell(0, 0)
    cell.text = "칸 항목"
    cell.paragraphs[0].element.set("paraPrIDRef", list_style)
    document.add_paragraph("범위")
    document.paragraphs[-1].element.set("paraPrIDRef", list_style)
    return document


def test_markdown_and_html_carry_the_labels() -> None:
    document = _numbered(2)

    assert "1. 항목1" in export_markdown(document, list_labels=True)
    assert "<p>2. 항목2</p>" in export_html(document, list_labels=True, full_document=False)


def test_numbered_paragraphs_in_a_left_out_table_still_count() -> None:
    document = _numbered_with_a_numbered_cell()

    assert "3. 범위" in export_markdown(document, list_labels=True, include_tables=False)
    assert "<p>3. 범위</p>" in export_html(document, list_labels=True, include_tables=False, full_document=False)


# ── tests/test_export_notes.py ────────────────────────────────────────────


def _body_footnote() -> HwpxDocument:
    document = HwpxDocument.new()
    document.add_paragraph("첫 문단")
    paragraph = document.add_paragraph("본문 앞")
    document.notes.add_footnote("각주 글", paragraph=paragraph)
    paragraph.add_run("본문 뒤")
    document.add_paragraph("끝 문단")
    return document


def test_html_and_markdown_write_notes_too() -> None:
    # notes="inline" writes them as Hancom's text save; notes=True as footnotes (test_markdown_export_fix7)
    assert "본문 앞1)1)각주 글\n본문 뒤" in export_html(_body_footnote(), notes="inline")
    assert "본문 앞1)1)각주 글\n본문 뒤" in export_markdown(_body_footnote(), notes="inline")
    assert "각주 글" not in export_markdown(_body_footnote())


# ── tests/test_export_text_boxes.py ───────────────────────────────────────


def _boxed() -> HwpxDocument:
    document = HwpxDocument.new(empty_first_line=True)
    document.add_paragraph("앞 문단")
    holder = document.add_paragraph("상자 담은 문단")
    document.shapes.add_rectangle(paragraph=holder).set_draw_text("상자 글")
    holder.add_table(1, 1).cell(0, 0).text = "같은 문단의 칸"
    document.add_paragraph("뒤 문단")
    return document


def _box_between_text() -> HwpxDocument:
    document = HwpxDocument.new(empty_first_line=True)
    holder = document.add_paragraph("상자 앞 글")
    document.shapes.add_rectangle(paragraph=holder).set_draw_text("상자 글")
    holder.add_run("상자 뒤 글")
    return document


def test_the_box_text_comes_where_the_box_sits_in_its_paragraph() -> None:
    document = _box_between_text()

    assert export_markdown(document).split("\n\n") == ["상자 앞 글", "상자 글", "상자 뒤 글"]
    assert "<p>상자 앞 글</p>\n<p>상자 글</p>\n<p>상자 뒤 글</p>" in export_html(document, full_document=False)


def test_markdown_and_html_carry_the_box_text() -> None:
    document = _boxed()

    markdown = export_markdown(document)
    html = export_html(document, full_document=False)

    assert markdown.index("상자 담은 문단") < markdown.index("상자 글") < markdown.index("| 같은 문단의 칸 |")
    assert "<p>상자 글</p>" in html
    assert html.index("<p>상자 글</p>") < html.index("<td>같은 문단의 칸</td>")


def test_the_functions_export_the_box_text() -> None:
    document = _boxed()

    assert "상자 글" in to_markdown(document)
    assert "상자 글" in to_html(document)


# ── tests/test_document_formatting.py ─────────────────────────────────────


def test_markdown_export_includes_table_caption() -> None:
    doc = HwpxDocument.new(empty_first_line=True)
    p = doc.sections[0].add_paragraph()
    tbl = p.add_table(1, 1)
    tbl.set_caption("표 1 매출 현황")
    md = rich_markdown(doc)
    doc.close()
    assert "표 1 매출 현황" in md


def test_markdown_export_includes_picture_caption(tmp_path) -> None:
    doc = HwpxDocument.new(empty_first_line=True)
    p = doc.sections[0].add_paragraph()
    media = doc.media.add_image(b"\x89PNG\r\n\x1a\n" + b"0" * 40, "png")
    pic = p.add_picture(media.item_id, width=10000, height=8000)
    pic.set_caption("그림 1. 매출 그래프")
    md = rich_markdown(doc, image_dir=str(tmp_path))
    doc.close()
    assert "![image]" in md
    assert "*그림 1. 매출 그래프*" in md


# ── tests/test_engine_small_defects_eng36.py ──────────────────────────────


def test_html_export_keeps_merged_cells_in_their_columns() -> None:
    with HwpxDocument.new() as document:
        table = document.add_table(rows=3, cols=3)
        for row in range(3):
            for col in range(3):
                table.cell(row, col).text = f"r{row}c{col}"
        table.merge_cells(0, 0, 0, 1)
        table.merge_cells(1, 0, 2, 0)
        html = to_html(document)

    rows = re.findall(r"<tr>(.*?)</tr>", html, flags=re.S)
    cells = [re.findall(r"<td([^>]*)>", row) for row in rows]
    assert cells == [
        [' colspan="2"', ""],
        [' rowspan="2"', "", ""],
        ["", ""],
    ]
    # 병합이 없는 표는 전과 같은 마크업이다.
    with HwpxDocument.new() as document:
        document.add_table(rows=1, cols=2)
        assert "colspan" not in to_html(document) and "rowspan" not in to_html(document)


# ── tests/test_hyperlink_hancom_form.py ───────────────────────────────────


def _field_begin(paragraph):
    return next(n for n in paragraph.element.iter(f"{HP}fieldBegin") if n.get("type") == "HYPERLINK")


def test_markdown_gives_back_the_url_it_was_given() -> None:
    doc = HwpxDocument.new()
    doc.refs.add_hyperlink("https://example.com/a?b=c", "링크")
    # the link text may carry the link's own character styling
    assert "](https://example.com/a?b=c)" in rich_markdown(doc)


def test_markdown_resolves_a_hancom_authored_web_link() -> None:
    doc = HwpxDocument.new()
    paragraph = doc.add_paragraph("")
    doc.refs.add_hyperlink("https://placeholder.invalid", "한컴 링크", paragraph=paragraph)
    begin = _field_begin(paragraph)
    begin.set("name", "")
    holder = begin.find(f"{HP}parameters")
    for child in list(holder):
        holder.remove(child)
    params = {"Prop": "0", "Command": "https\\://www.example.go.kr;1;0;0;",
              "Path": "https://www.example.go.kr", "Category": "HWPHYPERLINK_TYPE_URL"}
    for name, text in params.items():
        param = holder.makeelement(f"{HP}{'integerParam' if name == 'Prop' else 'stringParam'}", {"name": name})
        param.text = text
        holder.append(param)
    holder.set("cnt", str(len(params)))

    assert "](https://www.example.go.kr)" in rich_markdown(doc)


# ── tests/test_paragraph_hyperlink_style.py ───────────────────────────────


def test_markdown_writes_link_text_without_the_link_style() -> None:
    document = HwpxDocument.new(empty_first_line=True)
    paragraph = document.add_paragraph("")
    document.refs.add_hyperlink("https://example.com", "링크", paragraph=paragraph)

    markdown = rich_markdown(document)

    assert "[링크](https://example.com)" in markdown
    assert "<u>" not in markdown and "#0000FF" not in markdown


# ── tests/test_instid_attribute_case.py ───────────────────────────────────


def test_markdown_note_marker_carries_the_authored_inst_id() -> None:
    """저작(쓰기)과 export(읽기)가 같은 속성명으로 만나야 마커에 ID가 실린다."""

    document = HwpxDocument.new()
    paragraph = document.add_paragraph("본문")
    paragraph.add_footnote("각주 본문")

    markdown = rich_markdown(HwpxDocument.open(document.to_bytes()))
    match = re.search(r"\[\^fn(\d+)\]", markdown)
    assert match, f"각주 마커에 instId가 비었다: {markdown!r}"


# ── tests/test_note_authoring_contract.py ─────────────────────────────────


def test_markdown_reads_gold_shaped_notes() -> None:
    doc = HwpxDocument.new()
    para = doc.add_paragraph("누리호 발사 성공")
    para.add_footnote("한국형 발사체")
    md = rich_markdown(_reopened(doc))
    assert "[^fn" in md
    assert "한국형 발사체" in md


def test_markdown_still_reads_legacy_run_direct_notes() -> None:
    # 5.4 이전 자사 방출(run 직속 footNote) 호환 유지
    doc = HwpxDocument.new()
    para = doc.add_paragraph("본문")
    run = para.element.makeelement(f"{HP}run", {"charPrIDRef": "0"})
    para.element.append(run)
    note = run.makeelement(f"{HP}footNote", {"instId": "9999"})
    run.append(note)
    sub = note.makeelement(f"{HP}subList", {"id": "", "vertAlign": "TOP"})
    note.append(sub)
    body_p = sub.makeelement(f"{HP}p", {"id": "0", "paraPrIDRef": "0", "styleIDRef": "0"})
    sub.append(body_p)
    body_run = body_p.makeelement(f"{HP}run", {"charPrIDRef": "0"})
    body_p.append(body_run)
    t = body_run.makeelement(f"{HP}t", {})
    t.text = "구식 각주 본문"
    body_run.append(t)
    md = rich_markdown(_reopened(doc))
    assert "구식 각주 본문" in md


# ── tests/test_text_inline_elements.py ────────────────────────────────────


def test_markdown_export_keeps_text_after_inline_elements() -> None:
    hancom_t = (
        '<hp:t>성<hp:fwSpace/>명<hp:tab width="4000" leader="0" type="1"/>홍길동<hp:lineBreak/>'
        '둘째 줄<hp:markpenBegin color="#FFFF00"/>강조<hp:markpenEnd/>끝<hp:nbSpace/>.</hp:t>'
    )
    doc = HwpxDocument.new()
    doc.add_paragraph("PLACEHOLDER")
    source = io.BytesIO(doc.to_bytes())
    out = io.BytesIO()
    with zipfile.ZipFile(source) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "Contents/section0.xml":
                data = data.decode("utf-8").replace("<hp:t>PLACEHOLDER</hp:t>", hancom_t).encode("utf-8")
            zout.writestr(info, data, compress_type=zipfile.ZIP_STORED if info.filename == "mimetype" else zipfile.ZIP_DEFLATED)

    markdown = rich_markdown(HwpxDocument.open(io.BytesIO(out.getvalue())))
    for piece in ("명", "홍길동", "둘째 줄", "강조끝"):
        assert piece in markdown


# ── tests/test_section_settings_survive_removal.py, tests/test_new_document_first_line.py ──


def test_a_header_set_on_the_page_survives_removing_the_first_paragraph() -> None:
    doc = HwpxDocument.new()
    doc.page.set_header(text="머리말")
    doc.add_paragraph("지울 줄")
    doc.add_paragraph("남는 줄")
    doc.paragraphs[0].remove()
    again = _reopened(doc)
    assert [p.text for p in again.paragraphs] == ["남는 줄"]
    assert "머리말" in to_markdown(again, rich=True, headers_and_footers=True)


def test_a_header_set_first_does_not_keep_the_line_empty() -> None:
    doc = HwpxDocument.new()
    doc.page.set_header(text="머리말")
    doc.page.set_page_number()
    doc.add_paragraph("본문")
    again = _reopened(doc)
    assert [p.text for p in again.paragraphs] == ["본문"]
    assert "머리말" in to_markdown(again, rich=True, headers_and_footers=True)


# ── tests/test_style_resolution.py ────────────────────────────────────────


def test_the_functions_export_a_paragraph() -> None:
    document = HwpxDocument.new()
    document.add_paragraph("첫 문단")
    assert "첫 문단" in to_markdown(document)
    assert "첫 문단" in to_markdown(document, rich=True)
    assert "첫 문단" in to_html(document)


# ── tests/test_new_features.py, tests/test_integration_roundtrip.py ───────


def _doc_with_content() -> HwpxDocument:
    doc = HwpxDocument.new()
    doc.add_paragraph("Hello")
    tbl = doc.add_table(2, 2)
    tbl.cell(0, 0).text = "A"
    tbl.cell(0, 1).text = "B"
    tbl.cell(1, 0).text = "C"
    tbl.cell(1, 1).text = "D"
    doc.add_paragraph("End")
    return doc


def test_export_html_full_document() -> None:
    html = export_html(_doc_with_content())
    assert "<!DOCTYPE html>" in html
    assert "<p>Hello</p>" in html
    assert "<table" in html


def test_export_html_body_only() -> None:
    html = to_html(_doc_with_content(), full_document=False)
    assert "<!DOCTYPE" not in html
    assert "<p>Hello</p>" in html


def test_export_markdown_basic() -> None:
    md = to_markdown(_doc_with_content())
    assert "Hello" in md
    assert "| A | B |" in md
    assert "| --- | --- |" in md


def test_export_from_a_saved_and_reopened_document() -> None:
    doc = HwpxDocument.new()
    doc.add_paragraph("Markdown output")
    doc.add_table(1, 2).cell(0, 0).text = "Cell"
    again = _reopened(doc)
    md = to_markdown(again)
    assert "Markdown output" in md and "Cell" in md
    assert "Markdown output" in to_html(again)


# ── tests/test_migration_seams.py ─────────────────────────────────────────


def test_heading_callback_receives_formatted_markdown_and_can_decline() -> None:
    document = HwpxDocument.new()
    document.add_paragraph("Ⅰ. 기본 제목")
    paragraph = document.add_paragraph()
    paragraph.add_run("custom", bold=True)
    seen = []

    def detector(text: str) -> str | None:
        seen.append(text)
        return "### replacement" if "custom" in text else None

    result = rich_markdown(document, heading_detector=detector)
    assert "# Ⅰ." not in result and "Ⅰ. 기본 제목" in result
    assert "### replacement" in result and any("**custom**" in text for text in seen)


def test_heading_callback_reaches_one_cell_tables_and_disabled_flag() -> None:
    document = HwpxDocument.new()
    table = document.add_table(1, 1)
    table.cell(0, 0).text = "cell heading"
    seen = []

    def detector(text: str) -> str | None:
        seen.append(text)
        return "### cell heading" if "cell heading" in text else None

    assert "### cell heading" in rich_markdown(document, heading_detector=detector)
    seen.clear()
    assert "### cell heading" not in rich_markdown(document, detect_headings=False, heading_detector=detector)
    assert not seen


def test_omitted_heading_callback_keeps_legacy_default() -> None:
    document = HwpxDocument.new()
    document.add_paragraph("Ⅰ. 기본 제목")
    assert rich_markdown(document) == rich_markdown(document, heading_detector=None)
    assert "# Ⅰ. 기본 제목" in rich_markdown(document)


def test_heading_callback_reaches_the_function() -> None:
    document = HwpxDocument.new()
    document.add_paragraph("Ⅰ. 기본 제목")
    options = {"heading_detector": lambda text: "### injected" if "기본 제목" in text else None}
    assert "### injected" in to_markdown(document, rich=True, **options)


def test_an_invalid_callback_raises_a_structured_type_error_before_io() -> None:
    with pytest.raises(HwpxTypeError) as found:
        rich_markdown(b"not a package", heading_detector=42)  # type: ignore[arg-type]
    assert found.value.code == "hwpx-type-error"
    assert found.value.context == {"argument": "heading_detector"}
