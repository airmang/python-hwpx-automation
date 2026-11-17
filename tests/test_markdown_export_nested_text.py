# SPDX-License-Identifier: Apache-2.0
"""Rich Markdown keeps the text nested in headers, footers and table captions (baseline 3, r2·r3).

r2: a header or footer paragraph holding a table and a text box beside it lost the text box's text once
headers were read through ``doc.page.headers``; two headers whose only difference was that text then
read the same and the second was dropped. r3: a table caption holding a table lost that table's text.
Made-up text only.
"""

from __future__ import annotations

from hwpx import HwpxDocument

from hwpx_automation.markdown import to_markdown


def test_header_text_box_beside_a_table_and_both_page_types_are_written() -> None:
    document = HwpxDocument.new()
    document.sections[0].paragraphs[0].text = "본문"
    for page_type, label in (("ODD", "홀수 쪽 글상자"), ("EVEN", "짝수 쪽 글상자")):
        story = document.page.set_header(text="머리말 표", page_type=page_type)
        paragraph = story.paragraphs[0]
        paragraph.add_table(1, 1).rows[0].cells[0].text = "칸"
        paragraph.add_rectangle(width=7200, height=3600).set_draw_text(label)
    markdown = to_markdown(document, rich=True, headers_and_footers=True)
    header_lines = [line for line in markdown.splitlines() if line.startswith("> 머리말")]
    assert len(header_lines) == 2
    assert "홀수 쪽 글상자" in header_lines[0] and "짝수 쪽 글상자" in header_lines[1]


def test_table_caption_holding_a_table_keeps_that_text() -> None:
    document = HwpxDocument.new()
    paragraph = document.sections[0].paragraphs[0]
    paragraph.text = "앞 글"
    table = paragraph.add_table(1, 2)
    table.rows[0].cells[0].text = "가"
    caption = table.set_caption("표 설명")
    caption.paragraphs[0].add_table(1, 1).rows[0].cells[0].text = "캡션 안 칸"
    markdown = to_markdown(document, rich=True)
    assert "캡션 안 칸" in markdown
