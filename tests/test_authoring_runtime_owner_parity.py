# SPDX-License-Identifier: Apache-2.0
"""Parity between the automation authoring owner and core's frozen 4.x shape.

``hwpx.authoring``, ``hwpx.builder``, ``hwpx.design``, and ``hwpx.presets``
are scheduled for physical deletion from core once python-hwpx is reduced to
a library, so this file no longer imports them live. Instead:

- Structural claims (exports, signatures, dataclass fields) compare the live
  automation module's ``tests.parity_fingerprint.fingerprint()`` against
  ``tests/parity_fingerprints/authoring.json``, frozen from core while it
  still existed.
- Behavioural claims that need an actual computed value (plan schema,
  normalize/validate output, the proposal spec, ``available_profiles()``,
  and the exported text + open-safety of a plan-built and a builder-built
  document) compare against ``tests/parity_fingerprints/authoring.golden.json``
  — values captured from that same frozen core commit and confirmed
  identical to MCP's own output at freeze time.

The neutral part of ``hwpx.tools.template_analyzer`` remains in core and is
compared live. Its agent-oriented schema member moved to the automation owner,
so that one member is compared against its pre-removal frozen value instead of
being incorrectly required on core 5.0.

Every assertion the pre-freeze version of this file made is still made here;
none needed dropping.
"""
from __future__ import annotations

import dataclasses
import inspect
import json
from pathlib import Path
from typing import Any

import hwpx.tools.template_analyzer as core_template
from hwpx.tools.package_validator import validate_editor_open_safety
from parity_fingerprint import fingerprint

import hwpx_automation.office.authoring as mcp_authoring
import hwpx_automation.office.authoring.advanced_generators as mcp_generators
import hwpx_automation.office.authoring.builder as mcp_builder
import hwpx_automation.office.authoring.design as mcp_design
import hwpx_automation.office.authoring.presets as mcp_presets
import hwpx_automation.office.authoring.style_profile as mcp_style
import hwpx_automation.office.authoring.template_analyzer as mcp_template

_FIXTURES = Path(__file__).parent / "parity_fingerprints"
FROZEN = json.loads((_FIXTURES / "authoring.json").read_text(encoding="utf-8"))["modules"]
GOLDEN = json.loads(
    (_FIXTURES / "authoring.golden.json").read_text(encoding="utf-8")
)["calls"]

# The neutral template analyzer stays core-native: it reads package structure
# with hwpx.opc and the standard library only, so its shared surface is compared
# live. The agent-schema helper is the one automation-only member.
LIVE_MODULE_PAIRS = ((core_template, mcp_template),)
AUTOMATION_ONLY_TEMPLATE_MEMBERS = ("template_analysis_agent_schema",)
FROZEN_MODULES = (
    ("hwpx.authoring", mcp_authoring),
    ("hwpx.builder", mcp_builder),
    ("hwpx.design", mcp_design),
    ("hwpx.presets", mcp_presets),
    # Named explicitly as mcp-migrate in the standing ownership ledger despite
    # sitting under hwpx.tools, and already carried by the automation owner.
    ("hwpx.tools.advanced_generators", mcp_generators),
    ("hwpx.tools.style_profile", mcp_style),
)


def _public_names(module: Any) -> list[str]:
    names = list(getattr(module, "__all__", ()))
    if names:
        return names
    return sorted(
        name
        for name, value in vars(module).items()
        if not name.startswith("_")
        and (
            getattr(value, "__module__", None) == module.__name__
            or (
                name.isupper()
                and isinstance(
                    value,
                    (str, int, float, bool, tuple, frozenset),
                )
            )
        )
    )


def _assert_public_parity(
    left: Any,
    right: Any,
    *,
    right_only: tuple[str, ...] = (),
) -> None:
    left_names = _public_names(left)
    right_names = _public_names(right)
    assert [name for name in right_names if name not in right_only] == left_names
    assert [name for name in right_names if name in right_only] == list(right_only)
    for name in left_names:
        left_value = getattr(left, name)
        right_value = getattr(right, name)
        assert type(left_value).__name__ == type(right_value).__name__, name
        if callable(left_value):
            try:
                left_signature = str(inspect.signature(left_value))
                right_signature = str(inspect.signature(right_value))
            except (TypeError, ValueError):
                continue
            assert left_signature == right_signature, name
        else:
            assert left_value == right_value, name


def _plan() -> dict[str, Any]:
    return {
        "schemaVersion": "hwpx.document_plan.v1",
        "title": "정본 parity",
        "blocks": [
            {"type": "heading", "level": 1, "text": "개요"},
            {"type": "paragraph", "text": "본문"},
            {
                "type": "table",
                "columns": [
                    {"key": "item", "label": "항목"},
                    {"key": "value", "label": "값"},
                ],
                "rows": [{"item": "A", "value": "1"}],
            },
        ],
    }


def test_live_tools_public_exports_and_signatures_are_exact() -> None:
    for core_module, mcp_module in LIVE_MODULE_PAIRS:
        _assert_public_parity(
            core_module,
            mcp_module,
            right_only=AUTOMATION_ONLY_TEMPLATE_MEMBERS,
        )


# Fields added by the automation owner after the freeze. Each must be optional
# (have a default), so every call the frozen shape accepted is still accepted;
# they are removed from the live fingerprint before comparing, and everything
# else must still match the record exactly.
POST_FREEZE_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    # Keyed nodes and the save report's anchors: node -> saved paragraph.
    "hwpx.builder": {
        "Paragraph": ("key",),
        "Table": ("key",),
        "BuilderSaveReport": ("anchors",),
    },
}


def _without_post_freeze_fields(core_name: str, shape: dict[str, Any]) -> dict[str, Any]:
    for class_name, field_names in POST_FREEZE_FIELDS.get(core_name, {}).items():
        fields = shape[class_name]["fields"]
        for field_name in field_names:
            assert fields[field_name]["hasDefault"] is True, (class_name, field_name)
            assert field_name not in FROZEN[core_name][class_name]["fields"]
            del fields[field_name]
    return shape


def test_frozen_authoring_modules_shape_matches_frozen_core() -> None:
    for core_name, mcp_module in FROZEN_MODULES:
        live = _without_post_freeze_fields(core_name, fingerprint(mcp_module))
        assert live == FROZEN[core_name]


def test_document_plan_schema_normalization_validation_and_errors_match_frozen_core() -> (
    None
):
    plan = _plan()
    invalid = {
        "schemaVersion": "hwpx.document_plan.v1",
        "blocks": [{}],
    }

    assert mcp_authoring.get_document_plan_schema() == GOLDEN["documentPlanSchema"]
    assert (
        mcp_authoring.normalize_document_plan(plan).to_dict()
        == GOLDEN["normalizedPlan"]
    )
    assert (
        mcp_authoring.validate_document_plan(plan).to_dict()
        == GOLDEN["validPlanReport"]
    )
    assert (
        mcp_authoring.validate_document_plan(invalid).to_dict()
        == GOLDEN["invalidPlanReport"]
    )


def test_generators_and_style_profile_payloads_are_exact() -> None:
    """build_* / apply_style_profile_to_plan match the frozen core output.

    These two modules sit under ``hwpx.tools`` but the standing ownership ledger
    names both explicitly as automation-migrate, and the automation owner carries them,
    so they leave with the rest of authoring. Their payloads are frozen like the
    others rather than compared against a copy that is about to disappear.
    """

    profile = {
        "schemaVersion": "hwpx.style-profile.v1",
        "page": {
            "orientation": "LANDSCAPE",
            "widthMm": 297,
            "heightMm": 210,
            "marginsMm": {
                "left": 20,
                "right": 20,
                "top": 15,
                "bottom": 15,
            },
        },
        "body": {"font": "함초롬바탕", "sizePt": 11},
    }

    assert mcp_generators.build_image_grid(
        ["a.png", "b.png"],
        columns=2,
        image_width_mm=50,
    ) == GOLDEN["imageGrid"]
    assert mcp_generators.build_meeting_nameplates(
        ["가", "나"],
        columns=2,
    ) == GOLDEN["meetingNameplates"]
    hierarchy = {"name": "대표", "children": [{"name": "팀"}]}
    assert mcp_generators.build_organization_chart(hierarchy) == GOLDEN["organizationChart"]
    assert (
        mcp_style.apply_style_profile_to_plan(_plan(), profile)
        == GOLDEN["styleProfileApplied"]
    )


def test_proposal_spec_normalization_matches_frozen_core() -> None:
    assert dataclasses.asdict(
        mcp_presets.normalize_proposal_spec(
            {"title": "제안", "sections": [{"title": "배경"}]}
        )
    ) == GOLDEN["normalizedProposalSpec"]


def test_document_plan_creation_save_reopen_and_open_safety_match_frozen_core(
    tmp_path: Path,
) -> None:
    mcp_path = tmp_path / "mcp-plan.hwpx"
    mcp_document = mcp_authoring.create_document_from_plan(_plan())
    try:
        assert mcp_document.text.plain() == GOLDEN["planDocument"]["exportText"]
        mcp_document.save_to_path(mcp_path)
    finally:
        mcp_document.close()

    mcp_safety = validate_editor_open_safety(mcp_path)
    assert mcp_safety.ok is True
    assert mcp_safety.summary == GOLDEN["planDocument"]["openSafetySummary"]


def test_builder_lowering_and_computed_fields_match_frozen_core(
    tmp_path: Path,
) -> None:
    mcp_path = tmp_path / "mcp-builder.hwpx"
    mcp_plan = mcp_builder.Document(
        sections=[
            mcp_builder.Section(
                children=[
                    mcp_builder.Paragraph(text="{{ commas(1234567) }}"),
                    mcp_builder.Table(
                        header=["항목", "값"],
                        rows=[["A", "1"]],
                    ),
                ]
            )
        ]
    )
    mcp_document = mcp_plan.lower()
    try:
        assert mcp_document.text.plain() == GOLDEN["builderDocument"]["exportText"]
        mcp_document.save_to_path(mcp_path)
    finally:
        mcp_document.close()

    assert validate_editor_open_safety(mcp_path).ok is True


def test_design_profile_registry_matches_frozen_core_and_template_analysis_is_exact(
    tmp_path: Path,
) -> None:
    # analyze_template lives in hwpx.tools.template_analyzer, which stays —
    # compared live, same as before. Its input file no longer needs core's
    # create_document_from_plan; the automation owner builds an equivalent fixture.
    source = tmp_path / "source.hwpx"
    document = mcp_authoring.create_document_from_plan(_plan())
    try:
        document.save_to_path(source)
    finally:
        document.close()

    assert mcp_design.available_profiles() == GOLDEN["availableProfiles"]
    assert not hasattr(core_template, "template_analysis_agent_schema")
    assert (
        mcp_template.template_analysis_agent_schema()
        == GOLDEN["templateAnalysisAgentSchema"]
    )
    assert dataclasses.asdict(core_template.analyze_template(source)) == (
        dataclasses.asdict(mcp_template.analyze_template(source))
    )
