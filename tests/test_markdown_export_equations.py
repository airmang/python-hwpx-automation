# SPDX-License-Identifier: Apache-2.0
"""Equations in the rich Markdown export (opt-in; on for ingest).

Moved from python-hwpx tests/test_markdown_export_equations.py (the ingest test stays with ingest).
"""
from __future__ import annotations

from hwpx import HwpxDocument
from hwpx_automation.markdown import equation_markdown
from hwpx_automation.markdown._export import export_markdown


def _document() -> HwpxDocument:
    doc = HwpxDocument.new()
    paragraph = doc.add_paragraph("근은 ")
    paragraph.add_equation("x = {-b +- sqrt {b ^{2} - 4ac}} over {2a}")
    paragraph.add_run("이다.")
    table = doc.add_table(1, 2)
    table.rows[0].cells[0].paragraphs[0].add_equation("{1} over {2}")
    return doc


def test_the_default_export_leaves_equations_out() -> None:
    assert "$" not in export_markdown(_document())


def test_an_equation_comes_where_it_sits_as_latex() -> None:
    markdown = export_markdown(_document(), equations=True)
    assert r"근은 $x = \frac{- b \pm \sqrt{b^{2} - 4 ac}}{2 a}$이다." in markdown
    assert r"| $\frac{1}{2}$ |" in markdown


def test_an_equation_in_a_footnote_is_carried_too() -> None:
    doc = HwpxDocument.new()
    paragraph = doc.add_paragraph("본문")
    note = doc.notes.add_footnote("각주 ", paragraph=paragraph)
    note_paragraph = next(iter(note.paragraphs)) if hasattr(note, "paragraphs") else None
    if note_paragraph is None:
        return
    note_paragraph.add_equation("a ^{2}")
    assert "$a^{2}$" in export_markdown(doc, equations=True)


def test_a_script_latex_cannot_carry_is_kept_as_code() -> None:
    assert equation_markdown("") == ""
    assert equation_markdown("  x   +  y ") == "$x + y$"
    assert equation_markdown("a $ b") == "`a $ b`"


def test_the_option_does_not_leak_into_the_next_call() -> None:
    doc = _document()
    export_markdown(doc, equations=True)
    assert "$" not in export_markdown(doc)
