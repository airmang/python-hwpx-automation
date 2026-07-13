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


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _version_tuple(value: str) -> tuple[int, int, int]:
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)


def test_generated_contract_covers_recovered_skill_tools() -> None:
    contract = _contract()
    names = {tool["name"] for tool in contract["tools"]}
    required = set(contract["skillRequiredTools"])

    assert RECOVERED_TOOLS <= names
    assert RECOVERED_TOOLS <= required
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
    mcp_match = re.search(r"hwpx-mcp-server==(\d+\.\d+\.\d+)", launcher)
    skill_match = re.search(r"HWPX_SKILL_VERSION:-(\d+\.\d+\.\d+)", launcher)
    assert mcp_match is not None
    assert skill_match is not None
    assert _version_tuple(mcp_match.group(1)) >= _version_tuple(contract["minMcpVersion"])
    assert _version_tuple(skill_match.group(1)) >= _version_tuple(contract["minSkillVersion"])

    for manifest in (
        ROOT / "packaging" / "templates" / "claude.plugin.json",
        ROOT / "packaging" / "templates" / "codex.plugin.json",
        ROOT / "packaging" / "templates" / "openclaw.plugin.json",
    ):
        version = json.loads(manifest.read_text(encoding="utf-8"))["version"]
        assert _version_tuple(version) >= _version_tuple(contract["minSkillVersion"])


def test_skill_routes_to_generated_api_table() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    generated = (ROOT / "references" / "tool-contract.generated.md").read_text(
        encoding="utf-8"
    )

    assert "references/tool-contract.generated.md" in skill
    for tool in RECOVERED_TOOLS:
        assert re.search(rf"`{re.escape(tool)}`", generated)
