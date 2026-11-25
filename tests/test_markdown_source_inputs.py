# SPDX-License-Identifier: Apache-2.0
"""``to_markdown``·``to_html`` take a path or HWPX bytes as 6.x's exporters did.

6.x ``hwpx.tools.exporter.export_markdown`` took a document or the bytes of a package, and
``hwpx.tools.markdown_export.export_markdown`` a path too. 8.0.0 took only a document, so code
moved over with the same argument met ``AttributeError: 'str' object has no attribute 'oxml'``
and a fallback without Markdown tables (python-hwpx#821).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from hwpx import HwpxDocument
from hwpx.errors import HwpxTypeError

from hwpx_automation.markdown import to_html, to_markdown

TABLE = "| 항목 | 값 |\n| --- | --- |\n| 가 | 1 |"


def _saved(tmp_path: Path) -> Path:
    doc = HwpxDocument.new()
    doc.add_paragraph("머리 문단")
    table = doc.add_table(rows=2, cols=2)
    for row, values in enumerate((("항목", "값"), ("가", "1"))):
        for col, value in enumerate(values):
            table.set_cell_text(row, col, value)
    path = tmp_path / "표.hwpx"
    doc.save(path)
    return path


@pytest.mark.parametrize("kind", ["str", "path", "bytes", "bytearray", "document"])
def test_every_source_gives_the_same_markdown_and_html(tmp_path: Path, kind: str) -> None:
    path = _saved(tmp_path)
    expected_markdown = to_markdown(HwpxDocument.open(path))
    expected_rich = to_markdown(HwpxDocument.open(path), rich=True)
    expected_html = to_html(HwpxDocument.open(path))
    source = {
        "str": str(path),
        "path": path,
        "bytes": path.read_bytes(),
        "bytearray": bytearray(path.read_bytes()),
        "document": HwpxDocument.open(path),
    }[kind]

    assert TABLE in expected_markdown
    assert to_markdown(source) == expected_markdown
    assert to_markdown(source, rich=True) == expected_rich
    assert to_html(source) == expected_html


def test_a_path_is_closed_after_the_export(tmp_path: Path) -> None:
    path = _saved(tmp_path)
    to_markdown(path)
    to_html(str(path))
    os.remove(path)  # Windows refuses while a handle is open
    assert not path.exists()


def test_anything_else_is_a_typed_error_that_says_what_it_takes() -> None:
    with pytest.raises(HwpxTypeError) as refused:
        to_markdown(123)  # type: ignore[arg-type]
    assert "HwpxDocument" in str(refused.value)
    assert refused.value.context == {"type": "int"}
    with pytest.raises(HwpxTypeError):
        to_html(None)  # type: ignore[arg-type]


def test_the_pypi_description_has_no_repository_relative_links() -> None:
    """PyPI resolves a relative link under pypi.org and it 404s (#232)."""

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    relative = re.findall(r"\]\((?!https?:|#|mailto:)([^)\s]+)\)", readme)
    relative += re.findall(r'(?:src|href)="(?!https?:|#|mailto:)([^"]+)"', readme)
    assert relative == []
