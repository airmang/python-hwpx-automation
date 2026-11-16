# SPDX-License-Identifier: Apache-2.0
"""A paragraph inserted before a section's first paragraph takes the section settings (secPr) along."""

from __future__ import annotations

from hwpx import HwpxDocument

from hwpx_automation.core.content import insert_paragraph_to_doc


def _holds_secpr(paragraph) -> bool:
    return any(str(node.tag).endswith("}secPr") for node in paragraph.element.iter())


def test_inserting_before_the_first_paragraph_moves_the_section_settings() -> None:
    doc = HwpxDocument.new()
    doc.add_paragraph("원래 첫 문단")
    doc.page.set_margins(left=11339)
    doc.add_paragraph("둘째")
    insert_paragraph_to_doc(doc, 0, "새 첫 문단")
    first, second, third = doc.sections[0].paragraphs[:3]
    assert [first.text, second.text, third.text] == ["새 첫 문단", "원래 첫 문단", "둘째"]
    assert _holds_secpr(first) and not _holds_secpr(second)
    assert doc.page.margins().left == 11339
    reopened = HwpxDocument.open(doc.to_bytes())
    assert _holds_secpr(reopened.sections[0].paragraphs[0])


def test_inserting_in_the_middle_leaves_the_section_settings() -> None:
    doc = HwpxDocument.new()
    doc.add_paragraph("하나")
    doc.add_paragraph("둘")
    insert_paragraph_to_doc(doc, 1, "사이")
    paragraphs = doc.sections[0].paragraphs
    assert [p.text for p in paragraphs[:3]] == ["하나", "사이", "둘"]
    assert _holds_secpr(paragraphs[0]) and not _holds_secpr(paragraphs[1])
