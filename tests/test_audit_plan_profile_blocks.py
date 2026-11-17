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

    result = create_document_from_plan(str(target), plan, verbosity="full")

    assert result["created"] is True, result
    # 가정통신문 has no table fragment: the table is written as a plain table, and the result says so.
    if doc_type == "가정통신문":
        assert any(w.startswith("PROFILE_TABLE_FALLBACK") for w in result["warnings"]), result
    else:  # the 2-column table fits the fragment's grid (its spare column is named, not a fallback)
        assert not any(w.startswith("PROFILE_TABLE_FALLBACK") for w in result.get("warnings", []))
    xml = _section_xml(target)
    for mark in ("H1MARK", "P1MARK", "P1B", "B1MARK", "B2MARK", "MEMOTEXT", "H2MARK", "T1MARK", "P2MARK"):
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
    doc.save(str(target))
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


def test_official_draft_blocks_compose_on_the_official_profile(tmp_path: Path) -> None:
    """compose_official_draft's 결재란 (4 columns) and 결문 table (no header row) used to stop the
    공문 profile with TABLE_COLUMN_MISMATCH; they are now written whole, the 결재란 as a plain table."""

    from hwpx_automation.server import compose_official_draft

    draft = getattr(compose_official_draft, "fn", compose_official_draft)(
        {
            "agency": "가상기관",
            "subject": "점검 안내",
            "recipient": "각 부서장",
            "body": ["점검을 합니다."],
            "sender": "가상기관장",
            "approvers": [{"position": "담당", "name": "가"}, {"position": "과장", "name": "나", "mark": "전결"}],
            "issued": "총무-1(2031. 1. 2.)",
        }
    )
    plan = {
        "schemaVersion": "hwpx.document_plan.v1",
        "title": "점검 안내",
        "metadata": {"document_type": "공문"},
        "blocks": draft["blocks"],
    }
    target = tmp_path / "draft.hwpx"
    result = create_document_from_plan(str(target), plan, verbosity="full")

    assert result["created"] is True, result
    assert any("4칸" in w for w in result["warnings"])
    with HwpxDocument.open(str(target)) as doc:
        tables = [table for paragraph in doc.paragraphs for table in paragraph.tables]
        texts = [[cell.text for cell in row.cells] for table in tables for row in table.rows]
    assert ["담당", "가", "과장", "전결\n나"] in texts  # the 결재란, all four cells
    assert not any("직위0" in cell or "구분" == cell for row in texts for cell in row)  # no label rows


def test_official_plan_metadata_fills_the_dumun_and_gyeolmun(tmp_path: Path) -> None:
    plan = {
        "schemaVersion": "hwpx.document_plan.v1",
        "title": "휴관 안내",
        "metadata": {"document_type": "공문", "수신": "각 부서장", "발신": "가상도서관장", "시행": "자료-1(2031. 1. 2.)"},
        "blocks": [{"type": "paragraph", "text": "휴관합니다.  끝."}],
    }
    target = tmp_path / "gongmun.hwpx"
    result = create_document_from_plan(str(target), plan, verbosity="full")

    with HwpxDocument.open(str(target)) as doc:
        texts = [paragraph.text for paragraph in doc.paragraphs if paragraph.text]
    assert texts[:3] == ["휴관 안내", "수신  각 부서장", "휴관합니다.  끝."]
    assert "발신명의  가상도서관장" in texts and "시행일  자료-1(2031. 1. 2.)" in texts
    # 공개구분 is still missing: the gate says so and points at the 일반기안문 tool.
    assert result["quality"]["gongmun_structure"]["structure_pass"] is False
    assert "compose_official_draft" in result["next_action"]


@pytest.mark.parametrize("doc_type", [None, "공문"])
def test_title_is_not_printed_twice_when_a_block_carries_it(tmp_path: Path, doc_type: str | None) -> None:
    plan = {
        "schemaVersion": "hwpx.document_plan.v1",
        "title": "점검 안내",
        "blocks": [{"type": "paragraph", "text": "가상기관"}, {"type": "paragraph", "text": "제목  점검 안내"}],
    }
    if doc_type:
        plan["metadata"] = {"document_type": doc_type}
    target = tmp_path / "title.hwpx"
    create_document_from_plan(str(target), plan)
    with HwpxDocument.open(str(target)) as doc:
        texts = [paragraph.text for paragraph in doc.paragraphs if paragraph.text]
    assert texts[:2] == ["가상기관", "제목  점검 안내"]
