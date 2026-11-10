# SPDX-License-Identifier: Apache-2.0
"""Template form-fit reports success only for text that is really in the copy."""

from __future__ import annotations

from pathlib import Path

import pytest
from hwpx.document import HwpxDocument

from hwpx_automation.office.form_fill import template_formfit
from hwpx_automation.office.form_fill.template_formfit import apply_template_formfit

BODY = "새로 넣은 본문 문장"


def _local(tag: object) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _baseline(kind: str = "section-region") -> dict:
    return {
        "schemaVersion": "hwpx.template-formfit.baseline.v1",
        "baselineId": "audit-readback",
        "regionMappings": [
            {
                "id": "body",
                "anchor": "1. 추진 배경",
                "kind": kind,
                "sourcePath": "body",
                "required": True,
                "columns": ["월", "내용"],
            }
        ],
    }


def _strip_text_slot(paragraph) -> None:
    """Shape the paragraph the way the editor saves an empty line: no hp:t."""

    for run in paragraph.element:
        for child in list(run):
            if _local(child.tag) == "t":
                run.remove(child)


def _template_with_empty_line(path: Path) -> None:
    doc = HwpxDocument.new()
    doc.add_paragraph("1. 추진 배경")
    _strip_text_slot(doc.add_paragraph(""))
    doc.add_paragraph("2. 다음 제목")
    doc.save_to_path(str(path))
    doc.close()


def _template_with_table(path: Path) -> None:
    doc = HwpxDocument.new()
    doc.add_paragraph("1. 추진 배경")
    table = doc.add_table(2, 2)
    for row in range(2):
        for col in range(2):
            table.set_cell_text(row, col, f"칸{row}{col}")
    doc.add_paragraph("2. 다음 제목")
    doc.save_to_path(str(path))
    doc.close()


def _top_level_texts(path: Path) -> list[str]:
    doc = HwpxDocument.open(path)
    try:
        return [p.text or "" for s in doc.sections for p in s.paragraphs]
    finally:
        doc.close()


def _all_text(path: Path) -> str:
    doc = HwpxDocument.open(path)
    try:
        return doc.text.plain()
    finally:
        doc.close()


def test_text_survives_an_empty_line_without_a_text_slot(tmp_path: Path) -> None:
    source, destination = tmp_path / "t.hwpx", tmp_path / "out.hwpx"
    _template_with_empty_line(source)

    result = apply_template_formfit(
        source=source, baseline=_baseline(), content={"body": BODY},
        destination=destination,
    )

    assert result["handoff_status"] == "ready"
    texts = _top_level_texts(destination)
    assert texts[texts.index("1. 추진 배경") + 1] == BODY
    assert "2. 다음 제목" in texts


def test_following_table_is_kept_intact(tmp_path: Path) -> None:
    source, destination = tmp_path / "t.hwpx", tmp_path / "out.hwpx"
    _template_with_table(source)

    result = apply_template_formfit(
        source=source, baseline=_baseline(), content={"body": BODY},
        destination=destination,
    )

    assert result["handoff_status"] == "ready"
    assert result["applied"][0]["removed_placeholders"] == 0
    texts = _top_level_texts(destination)
    assert texts[texts.index("1. 추진 배경") + 1] == BODY
    everything = _all_text(destination)
    for cell in ("칸00", "칸01", "칸10", "칸11"):
        assert cell in everything
    assert everything.count(BODY) == 1


def test_section_properties_paragraph_is_not_cloned(tmp_path: Path) -> None:
    """The anchor may be the first paragraph, which carries section settings."""

    source, destination = tmp_path / "t.hwpx", tmp_path / "out.hwpx"
    doc = HwpxDocument.new()
    first = doc.sections[0].paragraphs[0]
    first.text = "1. 추진 배경"
    doc.add_paragraph("2. 다음 제목")
    doc.save_to_path(str(source))
    doc.close()

    result = apply_template_formfit(
        source=source, baseline=_baseline(), content={"body": BODY},
        destination=destination,
    )

    assert result["handoff_status"] == "ready"
    doc = HwpxDocument.open(destination)
    try:
        sec_pr = [
            node
            for paragraph in doc.sections[0].paragraphs
            for node in paragraph.element.iter()
            if _local(node.tag) == "secPr"
        ]
    finally:
        doc.close()
    assert len(sec_pr) == 1


def test_table_region_keeps_a_following_table(tmp_path: Path) -> None:
    source, destination = tmp_path / "t.hwpx", tmp_path / "out.hwpx"
    _template_with_table(source)

    result = apply_template_formfit(
        source=source,
        baseline=_baseline("table-region"),
        content={"body": [{"월": "3월", "내용": "협의체 구성"}]},
        destination=destination,
    )

    assert result["handoff_status"] == "ready"
    everything = _all_text(destination)
    for cell in ("칸00", "칸11", "3월", "협의체 구성"):
        assert cell in everything


def test_unverified_insert_is_not_reported_as_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, destination = tmp_path / "t.hwpx", tmp_path / "out.hwpx"
    _template_with_empty_line(source)
    real = template_formfit._paragraph_clone_with_text
    monkeypatch.setattr(
        template_formfit,
        "_paragraph_clone_with_text",
        lambda template, text: real(template, ""),
    )

    result = apply_template_formfit(
        source=source, baseline=_baseline(), content={"body": BODY},
        destination=destination,
    )

    assert result["handoff_status"] == "blocked"
    assert result["persisted"] is False
    assert not destination.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_unsupported_target_kind_is_not_reported_as_success(tmp_path: Path) -> None:
    source, destination = tmp_path / "t.hwpx", tmp_path / "out.hwpx"
    _template_with_empty_line(source)

    result = apply_template_formfit(
        analysis={
            "source": {"path": str(source)},
            "destination": {"path": str(destination)},
            "resolved": [{"id": "x", "kind": "mystery", "anchor": "1. 추진 배경"}],
            "unresolved": [],
        }
    )

    assert result["handoff_status"] == "blocked"
    assert not destination.exists()
