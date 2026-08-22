# SPDX-License-Identifier: Apache-2.0
"""Member-level rendering ownership and dependency seam."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

from hwpx_automation.office import rendering
from hwpx_automation.tool_contract import (
    contract_hash,
    expected_tool_names,
    skill_required_tool_names,
)

ROOT = Path(__file__).resolve().parents[1]
BOUNDARY = runpy.run_path(str(ROOT / "scripts" / "check_product_boundary.py"))
OWNER = json.loads(
    (ROOT / "docs" / "architecture" / "visual-runtime-owner.json").read_text(
        encoding="utf-8"
    )
)


def test_owner_ledger_matches_frozen_source_and_contract() -> None:
    assert OWNER["source"] == {
        "head": "3720196aa3ad4c4885059573c23bd7a8293302fb",
        "pythonFiles": 11,
        "loc": 2667,
        "manifestSha256": (
            "1d10fab2feba5b892bc2d6ea7a5af621b11394a6f3a65de0cd2861ce5445c758"
        ),
        "publicSurfaceSha256": (
            "66f3c71e9a03f714de4ab4c6259f362549d4eb0b0d8ab94282c99446cc500481"
        ),
    }
    assert tuple(OWNER["approvedCoreImports"]) == (
        BOUNDARY["ALLOWED_RENDERING_CORE_IMPORTS"]
    )
    assert tuple(OWNER["forbiddenCoreCompatibilityImports"]) == (
        BOUNDARY["FROZEN_CORE_VISUAL_RUNTIME_IMPORTS"]
    )
    assert OWNER["toolContract"] == {
        "default": 122,
        "advanced": 130,
        "skillRequired": 29,
        "hash": "8c278ebd5becba08",
    }


def test_rendering_owner_gate_rejects_runtime_and_private_core_seams() -> None:
    check = BOUNDARY["_rendering_owner_import_violation"]
    canonical = "src/hwpx_automation/office/rendering/oracle.py"

    assert check(canonical, "hwpx.visual.oracle") is not None
    assert check(canonical, "hwpx.visual.hancom_worker") is not None
    assert check(canonical, "hwpx.form_fit.wordbox") is not None
    assert check(canonical, "hwpx.visual.detectors") is None
    assert check(canonical, "hwpx.visual.diff") is None
    assert check(canonical, "hwpx.visual.qa_contracts") is None
    assert check(canonical, "hwpx.document") is not None


def test_exam_uses_neutral_block_split_contract() -> None:
    source = (
        ROOT / "src" / "hwpx_automation" / "office" / "exam" / "measure.py"
    ).read_text(encoding="utf-8")
    # The block-split contract lives with the rendering owner now, not in core.
    # The point of the assertion is unchanged: exam consumes the shared
    # geometry contract rather than carrying its own copy.
    assert "from ..rendering.block_splits import Block, detect_block_splits" in source
    assert "hwpx.visual.oracle" not in source


def test_canonical_package_inventory_and_runtime_identities_are_exact() -> None:
    canonical = ROOT / BOUNDARY["CANONICAL_RENDER_ROOT"]

    assert sorted(path.name for path in canonical.glob("*.py")) == OWNER[
        "packageFiles"
    ]
    assert sorted(
        path.name
        for path in canonical.iterdir()
        if path.suffix in {".ps1", ".applescript"}
    ) == OWNER["resourceFiles"]
    assert rendering.NullOracle.__module__ == (
        "hwpx_automation.office.rendering.oracle"
    )
    assert rendering.resolve_oracle.__module__ == (
        "hwpx_automation.office.rendering.oracle"
    )
    assert rendering.HancomRenderBackend.__module__ == (
        "hwpx_automation.office.rendering"
    )


def test_tool_surface_remains_exactly_frozen() -> None:
    assert len(expected_tool_names(advanced=False)) == 128
    assert len(expected_tool_names(advanced=True)) == 136
    assert len(skill_required_tool_names()) == 29
    assert contract_hash() == "8c278ebd5becba08"


def test_real_product_tree_passes_rendering_owner_gate() -> None:
    report = BOUNDARY["evaluate"](ROOT)

    assert report["ok"], report["violations"]
    assert report["canonicalRenderingPythonFiles"] == 10
    assert report["canonicalRenderingResources"] == OWNER["resourceFiles"]
