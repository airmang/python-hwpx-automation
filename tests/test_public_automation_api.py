from __future__ import annotations

import json
import inspect
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

import hwpx_automation
import pytest
from hwpx_automation.configuration import env_value
from hwpx_automation.identity import product_identity


def test_curated_root_facade_can_author_without_mcp_surface() -> None:
    assert "create_document_from_plan" in hwpx_automation.__all__
    document = hwpx_automation.create_document_from_plan(
        {
            "schemaVersion": "hwpx.document_plan.v1",
            "title": "Automation facade",
            "blocks": [{"type": "paragraph", "text": "base install"}],
        }
    )
    assert document.sections


def test_curated_task_facade_keeps_explicit_typed_signatures() -> None:
    analyze = inspect.signature(hwpx_automation.analyze_form_fill)
    apply = inspect.signature(hwpx_automation.apply_form_fill)
    compose = inspect.signature(hwpx_automation.compose_exam)

    assert tuple(analyze.parameters) == (
        "source_filename",
        "input_json",
        "input_json_path",
        "input_docx",
        "destination_filename",
        "options",
    )
    assert tuple(apply.parameters) == (
        "plan_id",
        "analysis",
        "source_filename",
        "destination_filename",
        "canonical_input",
        "confirm",
        "mask",
    )
    assert tuple(compose.parameters) == (
        "form_path",
        "exam_markdown",
        "output_path",
        "oracle",
        "max_rounds",
        "role_style_names",
    )
    assert all(
        parameter.kind is not inspect.Parameter.VAR_KEYWORD
        for signature in (analyze, apply, compose)
        for parameter in signature.parameters.values()
    )


def test_module_entry_point_runs_task_cli() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "hwpx_automation", "--help"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "hwpx" in completed.stdout.casefold()


def test_installed_identity_contract_is_machine_readable() -> None:
    raw = files("hwpx_automation").joinpath("identity.json").read_text(encoding="utf-8")
    assert json.loads(raw) == product_identity()
    manifest = product_identity()
    classified = {
        (item["surface"], item["value"]): item["classification"]
        for item in manifest["identifiers"]
    }
    assert classified[("distribution", "python-hwpx-automation")] == "canonical"
    assert classified[("distribution", "hwpx-mcp-server")] == "compatibility"
    assert classified[("mcp-console", "hwpx-automation-mcp")] == "canonical"
    assert classified[("capability-version-field", "versions.automation")] == (
        "canonical"
    )
    assert classified[("capability-version-field", "versions.mcp")] == (
        "compatibility-preserved"
    )
    assert classified[("protocol-error-schema", "hwpx.mcp-error/v1")] == (
        "compatibility-preserved"
    )
    frozen_receipts = {
        value
        for (surface, value), classification in classified.items()
        if surface == "frozen-receipt-schema"
        and classification == "compatibility-preserved"
    }
    assert frozen_receipts == {
        "hwpx-mcp.authoring-runtime-owner/v1",
        "hwpx-mcp.compliance-quality-utilities-owner/v1",
        "hwpx-mcp.document-operations-owner/v1",
        "hwpx-mcp.evalplan-runtime-owner/v1",
        "hwpx-mcp.exam-runtime-owner/v1",
        "hwpx-mcp.form-fill-runtime-owner/v1",
        "hwpx-mcp.form-fill-runtime-parity/v1",
        "hwpx-mcp.visual-runtime-owner/v1",
    }
    assert classified[
        ("frozen-parity-receipt-field", "mcpRuntimeMembers")
    ] == "compatibility-preserved"
    assert manifest["compatibilityPolicy"]["removalNotBeforeMajor"] == 7
    assert manifest["compatibilityPolicy"]["minimumPublicNoticeDays"] == 90
    release = manifest["releaseState"]
    assert release["status"] in {
        "unreleased-candidate",
        "release-approved",
        "released",
    }
    assert release["candidate"] == {
        "pythonHwpx": "6.1.0",
        "canonicalDistribution": "python-hwpx-automation",
        "canonicalAutomation": "7.0.1",
        "compatibilityDistribution": "hwpx-mcp-server",
        "compatibility": "7.0.1",
        "plugin": "2.0.0",
        "contractHash": "34a91560759dc47a",
    }
    promotion_gate = release["promotionGate"]
    assert all(
        required in promotion_gate
        for required in (
            "core",
            "canonical automation",
            "compatibility distribution",
            "plugin GitHub release",
            "marketplace entry",
            "real marketplace install",
            "leaves currentPublic unchanged",
            "attached receipt",
        )
    )
    if release["status"] != "released":
        assert release["currentPublic"] == {
            "pythonHwpx": "5.7.0",
            "primaryDistribution": "python-hwpx-automation",
            "primaryApplication": "6.7.1",
            "plugin": "1.7.0",
            "contractHash": "98510af22d13899c",
        }
    else:
        assert release["currentPublic"] == {
            "pythonHwpx": "6.1.0",
            "primaryDistribution": "python-hwpx-automation",
            "primaryApplication": "7.0.1",
            "plugin": "2.0.0",
            "contractHash": "34a91560759dc47a",
        }


def test_canonical_environment_precedes_legacy_fallback(monkeypatch) -> None:
    monkeypatch.setenv("HWPX_MCP_ADVANCED", "legacy")
    assert env_value("ADVANCED") == "legacy"
    monkeypatch.setenv("HWPX_AUTOMATION_ADVANCED", "canonical")
    assert env_value("ADVANCED") == "canonical"


def test_legacy_workspace_environment_remains_a_6_x_fallback(
    monkeypatch, tmp_path: Path
) -> None:
    from hwpx_automation.workspace import WorkspaceResolver

    monkeypatch.delenv("HWPX_AUTOMATION_WORKSPACE_ROOTS", raising=False)
    monkeypatch.setenv("HWPX_MCP_WORKSPACE_ROOTS", str(tmp_path))
    resolver = WorkspaceResolver.from_environment()
    assert resolver.roots == (tmp_path,)
    assert resolver.source == "HWPX_MCP_WORKSPACE_ROOTS"


def test_runtime_and_health_advertise_canonical_identity() -> None:
    from hwpx_automation import server

    assert server.mcp.name == "python-hwpx-automation"
    health = server.mcp_server_health()
    assert health["server"] == "python-hwpx-automation"
    assert health["serverInfo"] == {
        "name": "python-hwpx-automation",
        "canonicalMcpConsole": "hwpx-automation-mcp",
        "compatibilityMcpConsoles": ["hwpx-mcp-server"],
        "hostConfigKeyRole": "host-local-alias",
    }


def test_server_help_uses_canonical_program_name(capsys) -> None:
    from hwpx_automation import server

    with pytest.raises(SystemExit) as exc_info:
        server.main(["--help"])
    assert exc_info.value.code == 0
    assert capsys.readouterr().out.startswith("usage: hwpx-automation-mcp")
