# SPDX-License-Identifier: Apache-2.0
"""Machine-check the canonical exam owner boundary before routing production."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOUNDARY = runpy.run_path(str(ROOT / "scripts" / "check_product_boundary.py"))
OWNER = json.loads(
    (ROOT / "docs" / "architecture" / "exam-runtime-owner.json").read_text(
        encoding="utf-8"
    )
)


def test_owner_ledger_matches_frozen_source_and_contract() -> None:
    assert OWNER["source"] == {
        "head": "d0aa3f124ab410686f48f99e299f45958afd1002",
        "pythonFiles": 6,
        "loc": 708,
        "manifestSha256": (
            "c5fd6734f36efb254eab5cba6f012cff3e1a2af7dbccf53e9053018296884563"
        ),
    }
    assert tuple(OWNER["approvedCoreImports"]) == BOUNDARY["ALLOWED_EXAM_CORE_IMPORTS"]
    assert (
        tuple(OWNER["forbiddenCoreCompatibilityImports"])
        == BOUNDARY["FROZEN_CORE_EXAM_IMPORTS"]
    )
    assert OWNER["toolContract"]["hash"] == "8c278ebd5becba08"


def test_canonical_owner_rejects_frozen_and_unapproved_core_seams() -> None:
    check = BOUNDARY["_exam_owner_import_violation"]
    canonical = "src/hwpx_automation/office/exam/compose.py"

    assert check(canonical, "hwpx.exam") is not None
    assert check(canonical, "hwpx.form_fit.wordbox") is not None
    assert check(canonical, "hwpx.authoring") is not None
    assert check(canonical, "hwpx.document") is None
    assert check(canonical, "hwpx.tools.table_cleanup") is None
    assert (
        check(
            "src/hwpx_automation/office/exam/measure.py",
            "hwpx.visual.block_splits",
        )
        is None
    )


def test_real_tree_is_canonical_and_boundary_clean() -> None:
    report = BOUNDARY["evaluate"](ROOT)
    assert report["ok"], report["violations"]
    assert report["canonicalExamRoot"] == ("src/hwpx_automation/office/exam")
    assert report["canonicalExamPythonFiles"] == 6
