# SPDX-License-Identifier: Apache-2.0
"""Machine-check the planned compliance/quality/utilities owner boundary."""
from __future__ import annotations

import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOUNDARY = runpy.run_path(
    str(ROOT / "scripts" / "check_product_boundary.py")
)
CANONICAL_POLICY_ROOTS = BOUNDARY["CANONICAL_POLICY_ROOTS"]
FROZEN_CORE_POLICY_IMPORTS = BOUNDARY["FROZEN_CORE_POLICY_IMPORTS"]
_policy_owner_import_violation = BOUNDARY[
    "_policy_owner_import_violation"
]
OWNER = json.loads(
    (
        ROOT
        / "docs"
        / "architecture"
        / "compliance-quality-utilities-owner.json"
    ).read_text(encoding="utf-8")
)


def test_owner_ledger_matches_the_frozen_source_and_package_plan() -> None:
    assert OWNER["source"] == {
        "head": "ac88d5fb1a015de1217577090d62e92c36cf4d8a",
        "pythonFiles": 4,
        "loc": 1622,
        "manifestSha256": (
            "d97db5cac702059ce4297f10ca108c6e2a162ba84b93bd5fe1a914a27877ad1f"
        ),
    }
    assert set(OWNER["canonicalOwners"]) == set(FROZEN_CORE_POLICY_IMPORTS)
    assert OWNER["toolContract"] == {
        "default": 122,
        "advanced": 130,
        "skillRequired": 29,
        "hash": "8c278ebd5becba08",
    }


def test_canonical_policy_roots_use_only_declared_public_core_seams() -> None:
    assert OWNER["approvedCoreImports"] == {
        "compliance": ["hwpx.document"],
        "quality": ["hwpx"],
        "utilities": [],
    }
    assert CANONICAL_POLICY_ROOTS == {
        "src/hwpx_automation/office/compliance": ("hwpx.document",),
        "src/hwpx_automation/office/quality": ("hwpx",),
        "src/hwpx_automation/office/utilities": (),
    }

    assert (
        _policy_owner_import_violation(
            "src/hwpx_automation/office/compliance/pii.py",
            "hwpx.tools.pii",
        )
        is not None
    )
    assert (
        _policy_owner_import_violation(
            "src/hwpx_automation/office/quality/page_guard.py",
            "hwpx.opc.package",
        )
        is not None
    )
    assert (
        _policy_owner_import_violation(
            "src/hwpx_automation/office/utilities/table_compute.py",
            "hwpx",
        )
        is not None
    )
    assert (
        _policy_owner_import_violation(
            "src/hwpx_automation/office/compliance/official_lint.py",
            "hwpx.document",
        )
        is None
    )
