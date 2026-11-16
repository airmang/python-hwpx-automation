# SPDX-License-Identifier: Apache-2.0
"""HwpxOps methods 8.0 removed say where to go, and the memo shape is set per section."""

from __future__ import annotations

from pathlib import Path

import pytest
from hwpx import HwpxDocument

from hwpx_automation.hwpx_ops import HwpxOps


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "in.hwpx"
    doc = HwpxDocument.new()
    doc.add_paragraph("하나")
    doc.save(path)
    return path


@pytest.mark.parametrize(
    ("name", "replacement"),
    [
        ("add_memo", "add_memo_with_anchor"),
        ("attach_memo_field", "add_memo_with_anchor"),
        ("add_shape", "doc.shapes.add_rectangle"),
        ("add_control", "doc.shapes.add_"),
    ],
)
def test_a_removed_method_names_its_replacement(tmp_path: Path, name: str, replacement: str) -> None:
    ops = HwpxOps(base_directory=tmp_path)
    assert not hasattr(ops, name)
    with pytest.raises(AttributeError, match="removed in python-hwpx-automation 8.0") as error:
        getattr(ops, name)
    assert replacement in str(error.value)


def test_an_unknown_name_is_a_plain_attribute_error(tmp_path: Path) -> None:
    with pytest.raises(AttributeError) as error:
        getattr(HwpxOps(base_directory=tmp_path), "no_such_method")
    assert "8.0" not in str(error.value)


def test_add_memo_with_anchor_no_longer_takes_a_memo_shape(tmp_path: Path) -> None:
    ops = HwpxOps(base_directory=tmp_path)
    with pytest.raises(TypeError):
        ops.add_memo_with_anchor(str(_source(tmp_path)), text="메모", memo_shape_id_ref="0")  # type: ignore[call-arg]


def test_the_memo_shape_is_set_for_the_section(tmp_path: Path) -> None:
    source = _source(tmp_path)
    ops = HwpxOps(base_directory=tmp_path)
    memo = ops.add_memo_with_anchor(str(source), text="메모")
    doc = HwpxDocument.open(source)
    shape_id = doc.styles.ensure_memo_shape()
    doc.save(source)
    result = ops.set_memo_shape(str(source), shape_id, section_index=0)
    assert result == {"sectionIndex": 0, "memoShapeIDRef": str(shape_id)}
    reopened = HwpxDocument.open(source)
    assert reopened.sections[0].properties.memo_shape_id_ref == str(shape_id)
    assert [item.id for item in reopened.notes.memos] == [memo["memoId"]]
