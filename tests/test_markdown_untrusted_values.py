# SPDX-License-Identifier: Apache-2.0
"""Values that come from a document must not become Markdown markup, links or file names.

Moved from python-hwpx tests/test_preview_and_markdown_untrusted_values.py (its Markdown half; the
preview half moves with the preview).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hwpx import HwpxDocument
from hwpx_automation.markdown import _export as markdown_export


def test_markdown_wraps_only_hex_colours() -> None:
    wrapped = markdown_export._wrap("셀값", {"color": '#111"><b>MARK</b><span x="', "shade": "#FFFF00"})

    assert "MARK" not in wrapped
    assert wrapped == '<mark style="background-color:#FFFF00">셀값</mark>'
    assert markdown_export._wrap("값", {"color": "#FF0000"}) == '<span style="color:#FF0000">값</span>'


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/a?b=1", "https://example.com/a?b=1"),
        ("mailto:someone@example.com", "mailto:someone@example.com"),
        ("https://example.com/a) [x](javascript:mark()", "https://example.com/a%29%20[x]%28javascript:mark%28%29"),
        ("javascript:mark()", None),
        ("file:///C:/Windows/win.ini", None),
        ("\\\\server\\share\\x", None),
        ("", None),
        (None, None),
    ],
)
def test_markdown_links_only_web_and_mail_targets(url: str | None, expected: str | None) -> None:
    assert markdown_export._safe_link_url(url) == expected


def test_markdown_keeps_the_text_of_a_link_it_does_not_link() -> None:
    doc = HwpxDocument.new()
    doc.add_paragraph("앞 ").add_hyperlink("javascript:mark()", "눌러보기")

    md = markdown_export.export_markdown(doc)

    assert "눌러보기" in md
    assert "javascript:" not in md


@pytest.mark.parametrize(
    ("member", "expected"),
    [
        ("BinData/image1.png", "image1.png"),
        ("BinData/사진.JPG", "사진.JPG"),
        ("BinData/json.py", None),
        ("BinData/.env", None),
        ("BinData/index.html", None),
        ("BinData/C:evil.png", None),
        ("BinData/x.png:stream", None),
        ("BinData/sub\\..\\up.png", "up.png"),
        ("BinData/con.png", None),
        ("BinData/trailing.png.", None),
        ("BinData/", None),
    ],
)
def test_markdown_image_file_name_is_one_image_component(member: str, expected: str | None) -> None:
    assert markdown_export._image_file_name(member) == expected


def test_markdown_image_dir_receives_only_image_members(tmp_path: Path) -> None:
    class Package:
        def files(self) -> list[str]:
            return ["BinData/image1.png", "BinData/json.py", "BinData/C:evil.png", "Contents/section0.xml"]

        def read(self, name: str) -> bytes:
            return b"data"

    class Doc:
        package = Package()

    target = tmp_path / "imgs"
    mapping = markdown_export._build_image_map(Doc(), target, None)  # type: ignore[arg-type]

    assert sorted(p.name for p in target.iterdir()) == ["image1.png"]
    assert mapping == {"image1": "imgs/image1.png"}
