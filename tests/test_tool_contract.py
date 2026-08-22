from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import anyio
import pytest
from jsonschema import Draft202012Validator

from hwpx_automation import __version__
from hwpx_automation import server
import hwpx_automation.tool_contract as tool_contract_module
from hwpx_automation.handlers import quality_render as quality_render_handlers
from hwpx_automation.fastmcp_adapter import (
    runtime_server_version,
    snapshot_runtime_tools,
)
from hwpx_automation.tool_contract import (
    BASELINE_TOOL_SPECS,
    DOMAIN_SPECS,
    MIN_AUTOMATION_VERSION,
    MIN_MCP_VERSION,
    MIN_PYTHON_HWPX,
    MIN_SKILL_VERSION,
    RELEASED_CONTRACT_HASH,
    ToolClassification,
    ToolAvailability,
    bind_tool_specs,
    bound_tool_registry,
    classification_counts,
    contract_hash,
    expected_tool_names,
    skill_required_tool_names,
    validate_registered_tools,
)


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_TOOLS = {
    "start_workflow",
    "get_workflow",
    "get_workflow_result",
    "continue_workflow",
    "approve_workflow_decision",
    "cancel_workflow",
    "resume_workflow",
}
RENDER_TOOLS = {
    "render_submit",
    "render_status",
    "render_cancel",
    "render_health",
}
INTERNAL_FIXTURE_QA_TOOLS = {
    "run_fixture_benchmark",
    "export_fixture_benchmark",
    "visual_review_fixture",
    "visual_repair_fixture",
}
COMPATIBILITY_TOOLS = {
    "apply_edits",
    "apply_evalplan_fill",
    "create_comparison_table_document",
    "create_government_report_document",
    "create_proposal_document",
    "fill_by_path",
}
ADVANCED_TOOLS = {
    "lint_text_conventions",
    "object_find_by_attr",
    "object_find_by_tag",
    "package_get_text",
    "package_get_xml",
    "package_parts",
    "score_form_fill",
    "validate_structure",
}
# 5.0.0 (S-091): the five transition stubs are removed and the three
# template-formfit facades demote from compatibility to deprecated.
DEPRECATED_TOOLS = {
    "analyze_template_formfit",
    "apply_template_formfit",
    "fill_form_field",
}
REMOVED_TRANSITION_STUBS = {
    "analyze_quality_generation",
    "apply_edit",
    "apply_quality_generation",
    "plan_edit",
    "preview_edit",
}
AGENT_DOCUMENT_TOOLS = {
    "get_document_node",
    "query_document_nodes",
    "apply_document_commands",
    "dump_document_blueprint",
    "replay_document_blueprint",
}
REMOVED_PRACTICE_TOOLS = {
    "start_practice_scenario",
    "apply_practice_scenario",
    "start_practice_campaign",
    "get_practice_campaign",
    "continue_practice_campaign",
    "cancel_practice_campaign",
    "export_practice_campaign",
}


def test_active_registry_exactly_matches_contract() -> None:
    assert runtime_server_version(server.mcp) == __version__
    assert set(server._fastmcp_tool_names()) == expected_tool_names(
        advanced=server._ACTIVE_ADVANCED
    )
    active = expected_tool_names(advanced=server._ACTIVE_ADVANCED)
    assert skill_required_tool_names() & active <= set(server._fastmcp_tool_names())
    assert WORKFLOW_TOOLS <= set(server._fastmcp_tool_names())
    assert RENDER_TOOLS <= set(server._fastmcp_tool_names())
    assert INTERNAL_FIXTURE_QA_TOOLS.isdisjoint(server._fastmcp_tool_names())
    assert AGENT_DOCUMENT_TOOLS <= set(server._fastmcp_tool_names())
    # 5.0.0: the removed transition stubs are absent from every profile, with no
    # alias or ghost registration standing in for them.
    assert REMOVED_TRANSITION_STUBS.isdisjoint(server._fastmcp_tool_names())
    assert REMOVED_TRANSITION_STUBS.isdisjoint(expected_tool_names(advanced=True))
    assert REMOVED_TRANSITION_STUBS.isdisjoint({spec.name for spec in BASELINE_TOOL_SPECS})
    assert len(expected_tool_names(advanced=False)) == 128
    workflow_domains = [domain for domain in DOMAIN_SPECS if domain.key == "workflow"]
    assert len(workflow_domains) == 1
    assert set(workflow_domains[0].tools) == WORKFLOW_TOOLS
    render_domains = [domain for domain in DOMAIN_SPECS if domain.key == "real_hancom_render"]
    assert len(render_domains) == 1
    assert set(render_domains[0].tools) == RENDER_TOOLS
    assert "unverified" in render_domains[0].when_to_use
    assert all(domain.key not in {"visual_qa", "blind_eval"} for domain in DOMAIN_SPECS)
    assert all(domain.key != "private_practice" for domain in DOMAIN_SPECS)
    agent_domains = [domain for domain in DOMAIN_SPECS if domain.key == "agent_document"]
    assert len(agent_domains) == 1
    assert set(agent_domains[0].tools) == AGENT_DOCUMENT_TOOLS
    assert "전문 도구" in agent_domains[0].when_to_use


def test_artifact_materializing_render_tools_are_marked_mutating() -> None:
    specs = {spec.name: spec for spec in BASELINE_TOOL_SPECS}

    assert {
        name: specs[name].mutates
        for name in ("render_preview", "render_status")
    } == {
        "render_preview": True,
        "render_status": True,
    }


def test_release_contract_versions_counts_and_hash_are_exact() -> None:
    assert (
        MIN_PYTHON_HWPX,
        MIN_AUTOMATION_VERSION,
        MIN_MCP_VERSION,
        MIN_SKILL_VERSION,
    ) == (
        "6.3.0",
        "7.0.1",
        "7.0.1",
        "2.0.0",
    )
    assert len(expected_tool_names(advanced=False)) == 128
    assert len(expected_tool_names(advanced=True)) == 136
    assert len(skill_required_tool_names()) == 29
    assert RELEASED_CONTRACT_HASH == "8c278ebd5becba08"
    assert contract_hash() == RELEASED_CONTRACT_HASH == "8c278ebd5becba08"
    assert REMOVED_PRACTICE_TOOLS.isdisjoint(expected_tool_names(advanced=True))


def test_baseline_classification_is_disjoint_exact_and_exhaustive() -> None:
    assert len(BASELINE_TOOL_SPECS) == 140
    assert len({spec.name for spec in BASELINE_TOOL_SPECS}) == 140
    assert classification_counts() == {
        "public": 119,
        "compatibility": 6,
        "advanced": 8,
        "deprecated": 3,
        "internal": 4,
    }
    internal = {
        spec.name
        for spec in BASELINE_TOOL_SPECS
        if spec.classification is ToolClassification.INTERNAL
    }
    assert internal == INTERNAL_FIXTURE_QA_TOOLS
    assert internal.isdisjoint(expected_tool_names(advanced=True))
    by_class = {
        classification: {
            spec.name
            for spec in BASELINE_TOOL_SPECS
            if spec.classification is classification
        }
        for classification in ToolClassification
    }
    assert by_class[ToolClassification.COMPATIBILITY] == COMPATIBILITY_TOOLS
    assert by_class[ToolClassification.ADVANCED] == ADVANCED_TOOLS
    assert by_class[ToolClassification.DEPRECATED] == DEPRECATED_TOOLS
    assert all(
        spec.replacement_tools
        for spec in BASELINE_TOOL_SPECS
        if spec.classification
        in {ToolClassification.COMPATIBILITY, ToolClassification.DEPRECATED}
    )
    assert all(
        spec.availability is ToolAvailability.INTERNAL_ONLY
        for spec in BASELINE_TOOL_SPECS
        if spec.name in INTERNAL_FIXTURE_QA_TOOLS
    )


def test_live_fastmcp_binding_matches_callable_descriptions_and_schemas() -> None:
    assert validate_registered_tools(server.mcp, server._TOOL_REGISTRY)["ok"] is True


def test_registry_binding_fails_closed_before_partial_registration() -> None:
    namespace = dict(server._SERVER_TOOL_BINDINGS)
    namespace.pop("apply_document_commands")

    with pytest.raises(RuntimeError, match="apply_document_commands: missing callable"):
        bind_tool_specs(namespace, advanced=None)


def test_canonical_form_fill_tools_use_typed_closed_top_level_schemas() -> None:
    bound = bound_tool_registry().by_name()
    analyze = bound["analyze_form_fill"].input_schema
    apply = bound["apply_form_fill"].input_schema
    verify = bound["verify_form_fill"].input_schema

    assert analyze["additionalProperties"] is False
    assert apply["additionalProperties"] is False
    assert verify["additionalProperties"] is False
    assert len(analyze["oneOf"]) == 2
    assert len(apply["oneOf"]) == 2
    assert any(
        "$ref" in option for option in analyze["properties"]["input_json"]["anyOf"]
    )
    assert "$ref" in apply["properties"]["analysis"]
    assert set(verify["properties"]) == {
        "filename",
        "before_path",
        "require",
        "plan",
        "expected_output_revision",
    }
    assert verify["properties"]["plan"]["$ref"].endswith("MixedFormCompiledPlanInput")
    assert len(verify["oneOf"]) == 2
    assert verify["oneOf"][0]["required"] == ["plan"]
    assert verify["oneOf"][1]["required"] == ["filename", "before_path"]
    validator = Draft202012Validator(verify)
    assert not list(
        validator.iter_errors({"filename": "after.hwpx", "before_path": "before.hwpx"})
    )
    assert list(validator.iter_errors({}))
    assert list(validator.iter_errors({"filename": "after.hwpx"}))
    assert list(validator.iter_errors({"plan": None}))
    assert list(
        validator.iter_errors(
            {
                "filename": "after.hwpx",
                "before_path": "before.hwpx",
                "expected_output_revision": "sha256:" + "0" * 64,
            }
        )
    )


def test_form_tool_outputs_publish_typed_receipts_in_live_contract() -> None:
    outputs = {
        name: bound_tool_registry().by_name()[name].output_schema
        for name in (
            "analyze_form_fill",
            "apply_form_fill",
            "verify_form_fill",
            "apply_table_ops",
            "apply_body_ops",
            "apply_evalplan_fill",
        )
    }
    for schema in outputs.values():
        Draft202012Validator.check_schema(schema)
        assert schema["type"] == "object"
        assert not (
            schema.get("additionalProperties") is True
            and schema.get("properties") == {}
        )

    analyze = outputs["analyze_form_fill"]
    assert analyze["type"] == "object"
    assert len(analyze["anyOf"]) == 2
    assert analyze["$defs"]["CanonicalMixedFormAnalysisOutput"][
        "additionalProperties"
    ] is False
    assert analyze["$defs"]["LegacyFormFillAnalysisOutput"][
        "additionalProperties"
    ] is True

    apply = outputs["apply_form_fill"]
    assert apply["type"] == "object"
    assert len(apply["anyOf"]) == 2
    canonical_apply = apply["$defs"]["CanonicalMixedFormApplyOutput"]
    assert canonical_apply["additionalProperties"] is False
    assert canonical_apply["properties"]["verificationReceipt"]["$ref"].endswith(
        "/FormVerificationReceipt"
    )
    assert apply["$defs"]["LegacyFormFillApplyOutput"][
        "additionalProperties"
    ] is True
    assert apply["$defs"]["FormVerificationReceipt"][
        "additionalProperties"
    ] is False

    verify = outputs["verify_form_fill"]
    assert verify["type"] == "object"
    assert len(verify["anyOf"]) == 2
    assert verify["$defs"]["FormVerificationReceipt"][
        "additionalProperties"
    ] is False
    assert verify["$defs"]["LegacyFormFillVerifyOutput"][
        "additionalProperties"
    ] is True

    for name in ("apply_table_ops", "apply_body_ops", "apply_evalplan_fill"):
        schema = outputs[name]
        assert schema["additionalProperties"] is False
        assert "verificationReceipt" in schema["required"]
        assert schema["properties"]["verificationReceipt"]["$ref"].endswith(
            "/FormVerificationReceipt"
        )
        assert schema["$defs"]["FormVerificationReceipt"][
            "additionalProperties"
        ] is False


def test_missing_required_canonical_symbol_is_startup_fatal_and_never_ghost_registered() -> (
    None
):
    code = """
import hwpx_automation.office.authoring as authoring
delattr(authoring, 'create_document_from_plan')
import hwpx_automation.server  # noqa: F401
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=dict(os.environ),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "create_document_from_plan" in result.stderr


def test_missing_frozen_core_authoring_symbol_does_not_break_mcp_startup() -> None:
    """Startup must survive core not carrying the authoring names — and now it does.

    The 4.x version simulated the absence with delattr. From python-hwpx 5.0 the
    absence is simply the truth: create_document_from_plan lives in this package,
    not in core. Asserting the name is gone as well as that startup works keeps
    the guarantee meaningful — a delattr on a name that no longer exists would
    raise, and a test that only imports the server would no longer be testing
    anything about missing core symbols.
    """

    code = """
import hwpx
assert 'create_document_from_plan' not in dir(hwpx), (
    'core still exposes an authoring name this package owns'
)
import hwpx_automation.server  # noqa: F401
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=dict(os.environ),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_health_detects_live_schema_skew(monkeypatch) -> None:
    snapshots = dict(snapshot_runtime_tools(server.mcp))
    tool = snapshots["apply_table_ops"]
    skewed = dict(tool.input_schema)
    skewed["properties"] = dict(skewed["properties"])
    skewed["properties"].pop("ops")
    snapshots["apply_table_ops"] = replace(tool, input_schema=skewed)
    monkeypatch.setattr(
        tool_contract_module,
        "snapshot_runtime_tools",
        lambda _mcp: snapshots,
        raising=False,
    )

    health = server.mcp_server_health()

    assert health["toolSurface"]["status"] == "skewed"
    assert health["toolSurface"]["inputSchemaMismatches"] == ["apply_table_ops"]
    assert health["capability"]["writesBlocked"] is True


def test_advanced_registry_exactly_matches_contract_in_fresh_process() -> None:
    code = """
import json
from hwpx_automation import server
from hwpx_automation.tool_contract import expected_tool_names, validate_registered_tools
print(json.dumps({
    'actual': sorted(server._fastmcp_tool_names()),
    'expected': sorted(expected_tool_names(advanced=True)),
    'valid': validate_registered_tools(server.mcp, server._TOOL_REGISTRY)['ok'],
}))
"""
    env = dict(os.environ, HWPX_MCP_ADVANCED="1")
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["actual"] == payload["expected"]
    assert len(payload["actual"]) == 136
    assert payload["valid"] is True


def test_recovered_tool_schemas_preserve_public_argument_names() -> None:
    async def schemas() -> dict[str, set[str]]:
        tools = await server.mcp.list_tools()
        return {
            tool.name: set(tool.inputSchema.get("properties", {})) for tool in tools
        }

    inputs = anyio.run(schemas)
    canonical = bound_tool_registry().by_name()
    assert {
        "filename",
        "before_path",
        "require",
        "plan",
        "expected_output_revision",
    } == inputs["verify_form_fill"]
    assert {
        "filename",
        "gold_path",
        "blank_path",
        "run_render",
        "expected_pages",
    } == set(canonical["score_form_fill"].input_schema["properties"])
    assert {"filename", "blank_path"} == inputs["inspect_fill_residue"]
    assert {
        "filename",
        "review_md",
        "output",
        "render_check",
        "score_gold_path",
        "expected_pages",
        "phase",
    } == inputs["apply_evalplan_fill"]
    assert {
        "family",
        "idempotency_key",
        "source_path",
        "output_path",
        "expected_revision",
        "parameters",
        "budget",
        "policy",
    } == inputs["start_workflow"]
    assert {"workflow_id", "approved", "action_hash"} == inputs["approve_workflow_decision"]
    assert {"workflow_id", "action_hash"} == inputs["get_workflow_result"]
    assert {
        "filename",
        "path",
        "depth",
        "child_limit",
        "expected_revision",
    } == inputs["get_document_node"]
    assert {
        "filename",
        "selector",
        "limit",
        "node_depth",
        "child_limit",
        "expected_revision",
    } == inputs["query_document_nodes"]
    assert {
        "filename",
        "output",
        "commands",
        "expected_revision",
        "idempotency_key",
        "dry_run",
        "quality",
        "verification_requirements",
        "overwrite",
    } == inputs["apply_document_commands"]
    assert {
        "filename",
        "path",
        "mode",
        "expected_revision",
        "output",
        "overwrite",
        "include_assets",
        "require_replayable",
        "include_manifest",
    } == inputs["dump_document_blueprint"]
    assert {"request"} == inputs["replay_document_blueprint"]


def test_health_fails_exactly_when_required_tool_missing(monkeypatch) -> None:
    report = validate_registered_tools(server.mcp, server._TOOL_REGISTRY)
    report = {**report, "ok": False}
    report["actualOrder"] = [
        name for name in report["actualOrder"] if name != "apply_table_ops"
    ]
    report["missing"] = ["apply_table_ops"]
    monkeypatch.setattr(
        quality_render_handlers,
        "validate_registered_tools",
        lambda *_: report,
    )

    health = server.mcp_server_health()

    assert health["toolSurface"]["status"] == "skewed"
    assert health["toolSurface"]["missingExpectedTools"] == ["apply_table_ops"]
    assert health["toolSurface"]["missingSkillRequiredTools"] == ["apply_table_ops"]
    assert health["capability"]["ok"] is False
    assert health["capability"]["writesBlocked"] is True


def test_generated_mcp_contract_is_current() -> None:
    subprocess.run(
        [sys.executable, "scripts/render_tool_contract.py", "--check", "--skip-skill"],
        cwd=ROOT,
        check=True,
    )
    assert server.mcp_server_health()["toolSurface"]["contractHash"] == contract_hash()
    payload = json.loads(
        (ROOT / "docs" / "tool-contract.generated.json").read_text(encoding="utf-8")
    )
    assert payload["baselineToolCount"] == 140
    assert payload["classificationCounts"] == classification_counts()
    assert payload["contractHash"] == contract_hash()


def test_generated_versioned_contract_delta_is_current() -> None:
    subprocess.run(
        [sys.executable, "scripts/render_contract_delta.py", "--check"],
        cwd=ROOT,
        check=True,
    )
    payload = json.loads(
        (ROOT / "docs" / "tool-contract-delta-4.0.0.json").read_text(encoding="utf-8")
    )

    assert payload["baseline"] == {
        "versions": {
            "pythonHwpx": "3.0.0",
            "mcpServer": "3.0.0",
            "skill": "0.2.0",
        },
        "defaultToolCount": 126,
        "advancedToolCount": 136,
        "domainCount": 21,
        "skillRequiredToolCount": 30,
        "contractHash": "76d143ccc0787828",
    }
    assert payload["target"] == {
        "versions": {
            "pythonHwpx": "3.1.0",
            "mcpServer": "4.0.0",
            "skill": "0.3.0",
        },
        "defaultToolCount": 121,
        "advancedToolCount": 132,
        "domainCount": 19,
        "skillRequiredToolCount": 28,
        "contractHash": "f46ec677231b3a20",
    }
    assert {item["name"] for item in payload["removedTools"]} == INTERNAL_FIXTURE_QA_TOOLS
    assert all(item["alias"] is None for item in payload["removedTools"])
    assert len(payload["compatibility"]["facades"]) == 11
    assert len(payload["compatibility"]["deprecatedStubs"]) == 5
    assert payload["compatibility"]["aliases"] == []
    assert payload["compatibility"]["ghostRegistrations"] == []
    evidence = payload["registrationEvidence"]
    assert evidence["remainingRemovedRuntimeReferences"] == []
    assert evidence["activeRemovedNames"] == []
