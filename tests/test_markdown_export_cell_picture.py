# SPDX-License-Identifier: Apache-2.0
"""A picture in a table cell is written once, in its cell (rich Markdown export)."""

from __future__ import annotations

import base64

from hwpx import HwpxDocument

from hwpx_automation.markdown import to_markdown

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _document() -> HwpxDocument:
    doc = HwpxDocument.new()
    doc.add_paragraph("본문")
    table = doc.add_table(1, 2)
    picture = table.cell(0, 0).paragraphs[0].add_picture(doc.media.add_image(_PNG, "png"), width=7200, height=7200)
    picture.set_caption("칸 안 그림의 캡션")
    table.cell(0, 1).text = "옆 칸"
    return doc


def test_a_cell_picture_caption_is_written_once_in_its_cell() -> None:
    markdown = to_markdown(_document(), rich=True)
    assert markdown.count("칸 안 그림의 캡션") == 1
    assert "| *칸 안 그림의 캡션* | 옆 칸 |" in markdown


def test_a_cell_picture_is_written_once_when_pictures_are_extracted(tmp_path) -> None:
    markdown = to_markdown(_document(), rich=True, image_dir=tmp_path / "images")
    assert markdown.count("![image](") == 1
    assert markdown.count("칸 안 그림의 캡션") == 1
