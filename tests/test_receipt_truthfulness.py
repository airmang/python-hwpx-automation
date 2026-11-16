# SPDX-License-Identifier: Apache-2.0
"""The completion-truth invariant: a tool may not report work it did not do.

The invariant
=============

    ok is true AND the request asked for a nonzero amount of work
        implies
    the file's sha256 changed, OR a typed partial failure is reported.

The antecedent counts what was *requested*, never what was *produced*. Counting
production makes the invariant vacuous: a run that reports ``ok`` with zero
fills would satisfy "produced == 0 implies nothing", which is exactly the shape
of the defect this file exists to prevent.

What went wrong
===============

``apply_evalplan_fill`` captured its receipt from the structural step and then
ran six content-fill steps that kept mutating the bytes without touching it.
The publish decision in ``ops_services.form_fields`` reads ``byteIdentical``
from that receipt, so an in-place call reported ``ok`` together with a content
report listing twenty-six filled regions, and wrote nothing at all. The file's
sha256 was identical before and after.

That is the same class of failure the project already names elsewhere -- a
machine score read as a submission -- except here the score was not merely
optimistic, it was false.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path

import hwpx
import pytest

from hwpx_automation.hwpx_ops import HwpxOps

_CORE_REPO_PIN = os.environ.get("PYTHON_HWPX_REPO")
CORE_REPO = (
    Path(_CORE_REPO_PIN).expanduser().resolve()
    if _CORE_REPO_PIN
    else Path(hwpx.__file__).resolve().parents[2]
)
BLANK = CORE_REPO / "tests" / "fixtures" / "m105_evalplan" / "blank_form_3hak.hwpx"
OPS_SERVICES = Path(__file__).resolve().parents[1] / "src" / "hwpx_automation" / "ops_services"

REVIEW_MD = """# 2026학년도 2학기 3학년 「합성 과목」 교수학습운영 및 평가계획 (검토용)

> **담당교사: 홍길동** · 수행평가 100% · 성취도 3단계

## Ⅰ. 교수학습 운영 계획

| 월 | 주 | 단원 | 성취기준 | 수업방법 | 주안점 |
|---|---|---|---|---|---|
| 8 | 3 | 단원1 | [12합성01-01] | 강의 | 주안점1 |
| 9 | 1 | 단원2 | [12합성01-02] | 토의 | 주안점2 |
"""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _requested_work(report: dict) -> int:
    """How many regions the run was asked to fill, not how many it filled."""

    total = 0
    for value in (report or {}).values():
        if isinstance(value, dict):
            for key in ("requested", "filled", "filled_cells", "applied"):
                item = value.get(key)
                if isinstance(item, int):
                    total += item
                elif isinstance(item, list):
                    total += len(item)
    return total


needs_fixture = pytest.mark.skipif(
    not BLANK.is_file(),
    reason="python-hwpx evaluation-plan fixture is unavailable",
)


def _structurally_processed_form(tmp_path: Path) -> Path:
    """A form whose structural ops are already applied.

    This precondition is the whole test. On a pristine blank the structural
    step changes bytes on its own, so a receipt copied from that step happens
    to be right and the defect stays invisible. Run the structural phase first
    and the second run's structural step becomes a no-op -- from then on only
    the content fills change anything, and a receipt taken before they run
    reports "identical" over a document they rewrote.
    """

    staged = tmp_path / "staged.hwpx"
    shutil.copyfile(BLANK, staged)
    ops = HwpxOps(base_directory=tmp_path)
    ops.apply_evalplan_fill("staged.hwpx", "review.md", phase="structural")
    return staged


@needs_fixture
def test_in_place_fill_that_reports_work_must_change_the_file(tmp_path: Path) -> None:
    """The exact defect: ok with a content report and an untouched file."""

    review = tmp_path / "review.md"
    review.write_text(REVIEW_MD, encoding="utf-8")
    staged = _structurally_processed_form(tmp_path)

    before = _sha256(staged)
    ops = HwpxOps(base_directory=tmp_path)
    result = ops.apply_evalplan_fill("staged.hwpx", "review.md", phase="all")
    after = _sha256(staged)

    report = result.get("contentReport") or result.get("content_report")
    requested = _requested_work(report)
    assert result.get("ok"), result
    assert requested > 0, (
        "the fixture no longer requests content work, so this test can no "
        f"longer observe the invariant it exists for: {report!r}"
    )
    assert after != before, (
        "apply_evalplan_fill reported ok with "
        f"{requested} content regions and left the file byte-identical "
        f"({before[:16]}); a receipt may not claim work that did not happen"
    )


@needs_fixture
def test_receipt_byte_identical_matches_the_bytes(tmp_path: Path) -> None:
    """``byteIdentical`` must describe the produced bytes, not an early step."""

    from hwpx_automation.office.evalplan.runtime import fill_evalplan, parse_review_md

    review = tmp_path / "review.md"
    review.write_text(REVIEW_MD, encoding="utf-8")
    staged = _structurally_processed_form(tmp_path)

    content = parse_review_md(REVIEW_MD)
    payload = fill_evalplan(staged, content, phase="all")

    produced = payload["_data"]
    source = staged.read_bytes()
    assert payload["byteIdentical"] == (produced == source), (
        "byteIdentical describes the structural step rather than the produced "
        f"bytes (receipt says {payload['byteIdentical']}, bytes say "
        f"{produced == source})"
    )
    if payload["byteIdentical"]:
        assert not payload["changedParts"]
    else:
        assert payload["changedParts"], (
            "bytes changed but the receipt names no changed part"
        )


def test_incoherent_receipt_is_refused_not_forwarded() -> None:
    """"identical" and "these parts changed" cannot both be true."""

    from hwpx_automation.ops_services import save_policy

    source = (save_policy.__file__ and Path(save_policy.__file__)).read_text(
        encoding="utf-8"
    )
    assert "MUTATION_REPORT_INCOHERENT" in source, (
        "save_policy forwards the domain payload's preservation claim onto the "
        "written receipt; it must refuse the impossible combination"
    )
    assert re.search(r"if byte_identical and changed_parts", source)


#: Modules allowed to write document bytes, each with the reason.
#:
#: Publication is meant to funnel through one seam so one coherence guard
#: covers every mutating tool. A module that writes bytes without appearing
#: here has escaped that guard, and the invariant would have to be re-proved
#: per tool. Declared, not silent: adding an entry requires stating why.
_DECLARED_BYTE_WRITERS = {
    "save_policy.py": "the publish seam itself (_write_patched)",
    "transactions.py": (
        "the atomic publish implementation for non-local storage: writes a "
        "temp file and renames it, and records the verification report and "
        "backup for the same write"
    ),
}


def test_ops_services_write_only_through_declared_publish_seams() -> None:
    """Every byte write in the ops-service layer must be a declared seam."""

    undeclared: list[str] = []
    for path in sorted(OPS_SERVICES.glob("*.py")):
        if path.name in _DECLARED_BYTE_WRITERS:
            continue
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\.write_bytes\(", text):
            line = text.count("\n", 0, match.start()) + 1
            undeclared.append(f"{path.name}:{line}")
    assert not undeclared, (
        "these ops services write document bytes outside a declared publish "
        "seam, so the receipt-coherence guard does not cover them: "
        f"{undeclared}. Add the module to _DECLARED_BYTE_WRITERS with the "
        "reason, or route the write through save_policy."
    )


def test_every_declared_byte_writer_still_exists() -> None:
    """A declaration that no longer matches reality is itself a stale claim."""

    for name in _DECLARED_BYTE_WRITERS:
        path = OPS_SERVICES / name
        assert path.is_file(), f"declared byte writer {name} no longer exists"
        assert ".write_bytes(" in path.read_text(encoding="utf-8") or name == (
            "save_policy.py"
        ), f"{name} no longer writes bytes; drop its declaration"


def test_paragraph_patch_reports_no_applied_edit_when_all_are_discarded(
    tmp_path: Path,
) -> None:
    """A discarded set is reported as discarded, never as applied."""

    from hwpx.document import HwpxDocument
    from hwpx.patch import paragraph_patch

    document = HwpxDocument.new()
    document.add_paragraph("원래 문단")
    source = tmp_path / "src.hwpx"
    document.save(str(source))
    output = tmp_path / "out.hwpx"

    result = paragraph_patch(
        source,
        [
            {"paragraphIndex": 0, "text": "바뀐 문단"},
            {"paragraphIndex": 99, "text": "없는 문단"},
        ],
        output_path=output,
    )

    assert not result.ok
    assert result.applied == (), "a fully discarded set reported applied edits"
    assert result.discarded, "the discarded edits lost their diagnostic value"
    assert result.output_is_source_copy, (
        "output_path received the unmodified source and the receipt did not "
        "say so"
    )
    assert output.read_bytes() == source.read_bytes()
