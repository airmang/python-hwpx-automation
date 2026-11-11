# SPDX-License-Identifier: Apache-2.0
"""Audit ENG-15: partial formatting divides text only.

``format_text`` used to ``deepcopy`` the whole run for every piece, so a run
carrying the section definition, a column definition, a form field or inline
``hp:tab``/``hp:lineBreak`` came out with those nodes two or three times.
"""
from __future__ import annotations

from pathlib import Path

from hwpx import HwpxDocument
from lxml import etree

from hwpx_automation.core.formatting import format_text_range, split_run_for_format
from hwpx_automation.ops_services import memo_style
from hwpx_automation.server import create_document, format_text

_HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def _count(element, name: str) -> int:
    return sum(1 for node in element.iter() if isinstance(node.tag, str) and node.tag == _HP + name)


def _run_summaries(paragraph) -> list[tuple[str, str]]:
    return [(run.char_pr_id_ref or "", run.text or "") for run in paragraph.runs]


def test_first_paragraph_keeps_one_section_definition_after_partial_format() -> None:
    doc = HwpxDocument.new()
    first = doc.paragraphs[0]
    first.runs[0].text = "제목 글"
    before_sec = _count(first.element, "secPr")
    before_ctrl = _count(first.element, "ctrl")
    assert before_sec == 1

    format_text_range(doc, 0, 0, 2, bold=True)

    assert _count(first.element, "secPr") == before_sec
    assert _count(first.element, "ctrl") == before_ctrl
    assert first.text == "제목 글"
    summaries = _run_summaries(first)
    assert [text for _, text in summaries if text] == ["제목", " 글"]
    assert summaries[0][0] != summaries[-1][0]  # only the target piece is restyled
    # The section definition stays in the first run, before any text.
    assert _count(first.runs[0].element, "secPr") == 1


def test_inline_tab_and_line_break_are_moved_not_copied() -> None:
    doc = HwpxDocument.new()
    paragraph = doc.add_paragraph("x")
    paragraph.text = "제목\t12\n끝"
    assert _count(paragraph.element, "tab") == 1
    assert _count(paragraph.element, "lineBreak") == 1
    index = len(doc.paragraphs) - 1

    for start, end in ((0, 1), (1, 4), (5, 7), (2, 3)):
        format_text_range(doc, index, start, end, bold=True)
        assert paragraph.text == "제목\t12\n끝"
        assert _count(paragraph.element, "tab") == 1
        assert _count(paragraph.element, "lineBreak") == 1
        assert all(len(run.element) for run in paragraph.runs)  # no empty run left


def test_middle_split_gives_three_runs_and_drops_the_line_cache() -> None:
    doc = HwpxDocument.new()
    paragraph = doc.add_paragraph("가나다라마")
    cache = etree.SubElement(paragraph.element, _HP + "linesegarray")
    etree.SubElement(cache, _HP + "lineseg", {"textpos": "0"})
    run = paragraph.runs[0]
    original = run.char_pr_id_ref

    split_run_for_format(run, 1, 3, "7")

    assert _run_summaries(paragraph) == [(original, "가"), ("7", "나다"), (original, "라마")]
    assert _count(paragraph.element, "linesegarray") == 0


def test_field_controls_stay_single_when_formatting_inside_a_field() -> None:
    doc = HwpxDocument.new()
    paragraph = doc.add_paragraph("")
    paragraph.add_form_field("이름", prompt="홍길동입니다")
    begins = _count(paragraph.element, "fieldBegin")
    ends = _count(paragraph.element, "fieldEnd")
    assert begins >= 1 and ends >= 1
    text = paragraph.text
    position = text.index("길동")
    index = len(doc.paragraphs) - 1

    format_text_range(doc, index, position, position + 2, bold=True)

    assert paragraph.text == text
    assert _count(paragraph.element, "fieldBegin") == begins
    assert _count(paragraph.element, "fieldEnd") == ends
    order = [
        node.tag.rsplit("}", 1)[-1]
        for node in paragraph.element.iter()
        if isinstance(node.tag, str) and node.tag.rsplit("}", 1)[-1] in {"fieldBegin", "fieldEnd"}
    ]
    assert order[0] == "fieldBegin" and order[-1] == "fieldEnd"


def test_memo_style_uses_the_same_split() -> None:
    assert memo_style._split_run is split_run_for_format


def test_format_text_tool_does_not_duplicate_section_definition(tmp_path: Path) -> None:
    target = tmp_path / "format_first.hwpx"
    create_document(str(target))
    doc = HwpxDocument.open(str(target))
    doc.paragraphs[0].runs[0].text = "첫 문단 제목"
    doc.save_to_path(str(target))
    doc.close()

    result = format_text(str(target), paragraph_index=0, start_pos=0, end_pos=2, bold=True)
    assert result["formatted"] is True

    reopened = HwpxDocument.open(str(target))
    try:
        section = reopened.sections[0].element
        assert _count(section, "secPr") == 1
        assert reopened.paragraphs[0].text == "첫 문단 제목"
    finally:
        reopened.close()
