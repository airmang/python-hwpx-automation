# SPDX-License-Identifier: Apache-2.0
"""Values that come from a document must not become markup or CSS in the preview.

Moved from the preview half of python-hwpx
tests/test_preview_and_markdown_untrusted_values.py (the Markdown half moves
with the Markdown exporter).
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pytest

from hwpx import HwpxDocument

from hwpx_automation.preview import layout_preview, render_document_viewer, render_layout_preview


def _rewrite_member(source: Path, member: str, change) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == member:
                data = change(data.decode("utf-8")).encode("utf-8")
            dst.writestr(info, data)
    return out.getvalue()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("#1A2b3C", "#1A2b3C"),
        ("1A2B3C", "#1A2B3C"),
        ("#80112233", "#11223380"),
        ("none", "#000000"),
        (None, "#000000"),
        ("#000;background:url(http://127.0.0.1:1/x)", "#000000"),
        ("#000000;position:fixed", "#000000"),
        ("red", "#000000"),
        ("#12345", "#000000"),
    ],
)
def test_preview_colour_is_a_hex_colour_or_the_default(value: str | None, expected: str) -> None:
    assert layout_preview._css_color(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.12 mm", "0.12mm"),
        ("5mm", "5mm"),
        (None, "0.1mm"),
        ("0.1 mm solid red;background:url(x)", "0.1mm"),
        ("1px", "0.1mm"),
    ],
)
def test_preview_border_width_is_a_millimetre_length_or_the_default(value: str | None, expected: str) -> None:
    assert layout_preview._css_border_width(value) == expected


def test_preview_style_attributes_carry_no_document_supplied_css(tmp_path: Path) -> None:
    path = tmp_path / "doc.hwpx"
    doc = HwpxDocument.new()
    doc.add_paragraph("본문")
    doc.save(path)

    def inject(xml: str) -> str:
        xml, colours = re.subn(r'textColor="[^"]*"', 'textColor="#000;background:url(http://127.0.0.1:1/MARK)"', xml)
        xml, aligns = re.subn(r'horizontal="[^"]*"', 'horizontal="LEFT;position:fixed"', xml)
        assert colours and aligns
        return xml

    html = render_layout_preview(_rewrite_member(path, "Contents/header.xml", inject)).html

    assert "MARK" not in html
    assert "url(" not in html
    assert "position:fixed" not in html.replace(" ", "")


def test_preview_shows_the_text_after_line_breaks_tabs_and_marks(tmp_path: Path) -> None:
    path = tmp_path / "doc.hwpx"
    doc = HwpxDocument.new()
    doc.add_paragraph("ZQ첫줄\nZQ둘째줄\nZQ셋째줄")
    doc.add_paragraph("ZQ탭앞\tZQ탭뒤")
    doc.add_paragraph("ZQ형광앞ZQ형광뒤")
    doc.save(path)

    def mark(xml: str) -> str:
        changed = xml.replace("ZQ형광앞ZQ형광뒤", 'ZQ형광앞<hp:markpenBegin color="#FFFF00"/>ZQ형광<hp:markpenEnd/>뒤')
        assert changed != xml
        return changed

    data = _rewrite_member(path, "Contents/section0.xml", mark)

    for html in (render_layout_preview(data).html, render_document_viewer(data).html):
        for piece in ("ZQ첫줄", "ZQ둘째줄", "ZQ셋째줄", "ZQ탭앞", "ZQ탭뒤", "ZQ형광앞", "ZQ형광", "뒤"):
            assert piece in html
