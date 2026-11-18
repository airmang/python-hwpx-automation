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
the golden recorded their SHA-256 and length instead; the test now checks the
digest of the document's parts (``CORE_PARTS_SHA256``), which does not depend on
how the zip was compressed, as ``test_exam_runtime_parity.py`` hashes each part.

Those bytes come from the installed core's ``table_patch`` edits, so a
deliberate core change to them moves the digest while the parsed plan and
``fillResult`` stay the frozen ones. The golden keeps the frozen bytes (core up
to 6.10.0); ``CORE_PARTS_SHA256`` holds the outputs after the reviewed core
changes since (#659, #677, described there). Core 6.11.0 matched none: it set a
page-split table's height to 0 (core #539, fixed in core #672).

Every assertion the pre-freeze version of this file made is still made here;
none needed dropping.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import zipfile
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
GOLDEN = json.loads((_FIXTURES / "evalplan.golden.json").read_text(encoding="utf-8"))["calls"]

# The filled document's parts, as one digest (each part's name and the SHA-256 of its bytes as stored
# uncompressed): the zip layer (zlib level and implementation, entry dates) differs between
# machines, the parts do not. The values are the outputs the reviewed core changes settled on:
# core #659 (``split_cell_vertical`` leaves its new cells as one empty paragraph, copied
# paragraphs get ids of their own) and core #677 (the cleanup phase clears only the text the
# target run holds itself, so a guidance-coloured run holding a table keeps the table's first
# cell). They were frozen before as whole-file hashes (``dc5056d4…`` for "all:synthetic",
# ``09e642d2…``/``8272e38f…`` for the clean phase, the golden's for "structural:synthetic"); the
# same files give these digests. Change one only for such a reviewed core change, never to quiet a
# regression.
CORE_PARTS_SHA256 = {
    "structural:synthetic": "2fd5242eefa6dfec4b1e084770b41c7a13ba5482406ac89765fe4462746235ee",
    "all:synthetic": "545dca10fe143f090b53baae2318203fae783b5799b4abf31e53af362d61f25d",
    "clean:synthetic": "65c33a7a2300c47e5b4587d17f9cae310e01028455bf55eaddd1531d077402ef",
    "clean:detailed": "54ddbb655122452b7d524141906d5b4669d966ff24b545da80ff59346e45d467",
}


def _parts_sha256(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        listing = sorted(
            (info.filename, hashlib.sha256(archive.read(info)).hexdigest()) for info in archive.infolist()
        )
    joined = "\n".join(f"{name} {digest}" for name, digest in listing)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


# Core #711 (reviewed) stopped warning that the manifest does not list
# version.xml: every Hangul-saved HWPX keeps it at the fixed path unlisted, so
# it is the normal state. The frozen fillResult still carries that one warning
# in openSafety.validatePackage; it is accepted present or absent, nothing else.
CORE_711_DROPPED_WARNING = (
    "Contents/content.hpf: manifest does not reference a version part; "
    "engine will fall back to 'version.xml'"
)


def _without_core_711_warning(result: object) -> object:
    if not isinstance(result, dict):
        return result
    safety = result.get("openSafety")
    package = safety.get("validatePackage") if isinstance(safety, dict) else None
    if not (isinstance(package, dict) and isinstance(package.get("warnings"), list)):
        return result
    warnings = [w for w in package["warnings"] if w != CORE_711_DROPPED_WARNING]
    return {
        **result,
        "openSafety": {**safety, "validatePackage": {**package, "warnings": warnings}},
    }


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
def test_plan_fill_and_cleanup_byte_matches_frozen_core(
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
    assert _without_core_711_warning(_jsonify(canonical_result)) == _without_core_711_warning(
        expected["fillResult"]
    )
    assert _parts_sha256(data) == CORE_PARTS_SHA256[f"{phase}:{md_label}"]


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
