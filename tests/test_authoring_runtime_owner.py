# SPDX-License-Identifier: Apache-2.0
"""Canonical authoring-owner inventory and production-routing gates."""
from __future__ import annotations

from pathlib import Path

from hwpx_automation import quality_generation
from hwpx_automation.handlers import (
    _shared,
    authoring,
    layout_style,
    quality_render,
    specialized,
)
import hwpx_automation.office.authoring as canonical


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_ROOT = (
    ROOT / "src" / "hwpx_automation" / "office" / "authoring"
)


def test_canonical_authoring_inventory_and_profile_assets_are_complete() -> None:
    files = sorted(CANONICAL_ROOT.rglob("*.py"))
    profiles = CANONICAL_ROOT / "design" / "profiles"

    # 17 since the 5.0 train: report_parser joined the owner it always belonged to.
    # 18 with design.marked: profiles harvested from placeholder-marked templates.
    assert len(files) == 18
    assert len(canonical.__all__) == 14
    assert sorted(path.name for path in profiles.iterdir()) == [
        "application_form",
        "home_notice",
        "official_notice",
        "report",
    ]
    for profile in profiles.iterdir():
        assert (profile / "profile.json").is_file()
        assert (profile / "template.hwpx").is_file()


def test_all_authoring_production_bindings_use_the_automation_owner() -> None:
    bindings = (
        _shared.inspect_authoring_document_quality,
        authoring.build_document_from_plan,
        authoring.get_hwpx_document_plan_schema,
        authoring.build_proposal_document,
        authoring.describe_hwpx_template,
        layout_style.apply_hwpx_style_profile_to_plan,
        quality_render.inspect_operating_plan_document_quality,
        quality_render.inspect_proposal_document_quality,
        specialized.build_hwpx_image_grid,
        specialized.build_hwpx_meeting_nameplates,
        specialized.build_hwpx_organization_chart,
        quality_generation.create_proposal_document,
        quality_generation.inspect_proposal_quality,
    )

    for binding in bindings:
        assert binding is not None
        assert binding.__module__.startswith(
            "hwpx_automation.office.authoring"
        ), binding
