# SPDX-License-Identifier: Apache-2.0
"""Headers, footers and memos in the rich Markdown export (opt-in; on for ingest).

Moved from python-hwpx tests/test_markdown_export_outside_body.py (the two ingest tests stay with ingest).
"""
from __future__ import annotations

import io
import zipfile

from lxml import etree

from hwpx import HwpxDocument
from hwpx_automation.markdown._export import export_markdown


def _with_unplaced_memo(package: bytes, memogroup_xml: str) -> bytes:
    """*package* with a memo kept only in ``hp:memogroup`` (no MEMO field), as python-hwpx 6.x wrote.

    python-hwpx 7.0 refuses to save a memo it made without a paragraph
    (``note-memo-unanchored``), so the 6.x shape is written into the section part here.
    """

    source = zipfile.ZipFile(io.BytesIO(package))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for info in source.infolist():
            data = source.read(info)
            if info.filename == "Contents/section0.xml":
                text = data.decode("utf-8")
                end = text.rindex("</hs:sec>")
                data = (text[:end] + memogroup_xml + text[end:]).encode("utf-8")
            target.writestr(info, data)
    return out.getvalue()


def _document() -> HwpxDocument:
    doc = HwpxDocument.new()
    doc.add_paragraph("본문 첫 문단입니다.")
    reviewed = doc.add_paragraph("검토가 필요한 문장입니다.")
    doc.notes.add_memo("근거 자료를 붙여 주세요", paragraph=reviewed)
    unplaced = doc.notes.add_memo("자리 없는 메모")
    memogroup_xml = etree.tostring(doc.sections[0].memo_group.element, encoding="unicode")
    doc.notes.remove_memo(unplaced)
    doc.page.set_header(text="2026학년도 운영 계획")
    doc.page.set_footer(text="가나고등학교")
    buffer = io.BytesIO()
    doc.save(buffer)
    return HwpxDocument.open(_with_unplaced_memo(buffer.getvalue(), memogroup_xml))


def test_the_default_export_is_the_body_only() -> None:
    markdown = export_markdown(_document())
    assert markdown == "본문 첫 문단입니다.\n\n검토가 필요한 문장입니다."


def test_headers_and_footers_frame_the_section() -> None:
    lines = export_markdown(_document(), headers_and_footers=True).split("\n\n")
    assert lines[0] == "> 머리말: 2026학년도 운영 계획"
    assert lines[-1] == "> 꼬리말: 가나고등학교"
    assert "메모" not in "".join(lines)


def test_a_memo_is_marked_after_the_text_it_is_on() -> None:
    markdown = export_markdown(_document(), memos=True)
    assert "검토가 필요한 문장입니다.[^memo1]" in markdown
    assert "[^memo1]: 메모: 근거 자료를 붙여 주세요" in markdown
    assert markdown.count("근거 자료를 붙여 주세요") == 1
    assert "머리말" not in markdown


def test_a_memo_without_a_place_in_the_text_comes_at_the_section_end() -> None:
    markdown = export_markdown(_document(), memos=True)
    assert "> 메모: 자리 없는 메모" in markdown
    assert markdown.index("검토가 필요한") < markdown.index("> 메모: 자리 없는 메모") < markdown.index("[^memo1]:")


def test_the_same_header_is_written_once_across_sections() -> None:
    doc = HwpxDocument.new()
    doc.add_paragraph("첫 구역")
    doc.page.set_header(text="같은 머리말")
    second = doc.add_section()
    doc.add_paragraph("둘째 구역", section=second)
    doc.page.set_header(text="같은 머리말", section=second)
    markdown = export_markdown(doc, headers_and_footers=True)
    assert markdown.count("같은 머리말") == 1
