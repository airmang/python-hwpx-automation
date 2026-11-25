# SPDX-License-Identifier: Apache-2.0
"""평가계획 fill: a subject with a 정기시험 share keeps its exam column (#202), and the
clean phase leaves no ``(**)`` legend or ``ex)`` example lines in the AI box (#205).

Synthetic review markdown only, on the repository's blank-form fixtures.
"""

from __future__ import annotations

import html
import io
import re
import zipfile
from pathlib import Path

import pytest

from hwpx_automation.office.evalplan import (
    fill_evalplan,
    parse_review_md,
    plan_structural_ops,
)
from hwpx_automation.office.form_fill.classification import _classify, _tables
from hwpx_automation.office.form_fill.quality import score_compliance, score_content

FIXTURES = Path(__file__).parent / "fixtures" / "m105_evalplan"
BLANK_12 = FIXTURES / "blank_form_1-2hak.hwpx"
BLANK_3 = FIXTURES / "blank_form_3hak.hwpx"
BLANKS = [pytest.param(BLANK_12, id="1-2hak"), pytest.param(BLANK_3, id="3hak")]

pytestmark = pytest.mark.skipif(
    not (BLANK_12.is_file() and BLANK_3.is_file()), reason="evaluation-plan fixtures unavailable"
)

EXAM_S6 = """### 6. 평가의 종류와 반영비율

| 평가 종류 | 정기시험 | 수행평가 |  | 합계 |
|---|---|---|---|---|
| 반영 비율 | 30% | 70% |  | 100% |
| 시기/영역 | 2차 | 영역 가 | 영역 나 |  |
| 시기/영역 | 선택형 | 영역 가 | 영역 나 |  |
| 영역 만점<br>(반영 비율) | 100점<br>(30%) | 50점<br>(35%) | 50점<br>(35%) | 100% |
| 평가 시기 | 12월 3주 | 10월 4주 | 11월 2주 |  |
| 성취기준 | [12합성01-01] | [12합성01-01] | [12합성01-02] |  |
"""

PERF_ONLY_S6 = """### 6. 평가의 종류와 반영비율

| 구분 | ① 영역 가 | ② 영역 나 | 합계 |
|---|---|---|---|
| 영역 만점 | 60점(60%) | 40점(40%) | 100% |
"""

AI_S10 = """### 10. 평가 유의사항
- AI를 활용하여 합성 과제의 답안을 그대로 만들어 제출하는 행위는 금지되며 적발 시 부정행위로 간주함.
"""

PLAIN_S10 = """### 10. 평가 유의사항
- 합성 유의 문장.
"""


def _md(s6: str, s10: str) -> str:
    return f"""# 2026학년도 2학기 2학년 「합성과목」 교수학습운영 및 평가계획

> 담당교사: 홍길동

## Ⅰ. 교수학습 운영 계획

| 월 | 주 | 단원명(영역명) | (교육과정) 성취기준 | 수업방법 | 수업-평가 연계의 주안점 |
|---|---|---|---|---|---|
| 9 | 1 | Ⅰ. 단원 가 | [12합성01-01] 합성 성취기준 문장. | 강의 | 합성 주안점 |
| 12 | 3 | Ⅱ. 단원 나 | [12합성01-02] 합성 성취기준 문장. | ★2차 정기시험 | |

## Ⅱ. 평가 세부 계획

### 1. 평가의 목적
가. 합성 목적 문장.

### 2. 평가의 기본 방향
가. 합성 방향 문장.

### 3. 평가 방침
가. 합성 방침 문장.

### 4. 성취기준 및 성취수준
**가. 교육과정 성취기준·평가기준**

| 성취기준 | 상 | 중 | 하 |
|---|---|---|---|
| [12합성01-01] 합성 표준 | 상1 | 중1 | 하1 |

### 5. 기준 성취율과 성취도

| 성취율(원점수) | 성취도 |
|---|---|
| 90% 이상 | A |
| 80% 이상 ~ 90% 미만 | B |
| 70% 이상 ~ 80% 미만 | C |
| 60% 이상 ~ 70% 미만 | D |
| 60% 미만 | E |

{s6}
### 8. 정의적 능력 평가
- 인지적 측면(합성): 설명.

### 9. 수행평가 미응시자
가. 합성 처리.

{s10}
### 11. 평가 결과 분석 및 활용
- 합성 활용.
"""


def _ratio_rows(data: bytes) -> list[list[str]]:
    table = next(t for t in _tables(data) if _classify(t) == "ratio")
    from hwpx.table_patch import build_grid, table_text

    grid, rep = build_grid(table.bytes)
    rows = []
    for r in range(rep.row_count):
        row = []
        for c in range(rep.col_count):
            cell = grid.get((r, c))
            row.append(table_text(table.bytes[cell.start:cell.end]).strip() if cell else "")
        rows.append(row)
    return rows


def _row(rows: list[list[str]], label: str, nth: int = 0) -> list[str]:
    hits = [r for r in rows if r[0].replace(" ", "").startswith(label)]
    return hits[nth]


def _paragraph_texts(data: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        sec = archive.read("Contents/section0.xml").decode("utf-8")
    out = []
    for block in re.findall(r"<hp:p[ >].*?</hp:p>", sec, re.DOTALL):
        text = "".join(re.findall(r"<hp:t(?:\s[^>]*)?>(.*?)</hp:t>", block, re.DOTALL))
        out.append(html.unescape(re.sub(r"<[^>]+>", "", text)))
    return out


# --------------------------------------------------------------------------- #202


@pytest.mark.parametrize(
    ("blank", "drop", "keep"),
    [pytest.param(BLANK_12, [2, 3, 5], [4], id="1-2hak"), pytest.param(BLANK_3, [2], [1], id="3hak")],
)
def test_exam_subject_keeps_the_exam_column_it_names(blank: Path, drop: list[int], keep: list[int]) -> None:
    plan = plan_structural_ops(blank, parse_review_md(_md(EXAM_S6, PLAIN_S10)))
    column_ops = [op for op in plan["ops"] if op["op"] == "delete_column"]
    assert [op["cols"] for op in column_ops] == [drop]
    assert any(f"keep cols {keep}" in line for line in plan["transcript"])
    assert not any("100% 수행" in line for line in plan["transcript"])


@pytest.mark.parametrize("blank", BLANKS)
def test_performance_only_subject_still_drops_every_exam_column(blank: Path) -> None:
    plan = plan_structural_ops(blank, parse_review_md(_md(PERF_ONLY_S6, PLAIN_S10)))
    (column_op,) = [op for op in plan["ops"] if op["op"] == "delete_column"]
    assert any("100% 수행 subject" in line for line in plan["transcript"])
    assert len(column_op["cols"]) in (2, 4)


@pytest.mark.parametrize("blank", BLANKS)
def test_exam_subject_ratio_table_carries_the_md_shares(blank: Path) -> None:
    md = _md(EXAM_S6, PLAIN_S10)
    result = fill_evalplan(blank, parse_review_md(md), phase="all")
    assert result["content_report"]["ratio"]["skipped"] == []
    rows = _ratio_rows(result["_data"])
    head = rows[0]
    assert "정기시험" in head and "수행평가" in head

    exam = head.index("정기시험")
    perf = head.index("수행평가")
    share = _row(rows, "반영비율")
    assert (share[exam], share[perf], share[-1]) == ("30%", "70%", "100%")

    period, kind = _row(rows, "시기/영역", 0), _row(rows, "시기/영역", 1)
    assert (period[exam], kind[exam]) == ("2차", "선택형")
    assert period[perf:perf + 2] == ["영역 가", "영역 나"]
    assert not any("정기시험" in cell for row in rows[1:] for cell in row)

    full = _row(rows, "영역만점")
    assert full[exam].replace("\n", "") == "100점(30%)"
    assert _row(rows, "평가시기")[exam] == "12월 3주"
    assert _row(rows, "성취기준")[exam] == "[12합성01-01]"


@pytest.mark.parametrize("blank", BLANKS)
def test_scorer_sees_the_md_shares_and_accepts_the_kept_exam_column(blank: Path, tmp_path: Path) -> None:
    md = _md(EXAM_S6, PLAIN_S10)
    out = tmp_path / "out.hwpx"
    fill_evalplan(blank, parse_review_md(md), phase="clean", output=str(out))

    content = score_content(out, content=md, blank=blank)
    assert not any("SAMPLE percentages" in f for f in content.findings)
    compliance = score_compliance(out, content=md)
    assert not any("정기시험" in f for f in compliance.findings)
    # without the review MD the lint keeps its 수행평가-only rule
    assert any("정기시험" in f for f in score_compliance(out).findings)


# --------------------------------------------------------------------------- #205


@pytest.mark.parametrize("blank", BLANKS)
def test_clean_fills_the_ai_slot_and_drops_its_legend_and_examples(blank: Path) -> None:
    result = fill_evalplan(blank, parse_review_md(_md(PERF_ONLY_S6, AI_S10)), phase="clean")
    finalize = result["content_report"]["finalize"]
    texts = _paragraph_texts(result["_data"])

    assert not any("(**)" in t for t in texts)
    assert not any(t.strip().startswith("ex)") for t in texts)
    filled = [t for t in texts if "AI를 활용하여 합성 과제의 답안을 그대로 만들어 제출하는 행위" in t]
    assert len(filled) == 1
    assert finalize["ai_slot_filled"] is True
    assert finalize["placeholder_lines_deleted"] == 3
    assert finalize["placeholders_left"] == []


@pytest.mark.parametrize("blank", BLANKS)
def test_clean_reports_the_ai_slot_when_the_md_gives_no_text(blank: Path) -> None:
    result = fill_evalplan(blank, parse_review_md(_md(PERF_ONLY_S6, PLAIN_S10)), phase="clean")
    finalize = result["content_report"]["finalize"]
    texts = _paragraph_texts(result["_data"])

    # the slot sentence stays (with its mark); the legend and example lines do not
    assert sum("(**)" in t for t in texts) == 1
    assert not any(t.strip().startswith("ex)") for t in texts)
    assert finalize.get("ai_slot_filled") is False
    assert finalize.get("placeholder_lines_deleted") == 3
    assert len(finalize.get("placeholders_left", [])) == 1
    assert "(**)" in finalize["placeholders_left"][0]
