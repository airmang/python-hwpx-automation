# SPDX-License-Identifier: Apache-2.0
"""개인정보 검사의 범위와, 가림을 준 경로에서 새던 두 곳 (합성 문서만).

- ``scan_personal_info`` 는 본문·표 칸만 보고 ``total: 0`` 을 돌려주었다. 머리말·꼬리말·
  각주·미주·메모·글상자·숨은 설명·누름틀 안내문·문서 정보·미리 보기 글도 검사하고,
  검사한 자리와 검사하지 않은 자리를 결과에 싣는다.
- ``to_markdown``/``to_html`` 에 ``masking_policy`` 를 주어도 ``notes=True`` 의 각주·미주 글은
  가리지 않았다.
- ``hwpx_extract_json(format_detail=True)`` 의 기본 가림은 런마다 따로 보아, 런에 걸친 값이
  조각으로 나왔다(각주의 ``bodySpans`` 도 같다).

모든 번호·주소는 지어낸 값이다.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from hwpx.document import HwpxDocument
from hwpx.oxml.namespaces import HP
from lxml import etree

from hwpx_automation.markdown import to_html, to_markdown
from hwpx_automation.office.compliance import PIIPolicy, mask_pii
from hwpx_automation.server import hwpx_extract_json, scan_personal_info

# 자리마다 다른 합성 값 (자리 이름 -> 값)
OUTSIDE = {
    "cell": "010-5550-0101",
    "header": "010-5550-0102",
    "footer": "synthetic.user@example.com",
    "footnote": "900101-1234567",
    "endnote": "010-5550-0105",
    "memo": "010-5550-0106",
    "text_box": "010-5550-0107",
    "hidden_comment": "010-5550-0108",
    "field_prompt": "010-5550-0109",
    "form_object": "010-5550-0120",
    "equation": "010-5550-0117",
    "document_info": "010-5550-0110",
    "preview_text": "010-5550-0111",
}


def _add_hidden_comment(paragraph, text: str) -> None:
    """숨은 설명(``hp:hiddenComment``)을 문단에 손으로 단다 (core 에 만드는 API 가 없다)."""

    run = paragraph.element.find(f"{HP}run")
    ctrl = etree.SubElement(run, f"{HP}ctrl")
    hidden = etree.SubElement(ctrl, f"{HP}hiddenComment")
    sub_list = etree.SubElement(
        hidden,
        f"{HP}subList",
        {
            "id": "",
            "textDirection": "HORIZONTAL",
            "lineWrap": "BREAK",
            "vertAlign": "TOP",
            "linkListIDRef": "0",
            "linkListNextIDRef": "0",
            "textWidth": "0",
            "textHeight": "0",
            "hasTextRef": "0",
            "hasNumRef": "0",
        },
    )
    inner = etree.SubElement(
        sub_list,
        f"{HP}p",
        {"id": "0", "paraPrIDRef": "0", "styleIDRef": "0", "pageBreak": "0", "columnBreak": "0", "merged": "0"},
    )
    inner_run = etree.SubElement(inner, f"{HP}run", {"charPrIDRef": "0"})
    etree.SubElement(inner_run, f"{HP}t").text = text


def _outside_only_document(path: Path) -> Path:
    """본문에는 개인정보가 없고, 본문 밖 자리마다 합성 값이 하나씩 있는 문서."""

    doc = HwpxDocument.new(empty_first_line=True)
    doc.add_paragraph("본문에는 개인정보가 없다")
    table = doc.add_table(2, 2)
    table.cell(0, 0).text = "구분"
    table.cell(0, 1).text = "내용"
    inner = table.cell(1, 0).paragraphs[0].add_table(1, 1)
    inner.cell(0, 0).text = f"칸 안 표 {OUTSIDE['cell']}"
    doc.page.set_header(text=f"머리말 담당 {OUTSIDE['header']}")
    doc.page.set_footer(text=f"꼬리말 문의 {OUTSIDE['footer']}")
    doc.notes.add_footnote(f"각주 {OUTSIDE['footnote']}", paragraph=doc.add_paragraph("각주 문단"))
    doc.notes.add_endnote(f"미주 {OUTSIDE['endnote']}", paragraph=doc.add_paragraph("미주 문단"))
    doc.notes.add_memo(f"메모 {OUTSIDE['memo']}", paragraph=doc.add_paragraph("메모 문단"))
    doc.shapes.add_rectangle(paragraph=doc.add_paragraph("상자 문단")).set_draw_text(
        f"글상자 {OUTSIDE['text_box']}"
    )
    _add_hidden_comment(doc.add_paragraph("숨은 설명 문단"), f"숨은 설명 {OUTSIDE['hidden_comment']}")
    doc.sections[0].mark_dirty()
    # 채운 누름틀: 안내문은 문단 글에 없고 누름틀의 속성에만 남는다
    doc.fields.add("신청인", prompt=f"안내 {OUTSIDE['field_prompt']}")
    doc.fields.fill("채운 값", name="신청인")
    doc.fields.add_edit_box(f"입력 상자 {OUTSIDE['form_object']}")
    doc.shapes.add_equation(OUTSIDE["equation"], paragraph=doc.add_paragraph("수식 문단"))
    doc.parts.set_document_metadata(creator=f"작성 {OUTSIDE['document_info']}")
    doc.package.write("Preview/PrvText.txt", f"미리 보기 {OUTSIDE['preview_text']}".encode("utf-8"))
    doc.save(path)
    return path


# --------------------------------------------------------------------------- #
# scan_personal_info: 범위
# --------------------------------------------------------------------------- #


def test_scan_personal_info_reads_every_place_not_only_body_and_cells(tmp_path: Path) -> None:
    report = scan_personal_info(str(_outside_only_document(tmp_path / "outside.hwpx")))

    assert report["total"] == len(OUTSIDE)
    assert {entry["place"]: entry["count"] for entry in report["byPlace"]} == {place: 1 for place in OUTSIDE}
    assert set(OUTSIDE) <= set(report["scanned"])
    assert "body" in report["scanned"]
    # 원본값은 돌려주지 않는다
    blob = json.dumps(report, ensure_ascii=False)
    for value in OUTSIDE.values():
        assert value not in blob


def test_scan_personal_info_names_the_places_it_does_not_scan(tmp_path: Path) -> None:
    report = scan_personal_info(str(_outside_only_document(tmp_path / "outside.hwpx")))

    not_scanned = {entry["place"]: entry["reason"] for entry in report["notScanned"]}
    assert "image_text" in not_scanned  # 그림 속 글은 볼 수 없다
    assert all(reason for reason in not_scanned.values())
    assert not set(not_scanned) & set(report["scanned"])


def test_scan_personal_info_reports_a_preview_text_it_cannot_read(tmp_path: Path) -> None:
    path = tmp_path / "bad-preview.hwpx"
    doc = HwpxDocument.new(empty_first_line=True)
    doc.add_paragraph("본문")
    doc.package.write("Preview/PrvText.txt", bytes([0xFF, 0xFE, 0x00]))  # 어느 인코딩으로도 못 읽는다
    doc.save(path)

    report = scan_personal_info(str(path))

    assert "preview_text" not in report["scanned"]
    assert "preview_text" in {entry["place"] for entry in report["notScanned"]}


def test_scan_personal_info_text_input_says_it_scanned_the_text_only() -> None:
    report = scan_personal_info(text="연락처 010-5550-0112")

    assert report["total"] == 1
    assert report["scanned"] == ["text"]
    assert report["notScanned"] == []
    assert report["byPlace"] == [{"place": "text", "count": 1}]


def test_scan_personal_info_counts_body_and_cells_as_before(tmp_path: Path) -> None:
    path = tmp_path / "body.hwpx"
    doc = HwpxDocument.new(empty_first_line=True)
    doc.add_paragraph("본문 010-5550-0113")
    table = doc.add_table(1, 2)
    table.cell(0, 0).text = "구분"
    table.cell(0, 1).text = "010-5550-0114"
    doc.save(path)

    report = scan_personal_info(str(path))

    assert report["total"] == 2
    assert {entry["place"]: entry["count"] for entry in report["byPlace"]} == {"body": 1, "cell": 1}
    assert report["byType"][0]["type"] == "phone" and report["byType"][0]["count"] == 2


def test_scan_personal_info_counts_a_field_prompt_once(tmp_path: Path) -> None:
    """빈 누름틀의 안내문은 문단 글로 보이므로 본문에서 한 번만 세고, 도움말은 누름틀에서 센다."""

    path = tmp_path / "fields.hwpx"
    doc = HwpxDocument.new(empty_first_line=True)
    doc.fields.add("빈 칸", prompt="안내 010-5550-0115", memo="도움말 010-5550-0116")
    doc.save(path)

    report = scan_personal_info(str(path))

    assert {entry["place"]: entry["count"] for entry in report["byPlace"]} == {"body": 1, "field_prompt": 1}
    assert report["total"] == 2


def test_scan_personal_info_reads_ruby_text_with_its_paragraph(tmp_path: Path) -> None:
    """덧말을 단 글(본말·덧말)은 문단 글에 들지 않는다: 그 문단의 자리에서 함께 센다."""

    path = tmp_path / "ruby.hwpx"
    doc = HwpxDocument.new(empty_first_line=True)
    doc.shapes.add_ruby("본말 010-5550-0118", "덧말 010-5550-0119", paragraph=doc.add_paragraph("덧말 문단 "))
    doc.save(path)

    report = scan_personal_info(str(path))

    assert report["byPlace"] == [{"place": "body", "count": 2}]


def test_scan_personal_info_says_what_an_hwp_source_left_out(tmp_path: Path, monkeypatch) -> None:
    from hwpx_automation.handlers import specialized

    path = tmp_path / "body.hwpx"
    doc = HwpxDocument.new(empty_first_line=True)
    doc.add_paragraph("본문")
    doc.save(path)
    monkeypatch.setattr(
        specialized,
        "hwp5_conversion_report",
        lambda document: {"unconverted": {"ole": 1}, "dropped": {"script": 2}},
    )

    not_scanned = {entry["place"]: entry["reason"] for entry in scan_personal_info(str(path))["notScanned"]}

    assert "ole" in not_scanned["hwp_unconverted"] and "script" in not_scanned["hwp_unconverted"]


# --------------------------------------------------------------------------- #
# to_markdown / to_html: masking_policy 와 각주·미주
# --------------------------------------------------------------------------- #


def _mask_with_x(text: str) -> str:
    """Markdown 이 이스케이프하지 않는 글자로 가린다 (가린 곳을 세기 쉽게)."""

    return mask_pii(text, PIIPolicy(mask_char="X"))


def _notes_document() -> HwpxDocument:
    doc = HwpxDocument.new(empty_first_line=True)
    doc.add_paragraph("본문 010-5550-0121")
    doc.notes.add_footnote("각주 010-5550-0122", paragraph=doc.add_paragraph("각주 문단"))
    doc.notes.add_endnote("미주 010-5550-0123", paragraph=doc.add_paragraph("미주 문단"))
    return doc


@pytest.mark.parametrize("export", [to_markdown, to_html], ids=["markdown", "html"])
@pytest.mark.parametrize("notes", [True, "inline"], ids=["deferred", "inline"])
def test_masking_policy_covers_note_text(export, notes) -> None:
    out = export(_notes_document(), masking_policy=_mask_with_x, notes=notes)

    assert "각주" in out and "미주" in out  # 각주·미주 글은 나온다
    for raw in ("010-5550-0121", "010-5550-0122", "010-5550-0123"):
        assert raw not in out
    assert out.count("010-XXXX-XXXX") == 3


@pytest.mark.parametrize("export", [to_markdown, to_html], ids=["markdown", "html"])
def test_notes_without_masking_policy_stay_as_written(export) -> None:
    out = export(_notes_document(), notes=True)

    assert "010-5550-0122" in out and "010-5550-0123" in out


# --------------------------------------------------------------------------- #
# hwpx_extract_json(format_detail=True): 런에 걸친 값
# --------------------------------------------------------------------------- #


def _split_run_payload() -> str:
    doc = HwpxDocument.new(empty_first_line=True)
    paragraph = doc.add_paragraph("연락처 010-5550-")
    paragraph.add_run("0131 끝", bold=True)
    note = doc.notes.add_footnote("각주 010-5550-", paragraph=doc.add_paragraph("각주 문단"))
    note.body_paragraph.add_run("0132 끝", bold=True)
    return base64.b64encode(doc.to_bytes()).decode()


def _runs_of(result: dict, needle: str) -> list[dict]:
    sections = result["doc"]["sections"] if "doc" in result else [c["section"] for c in result["chunks"]]
    for section in sections:
        for paragraph in section["paragraphs"]:
            if needle in paragraph["text"]:
                return paragraph["format"]["runs"]
    raise AssertionError(f"no paragraph with {needle!r}")


def test_extract_json_format_detail_masks_a_value_split_across_runs() -> None:
    result = hwpx_extract_json(hwpx_base64=_split_run_payload(), format_detail=True, output="chunks")

    blob = json.dumps(result, ensure_ascii=False)
    for fragment in ("010-5550-", "0131", "0132"):
        assert fragment not in blob
    for runs in (_runs_of(result, "연락처"), _runs_of({"chunks": result["chunks"]}, "연락처")):
        assert "".join(run["text"] for run in runs) == "연락처 010-****-**** 끝"
        assert [run["bold"] for run in runs] == [False, True]  # 런과 그 서식은 그대로 실린다
    note = result["doc"]["notes"][0]
    assert note["bodyText"] == "각주 010-****-**** 끝"
    assert "".join(span["text"] for span in note["bodySpans"]) == note["bodyText"]
    assert [span["bold"] for span in note["bodySpans"]] == [False, True]


def test_extract_json_format_detail_mask_off_returns_the_runs_as_written() -> None:
    result = hwpx_extract_json(hwpx_base64=_split_run_payload(), format_detail=True, mask=False)

    assert [run["text"] for run in _runs_of(result, "연락처")] == ["연락처 010-5550-", "0131 끝"]
    assert [span["text"] for span in result["doc"]["notes"][0]["bodySpans"]] == ["각주 010-5550-", "0132 끝"]
