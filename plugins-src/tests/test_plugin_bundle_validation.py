# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _validator_module():
    script = ROOT / "scripts" / "validate_hwpx_plugin.py"
    spec = importlib.util.spec_from_file_location("validate_hwpx_plugin", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _identity() -> dict:
    return json.loads(
        (ROOT / "packaging" / "product-identity.json").read_text(encoding="utf-8")
    )


def test_generated_plugin_bundles_validate() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_hwpx_plugin.py")],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_markdown_link_validator_accepts_only_safe_existing_relative_targets(
    tmp_path: Path,
) -> None:
    validator = _validator_module()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "target.md").write_text("# target\n", encoding="utf-8")
    markdown = docs / "index.md"
    markdown.write_text(
        "[local](target.md#section) [external](https://example.com/docs) [anchor](#here)\n",
        encoding="utf-8",
    )

    validator.validate_markdown_links([markdown], tmp_path, "test")

    unsafe_targets = (
        "missing.md",
        "../outside.md",
        "/absolute.md",
        "//example.com/path",
        "file:///tmp/secret",
        "javascript:alert(1)",
        "%2e%2e/outside.md",
    )
    for target in unsafe_targets:
        markdown.write_text(f"[unsafe]({target})\n", encoding="utf-8")
        with pytest.raises(SystemExit):
            validator.validate_markdown_links([markdown], tmp_path, "test")


def test_packaging_carries_identity_changelog_and_toc_but_not_qa_fixture_routes() -> None:
    config = json.loads((ROOT / "packaging" / "hosts.json").read_text(encoding="utf-8"))
    assets = set(config["sharedAssets"])

    assert "packaging/product-identity.json" in assets
    assert "CHANGELOG.md" in assets
    assert "references/workflows-toc.md" in assets
    assert "references/workflows-visual-fixture-qa.md" not in assets
    assert "references/workflows-fixture-benchmark.md" not in assets
    assert "scripts/plugin_fixture_qa_e2e.py" not in assets


def test_bundled_launchers_use_isolated_editable_dev_stack() -> None:
    launchers = sorted((ROOT / "plugins").glob("*/hwpx*/scripts/hwpx-mcp-server"))
    assert launchers

    for launcher in launchers:
        text = launcher.read_text(encoding="utf-8")
        assert "uv run --no-project" in text
        assert "uv run --project" not in text
        assert '--with-editable "${PYTHON_HWPX_REPO}[visual]"' in text
        assert '--with-editable "${MCP_REPO}"' in text
        assert "HWPX_MCP_RUNTIME_ROOT" in text
        assert 'rm -rf "${VENV_DIR}"' not in text


def test_codex_mcp_command_is_workspace_preserving_and_root_independent() -> None:
    components = _identity()["components"]
    config = json.loads(
        (ROOT / "plugins/codex/hwpx-plugin/.mcp.json").read_text(encoding="utf-8")
    )["mcpServers"]["hwpx-mcp-server"]
    assert config["command"] == "uvx"
    assert "cwd" not in config
    assert (
        f"{components['mcp']['distribution']}=={components['mcp']['currentVersion']}"
        in config["args"]
    )
    assert (
        f"{components['core']['distribution']}[visual]=={components['core']['currentVersion']}"
        in config["args"]
    )


def test_claude_mcp_command_preserves_project_cwd() -> None:
    config = json.loads(
        (ROOT / "plugins/claude/hwpx-plugin/.mcp.json").read_text(encoding="utf-8")
    )["mcpServers"]["hwpx-mcp-server"]
    assert config["command"].startswith("${CLAUDE_PLUGIN_ROOT}/")
    assert "cwd" not in config


def test_quickcheck_verifies_editor_open_safety_for_generated_outputs() -> None:
    quickchecks = [ROOT / "scripts" / "quickcheck.py"]
    quickchecks.extend(sorted((ROOT / "plugins").glob("*/hwpx*/scripts/quickcheck.py")))
    assert quickchecks

    for quickcheck in quickchecks:
        text = quickcheck.read_text(encoding="utf-8")
        assert "validate_editor_open_safety" in text
        assert "create-open-safety" in text
        assert "proposal-open-safety" in text
        assert "document-plan-open-safety" in text
        assert "builder-open-safety" in text
        assert "operating-plan-open-safety" in text
        assert "template-formfit-open-safety" in text


def test_namespace_helpers_require_editor_open_safety_validator() -> None:
    helpers = [ROOT / "scripts" / "fix_namespaces.py"]
    helpers.extend(sorted((ROOT / "plugins").glob("*/hwpx*/scripts/fix_namespaces.py")))
    assert helpers

    for helper in helpers:
        text = helper.read_text(encoding="utf-8")
        assert "validate_editor_open_safety" in text
        assert "python-hwpx>=2.10.3 is required" in text
        assert "validate_package(" not in text
        assert "HwpxDocument.open" not in text
        assert "verify_open_safety" not in text


def test_zip_replace_helpers_do_not_expose_open_safety_bypass() -> None:
    helpers = [ROOT / "scripts" / "zip_replace_all.py"]
    helpers.extend(sorted((ROOT / "plugins").glob("*/hwpx*/scripts/zip_replace_all.py")))
    assert helpers

    for helper in helpers:
        text = helper.read_text(encoding="utf-8")
        assert "validate_open_safety" in text
        assert "verify_open_safety" not in text


def test_template_replace_examples_route_through_validated_helpers() -> None:
    examples = [ROOT / "examples" / "03_template_replace.py"]
    examples.extend(sorted((ROOT / "plugins").glob("*/hwpx*/**/examples/03_template_replace.py")))
    assert examples

    for example in examples:
        text = example.read_text(encoding="utf-8")
        assert "zip_replace_all(" in text
        assert "fix_namespaces(" in text
        assert "zipfile.ZipFile" not in text
        assert "os.replace" not in text
        assert "verify_open_safety" not in text


def test_api_reference_requires_current_open_safety_stack() -> None:
    references = [ROOT / "references" / "api.md"]
    references.extend(sorted((ROOT / "plugins").glob("*/hwpx*/references/api.md")))
    assert references

    for reference in references:
        text = reference.read_text(encoding="utf-8")
        assert "`python-hwpx 3.6.0`" in text
        assert "공개 릴리스" in text
        assert "최소 호환 버전" in text
        assert "플러그인 설치 핀" in text
        assert "validate_editor_open_safety(path).ok == True" in text
        assert "2.11.1" not in text
        assert "2.5.0" not in text


def test_task_eval_harness_assets_are_bundled() -> None:
    bundles = sorted((ROOT / "plugins").glob("*/hwpx*"))
    assert bundles

    for bundle in bundles:
        skill_root = bundle / "skills" / "hwpx"
        if not skill_root.exists():
            skill_root = bundle
        assert (skill_root / "scripts" / "task_eval_harness.py").exists()
        assert (skill_root / "examples" / "12_task_eval_replay.md").exists()
        assert (skill_root / "examples" / "eval_tasks" / "tasks.json").exists()
        assert (
            skill_root
            / "examples"
            / "eval_tasks"
            / "profiles"
            / "current-0.6.3.json"
        ).exists()
        assert (
            skill_root
            / "examples"
            / "eval_tasks"
            / "profiles"
            / "current-0.1.6.json"
        ).exists()


def test_generated_bundles_carry_toc_changelog_identity_and_exclude_internal_qa() -> None:
    bundles = sorted((ROOT / "plugins").glob("*/hwpx*"))
    assert len(bundles) == 4
    for bundle in bundles:
        skill_root = bundle / "skills" / "hwpx"
        if not skill_root.exists():
            skill_root = bundle
        assert (skill_root / "references" / "workflows-toc.md").is_file()
        assert (skill_root / "CHANGELOG.md").is_file()
        assert (skill_root / "packaging" / "product-identity.json").is_file()
        assert not (skill_root / "references" / "workflows-visual-fixture-qa.md").exists()
        assert not (skill_root / "references" / "workflows-fixture-benchmark.md").exists()
        assert not (skill_root / "scripts" / "plugin_fixture_qa_e2e.py").exists()


def test_product_identity_is_the_name_version_and_maturity_authority() -> None:
    identity = _identity()
    components = identity["components"]
    hosts = json.loads((ROOT / "packaging" / "hosts.json").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert identity["schemaVersion"] == "hwpx.product-identity.v1"
    assert identity["releaseState"] == "released"
    assert components["core"]["currentVersion"] == "3.6.0"
    assert components["core"]["minimumCompatibleVersion"] == "3.3.1"
    assert components["mcp"]["currentVersion"] == "4.3.0"
    assert components["mcp"]["minimumCompatibleVersion"] == "4.3.0"
    assert components["plugin"]["currentVersion"] == "0.6.3"
    assert components["plugin"]["minimumCompatibleVersion"] == "0.5.0"
    assert hosts["identityFile"] == "product-identity.json"
    assert "pluginName" not in hosts and "skillName" not in hosts
    assert identity["firstPartyLabelKo"] in readme
    assert components["core"]["maturity"] == "alpha"
    assert components["mcp"]["maturity"] == "not-declared"
    assert components["plugin"]["maturity"] == "not-declared"
    for host in hosts["hosts"]:
        assert "version:" not in host.get("frontmatterExtra", "")
