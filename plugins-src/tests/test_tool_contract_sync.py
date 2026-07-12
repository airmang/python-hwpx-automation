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
    assert contract["defaultToolCount"] == 118
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
