from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "references" / "tool-contract.generated.json"
RECOVERED_TOOLS = {
    "apply_table_ops",
    "apply_body_ops",
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
FIXTURE_BENCHMARK_TOOLS = {"run_fixture_benchmark", "export_fixture_benchmark"}
PRACTICE_SCENARIO_TOOLS = {"start_practice_scenario", "apply_practice_scenario"}
PRACTICE_CAMPAIGN_TOOLS = {
    "start_practice_campaign",
    "get_practice_campaign",
    "continue_practice_campaign",
    "cancel_practice_campaign",
    "export_practice_campaign",
}
PRACTICE_TOOLS = PRACTICE_SCENARIO_TOOLS | PRACTICE_CAMPAIGN_TOOLS
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
    assert FIXTURE_BENCHMARK_TOOLS <= names
    assert PRACTICE_TOOLS <= names
    assert AGENT_DOCUMENT_TOOLS <= names
    assert AGENT_DOCUMENT_TOOLS <= required
    assert BLUEPRINT_TOOLS <= names
    assert BLUEPRINT_TOOLS <= required
    assert PRACTICE_SCENARIO_TOOLS <= required
    assert contract["defaultToolCount"] == 133
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
    launcher = (ROOT / "packaging" / "templates" / "hwpx-mcp-server").read_text(
        encoding="utf-8"
    )
    assert f"hwpx-mcp-server=={contract['minMcpVersion']}" in launcher
    assert f'HWPX_SKILL_VERSION:-{contract["minSkillVersion"]}' in launcher
    assert 'export HWPX_SKILL_ROOT="${PLUGIN_ROOT}/skills/hwpx"' in launcher

    for manifest in (
        ROOT / "packaging" / "templates" / "claude.plugin.json",
        ROOT / "packaging" / "templates" / "codex.plugin.json",
        ROOT / "packaging" / "templates" / "openclaw.plugin.json",
    ):
        assert json.loads(manifest.read_text(encoding="utf-8"))["version"] == contract[
            "minSkillVersion"
        ]


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
    for tool in PRACTICE_TOOLS:
        assert re.search(rf"`{re.escape(tool)}`", generated)
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
    reference = (ROOT / "references" / "workflows-autonomous.md").read_text(encoding="utf-8")

    assert "references/workflows-autonomous.md" in skill
    assert "primitive 도구는 workflow가 지원하지 않는 전문 작업" in skill
    assert "unknown_form_fill" in reference
    assert "renderChecked=false" in reference
    assert all(tool in reference for tool in WORKFLOW_TOOLS)


def test_every_host_bundle_carries_autonomous_reference_and_routing() -> None:
    canonical = (ROOT / "references" / "workflows-autonomous.md").read_bytes()
    bundled = sorted((ROOT / "plugins").glob("**/workflows-autonomous.md"))

    assert len(bundled) == 4
    assert all(path.read_bytes() == canonical for path in bundled)
    bundled_skills = sorted((ROOT / "plugins").glob("**/SKILL.md"))
    assert len(bundled_skills) == 4
    assert all("references/workflows-autonomous.md" in path.read_text(encoding="utf-8") for path in bundled_skills)


def test_every_host_bundle_carries_private_practice_reference_and_routing() -> None:
    canonical = (ROOT / "references" / "workflows-private-practice.md").read_bytes()
    bundled = sorted((ROOT / "plugins").glob("**/workflows-private-practice.md"))

    assert len(bundled) == 4
    assert all(path.read_bytes() == canonical for path in bundled)
    bundled_skills = sorted((ROOT / "plugins").glob("**/SKILL.md"))
    assert len(bundled_skills) == 4
    assert all(
        "references/workflows-private-practice.md" in path.read_text(encoding="utf-8")
        for path in bundled_skills
    )


def test_private_practice_routes_durable_campaign_without_claim_inflation() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    reference = (ROOT / "references" / "workflows-private-practice.md").read_text(
        encoding="utf-8"
    )

    for tool in PRACTICE_CAMPAIGN_TOOLS:
        assert f"`{tool}`" in skill
        assert f"`{tool}" in reference
    assert 'campaign `state == "completed"`' in reference
    assert "전부 성공했다는 뜻이 아니다" in reference
    assert '`needs_review`' in reference and '`unverified`' in reference
    assert re.search(r"자동\s+`adopt`하지 않는다", reference)
    assert "게시·push·병합·릴리스" in reference
    assert "raw source와 sanitized source는 직접 수정하지 않는다" in reference
    assert re.search(r"중복\s+mutation 없이 terminal receipt가 run마다 하나", reference)


def test_private_campaign_packaging_binds_skill_bytes_without_shipping_roots() -> None:
    launcher = (ROOT / "packaging" / "templates" / "hwpx-mcp-server").read_text(
        encoding="utf-8"
    )
    assert '${PLUGIN_ROOT}/skills/hwpx/SKILL.md' in launcher
    assert 'export HWPX_SKILL_ROOT="${PLUGIN_ROOT}/skills/hwpx"' in launcher

    for template in (
        ROOT / "packaging" / "templates" / "openclaw.mcp-install.md",
        ROOT / "packaging" / "templates" / "hermes.mcp-install.md",
    ):
        text = template.read_text(encoding="utf-8")
        assert "Private practice campaign (opt-in)" in text
        assert all(
            name in text
            for name in (
                "HWPX_CORPUS_SOURCE",
                "HWPX_PRACTICE_ROOT",
                "HWPX_SKILL_ROOT",
            )
        )
        assert "never put" in text and "publication, adoption, merge, or release" in text


def test_clean_install_smoke_runs_workflow_protocol_e2e_from_wheels() -> None:
    smoke = (ROOT / "scripts" / "clean_install_smoke.py").read_text(encoding="utf-8")
    e2e = (ROOT / "scripts" / "plugin_mcp_e2e.py").read_text(encoding="utf-8")

    assert "plugin_mcp_e2e.py" in smoke
    assert "--server-package" in smoke and "--server-venv" in smoke
    assert 'parser.add_argument("--report", type=Path)' in smoke
    assert 'parser.add_argument("--report", type=Path)' in e2e
    assert "start_workflow" in e2e
    assert "unknown_form_fill" in e2e
    assert "approve_workflow_decision" in e2e
    assert "render_health" in e2e and "render_submit" in e2e and "render_status" in e2e
    assert "--require-real-render" in e2e


def test_skill_routes_real_hancom_render_to_one_level_reference() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    autonomous = (ROOT / "references" / "workflows-autonomous.md").read_text(encoding="utf-8")
    render = (ROOT / "references" / "workflows-real-hancom-render.md").read_text(encoding="utf-8")

    assert "references/workflows-real-hancom-render.md" in skill
    assert "`render_health` → `render_submit` → `render_status`" in skill
    assert "policy.require_real_hancom_render=true" in autonomous
    assert "`VERIFY`" in autonomous and "`resume_workflow`" in autonomous
    for tool in ("render_health", "render_submit", "render_status", "render_cancel"):
        assert f"`{tool}" in render
    assert "output_dir" in render
    assert "render_checked == true" in render
    assert "local `render_preview`" in render
