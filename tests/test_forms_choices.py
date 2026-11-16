# SPDX-License-Identifier: Apache-2.0
"""Choices typed as check marks: listing the groups and checking options.

Moved with the code from python-hwpx (tests/test_form_choices.py and
tests/test_form_choices_prose.py; ``doc.fields.choices()`` / ``choose()`` became
``form_choices(doc)`` / ``choose(doc, ...)``).
"""

from __future__ import annotations

import io

from hwpx import HwpxDocument
from hwpx_automation.forms import choose, form_choices


def _form() -> HwpxDocument:
    doc = HwpxDocument.new(empty_first_line=True)
    doc.add_paragraph("○ 추진 배경")
    doc.add_paragraph("□ 세부 계획은 붙임과 같다")
    doc.add_paragraph("참석 여부: □ 예  □ 아니오")
    table = doc.add_table(4, 2)
    rows = [
        ("성  별", "☐ 남   ☑ 여"),
        ("신청 구분", "○ 신규, ● 변경, ○ 해지"),
        ("동의", "□   □"),
        ("비고", "해당 없음"),
    ]
    for row, (label, value) in zip(table.rows, rows):
        row.cells[0].paragraphs[0].text = label
        row.cells[1].paragraphs[0].text = value
    return doc


def _reopened(doc: HwpxDocument) -> HwpxDocument:
    buffer = io.BytesIO()
    doc.save_to_stream(buffer)
    return HwpxDocument.open(buffer.getvalue())


def test_a_single_leading_mark_is_a_bullet_not_a_choice() -> None:
    listed = form_choices(_form())
    assert listed["count"] == 4
    assert [group["path"] for group in listed["choices"]] == ["참석 여부", "성 별", "신청 구분", "동의"]


def test_a_group_lists_its_options_and_where_it_is() -> None:
    groups = {group["path"]: group for group in form_choices(_form())["choices"]}
    assert "paragraph_index" in groups["참석 여부"]
    assert (groups["성 별"]["table_index"], groups["성 별"]["row"], groups["성 별"]["col"]) == (0, 0, 1)
    assert groups["성 별"]["options"] == [
        {"position": 1, "text": "남", "checked": False, "mark": "☐"},
        {"position": 2, "text": "여", "checked": True, "mark": "☑"},
    ]
    assert [option["text"] for option in groups["신청 구분"]["options"]] == ["신규", "변경", "해지"]
    assert [option["text"] for option in groups["동의"]["options"]] == ["", ""]


def test_choosing_checks_the_option_and_unchecks_the_others() -> None:
    doc = _form()
    result = choose(doc, {"참석여부": "예", "성별": "남", "신청 구분": ["신규", 3], "동의": 2})
    assert result["failed"] == []
    assert [entry["changed"] for entry in result["applied"]] == [1, 2, 3, 1]
    text = _reopened(doc).text.plain()
    assert "참석 여부: ■ 예  □ 아니오" in text
    assert "☑ 남   ☐ 여" in text  # the group's own marks
    assert "● 신규, ○ 변경, ● 해지" in text
    assert "□   ■" in text
    assert "○ 추진 배경" in text and "□ 세부 계획은 붙임과 같다" in text


def test_an_empty_list_clears_the_group_and_a_repeat_changes_nothing() -> None:
    doc = _form()
    assert choose(doc, {"성별": []})["applied"][0]["changed"] == 1
    assert "☐ 남   ☐ 여" in doc.text.plain()
    assert choose(doc, {"성별": []})["applied"][0]["changed"] == 0


def test_what_cannot_be_told_apart_is_left_alone() -> None:
    doc = _form()
    before = doc.text.plain()
    result = choose(doc, {"없는 묶음": "예", "성별": "중", "동의": 3, "신청 구분": 1.5, "#9": 1})  # type: ignore[dict-item]
    assert result["applied"] == []
    reasons = {entry["path"]: entry for entry in result["failed"]}
    assert reasons["없는 묶음"]["reason"] == "choice group not found"
    assert reasons["없는 묶음"]["candidates"] == ["참석 여부", "성 별", "신청 구분", "동의"]
    assert reasons["성별"] == {"path": "성별", "reason": "option not found", "options": ["남", "여"]}
    assert reasons["동의"]["reason"] == "option position out of range: 3 of 2"
    assert "selection must be" in reasons["신청 구분"]["reason"]
    assert reasons["#9"]["reason"] == "no choice group #9 (there are 4)"
    assert doc.text.plain() == before


def test_groups_with_one_label_are_numbered_and_unnamed_ones_go_by_position() -> None:
    doc = HwpxDocument.new(empty_first_line=True)
    doc.add_paragraph("□ 가  □ 나")
    doc.add_paragraph("선택: □ 가  □ 나")
    doc.add_paragraph("선택: □ 다  □ 라")
    paths = [group["path"] for group in form_choices(doc)["choices"]]
    assert paths == ["#1", "선택[1]", "선택[2]"]

    ambiguous = choose(doc, {"선택": "가"})
    assert ambiguous["failed"] == [
        {"path": "선택", "reason": "ambiguous label", "candidates": ["선택[1]", "선택[2]"]}
    ]
    assert choose(doc, {"#1": "나", "선택[2]": "다"})["failed_count"] == 0
    assert doc.text.plain().splitlines()[-3:] == ["□ 가  ■ 나", "선택: □ 가  □ 나", "선택: ■ 다  □ 라"]


def test_the_checked_mark_follows_the_documents_habit() -> None:
    doc = HwpxDocument.new(empty_first_line=True)
    doc.add_paragraph("가: □ 하나  ▣ 둘")
    doc.add_paragraph("나: □ 셋  □ 넷")
    choose(doc, {"나": "셋"})
    assert "나: ▣ 셋  □ 넷" in doc.text.plain()


def test_a_label_can_sit_on_the_line_above_or_in_the_cell_above() -> None:
    doc = HwpxDocument.new(empty_first_line=True)
    table = doc.add_table(2, 2)
    table.rows[0].cells[0].paragraphs[0].text = "수령 방법"
    table.rows[1].cells[0].paragraphs[0].text = "□ 방문  □ 우편"
    cell = table.rows[0].cells[1]
    cell.paragraphs[0].text = "결제 수단"
    cell.add_paragraph("□ 카드  □ 현금")
    paths = [group["path"] for group in form_choices(doc)["choices"]]
    assert paths == ["결제 수단", "수령 방법"]


def test_marks_split_over_runs_are_still_one_group() -> None:
    doc = HwpxDocument.new(empty_first_line=True)
    paragraph = doc.add_paragraph("구분: □ 갑")
    paragraph.add_run("  □ 을", bold=True)
    choose(doc, {"구분": "을"})
    assert _reopened(doc).text.plain().endswith("구분: □ 갑  ■ 을")
    assert len(list(paragraph.runs)) == 2


def test_marks_side_by_side_are_not_choices() -> None:
    doc = HwpxDocument.new(empty_first_line=True)
    doc.add_paragraph("○○고등학교 김○○ 교사")
    doc.add_paragraph("주민등록번호 □□□□□□-□□□□□□□")
    doc.add_paragraph("구분: □ 갑  □ 을 (○○과 제출)")
    listed = form_choices(doc)
    assert [group["path"] for group in listed["choices"]] == ["구분"]
    assert [option["text"] for option in listed["choices"][0]["options"]] == ["갑", "을 (○○과 제출)"]


def test_choosing_in_a_cell_drops_the_line_cache_and_marks_the_document_changed() -> None:
    doc = _form()
    cell_paragraph = doc.tables[0].cell(0, 1).paragraphs[0]
    cell_paragraph.element.append(
        cell_paragraph.element.makeelement("{http://www.hancom.co.kr/hwpml/2011/paragraph}linesegarray", {})
    )
    doc.sections[0].reset_dirty()

    choose(doc, {"성별": "남"})

    assert cell_paragraph.element.find("{http://www.hancom.co.kr/hwpml/2011/paragraph}linesegarray") is None
    assert doc.sections[0].dirty


# --- from tests/test_form_choices_prose.py ------------------------------------


def _labels(*lines: str) -> list[list[str]]:
    doc = HwpxDocument.new()
    for line in lines:
        doc.add_paragraph(line)
    return [[option["text"] for option in group["options"]] for group in form_choices(doc)["choices"]]


def test_a_mark_alone_in_brackets_is_not_an_option() -> None:
    assert _labels("(예시) 200,000천원(○), 170,000천원(○), 136,000천원( ○ )") == []
    assert _labels("<예시> 오후 3시 20분(×) → 15:20(○), 오전 7시 9분(×) → 07:09(○)") == []


def test_marks_between_long_clauses_are_prose() -> None:
    line = (
        "a) ○ 성년이고 승낙능력이 있으며 ○ 법에 규정된 적출에 관한 정보를 받았고 적출에 승낙했으며 "
        "○ 의사가 판단할 때 기증자로서 적합하고 수술위험 이외의 위험이 발생하지 않는 경우"
    )
    assert _labels(line) == []


def test_real_choices_are_still_groups() -> None:
    assert _labels(
        "참석 여부: □ 예  □ 아니오",
        "평가 방법: ☐ 교사 관찰 및 기록 ☐ 자기평가 ☐ 동료평가",
        "□ 개인정보 수집·이용에 동의합니다  □ 동의하지 않습니다",
        "구분: ○ 신규 ( ) ○ 변경",
    ) == [
        ["예", "아니오"],
        ["교사 관찰 및 기록", "자기평가", "동료평가"],
        ["개인정보 수집·이용에 동의합니다", "동의하지 않습니다"],
        ["신규 ( )", "변경"],
    ]
