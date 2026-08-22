# SPDX-License-Identifier: Apache-2.0
"""Machine-check the planned canonical evalplan owner boundary."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOUNDARY = runpy.run_path(str(ROOT / "scripts" / "check_product_boundary.py"))
OWNER = json.loads(
    (ROOT / "docs" / "architecture" / "evalplan-runtime-owner.json").read_text(
        encoding="utf-8"
    )
)


def test_owner_ledger_matches_frozen_source_and_contract() -> None:
    assert OWNER["source"] == {
        "head": "98a6282bcf486859c9c3b9786d9744a1ff3bd362",
        "pythonFiles": 1,
        "loc": 2727,
        "sha256": (
            "35aaf4ab6964a028cd5470da05e80ccb0a7537532b48644c31dd142604a9eb52"
        ),
        "manifestSha256": (
            "3769acd8a4d599f20fe3658f212c83b384096bdf64014c8ca1892e52b6115089"
        ),
    }
    assert (
        tuple(OWNER["approvedCoreImports"])
        == BOUNDARY["ALLOWED_EVALPLAN_CORE_IMPORTS"]
    )
    assert (
        tuple(OWNER["forbiddenCoreCompatibilityImports"])
        == BOUNDARY["FROZEN_CORE_EVALPLAN_IMPORTS"]
    )
    assert OWNER["toolContract"]["hash"] == "8c278ebd5becba08"


def test_canonical_owner_rejects_frozen_and_unapproved_core_seams() -> None:
    check = BOUNDARY["_evalplan_owner_import_violation"]
    canonical = "src/hwpx_automation/office/evalplan/runtime.py"

    assert check(canonical, "hwpx.evalplan_fill") is not None
    assert check(canonical, "hwpx.formfill_quality") is not None
    assert check(canonical, "hwpx.table_patch") is None
    assert check(canonical, "hwpx.patch") is None


def test_real_tree_declares_the_evalplan_boundary() -> None:
    report = BOUNDARY["evaluate"](ROOT)
    assert report["ok"], report["violations"]
    assert report["canonicalEvalplanRoot"] == (
        "src/hwpx_automation/office/evalplan"
    )
    assert report["canonicalEvalplanPythonFiles"] == 2
