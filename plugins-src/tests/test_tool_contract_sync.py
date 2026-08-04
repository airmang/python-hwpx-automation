from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "references" / "tool-contract.generated.json"
RECOVERED_TOOLS = {
    "apply_table_ops",
    "apply_body_ops",
    "run_edit_plan",
    "scan_form_guidance",
    "inspect_fill_residue",
    "verify_form_fill",
    "apply_evalplan_fill",
    "score_form_fill",
}
WORKFLOW_TOOLS = {
    "start_workflow",
    "get_workflow",
    "continue_workflow",
    "approve_workflow_decision",
    "cancel_workflow",
    "resume_workflow",
}
RENDER_TOOLS = {"render_submit", "render_status", "render_cancel", "render_health"}
REMOVED_QA_FIXTURE_TOOLS = {
    "visual_review_fixture",
    "visual_repair_fixture",
    "run_fixture_benchmark",
    "export_fixture_benchmark",
}
REMOVED_PRIVATE_PRACTICE_TOOLS = {
    "start_practice_scenario",
    "apply_practice_scenario",
    "start_practice_campaign",
    "get_practice_campaign",
    "continue_practice_campaign",
    "cancel_practice_campaign",
    "export_practice_campaign",
}
AGENT_DOCUMENT_TOOLS = {
    "get_document_node",
    "query_document_nodes",
    "apply_document_commands",
}
BLUEPRINT_TOOLS = {"dump_document_blueprint", "replay_document_blueprint"}


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_generated_contract_covers_recovered_skill_tools() -> None:
    contract = _contract()
    names = {tool["name"] for tool in contract["tools"]}
    required = set(contract["skillRequiredTools"])

    assert RECOVERED_TOOLS <= names
    assert RECOVERED_TOOLS <= required
    assert WORKFLOW_TOOLS <= names
    assert RENDER_TOOLS <= names
    assert REMOVED_QA_FIXTURE_TOOLS.isdisjoint(names)
    assert REMOVED_PRIVATE_PRACTICE_TOOLS.isdisjoint(names)
    assert all(tool["domain"] != "private_practice" for tool in contract["tools"])
    assert AGENT_DOCUMENT_TOOLS <= names
    assert AGENT_DOCUMENT_TOOLS <= required
    assert BLUEPRINT_TOOLS <= names
    assert BLUEPRINT_TOOLS <= required
    assert REMOVED_PRIVATE_PRACTICE_TOOLS.isdisjoint(required)
    assert contract["contractHash"] == "b468d0cab8179f79"
    assert contract["defaultToolCount"] == 128
    assert contract["advancedToolCount"] == 136
    assert len(contract["skillRequiredTools"]) == 29
    assert contract["defaultToolCount"] == sum(
        tool["profile"] == "default" for tool in contract["tools"]
    )
    assert contract["advancedToolCount"] == len(contract["tools"])


def test_every_host_bundle_carries_the_canonical_contract() -> None:
    canonical = CONTRACT_PATH.read_bytes()
    bundled = sorted((ROOT / "plugins").glob("**/tool-contract.generated.json"))

    assert len(bundled) == 4
    assert all(path.read_bytes() == canonical for path in bundled)


def test_launcher_and_manifests_match_contract_minimums() -> None:
    contract = _contract()
    identity = json.loads(
        (ROOT / "packaging" / "product-identity.json").read_text(encoding="utf-8")
    )
    components = identity["components"]
    launcher = (ROOT / "packaging" / "templates" / "hwpx-automation-mcp").read_text(
        encoding="utf-8"
    )
    assert (
        contract["minMcpVersion"]
        == components["automation"]["minimumCompatibleVersion"]
    )
    assert contract["minPythonHwpx"] == components["core"]["minimumCompatibleVersion"]
    assert contract["minSkillVersion"] == components["plugin"]["minimumCompatibleVersion"]
    assert (
        "python-hwpx-automation[mcp,oracle]"
        f"=={components['automation']['currentVersion']}"
        in launcher
    )
    assert f"HWPX_SKILL_VERSION:-{components['plugin']['currentVersion']}" in launcher
    assert 'export HWPX_PLUGIN_ROOT="${HWPX_PLUGIN_ROOT:-${PLUGIN_ROOT}}"' in launcher

    for manifest in (
        ROOT / "packaging" / "templates" / "claude.plugin.json",
        ROOT / "packaging" / "templates" / "codex.plugin.json",
        ROOT / "packaging" / "templates" / "openclaw.plugin.json",
    ):
        assert (
            json.loads(manifest.read_text(encoding="utf-8"))["version"]
            == components["plugin"]["currentVersion"]
        )


def test_skill_routes_to_generated_api_table() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    generated = (ROOT / "references" / "tool-contract.generated.md").read_text(
        encoding="utf-8"
    )

    assert "references/tool-contract.generated.md" in skill
    for tool in RECOVERED_TOOLS:
        assert re.search(rf"`{re.escape(tool)}`", generated)
    for tool in WORKFLOW_TOOLS:
        assert re.search(rf"`{re.escape(tool)}`", generated)
    for tool in RENDER_TOOLS:
        assert re.search(rf"`{re.escape(tool)}`", generated)
    assert "## Internal fixture QA removals" in generated
    for tool in REMOVED_QA_FIXTURE_TOOLS:
        # The generated contract keeps one explicit removal receipt, but the
        # removed repository-QA names must never appear as installed API rows.
        assert f"| `{tool}` |" not in generated
        assert generated.count(f"`{tool}`") == 1
    assert "private_practice" not in generated
    for tool in REMOVED_PRIVATE_PRACTICE_TOOLS:
        assert not re.search(rf"`{re.escape(tool)}`", generated)
    for tool in AGENT_DOCUMENT_TOOLS:
        assert re.search(rf"`{re.escape(tool)}`", generated)
    for tool in BLUEPRINT_TOOLS:
        assert re.search(rf"`{re.escape(tool)}`", generated)


def test_skill_routes_blueprint_transplant_to_focused_contract() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    reference_path = ROOT / "references" / "workflows-agent-blueprint.md"
    reference = reference_path.read_text(encoding="utf-8")

    assert "references/workflows-agent-blueprint.md" in skill
    for tool in BLUEPRINT_TOOLS:
        assert f"`{tool}`" in skill
        assert f"`{tool}" in reference
    for term in (
        "unsupported",
        "exact|mapped",
        "hwpx dump --inspect",
        "hwpx dump --repack",
        "SavePipeline은 정확히 한 번",
        "rolledBack == true",
        "real-Hancom",
        "raw XML",
        "resident session",
        "OfficeCLI adapter",
    ):
        assert term in reference


def test_skill_routes_unfamiliar_structure_to_shared_agent_document_contract() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    reference_path = ROOT / "references" / "workflows-agent-document.md"
    reference = reference_path.read_text(encoding="utf-8")

    assert "references/workflows-agent-document.md" in skill
    assert "낯선 기존 문서" in skill
    assert "여러 후보 중 첫 항목을 임의 선택" in skill
    assert "전문 도구를 유지" in skill
    for tool in AGENT_DOCUMENT_TOOLS:
        assert f"`{tool}`" in skill
        assert f"`{tool}" in reference
    for term in (
        "canonical path",
        "volatilePath",
        "dry-run과 commit",
        "같은 idempotency key를 재사용하지 않는다",
        "rolledBack == true",
        "real-Hancom",
        "hwpx batch commands.json",
        '/section[1]/header[@page-type="BOTH"]',
        "storyPreservation",
    ):
        assert term in reference


def test_every_host_bundle_carries_agent_document_reference_and_routing() -> None:
    canonical = (ROOT / "references" / "workflows-agent-document.md").read_bytes()
    bundled = sorted((ROOT / "plugins").glob("**/workflows-agent-document.md"))
    bundled_skills = sorted((ROOT / "plugins").glob("**/SKILL.md"))

    assert len(bundled) == 4
    assert all(path.read_bytes() == canonical for path in bundled)
    assert len(bundled_skills) == 4
    assert all(
        "references/workflows-agent-document.md" in path.read_text(encoding="utf-8")
        for path in bundled_skills
    )


def test_every_host_bundle_carries_blueprint_reference_and_routing() -> None:
    canonical = (ROOT / "references" / "workflows-agent-blueprint.md").read_bytes()
    bundled = sorted((ROOT / "plugins").glob("**/workflows-agent-blueprint.md"))
    bundled_skills = sorted((ROOT / "plugins").glob("**/SKILL.md"))

    assert len(bundled) == 4
    assert all(path.read_bytes() == canonical for path in bundled)
    assert len(bundled_skills) == 4
    assert all(
        "references/workflows-agent-blueprint.md" in path.read_text(encoding="utf-8")
        for path in bundled_skills
    )


def test_skill_routes_general_work_to_one_level_autonomous_reference() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    reference = (ROOT / "references" / "workflows-autonomous.md").read_text(
        encoding="utf-8"
    )

    assert "references/workflows-autonomous.md" in skill
    assert "primitive 도구는 workflow가 지원하지 않는 전문 작업" in skill
    assert "unknown_form_fill" in reference
    assert "renderChecked=false" in reference
    assert all(tool in reference for tool in WORKFLOW_TOOLS)


def test_skill_routes_forms_through_one_mixed_plan_and_keeps_exam_separate() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    forms = (ROOT / "references" / "workflows-forms.md").read_text(encoding="utf-8")

    assert "`analyze_form_fill` → `apply_form_fill`" in skill
    assert "**한 트랜잭션**" in skill
    assert "시험은 `compose_exam`" in skill
    assert "평가계획은 `apply_evalplan_fill`" in skill
    for target_kind in ("nativeField", "canonicalPath", "labelCell", "bodyAnchor"):
        assert f"`{target_kind}`" in forms
    assert "다른 kind로 runtime fallback하지 않는다" in forms
    assert "stable native field" in forms
    assert "`apply_table_ops`와\n   `apply_body_ops`를 따로 commit" in forms
    assert "generated contract의 replacement guidance" in forms
    assert "`compose_exam`" in forms


def test_every_host_bundle_carries_autonomous_reference_and_routing() -> None:
    canonical = (ROOT / "references" / "workflows-autonomous.md").read_bytes()
    bundled = sorted((ROOT / "plugins").glob("**/workflows-autonomous.md"))

    assert len(bundled) == 4
    assert all(path.read_bytes() == canonical for path in bundled)
    bundled_skills = sorted((ROOT / "plugins").glob("**/SKILL.md"))
    assert len(bundled_skills) == 4
    assert all(
        "references/workflows-autonomous.md" in path.read_text(encoding="utf-8")
        for path in bundled_skills
    )


def test_every_host_bundle_excludes_private_practice_reference_and_routing() -> None:
    canonical = ROOT / "references" / "workflows-private-practice.md"
    bundled = sorted((ROOT / "plugins").glob("**/workflows-private-practice.md"))

    assert not canonical.exists()
    assert not bundled
    bundled_skills = sorted((ROOT / "plugins").glob("**/SKILL.md"))
    assert len(bundled_skills) == 4
    assert all(
        "references/workflows-private-practice.md"
        not in path.read_text(encoding="utf-8")
        for path in bundled_skills
    )
    for path in bundled_skills:
        text = path.read_text(encoding="utf-8")
        assert all(tool not in text for tool in REMOVED_PRIVATE_PRACTICE_TOOLS)
    for sync_path in sorted((ROOT / "plugins").glob("**/plugin-sync.json")):
        assert "workflows-private-practice.md" not in sync_path.read_text(
            encoding="utf-8"
        )


def test_canonical_skill_excludes_private_practice_routing() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "references/workflows-private-practice.md" not in skill
    assert "private_practice" not in skill
    assert all(tool not in skill for tool in REMOVED_PRIVATE_PRACTICE_TOOLS)


def test_public_packaging_excludes_private_practice_configuration() -> None:
    launcher = (ROOT / "packaging" / "templates" / "hwpx-automation-mcp").read_text(
        encoding="utf-8"
    )
    hosts = (ROOT / "packaging" / "hosts.json").read_text(encoding="utf-8")
    assert 'export HWPX_PLUGIN_ROOT="${HWPX_PLUGIN_ROOT:-${PLUGIN_ROOT}}"' in launcher
    assert "HWPX_SKILL_VERSION" in launcher
    assert "workflows-private-practice.md" not in hosts

    for template in (
        ROOT / "packaging" / "templates" / "openclaw.mcp-install.md",
        ROOT / "packaging" / "templates" / "hermes.mcp-install.md",
    ):
        text = template.read_text(encoding="utf-8")
        assert "Private practice campaign (opt-in)" not in text
        assert "HWPX_CORPUS_SOURCE" not in text
        assert "HWPX_PRACTICE_ROOT" not in text


def test_clean_install_smoke_runs_workflow_protocol_e2e_from_wheels() -> None:
    smoke = (ROOT / "scripts" / "clean_install_smoke.py").read_text(encoding="utf-8")
    e2e = (ROOT / "scripts" / "plugin_mcp_e2e.py").read_text(encoding="utf-8")

    assert "plugin_mcp_e2e.py" in smoke
    assert "--server-package" in smoke and "--server-runtime" in smoke
    assert "_probe_concurrent_cold_start" in smoke
    assert "_probe_editable_runtime" in smoke
    assert '"editableRuntime": editable_runtime' in smoke
    assert (
        re.search(
            r"(?:python-hwpx(?:-automation)?|hwpx-mcp-server|hwpx-skill)-s[0-9]{3}\b",
            smoke,
            re.IGNORECASE,
        )
        is None
    )
    assert "candidate checkout is required" in smoke
    assert "no sibling or private worktree is selected implicitly" in smoke
    assert "python-hwpx-automation[mcp,oracle]" not in smoke
    assert "[mcp,oracle]" in smoke and "[preview]" in smoke
    assert "editable runtime extras are incomplete" in smoke
    assert "did not load from the selected editable checkout" in smoke
    launcher = (
        ROOT / "packaging" / "templates" / "hwpx-automation-mcp"
    ).read_text(encoding="utf-8")
    assert "uv venv --quiet --relocatable" in launcher
    assert '"runtimeLayout": "relocatable-console-v1"' in launcher
    assert '--with-editable "${MCP_REPO}[mcp,oracle]"' in launcher
    assert '--with-editable "${MCP_REPO}[mcp]"' not in launcher
    assert "HWPX_AUTOMATION_WORKSPACE_ROOTS" in e2e
    assert "site-packages" in e2e
    assert 'parser.add_argument("--report", type=Path)' in smoke
    assert 'parser.add_argument("--report", type=Path)' in e2e
    assert "start_workflow" in e2e
    assert "unknown_form_fill" in e2e
    assert "approve_workflow_decision" in e2e
    assert "render_health" in e2e and "render_submit" in e2e and "render_status" in e2e
    assert "--require-real-render" in e2e


def test_skill_routes_real_hancom_render_to_one_level_reference() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    autonomous = (ROOT / "references" / "workflows-autonomous.md").read_text(
        encoding="utf-8"
    )
    render = (ROOT / "references" / "workflows-real-hancom-render.md").read_text(
        encoding="utf-8"
    )

    assert "references/workflows-real-hancom-render.md" in skill
    assert "`render_health` → `render_submit` → `render_status`" in skill
    assert "policy.require_real_hancom_render=true" in autonomous
    assert "`VERIFY`" in autonomous and "`resume_workflow`" in autonomous
    for tool in ("render_health", "render_submit", "render_status", "render_cancel"):
        assert f"`{tool}" in render
    assert "output_dir" in render
    assert "render_checked == true" in render
    assert "local `render_preview`" in render
