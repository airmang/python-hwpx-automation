# SPDX-License-Identifier: Apache-2.0
"""The Claude locked runtime follows the install window through a CI bot, not the user's machine."""

import importlib.util
import json
import re
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


refresh = _load("refresh_claude_runtime")
validator = _load("validate_hwpx_plugin")
IDENTITY = json.loads((ROOT / "packaging" / "product-identity.json").read_text(encoding="utf-8"))


def _file(yanked: bool = False) -> list[dict]:
    return [{"filename": "x.whl", "yanked": yanked}]


def test_newest_in_window_skips_prereleases_yanked_and_next_major() -> None:
    releases = {
        "6.5.9": _file(),
        "6.6.0": _file(),
        "6.6.1": _file(),
        "6.7.0": _file(yanked=True),
        "6.8.0rc1": _file(),
        "6.8.0": [],
        "7.0.0": _file(),
    }
    assert refresh.newest_in_window("python-hwpx", "6.6.0", releases) == "6.6.1"


def test_newest_in_window_refuses_an_empty_window() -> None:
    with pytest.raises(SystemExit, match="no published release"):
        refresh.newest_in_window("python-hwpx", "6.6.0", {"6.5.0": _file(), "7.0.0": _file()})


def test_plugin_version_is_the_train_version_only_for_the_verified_pair() -> None:
    components = IDENTITY["components"]
    plugin = components["plugin"]["currentVersion"]
    core = components["core"]["currentVersion"]
    automation = components["automation"]["currentVersion"]
    assert refresh.claude_plugin_version(plugin, core, automation, IDENTITY) == plugin
    bumped = refresh.claude_plugin_version(plugin, "6.9.9", automation, IDENTITY)
    assert bumped != plugin and bumped.startswith(plugin + "+") and "6.9.9" in bumped


def test_validator_rejects_a_claude_version_that_hides_the_runtime(tmp_path: Path) -> None:
    bundle = tmp_path / "hwpx-plugin"
    shutil.copytree(ROOT / "plugins" / "claude" / "hwpx-plugin", bundle)
    validator.validate_claude_locked_runtime(bundle, IDENTITY)  # the committed bundle is consistent

    manifest_path = bundle / ".claude-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = manifest["version"] + "-stale"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(SystemExit, match="plugin.json version"):
        validator.validate_claude_locked_runtime(bundle, IDENTITY)


def test_validator_rejects_a_pin_outside_the_window(tmp_path: Path) -> None:
    bundle = tmp_path / "hwpx-plugin"
    shutil.copytree(ROOT / "plugins" / "claude" / "hwpx-plugin", bundle)
    pyproject = bundle / "server" / "pyproject.toml"
    # The bot may already pin a newer core inside the window, so move whatever is pinned now.
    text = pyproject.read_text(encoding="utf-8")
    core = re.search(r'"python-hwpx\[[^\]]*\]==([^"]+)"', text).group(1)
    major = int(core.split(".")[0])
    pyproject.write_text(text.replace(f"=={core}", f"=={major + 1}.0.0"), encoding="utf-8")
    with pytest.raises(SystemExit, match="outside the install window"):
        validator.validate_claude_locked_runtime(bundle, IDENTITY)


def test_refresh_workflow_opens_a_pull_request_after_the_tests_run_passes() -> None:
    text = (ROOT / ".github" / "workflows" / "claude-runtime-refresh.yml").read_text(encoding="utf-8")
    assert "gh run watch" in text and "--exit-status" in text
    tests_step = text.index("Run the Tests workflow on the candidate branch")
    pr_step = text.index("gh pr create --base main")
    assert tests_step < pr_step
    assert "merge-base --is-ancestor origin/main HEAD" in text
    assert "pull-requests: write" in text


def test_refresh_workflow_never_writes_to_main_itself() -> None:
    """Passing tests must not ship freshly published PyPI code without a human (audit SEC-16)."""
    text = (ROOT / ".github" / "workflows" / "claude-runtime-refresh.yml").read_text(encoding="utf-8")
    commands = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "HEAD:main" not in commands
    assert re.search(r"git push[^\n]*\bmain\b", commands) is None
    assert "gh pr merge" not in commands and "--auto" not in commands
    # The only pushes are the candidate branch and its removal.
    pushes = re.findall(r"git push origin ([^\n]+)", commands)
    assert pushes and all(push.strip() in {'"${branch}"', '--delete "${BRANCH}"'} for push in pushes), pushes


def test_relock_moves_transitive_dependencies_forward() -> None:
    """Plain `uv lock` keeps old transitive versions forever (audit SEC-17)."""
    command = refresh.lock_command()
    assert command[:2] == ["uv", "lock"] and "--upgrade" in command
    assert str(refresh.RUNTIME) in command


def test_dependabot_watches_the_locked_runtime_but_not_the_engine_pins() -> None:
    text = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    block = text[text.index("package-ecosystem: uv"):]
    assert "directory: /packaging/templates/claude-runtime" in block
    for pinned in ("python-hwpx", "python-hwpx-automation", "tomli"):
        assert f"- dependency-name: {pinned}\n" in block
