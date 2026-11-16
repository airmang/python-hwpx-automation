# SPDX-License-Identifier: Apache-2.0
"""7.0 배포 전 수정(내보내기): 결과를 직접 단언한다.

Moved from python-hwpx tests/test_export_fix7_convert.py (its Markdown/HTML tests; the ingest
assertions and tests stay with ingest, ``doc.text.plain()`` stays with the engine).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from hwpx.document import HwpxDocument
from hwpx.errors import HwpxTypeError
from hwpx_automation.markdown import escape_markdown, to_html, to_markdown
from hwpx_automation.markdown._export import export_markdown as rich_markdown
from hwpx_automation.markdown._plain_export import export_html, export_markdown

FIXTURES = Path(__file__).parent / "fixtures"
HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def _doc(*texts: str) -> HwpxDocument:
    document = HwpxDocument.new()
    for text in texts:
        document.add_paragraph(text)
    return document


def test_a_table_placed_in_the_section_is_exported() -> None:
    source = FIXTURES / "reader_robustness" / "irb_form_filled.hwpx"
    document = HwpxDocument.open(source)
    root = etree.fromstring(_section_xml(source))
    loose = [child for child in root if child.tag == f"{HP}tbl"]
    assert loose, "시험 문서의 표는 구역에 바로 놓여 있어야 한다"
    cell_text = next("".join(t.itertext()) for t in loose[0].iter(f"{HP}t") if "".join(t.itertext()).strip())
    assert cell_text.strip() in to_markdown(document, rich=True)
    assert cell_text.strip() in to_markdown(document)
    assert cell_text.strip() in to_html(document)


def _section_xml(path: Path) -> bytes:
    import zipfile

    with zipfile.ZipFile(path) as archive:
        return archive.read("Contents/section0.xml")


# ── 2. 제목: 개요 수준을 먼저 본다 ──────────────────────────────────────────


def test_add_heading_paragraphs_are_markdown_headings() -> None:
    document = HwpxDocument.new()
    document.add_heading("문서 제목", level=1)
    document.add_heading("둘째 수준", level=2)
    document.add_paragraph("1. 서론은 제목이 아닌 문단입니다")
    rich = to_markdown(document, rich=True)
    assert "# 문서 제목" in rich.split("\n")
    assert "## 둘째 수준" in rich.split("\n")
    assert "## 1." not in rich  # 개요가 있는 문서는 글 모양으로 짐작하지 않는다
    plain = to_markdown(document)
    assert "# 문서 제목" in plain.split("\n") and "## 둘째 수준" in plain.split("\n")
    assert "<h1>문서 제목</h1>" in to_html(document)
    # 옛 결과
    assert "# 문서 제목" not in to_markdown(document, headings=False).split("\n")
    assert "# 문서 제목" not in rich_markdown(document, heading_source="text").split("\n")


def test_text_shape_guess_skips_questions_and_toc_lines() -> None:
    document = _doc("Ⅰ. 추진 배경", "1. 다음 중 옳은 것은?", "Ⅱ. 추진 과제 ······ 12", "1. 운영 계획")
    lines = to_markdown(document, rich=True).split("\n")
    assert "# Ⅰ. 추진 배경" in lines and "## 1. 운영 계획" in lines
    assert not any(line.startswith("#") and ("?" in line or "··" in line) for line in lines)
    legacy = rich_markdown(document, heading_source="text").split("\n")
    assert "## 1. 다음 중 옳은 것은?" in legacy


# ── 3. 이스케이프 ──────────────────────────────────────────────────────────


def test_plain_markdown_escapes_document_text() -> None:
    document = _doc("<img src=x onerror=alert(1)> [x](javascript:alert(1)) *별표* a_b ~물결~", "# 해시 줄", "- 대시 줄")
    markdown = to_markdown(document)
    assert "<img" not in markdown and "&lt;img" in markdown
    assert "\\[x\\](javascript" in markdown
    assert "\\*별표\\*" in markdown and "a\\_b" in markdown and "\\~물결\\~" in markdown
    assert "\\# 해시 줄" in markdown.split("\n") and "\\- 대시 줄" in markdown.split("\n")


def test_rich_markdown_escapes_line_starts_but_not_math_spans() -> None:
    document = _doc("# cd /etc", "수식 $\\frac{a}{b}$ 입니다", "2024. 3. 1. 시행")
    lines = to_markdown(document, rich=True, heading_source="outline").split("\n")
    assert "\\# cd /etc" in lines
    assert "수식 $\\frac{a}{b}$ 입니다" in lines
    assert "2024\\. 3. 1. 시행" in lines


def test_escape_markdown_keeps_unsafe_math_spans_escaped() -> None:
    assert escape_markdown("$a<b$") == "$a&lt;b$"
    assert escape_markdown("$[x](javascript:y)$") == "$\\[x\\](javascript:y)$"
    assert escape_markdown("$|x|$", pipe=True) == "$\\|x\\|$"


# ── 4. 목록 번호 ──────────────────────────────────────────────────────────


def test_rich_markdown_carries_list_labels() -> None:
    document = HwpxDocument.new(empty_first_line=True)
    for text in ("첫째", "둘째", "글머리"):
        document.add_paragraph(text)
    document.styles.apply_list_format(paragraph_indexes=[1, 2], kind="number")
    document.styles.apply_list_format(paragraph_indexes=[3], kind="bullet")
    lines = to_markdown(document, rich=True, list_labels=True).split("\n")
    assert "1. 첫째" in lines and "2. 둘째" in lines and "- 글머리" in lines
    assert "1. 첫째" not in to_markdown(document, rich=True).split("\n")


# ── 5. 표 ────────────────────────────────────────────────────────────────


def test_rich_table_cells_stay_on_their_row() -> None:
    document = _doc("본문")
    table = document.add_table(2, 2)
    table.cell(0, 0).text = "줄1\n줄2"
    table.cell(0, 1).paragraphs[0].add_run(" ", bold=True)
    inner = table.cell(1, 0).add_table(2, 2)
    inner.cell(0, 0).text = "안쪽"
    markdown = to_markdown(document, rich=True)
    rows = [line for line in markdown.split("\n") if line.startswith("|")]
    assert len(rows) == 3  # 머리 행, 구분 행, 둘째 행
    assert "줄1<br>줄2" in rows[0]
    assert "** **" not in markdown
    assert "<table><tr>" in rows[2] and "안쪽" in rows[2]


def test_html_table_cells_are_html() -> None:
    document = _doc("본문")
    table = document.add_table(2, 2)
    table.merge_cells(0, 0, 0, 1)
    table.cell(1, 0).paragraphs[0].add_run("굵게", bold=True)
    table.cell(1, 1).text = "a|b"
    markdown = to_markdown(document, rich=True)
    assert "<strong>굵게</strong>" in markdown
    assert "a|b" in markdown and "\\|" not in markdown and "**" not in markdown


# ── 6. 같은 instId의 각주 ───────────────────────────────────────────────────


def test_footnotes_sharing_an_inst_id_keep_their_own_text() -> None:
    document = _doc("본문")
    table = document.add_table(1, 1)
    cell_p = table.cell(0, 0).paragraphs[0]
    cell_p.add_run("칸 글")
    first = document.notes.add_footnote("첫 각주", paragraph=cell_p)
    body = document.add_paragraph("뒤 문단")
    document.notes.add_footnote("둘째 각주", paragraph=body)
    for section in document.sections:
        for note in section.element.iter(f"{HP}footNote"):
            note.set("instId", "1065353216")
    del first
    markdown = to_markdown(document, rich=True)
    assert "[^fn1]: 첫 각주" in markdown and "[^fn2]: 둘째 각주" in markdown


# ── 7. to_markdown() 옵션 ───────────────────────────────────────────────────


def test_markdown_option_of_the_other_mode_names_the_mode() -> None:
    document = _doc("본문")
    with pytest.raises(HwpxTypeError, match="rich=True") as found:
        to_markdown(document, image_dir="x")
    assert found.value.context["argument"] == "image_dir"
    with pytest.raises(HwpxTypeError, match="rich=False"):
        to_markdown(document, rich=True, include_tables=False)
    with pytest.raises(TypeError):
        to_markdown(document, nonsense=True)


# ── 9. 각주 번호·하이픈 ─────────────────────────────────────────────────────


def test_markdown_notes_are_footnotes_and_inline_keeps_the_old_form() -> None:
    document = _doc("앞 문단")
    paragraph = document.add_paragraph("문장")
    document.notes.add_footnote("각주 내용", paragraph=paragraph)
    markdown = export_markdown(document, notes=True)
    assert "1)1)" not in markdown
    assert "문장[^fn1]" in markdown and "[^fn1]: 각주 내용" in markdown
    assert "문장1)1)각주 내용" in export_markdown(document, notes="inline")
    html = export_html(document, notes=True, full_document=False)
    assert '<a href="#fn1">' in html and "1)1)" not in html


def test_hyphen_is_a_visible_hyphen() -> None:
    document = HwpxDocument.new()
    paragraph = document.add_paragraph("Word")
    t = next(paragraph.element.iter(f"{HP}t"))
    hyphen = etree.SubElement(t, f"{HP}hyphen")
    hyphen.tail = "processor"
    assert "\xad" not in to_markdown(document, rich=True)
    assert "Word-processor" in to_markdown(document, rich=True)


def test_colour_spans_can_be_left_out() -> None:
    document = HwpxDocument.new()
    paragraph = document.add_paragraph("앞 ")
    paragraph.add_run("빨강", color="#FF0000")
    assert "<span" in to_markdown(document, rich=True)
    assert "<span" not in to_markdown(document, rich=True, colors=False)


# ── 11. HTML ─────────────────────────────────────────────────────────────


def test_html_keeps_a_nested_table_nested() -> None:
    document = _doc("본문")
    table = document.add_table(1, 1)
    inner = table.cell(0, 0).add_table(1, 2)
    inner.cell(0, 1).text = "안쪽 칸"
    html = export_html(document, full_document=False)
    assert html.count("<table") == 2
    assert export_html(document, full_document=False, nested_tables=False).count("<table") == 1
