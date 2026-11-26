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


def _bundle_pinned_at(tmp_path: Path, core: str, automation: str) -> Path:
    """The committed Claude bundle with its two pins rewritten (lock and manifest left as they are)."""

    bundle = tmp_path / "hwpx-plugin"
    shutil.copytree(ROOT / "plugins" / "claude" / "hwpx-plugin", bundle)
    pyproject = bundle / "server" / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    text = re.sub(r'("python-hwpx\[[^\]]*\]==)[^"]+"', rf'\g<1>{core}"', text)
    text = re.sub(r'("python-hwpx-automation\[[^\]]*\]==)[^"]+"', rf'\g<1>{automation}"', text)
    pyproject.write_text(text, encoding="utf-8")
    return bundle


def _identity_with(status: str, public_core: str, public_automation: str, core: str, automation: str) -> dict:
    identity = json.loads(json.dumps(IDENTITY))
    identity["releaseState"]["status"] = status
    identity["releaseState"]["currentPublic"]["pythonHwpx"] = public_core
    identity["releaseState"]["currentPublic"]["primaryApplication"] = public_automation
    identity["components"]["core"]["currentVersion"] = core
    identity["components"]["automation"]["currentVersion"] = automation
    return identity


def _window_refusal(bundle: Path, identity: dict) -> str | None:
    """The install-window refusal for *bundle*, or None when the window admits its pins.

    Later checks (the lock, the manifest) may refuse a rewritten bundle for their own reasons; only
    the window's verdict is read here.
    """

    try:
        validator.validate_claude_locked_runtime(bundle, identity)
    except SystemExit as refused:
        return str(refused) if "outside the install window" in str(refused) else None
    return None


def test_before_publication_the_window_floor_is_the_public_pair(tmp_path: Path) -> None:
    """An approved candidate is not on PyPI, so the lock keeps the public pair until it is."""

    bundle = _bundle_pinned_at(tmp_path, "7.0.0", "8.0.0")
    approved = _identity_with("release-approved", "7.0.0", "8.0.0", core="7.0.2", automation="8.0.1")
    assert _window_refusal(bundle, approved) is None

    # once released the verified pair is the floor again: the same lock is stale
    released = _identity_with("released", "7.0.2", "8.0.1", core="7.0.2", automation="8.0.1")
    refusal = _window_refusal(bundle, released)
    assert refusal is not None and ">=7.0.2,<8" in refusal


def test_before_publication_a_pin_below_the_public_pair_is_still_refused(tmp_path: Path) -> None:
    bundle = _bundle_pinned_at(tmp_path, "7.0.0", "7.9.0")
    approved = _identity_with("release-approved", "7.0.0", "8.0.0", core="7.0.2", automation="8.0.1")
    refusal = _window_refusal(bundle, approved)
    assert refusal is not None and "python-hwpx-automation" in refusal and ">=8.0.0,<9" in refusal


def test_before_publication_a_pin_of_another_major_is_still_refused(tmp_path: Path) -> None:
    bundle = _bundle_pinned_at(tmp_path, "8.0.0", "8.0.0")
    approved = _identity_with("release-approved", "7.0.0", "8.0.0", core="7.0.2", automation="8.0.1")
    refusal = _window_refusal(bundle, approved)
    assert refusal is not None and "python-hwpx pin" in refusal


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


def test_the_locked_runtime_installs_the_equation_renderer() -> None:
    """The preview moved from python-hwpx to python-hwpx-automation in 8.0, so the core
    ``preview`` extra brings nothing. The runtime pinned only that one, the bundle had no
    latex2mathml, and render_preview showed every equation as a LaTeX code block
    (reliability audit CS-11)."""

    import tomllib

    runtime = ROOT / "packaging" / "templates" / "claude-runtime"
    project = tomllib.loads((runtime / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    extras = {
        spec.split("[")[0]: spec.split("[")[1].split("]")[0].split(",")
        for spec in project["dependencies"]
    }
    # every host's install extras, with oracle left to the render group
    assert extras["python-hwpx-automation"] == [
        extra for extra in validator.PLUGIN_INSTALL_EXTRAS if extra != "oracle"
    ]
    assert "preview" in extras["python-hwpx-automation"]

    # the extra is one python-hwpx-automation declares, and it is the one with the renderer
    automation = tomllib.loads((ROOT.parent / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    declared = automation["optional-dependencies"]
    assert all(extra in declared for extra in extras["python-hwpx-automation"])
    assert any(spec.startswith(validator.CLAUDE_EQUATION_RENDERER) for spec in declared["preview"])

    lock = tomllib.loads((runtime / "uv.lock").read_text(encoding="utf-8"))
    packages = {package["name"]: package for package in lock["package"]}
    assert validator.CLAUDE_EQUATION_RENDERER in packages
    root = next(p for p in lock["package"] if p.get("source", {}).get("virtual") == ".")
    default = [d for d in root["dependencies"] if d["name"] == "python-hwpx-automation"]
    assert default == [{"name": "python-hwpx-automation", "extra": ["mcp", "preview"]}]
    locked_extra = packages["python-hwpx-automation"]["optional-dependencies"]["preview"]
    assert {"name": validator.CLAUDE_EQUATION_RENDERER} in locked_extra
    for artifact in [packages[validator.CLAUDE_EQUATION_RENDERER].get("sdist"),
                     *packages[validator.CLAUDE_EQUATION_RENDERER].get("wheels", [])]:
        assert artifact is None or artifact["hash"].startswith("sha256:")


def test_validator_rejects_a_runtime_without_the_preview_extra(tmp_path: Path) -> None:
    bundle = tmp_path / "hwpx-plugin"
    shutil.copytree(ROOT / "plugins" / "claude" / "hwpx-plugin", bundle)
    pyproject = bundle / "server" / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert '"python-hwpx-automation[mcp,preview]==' in text
    pyproject.write_text(
        text.replace('"python-hwpx-automation[mcp,preview]==', '"python-hwpx-automation[mcp]=='),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="preview brings latex2mathml"):
        validator.validate_claude_locked_runtime(bundle, IDENTITY)
