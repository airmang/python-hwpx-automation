# SPDX-License-Identifier: Apache-2.0
"""The quality page guard delegates its structural metrics to core (#177).

``hwpx.tools.page_guard`` is the one implementation; the automation path
re-exports it. These cases pin the public contract through the automation
path: inputs, multi-section counting, nested structures, the drift limits and
how a broken package fails.
"""

from __future__ import annotations

import dataclasses
import io
import zipfile
from pathlib import Path

import hwpx.tools.page_guard as core_page_guard
import pytest
from hwpx import HwpxDocument

from hwpx_automation.office import quality
from hwpx_automation.office.quality import page_guard

_SECTION = "Contents/section0.xml"


def _document() -> bytes:
    doc = HwpxDocument.new()
    doc.add_paragraph("가나다 라마")
    doc.add_paragraph("")
    outer = doc.add_table(2, 2)
    outer.cell(0, 0).text = "바깥"
    outer.cell(1, 1).add_table(1, 2).cell(0, 1).text = "안쪽"
    doc.add_paragraph("끝")
    doc.add_section()
    doc.add_paragraph("둘째 구역", section_index=1)
    return doc.to_bytes()


def _replace(data: bytes, name: str, payload: bytes) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            dst.writestr(info, payload if info.filename == name else src.read(info))
    return out.getvalue()


def test_the_automation_path_hands_out_cores_objects() -> None:
    assert page_guard.__all__ == core_page_guard.__all__
    for name in page_guard.__all__:
        assert getattr(page_guard, name) is getattr(core_page_guard, name), name
    for name in quality.__all__:
        assert getattr(quality, name) is getattr(core_page_guard, name), name
    fields = [field.name for field in dataclasses.fields(page_guard.DocumentMetrics)]
    assert fields == [
        "section_count",
        "paragraph_count",
        "page_break_count",
        "column_break_count",
        "table_count",
        "shape_count",
        "control_count",
        "table_shapes",
        "shape_types",
        "control_types",
        "text_char_total",
        "text_char_total_nospace",
        "paragraph_text_lengths",
    ]


def test_path_bytes_and_file_like_inputs_agree(tmp_path: Path) -> None:
    data = _document()
    path = tmp_path / "doc.hwpx"
    path.write_bytes(data)

    by_bytes = page_guard.collect_metrics(data)

    assert page_guard.collect_metrics(path) == by_bytes
    assert page_guard.collect_metrics(str(path)) == by_bytes
    assert page_guard.collect_metrics(io.BytesIO(data)) == by_bytes


def test_sections_nested_tables_and_empty_paragraphs_are_counted() -> None:
    metrics = page_guard.collect_metrics(_document())

    # Values the automation copy produced for this document before #177; core
    # produces the same. A nested table's text counts in its own paragraph and
    # again in the cell paragraph that holds the table.
    assert metrics == page_guard.DocumentMetrics(
        section_count=2,
        paragraph_count=14,
        page_break_count=0,
        column_break_count=0,
        table_count=2,
        shape_count=0,
        control_count=2,
        table_shapes=[("2", "2", "42520", "564", "0", "CELL"), ("1", "2", "20240", "282", "0", "CELL")],
        shape_types=[],
        control_types=[("colPr", 2)],
        text_char_total=22,
        text_char_total_nospace=20,
        paragraph_text_lengths=[0, 6, 0, 4, 2, 0, 0, 0, 2, 0, 2, 1, 0, 5],
    )


def test_identical_documents_compare_clean_and_drift_respects_the_limits() -> None:
    reference = page_guard.collect_metrics(_document())
    assert page_guard.compare_metrics(reference, reference) == []

    grown = dataclasses.replace(
        reference,
        text_char_total_nospace=reference.text_char_total_nospace * 115 // 100,
    )
    # A 15% change sits exactly on the default limit and passes; any more fails.
    assert page_guard.compare_metrics(reference, grown, max_text_delta_ratio=0.15) == []
    errors = page_guard.compare_metrics(reference, grown, max_text_delta_ratio=0.1)
    assert errors and errors[0].startswith("total text length drift exceeded:")

    fewer = dataclasses.replace(reference, paragraph_count=reference.paragraph_count - 1, table_count=0)
    assert page_guard.compare_metrics(reference, fewer)[:2] == [
        f"paragraph count mismatch: ref={reference.paragraph_count}, out={reference.paragraph_count - 1}",
        f"table count mismatch: ref={reference.table_count}, out=0",
    ]


def test_a_broken_package_fails_loudly() -> None:
    with pytest.raises(SyntaxError):  # ElementTree.ParseError (lxml's error before #177)
        page_guard.collect_metrics(_replace(_document(), _SECTION, b"<hs:sec"))
    with pytest.raises(Exception):
        page_guard.collect_metrics(b"not a zip")
