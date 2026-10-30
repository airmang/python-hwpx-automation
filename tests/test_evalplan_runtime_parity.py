# SPDX-License-Identifier: Apache-2.0
"""Behavior parity between the automation owner and the frozen core 4.x copy.

``hwpx.evalplan_fill`` is gone from core as of python-hwpx 5.0. Structural
claims (exports, signatures, dataclass fields) compare the live automation module's
``tests.parity_fingerprint.fingerprint()`` against
``tests/parity_fingerprints/evalplan.json``. ``RubricItem``/``RubricSubArea``
are reachable module attributes but not in ``__all__`` (``Rubric.items``
holds a list of ``RubricItem``; ``RubricSubArea`` composes it) — the
pre-freeze version of this file checked their dataclass shape explicitly by
name, so this one does too, via the same ``parity_fingerprint._describe_class``
the fingerprint module itself uses. Behavioural claims (parsing, skeleton
projection, structural-ops planning, and the fill/finalize byte output) compare
against ``tests/parity_fingerprints/evalplan.golden.json``. Both were captured
from a scratch git worktree at the commit before removal (see
``scripts/freeze_parity_fingerprints.py --historical``) rather than a live
``hwpx.evalplan_fill`` import.

The filled document's raw bytes (``result["_data"]``) can't live in JSON —
the golden records their SHA-256 and length instead, the same tradeoff
``test_exam_runtime_parity.py`` made for its composed output.

The historical API, plan and report captures remain exact. Output bytes after
core's structural-height synchronization (#539) have a separate, explicitly
attributed capture; the historical golden file remains unchanged. This checks
application migration parity and does not approve rendered layout.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import hwpx
import pytest

import parity_fingerprint
from parity_fingerprint import fingerprint

from hwpx_automation.office.evalplan import runtime as canonical

SYNTHETIC_MD = """# 2026학년도 2학기 3학년 「합성 과목」 교수학습운영 및 평가계획

> **담당교사: 홍길동**

## Ⅰ. 교수학습 운영 계획

| 월 | 주 | 단원 | 성취기준 | 수업방법 | 주안점 |
|---|---|---|---|---|---|
| 8 | 3 | 단원1 | [12합성01-01] | 강의 | 주안점1 |

## Ⅱ. 평가 세부 계획

### 1. 평가의 목적
가. 목적 하나.

### 2. 평가의 기본 방향
가. 방향 하나.

### 3. 평가 방침
가. 방침 하나.

### 4. 성취기준 및 성취수준
**가. 교육과정 성취기준·평가기준(상/중/하)**

| 성취기준 | 상 | 중 | 하 |
|---|---|---|---|
| [12합성01-01] 표준 하나 | 상1 | 중1 | 하1 |

**나. 영역별 성취수준(A/B/C)**

| 영역 | A | B | C |
|---|---|---|---|
| 영역 가 | A1 | B1 | C1 |

### 5. 기준 성취율과 성취도
| 성취율(원점수) | 성취도 |
|---|---|
| 80% 이상 | A |
| 60% 이상 ~ 80% 미만 | B |
| 60% 미만 | C |

### 6. 평가의 종류와 반영비율
| 구분 | ① 영역 가 | ② 영역 나 | 합계 |
|---|---|---|---|
| 영역 만점 | 60점(60%) | 40점(40%) | 100% |

### 7. 수행평가 세부기준
**① 영역 가 (60점)** · [12합성01-01]

| 평가항목 | 채점 기준(배점) |
|---|---|
| 항목1 | 완비 **40** / 부분 **20** |
| 기본점수 **18** · 장기 미인정 결석 **17** | |

### 8. 정의적 능력 평가
- 요소 하나.

### 9. 수행평가 미응시자
가. 처리 하나.

### 10. 평가 유의사항
- 유의 하나.

### 11. 평가 결과 분석 및 활용
- 활용 하나.
"""

DETAILED_S7 = """### 7. 수행평가 세부기준

#### ① 영역 가

- **평가 영역명**: 영역 가 ｜ **영역 만점**: 60점
- **수행과제**: 합성 과제
- **성취기준 / 성취수준(A~E)**: [12합성01-01]
- **평가 방법**: ☑ 산출물

**［세부 영역 가. 세부 하나 (60점)］ 평가요소 ｜ 수행수준(채점 기준) ｜ 배점**

| 평가요소 | 수행수준(채점 기준) | 배점 |
|---|---|---|
| 항목1 | 완비하여 산출함 | 40 |
| | 부분만 완성함 | 20 |
| **가. 소계** | | **60** |

**［영역 공통］**

| 구분 | 배점 |
|---|---|
| 기본점수 | 18 |
| 장기 미인정 결석자 | 17 |

"""

DETAILED_MD = (
    SYNTHETIC_MD[: SYNTHETIC_MD.index("### 7. 수행평가 세부기준")]
    + DETAILED_S7
    + SYNTHETIC_MD[SYNTHETIC_MD.index("### 8. 정의적 능력 평가") :]
)

# hwpx itself (the top-level package) is not removed, only many of its
# submodules — so the core repo root is still reachable this way even though
# `from hwpx import evalplan_fill` no longer is. Same technique
# test_form_fill_wild_safety.py uses for its own core-fixture reads.
CORE_ROOT = Path(hwpx.__file__).resolve().parents[2]
BLANK_3HAK = CORE_ROOT / "tests" / "fixtures" / "m105_evalplan" / "blank_form_3hak.hwpx"

# A relative, deterministic non-existent path: parse_review_file embeds the
# path it was given verbatim (not resolved to absolute), so this reproduces
# byte-identically against the golden captured at freeze time — unlike
# pytest's tmp_path, which is a fresh absolute path every run.
MISSING_PATH = "__parity_fixture_missing__/missing-review.md"

_FIXTURES = Path(__file__).parent / "parity_fingerprints"
FROZEN = json.loads((_FIXTURES / "evalplan.json").read_text(encoding="utf-8"))["modules"]
GOLDEN_BYTES = (_FIXTURES / "evalplan.golden.json").read_bytes()
GOLDEN = json.loads(GOLDEN_BYTES)["calls"]
POST_HEIGHT_SYNC = json.loads(
    (_FIXTURES / "evalplan.post-height-sync.json").read_text(encoding="utf-8")
)


def test_post_height_sync_receipt_preserves_the_historical_golden() -> None:
    assert hashlib.sha256(GOLDEN_BYTES).hexdigest() == POST_HEIGHT_SYNC["historicalGoldenSha256"]
    assert set(POST_HEIGHT_SYNC["cases"]) == set(GOLDEN["fillCases"])


def _jsonify(value: object) -> object:
    """Round-trip through JSON so tuples (``dataclasses.asdict`` keeps
    ``RubricItem.levels: list[tuple[str, str]]`` as ``tuple``) compare equal
    to GOLDEN, which already went through JSON and came back as ``list`` —
    the same normalisation ``test_exam_runtime_parity.py`` needed."""

    return json.loads(json.dumps(value, ensure_ascii=False))


def test_public_api_and_dataclass_shape_matches_frozen_core() -> None:
    assert fingerprint(canonical) == FROZEN["hwpx.evalplan_fill"]

    for name in ("RubricItem", "RubricSubArea"):
        described = parity_fingerprint._describe_class(getattr(canonical, name))
        assert described == GOLDEN["extraDataclasses"][name]


@pytest.mark.parametrize("label,markdown", [("synthetic", SYNTHETIC_MD), ("detailed", DETAILED_MD)])
def test_synthetic_parse_and_skeleton_matches_frozen_core(label: str, markdown: str) -> None:
    canonical_content = canonical.parse_review_md(markdown)
    expected = GOLDEN["parses"][label]

    assert canonical_content.to_dict() == expected["toDict"]
    assert _jsonify(dataclasses.asdict(canonical_content)) == expected["asDict"]
    assert canonical.expected_skeleton(canonical_content) == expected["expectedSkeleton"]


@pytest.mark.parametrize(
    "label,markdown",
    [
        ("empty", ""),
        ("titleOnly", "# 제목만"),
        ("s7Only", "### 7. 수행평가 세부기준\n"),
    ],
)
def test_empty_and_partial_input_matches_frozen_core(label: str, markdown: str) -> None:
    canonical_content = canonical.parse_review_md(markdown)
    assert _jsonify(dataclasses.asdict(canonical_content)) == GOLDEN["emptyPartial"][label]


@pytest.mark.skipif(
    not BLANK_3HAK.is_file(),
    reason="public evaluation-plan blank fixture is unavailable",
)
@pytest.mark.parametrize(
    ("phase", "md_label", "markdown"),
    [
        ("structural", "synthetic", SYNTHETIC_MD),
        ("all", "synthetic", SYNTHETIC_MD),
        ("clean", "synthetic", SYNTHETIC_MD),
        ("clean", "detailed", DETAILED_MD),
    ],
)
def test_plan_fill_and_cleanup_matches_frozen_reports_and_height_sync_bytes(
    phase: str, md_label: str, markdown: str
) -> None:
    expected = GOLDEN["fillCases"][f"{phase}:{md_label}"]
    canonical_content = canonical.parse_review_md(markdown)

    assert _jsonify(canonical.plan_structural_ops(BLANK_3HAK, canonical_content)) == (
        expected["structuralOps"]
    )

    canonical_result = canonical.fill_evalplan(
        BLANK_3HAK,
        canonical_content,
        phase=phase,
    )
    data = canonical_result.pop("_data")
    assert _jsonify(canonical_result) == expected["fillResult"]
    # Core's structural byte path now applies the existing object-model height
    # delta (#539). Keep the old capture; record only those changed output bytes
    # separately. Plans, reports, API fingerprints above stay historically exact.
    output = POST_HEIGHT_SYNC["cases"][f"{phase}:{md_label}"]
    assert hashlib.sha256(data).hexdigest() == output["dataSha256"]
    assert len(data) == output["dataLength"]


def test_missing_input_refusal_matches_frozen_core() -> None:
    try:
        canonical.parse_review_file(MISSING_PATH)
    except FileNotFoundError as exc:
        payload = (type(exc).__name__, str(exc))
    else:
        raise AssertionError("call unexpectedly succeeded")

    assert payload == (
        GOLDEN["missingInputError"]["type"],
        GOLDEN["missingInputError"]["message"],
    )
