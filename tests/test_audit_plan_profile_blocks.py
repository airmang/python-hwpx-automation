# SPDX-License-Identifier: Apache-2.0
"""Audit ENG-18: the design-profile route carries every plan block.

With ``metadata.document_type`` set (공문/보고서/가정통신문) the plan is lowered
onto a harvested profile. That route used to drop ``page_break`` and ``memo``
blocks (memo body text included) and wrote ``"\n"`` raw into ``hp:t`` while the
response said ``created: true`` / ``quality.pass: true``.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from hwpx import HwpxDocument

from hwpx_automation.office import authoring
from hwpx_automation.office.authoring.design import _support
from hwpx_automation.server import create_document_from_plan
from lxml import etree

_HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def _plan(doc_type: str | None) -> dict:
    plan = {
        "schemaVersion": "hwpx.document_plan.v1",
        "title": "점검용 계획 문서",
        "blocks": [
            {"type": "heading", "level": 1, "text": "1. 개요 H1MARK"},
            {"type": "paragraph", "text": "첫줄 P1MARK\n둘째줄 P1B"},
            {"type": "bullets", "items": ["글머리 하나 B1MARK", "글머리 둘 B2MARK"]},
            {"type": "page_break"},
            {"type": "memo", "text": "메모가 붙는 문단 MEMOTEXT", "memo": "메모 내용 MEMOMARK"},
            {"type": "heading", "level": 2, "text": "가. 세부 H2MARK"},
            {
                "type": "table",
                "columns": [{"key": "item", "label": "항목"}, {"key": "value", "label": "값"}],
                "rows": [{"item": "예산 T1MARK", "value": "100"}],
            },
            {"type": "paragraph", "text": "끝 문단 P2MARK"},
        ],
    }
    if doc_type:
        plan["metadata"] = {"document_type": doc_type}
    return plan


def _section_xml(path: Path) -> str:
    with zipfile.ZipFile(io.BytesIO(path.read_bytes())) as archive:
        return archive.read("Contents/section0.xml").decode("utf-8")


@pytest.mark.parametrize("doc_type", ["보고서", "공문", "가정통신문"])
def test_profile_route_carries_page_break_memo_and_line_break(tmp_path: Path, doc_type: str) -> None:
    if authoring._resolve_design_profile(_plan(doc_type)) is None:
        pytest.skip(f"no committed design profile for {doc_type}")
    target = tmp_path / "plan.hwpx"
    plan = _plan(doc_type)
    has_table = doc_type != "가정통신문"  # that profile has no table fragment and refuses one
    if not has_table:
        plan["blocks"] = [block for block in plan["blocks"] if block["type"] != "table"]

    result = create_document_from_plan(str(target), plan, verbosity="full")

    assert result["created"] is True, result
    xml = _section_xml(target)
    for mark in ("H1MARK", "P1MARK", "P1B", "B1MARK", "B2MARK", "MEMOTEXT", "H2MARK", "T1MARK", "P2MARK"):
        if mark == "T1MARK" and not has_table:
            continue
        assert mark in xml, mark
    # "\n" is an hp:lineBreak element, never a raw LF inside hp:t.
    root = etree.fromstring(xml.encode("utf-8"))
    holder = next(t for t in root.iter(_HP + "t") if "P1MARK" in "".join(t.itertext()))
    assert "\n" not in "".join(holder.itertext())
    assert [child.tag for child in holder] == [_HP + "lineBreak"]
    doc = HwpxDocument.open(str(target))
    try:
        paragraphs = doc.paragraphs
        breaks = [p for p in paragraphs if p.element.get("pageBreak") == "1"]
        assert len(breaks) == 1
        assert "MEMOTEXT" in (breaks[0].text or "")  # the block after the page_break starts the page
        memos = list(doc.notes.memos)
        assert len(memos) == 1
        assert "MEMOMARK" in (memos[0].text or "")
    finally:
        doc.close()
    assert not [gap for gap in result["quality"]["gaps"] if "not carried" in gap]


def test_quality_reports_plan_blocks_that_were_not_carried(tmp_path: Path) -> None:
    """A document missing the plan's page break / memo is a reported gap."""

    target = tmp_path / "bare.hwpx"
    doc = HwpxDocument.new()
    doc.add_paragraph("1. 개요 H1MARK")
    doc.save_to_path(str(target))
    doc.close()

    report = authoring.inspect_document_authoring_quality(target, plan=_plan(None))

    assert report["pass"] is False
    assert any("not carried: page_break" in gap for gap in report["gaps"])
    assert any("not carried: memo" in gap for gap in report["gaps"])


def test_general_route_has_no_carry_gap(tmp_path: Path) -> None:
    target = tmp_path / "general.hwpx"
    result = create_document_from_plan(str(target), _plan(None), verbosity="full")
    assert result["created"] is True
    assert not [gap for gap in result["quality"]["gaps"] if "not carried" in gap]


def test_bridge_refuses_a_block_type_it_cannot_place() -> None:
    plan = {"blocks": [{"type": "hologram", "text": "x"}]}
    with pytest.raises(ValueError, match="cannot place"):
        authoring._bridge_to_design_plan(plan, "report")


def test_set_paragraph_text_writes_marks_and_drops_control_characters() -> None:
    paragraph = etree.fromstring(
        f'<hp:p xmlns:hp="{_HP[1:-1]}"><hp:run charPrIDRef="3"><hp:t>old<hp:tab/>x</hp:t></hp:run>'
        "<hp:linesegarray/></hp:p>"
    )
    _support.set_paragraph_text(paragraph, "가\x01나\n다\t라\x0b")
    text = paragraph.find(f".//{_HP}t")
    assert text.text == "가나"
    assert [(c.tag.rsplit("}", 1)[-1], c.tail) for c in text] == [("lineBreak", "다"), ("tab", "라")]
    assert paragraph.find(_HP + "linesegarray") is None
    assert paragraph.find(_HP + "run").get("charPrIDRef") == "3"
