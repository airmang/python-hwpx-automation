# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
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


def _builder_module():
    script = ROOT / "scripts" / "build_hwpx_plugins.py"
    spec = importlib.util.spec_from_file_location("build_hwpx_plugins", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clean_smoke_module():
    script = ROOT / "scripts" / "clean_install_smoke.py"
    spec = importlib.util.spec_from_file_location("clean_install_smoke", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _plugin_e2e_module():
    script = ROOT / "scripts" / "plugin_mcp_e2e.py"
    spec = importlib.util.spec_from_file_location("plugin_mcp_e2e", script)
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
    assert "packaging/old-name-taxonomy.json" in assets
    assert "CHANGELOG.md" in assets
    assert "references/workflows-toc.md" in assets
    assert "examples/10_create_government_report.py" in assets
    assert "examples/10_mcp_government_report.md" in assets
    assert "examples/11_computeruse_visual_review.md" in assets
    assert "scripts/detect_hwpx_viewer.py" in assets
    assert "scripts/visual_review_batch.py" in assets
    user_examples = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "examples").iterdir()
        if path.is_file() and path.suffix in {".py", ".md"}
    }
    assert user_examples <= assets
    assert "references/workflows-visual-fixture-qa.md" not in assets
    assert "references/workflows-fixture-benchmark.md" not in assets
    assert "scripts/plugin_fixture_qa_e2e.py" not in assets


def test_bundled_launchers_use_isolated_editable_dev_stack() -> None:
    assert os.access(
        ROOT / "packaging" / "templates" / "hwpx-automation-mcp",
        os.X_OK,
    )
    assert os.access(
        ROOT / "packaging" / "templates" / "hwpx-mcp-server",
        os.X_OK,
    )
    launchers = sorted((ROOT / "plugins").glob("*/hwpx*/scripts/hwpx-automation-mcp"))
    assert launchers

    for launcher in launchers:
        text = launcher.read_text(encoding="utf-8")
        assert "uv run --no-project" in text
        assert "uv run --project" not in text
        assert '--with-editable "${PYTHON_HWPX_REPO}[preview]"' in text
        assert '--with-editable "${MCP_REPO}[mcp,oracle]"' in text
        assert '--with-editable "${MCP_REPO}[mcp]"' not in text
        assert "HWPX_AUTOMATION_RUNTIME_ROOT" in text
        assert "find_stack_root" not in text
        assert "Editable mode is deliberately opt-in" in text
        assert '"runtimeLayout": "relocatable-console-v1"' in text
        assert "uv venv --quiet --relocatable" in text
        assert 'RUNTIME_CONSOLE="${VENV_DIR}/bin/hwpx-automation-mcp"' in text
        assert "relocated hwpx-automation-mcp console self-check failed" in text
        assert "-m hwpx_automation.server" not in text
        assert 'rm -rf "${VENV_DIR}"' not in text
        compatibility = launcher.with_name("hwpx-mcp-server")
        compatibility_text = compatibility.read_text(encoding="utf-8")
        assert 'exec "${SCRIPT_DIR}/hwpx-automation-mcp" "$@"' in compatibility_text
        assert "SERVER_PACKAGE=" not in compatibility_text
        assert "uv pip install" not in compatibility_text


def test_codex_mcp_command_is_workspace_preserving_and_root_independent() -> None:
    components = _identity()["components"]
    config = json.loads(
        (ROOT / "plugins/codex/hwpx-plugin/.mcp.json").read_text(encoding="utf-8")
    )
    assert set(config["mcpServers"]) == {"hwpx"}
    config = config["mcpServers"]["hwpx"]
    assert config["command"] == "uvx"
    assert "cwd" not in config
    # extra를 포함한 핀이어야 한다. 6.0.0부터 mcp SDK는 필수가 아니라 [mcp]
    # extra이므로, extra 없는 핀으로 설치하면 MCP 서버가 없는 환경이 된다.
    automation = components["automation"]
    extras = ",".join(automation["pluginInstallExtras"])
    assert (
        f"{automation['distribution']}[{extras}]=={automation['currentVersion']}"
        in config["args"]
    )
    assert (
        f"{components['core']['distribution']}[preview]=={components['core']['currentVersion']}"
        in config["args"]
    )
    assert automation["mcpConsole"] in config["args"]
    assert config["env"]["HWPX_AUTOMATION_ADVANCED"] == "0"


def test_claude_mcp_command_preserves_project_cwd() -> None:
    config = json.loads(
        (ROOT / "plugins/claude/hwpx-plugin/.mcp.json").read_text(encoding="utf-8")
    )
    assert set(config["mcpServers"]) == {"hwpx"}
    config = config["mcpServers"]["hwpx"]
    assert config["command"].startswith("${CLAUDE_PLUGIN_ROOT}/")
    assert config["command"].endswith("/scripts/hwpx-automation-mcp")
    assert "scripts/hwpx-mcp-server" not in config["command"]
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

    status = _identity()["releaseState"]["status"]
    for reference in references:
        text = reference.read_text(encoding="utf-8")
        assert "`python-hwpx 4.2.0`" not in text
        assert "`hwpx-mcp-server 5.1.0`" not in text
        assert "`hwpx-plugin 0.8.0`" not in text
        assert "`python-hwpx 5.0.1`" not in text
        assert "`hwpx-plugin 1.0.0`" not in text
        assert "`python-hwpx 5.0.2`" in text
        assert "`python-hwpx-automation 6.0.4`" in text
        assert "`hwpx-plugin 1.0.1`" in text
        assert "공개 릴리스" in text
        if status == "released":
            assert "미발행 후보" not in text
        else:
            # candidate checkout: the doc must distinguish the unreleased
            # candidate train from the public train, not hide it
            assert "미발행 후보" in text
            assert "`python-hwpx 5.1.0`" in text
            assert "`python-hwpx-automation 6.1.0`" in text
            assert "`hwpx-plugin 1.1.0`" in text
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
            / "current-1.0.0.json"
        ).exists()
        assert (
            skill_root
            / "examples"
            / "eval_tasks"
            / "profiles"
            / "current-1.1.0.json"
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
        assert (skill_root / "packaging" / "old-name-taxonomy.json").is_file()
        assert not (skill_root / "references" / "workflows-visual-fixture-qa.md").exists()
        assert not (skill_root / "references" / "workflows-fixture-benchmark.md").exists()
        assert not (skill_root / "scripts" / "plugin_fixture_qa_e2e.py").exists()


def test_product_identity_is_the_name_version_and_maturity_authority() -> None:
    identity = _identity()
    components = identity["components"]
    hosts = json.loads((ROOT / "packaging" / "hosts.json").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert identity["schemaVersion"] == "hwpx.product-identity.v3"
    assert identity["releaseState"] == {
        "status": "unreleased-candidate",
        "candidate": {
            "pythonHwpx": "5.1.0",
            "canonicalDistribution": "python-hwpx-automation",
            "canonicalAutomation": "6.1.0",
            "compatibilityDistribution": "hwpx-mcp-server",
            "compatibility": "6.1.0",
            "plugin": "1.1.0",
            "contractHash": "ac1a422376b5ac84",
        },
        "currentPublic": {
            "pythonHwpx": "5.0.2",
            "primaryDistribution": "python-hwpx-automation",
            "primaryApplication": "6.0.4",
            "plugin": "1.0.1",
            "contractHash": "0ce938371f0b55a6",
        },
        "promotionGate": (
            "Three states are mandatory: unreleased-candidate while auditing; "
            "release-approved only after separate owner approval and while "
            "currentPublic still names the previously observed coherent stack; "
            "released only in a follow-up commit after remote truth is observed "
            "for core, canonical automation, the compatibility distribution, the "
            "plugin GitHub release, the marketplace entry, and a real marketplace "
            "install. The automation tag workflow publishes only release-approved, "
            "leaves currentPublic unchanged, and hands an attached receipt to "
            "plugin publication."
        ),
    }
    assert identity["currentPublicStack"] == {
        "core": {"distribution": "python-hwpx", "version": "5.0.2"},
        "application": {
            "distribution": "python-hwpx-automation",
            "version": "6.0.4",
        },
        "plugin": {"installedPluginId": "hwpx-plugin", "version": "1.0.1"},
    }
    assert components["core"]["currentVersion"] == "5.1.0"
    assert components["core"]["minimumCompatibleVersion"] == "5.1.0"
    assert components["automation"]["currentVersion"] == "6.1.0"
    assert components["automation"]["minimumCompatibleVersion"] == "6.1.0"
    assert components["automation"]["mcpConsole"] == "hwpx-automation-mcp"
    assert components["automation"]["hostConfigKey"] == "hwpx"
    assert components["automation"]["hostConfigKeyKind"] == "local-alias"
    assert components["automation"]["launcherPath"] == "scripts/hwpx-automation-mcp"
    assert identity["compatibility"]["hostConfigKey"] == "hwpx-mcp-server"
    assert identity["compatibility"]["launcherPath"] == "scripts/hwpx-mcp-server"
    assert components["plugin"]["currentVersion"] == "1.1.0"
    assert components["plugin"]["minimumCompatibleVersion"] == "1.1.0"
    assert hosts["identityFile"] == "product-identity.json"
    assert "pluginName" not in hosts and "skillName" not in hosts
    assert identity["firstPartyLabelKo"] in readme
    assert components["core"]["maturity"] == "alpha"
    assert components["automation"]["maturity"] == "not-declared"
    assert components["plugin"]["maturity"] == "not-declared"
    for host in hosts["hosts"]:
        assert "version:" not in host.get("frontmatterExtra", "")


@pytest.mark.parametrize("status", ("release-approved", "released"))
def test_product_identity_validator_supports_the_full_release_lifecycle(
    tmp_path: Path,
    status: str,
) -> None:
    checkout = tmp_path / "hwpx-plugins"
    shutil.copytree(
        ROOT,
        checkout,
        ignore=shutil.ignore_patterns(
            ".git",
            ".pytest_cache",
            "__pycache__",
            "examples/out",
        ),
    )
    identity_path = checkout / "packaging" / "product-identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity["releaseState"]["status"] = status
    if status != "released":
        # A pre-released synthesis must carry the PREVIOUS public stack: the
        # validator requires unreleased/approved states to keep naming the
        # last coherent public train (the 2026-07-28 5.0.1 train).
        identity["releaseState"]["currentPublic"] = {
            "pythonHwpx": "5.0.2",
            "primaryDistribution": "python-hwpx-automation",
            "primaryApplication": "6.0.4",
            "plugin": "1.0.1",
            "contractHash": "0ce938371f0b55a6",
        }
        identity["currentPublicStack"] = {
            "core": {"distribution": "python-hwpx", "version": "5.0.2"},
            "application": {
                "distribution": "python-hwpx-automation",
                "version": "6.0.4",
            },
            "plugin": {"installedPluginId": "hwpx-plugin", "version": "1.0.1"},
        }

    readme_path = checkout / "README.md"
    api_path = checkout / "references" / "api.md"
    cross_readme_path = (
        checkout / "packaging" / "s080-cross-repo-readme-wording.md"
    )
    readme = re.sub(
        r"<!-- release-state: [a-z-]+ -->",
        f"<!-- release-state: {status} -->",
        readme_path.read_text(encoding="utf-8"),
        count=1,
    )
    api = api_path.read_text(encoding="utf-8")
    cross_readme = cross_readme_path.read_text(encoding="utf-8")
    if status == "release-approved":
        # The pre-released fragment sets also require the previous public
        # coordinates to be visible; the released checkout no longer carries
        # them, so the synthesis injects them alongside the state note.
        prior = (
            "\n미발행 후보: `python-hwpx 5.1.0` · `python-hwpx-automation 6.1.0` ·"
            " `hwpx-plugin 1.1.0`\n"
        )
        readme += prior + "\nrelease-approved: remote truth is still pending.\n"
        api += prior + "\nrelease-approved: remote truth is still pending.\n"
        cross_readme += (
            "\npython-hwpx-automation 6.1.0 / python-hwpx 5.1.0 / hwpx-plugin 1.1.0\n"
            "\nrelease-approved: remote truth is still pending.\n"
        )
    else:
        promoted = {
            "pythonHwpx": "5.1.0",
            "primaryDistribution": "python-hwpx-automation",
            "primaryApplication": "6.1.0",
            "plugin": "1.1.0",
            "contractHash": "ac1a422376b5ac84",
        }
        identity["releaseState"]["currentPublic"] = promoted
        identity["currentPublicStack"] = {
            "core": {"distribution": "python-hwpx", "version": "5.1.0"},
            "application": {
                "distribution": "python-hwpx-automation",
                "version": "6.1.0",
            },
            "plugin": {"installedPluginId": "hwpx-plugin", "version": "1.1.0"},
        }
        for stale in (
            "아직 공개되지 않은 1.1.0 미발행 후보",
            "미발행 후보",
            "`python-hwpx 4.2.0`",
            "`hwpx-mcp-server 5.1.0`",
            "`hwpx-plugin 0.8.0`",
            "`python-hwpx 5.0.1`",
            "`hwpx-plugin 1.0.0`",
        ):
            readme = readme.replace(stale, "공개 전환 완료")
            api = api.replace(stale, "공개 전환 완료")
            cross_readme = cross_readme.replace(stale.strip("`"), "공개 전환 완료")
        readme += "\nreleased\n"
        api += "\nreleased\n"
        cross_readme += (
            "\nreleased\n"
            "python-hwpx 5.1.0\n"
            "python-hwpx-automation 6.1.0\n"
            "hwpx-plugin 1.1.0\n"
        )

    identity_path.write_text(
        json.dumps(identity, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    readme_path.write_text(readme, encoding="utf-8")
    api_path.write_text(api, encoding="utf-8")
    cross_readme_path.write_text(cross_readme, encoding="utf-8")

    built = subprocess.run(
        [sys.executable, "scripts/build_hwpx_plugins.py"],
        cwd=checkout,
        check=False,
        text=True,
        capture_output=True,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    validated = subprocess.run(
        [sys.executable, "scripts/validate_hwpx_plugin.py"],
        cwd=checkout,
        check=False,
        text=True,
        capture_output=True,
    )
    assert validated.returncode == 0, validated.stdout + validated.stderr


def _shipped_guidance() -> list[Path]:
    """Every user-facing document that states a version the reader will act on."""
    return [ROOT / "README.md", ROOT / "SKILL.md", *sorted((ROOT / "references").glob("*.md"))]


def test_no_shipped_guidance_states_a_superseded_version_floor() -> None:
    """The identity file must be the authority in fact, not only by declaration.

    It already named 5.0.0/6.0.0/1.0.0 while README and ``references/api.md``
    still told readers the contract supported core >=4.2.0 and MCP >=5.1.0, and
    api.md's install-pin row named a package pair that cannot run this skill —
    disagreeing with README's own pin row two files away. Nothing failed,
    because the previous test only checked that the identity file said the right
    thing.

    So this compares what the documents state against what the identity file
    declares. A floor below the declared minimum is the failure: a reader who
    installs what the sentence says gets a stack this skill does not support.
    """

    identity = _identity()
    components = identity["components"]
    # 세 이름을 다 본다. 6.0.0에서 응용 배포가 python-hwpx-automation이 됐고,
    # hwpx-mcp-server는 같은 버전을 끌어오는 호환 셸로 남았다. 새 이름을
    # 목록에서 빠뜨리면 게이트가 정작 현재 배포명의 낡은 바닥을 못 잡는다.
    minimums = {
        "python-hwpx": components["core"]["minimumCompatibleVersion"],
        "python-hwpx-automation": components["automation"]["minimumCompatibleVersion"],
        "hwpx-mcp-server": components["automation"]["minimumCompatibleVersion"],
    }

    # 긴 이름을 먼저 — python-hwpx가 python-hwpx-automation의 접두사다.
    names = "|".join(sorted(minimums, key=len, reverse=True))
    pattern = re.compile(
        rf"({names})(?:\[[^\]]*\])?\s*(>=|==)\s*(\d+)\.(\d+)\.(\d+)"
    )
    stale: list[str] = []
    for document in _shipped_guidance():
        for number, line in enumerate(document.read_text(encoding="utf-8").splitlines(), 1):
            for package, operator, *parts in pattern.findall(line):
                stated = tuple(int(part) for part in parts)
                required = tuple(int(part) for part in minimums[package].split("."))
                if stated < required:
                    stale.append(
                        f"{document.relative_to(ROOT)}:{number}: "
                        f"{package}{operator}{'.'.join(parts)} "
                        f"is below the declared minimum {minimums[package]}"
                    )

    assert not stale, "shipped guidance names superseded versions:\n" + "\n".join(stale)


def test_bundle_rebuild_preserves_untracked_runtime_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder = _builder_module()
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    out = tmp_path / "plugins" / "claude" / "hwpx-plugin"
    generated = out / "skills" / "hwpx" / "README.md"
    generated.parent.mkdir(parents=True)
    generated.write_text("generated\n", encoding="utf-8")
    runtime_output = out / "skills" / "hwpx" / "examples" / "out" / "result.hwpx"
    runtime_output.parent.mkdir(parents=True)
    runtime_output.write_bytes(b"runtime-output")
    (out / "plugin-sync.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "dest": generated.relative_to(tmp_path).as_posix(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    builder.remove_previous_generated_files(out)

    assert not generated.exists()
    assert runtime_output.read_bytes() == b"runtime-output"


def test_legacy_release_stack_is_hard_disabled() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "release_stack.py"), "--yes"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 78
    assert "no release action was performed" in result.stderr


def test_clean_install_smoke_requires_explicit_candidate_checkouts() -> None:
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "PYTHON_HWPX_CANDIDATE_REPO",
            "HWPX_AUTOMATION_CANDIDATE_REPO",
        }
    }
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "clean_install_smoke.py")],
        cwd=ROOT,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "core candidate checkout is required" in result.stderr
    assert "--core-repo" in result.stderr


def test_clean_runtime_environment_strips_ambient_python_source_selectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke = _clean_smoke_module()
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        monkeypatch.setenv(name, f"/poison/{name.lower()}")

    sanitized = smoke._sanitized_environment()

    assert all(name not in sanitized for name in smoke._SOURCE_AFFECTING_ENV)
    assert "PATH" in sanitized


def test_e2e_uses_canonical_host_key_and_legacy_requires_explicit_override(
    tmp_path: Path,
) -> None:
    e2e = _plugin_e2e_module()
    source = tmp_path / ".mcp.json"
    canonical = {"command": "canonical"}
    legacy = {"command": "compatibility"}
    payload = {"mcpServers": {"hwpx": canonical, "hwpx-mcp-server": legacy}}

    assert e2e.DEFAULT_MCP_CONFIG_KEY == "hwpx"
    assert not (
        {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}
        & e2e._sanitized_environment(
            {
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": "/poison/pythonpath",
                "PYTHONHOME": "/poison/pythonhome",
                "VIRTUAL_ENV": "/poison/venv",
            }
        ).keys()
    )
    assert e2e._select_mcp_server(
        payload,
        e2e.DEFAULT_MCP_CONFIG_KEY,
        source=source,
    ) == canonical
    assert e2e._select_mcp_server(
        payload,
        e2e.LEGACY_MCP_CONFIG_KEY,
        source=source,
    ) == legacy
    with pytest.raises(RuntimeError, match="'hwpx'.*absent"):
        e2e._select_mcp_server(
            {"mcpServers": {"hwpx-mcp-server": legacy}},
            e2e.DEFAULT_MCP_CONFIG_KEY,
            source=source,
        )


def test_ci_requires_reviewed_candidate_refs_without_fake_commit_pins() -> None:
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8"
    )
    assert "HWPX_CORE_CANDIDATE_REF" in workflow
    assert "HWPX_AUTOMATION_CANDIDATE_REF" in workflow
    assert "Require explicit candidate refs" in workflow
    assert "path: python-hwpx-automation" in workflow
    assert "--automation-repo ../python-hwpx-automation" in workflow
    assert "--mcp-repo ../python-hwpx-automation" not in workflow
    assert "f6b79f010d40a190fa6a8391eb212835022b3851" not in workflow
    assert "c0cb5bb347fdb2e76333d7145845efd3d62d069a" not in workflow


def test_old_name_taxonomy_is_explicit_and_has_no_unreviewed_class() -> None:
    taxonomy = json.loads(
        (ROOT / "packaging" / "old-name-taxonomy.json").read_text(
            encoding="utf-8"
        )
    )
    classifications = {entry["classification"] for entry in taxonomy["entries"]}
    assert {"canonical", "compatibility", "historical", "generated"} <= classifications
    assert classifications <= set(taxonomy["allowedClassifications"])
    assert all(entry["classification"] != "stale-defect" for entry in taxonomy["entries"])
    surfaces = {
        (entry["surface"], entry["value"], entry["classification"])
        for entry in taxonomy["entries"]
    }
    assert ("host config key", "hwpx", "canonical") in surfaces
    assert ("host config key", "hwpx-mcp-server", "compatibility") in surfaces
    assert ("launcher filename", "scripts/hwpx-automation-mcp", "canonical") in surfaces
    assert (
        "launcher filename",
        "scripts/hwpx-mcp-server",
        "compatibility",
    ) in surfaces


def test_public_bundles_and_scripts_have_no_internal_stage_or_worktree_names() -> None:
    codename = re.compile(r"(?<![A-Za-z0-9])(?:S-[0-9]{3}|STG-[A-Za-z0-9_-]+)")
    worktree = re.compile(
        r"(?:python-hwpx(?:-automation)?|hwpx-mcp-server|hwpx-skill)-s[0-9]{3}\b",
        re.IGNORECASE,
    )
    paths = [
        *sorted((ROOT / "plugins").rglob("*")),
        *sorted((ROOT / "scripts").glob("*.py")),
    ]
    failures = []
    for path in paths:
        if not path.is_file() or "examples/out" in path.as_posix():
            continue
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue
        text = data.decode("utf-8", "replace")
        if codename.search(text) or worktree.search(text):
            failures.append(path.relative_to(ROOT).as_posix())
    assert not failures


def test_shipped_python_and_markdown_code_blocks_parse() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_shipped_code.py")],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "JSON Markdown fences" in result.stdout
