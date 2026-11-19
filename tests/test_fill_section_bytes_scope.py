# SPDX-License-Identifier: Apache-2.0
"""``fill_section_bytes`` changes only the paragraphs whose placeholders it fills: the line layout cache
of a paragraph it edits goes, the caches of the paragraphs inside that paragraph's table cells (which
it did not edit) stay."""

from __future__ import annotations

import io
import zipfile

from hwpx import HwpxDocument
from lxml import etree

from hwpx_automation.office.form_fill import fill_section_bytes


def _section_with_caches() -> bytes:
    with HwpxDocument.new() as document:
        paragraph = document.add_paragraph("{{k}}")
        table = paragraph.add_table(1, 1)
        table.rows[0].cells[0].text = "칸"
        with zipfile.ZipFile(io.BytesIO(document.to_bytes())) as archive:
            root = etree.fromstring(archive.read("Contents/section0.xml"))
    for paragraph in root.xpath('//*[local-name()="p"]'):
        if not paragraph.xpath('./*[local-name()="linesegarray"]'):
            cache = etree.SubElement(paragraph, "{" + etree.QName(paragraph).namespace + "}linesegarray")
            etree.SubElement(cache, "{" + etree.QName(paragraph).namespace + "}lineseg", textpos="0")
    return etree.tostring(root)


def _caches(root: etree._Element, inside_cells: bool) -> int:
    xpath = '//*[local-name()="tc"]//*[local-name()="linesegarray"]'
    if not inside_cells:
        xpath = '//*[local-name()="p"][not(ancestor::*[local-name()="tc"])]/*[local-name()="linesegarray"]'
    return len(root.xpath(xpath))


def test_only_the_filled_paragraph_loses_its_layout_cache() -> None:
    section = _section_with_caches()
    before = etree.fromstring(section)
    out, receipt = fill_section_bytes(section, {"{{k}}": "값"})
    after = etree.fromstring(out)
    assert receipt.replacements == 1
    assert _caches(after, inside_cells=True) == _caches(before, inside_cells=True) == 1
    filled = after.xpath('//*[local-name()="p"][.//*[local-name()="t"][contains(text(), "값")]]')
    assert filled and not filled[0].xpath('./*[local-name()="linesegarray"]')
