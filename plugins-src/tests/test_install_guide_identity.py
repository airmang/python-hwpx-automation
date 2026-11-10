# SPDX-License-Identifier: Apache-2.0
"""Direct-host install guides take their coordinates from product-identity.json (audit ARC-11).

The OpenClaw and Hermes guides shipped "unpublished candidate" and a public
stack three trains old after the release, because the sentences were typed by
hand and no check looked at them.
"""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ("openclaw.mcp-install.md", "hermes.mcp-install.md")
BUNDLED = {
    "openclaw.mcp-install.md": ROOT / "plugins/openclaw/hwpx-plugin/INSTALL-mcp.md",
    "hermes.mcp-install.md": ROOT / "plugins/hermes/hwpx/INSTALL-mcp.md",
}


def _module(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _identity() -> dict:
    return json.loads((ROOT / "packaging" / "product-identity.json").read_text(encoding="utf-8"))


def _template(name: str) -> str:
    return (ROOT / "packaging" / "templates" / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", TEMPLATES)
def test_bundled_guide_is_the_template_rendered_with_identity(name: str) -> None:
    builder = _module("build_hwpx_plugins")
    identity = _identity()
    rendered = builder.render_install_guide(_template(name), identity)

    assert BUNDLED[name].read_bytes() == rendered.encode("utf-8")
    assert "{{" not in rendered
    public = identity["currentPublicStack"]
    assert f"`python-hwpx {public['core']['version']}`" in rendered
    assert f"`python-hwpx-automation {public['application']['version']}`" in rendered
    assert f"`hwpx-plugin {public['plugin']['version']}`" in rendered
    assert identity["installConstraint"]["core"] in rendered
    assert identity["installConstraint"]["automation"] in rendered
    assert identity["components"]["plugin"]["currentVersion"] in rendered
    lowered = rendered.lower()
    for stale in ("unpublished candidate", "4.2.0", "5.1.0", "0.8.0"):
        assert stale not in lowered


@pytest.mark.parametrize("name", TEMPLATES)
def test_guide_follows_identity_when_the_train_moves(name: str) -> None:
    builder = _module("build_hwpx_plugins")
    identity = copy.deepcopy(_identity())
    identity["installConstraint"] = {
        "core": "python-hwpx[preview]>=9.1.0,<10",
        "automation": "python-hwpx-automation[mcp,oracle]>=8.2.0,<9",
    }
    identity["components"]["plugin"]["currentVersion"] = "3.5.0"
    identity["currentPublicStack"]["core"]["version"] = "9.1.0"
    identity["currentPublicStack"]["application"]["version"] = "8.2.0"
    identity["currentPublicStack"]["plugin"]["version"] = "3.5.0"

    rendered = builder.render_install_guide(_template(name), identity)

    assert '"python-hwpx[preview]>=9.1.0,<10" "python-hwpx-automation[mcp,oracle]>=8.2.0,<9"' in rendered
    assert "`>=8.2.0,<9`, `>=9.1.0,<10`" in rendered
    assert "current public release: `python-hwpx 9.1.0` / `python-hwpx-automation 8.2.0` / `hwpx-plugin 3.5.0`" in rendered
    assert '"3.5.0"' in rendered
    old = _identity()["components"]
    assert old["core"]["currentVersion"] not in rendered
    assert old["automation"]["currentVersion"] not in rendered


@pytest.mark.parametrize("name", TEMPLATES)
def test_guide_states_a_pre_release_state_without_claiming_the_release(name: str) -> None:
    builder = _module("build_hwpx_plugins")
    identity = copy.deepcopy(_identity())
    identity["releaseState"]["status"] = "release-approved"
    identity["currentPublicStack"]["core"]["version"] = "6.5.0"
    identity["currentPublicStack"]["application"]["version"] = "7.2.0"
    identity["currentPublicStack"]["plugin"]["version"] = "2.3.0"

    rendered = builder.render_install_guide(_template(name), identity)

    assert "Release state `release-approved`" in rendered
    assert "not yet the public release" in rendered
    assert "The current public release is `python-hwpx 6.5.0` / `python-hwpx-automation 7.2.0` / `hwpx-plugin 2.3.0`" in rendered


def test_unknown_token_stops_the_build() -> None:
    builder = _module("build_hwpx_plugins")
    with pytest.raises(SystemExit, match="unknown tokens"):
        builder.render_install_guide("install {{HWPX_NO_SUCH_VALUE}}", _identity())


@pytest.mark.parametrize("name", TEMPLATES)
@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("{{HWPX_PLUGIN_VERSION}}", "2.4.0", "must take {{HWPX_PLUGIN_VERSION}} from product identity"),
        (
            "{{HWPX_RELEASE_NOTE}}",
            "{{HWPX_RELEASE_NOTE}}\n\nThe current public stack remains `python-hwpx 4.2.0`.",
            "hand-typed versions 4.2.0",
        ),
        (
            "{{HWPX_RELEASE_NOTE}}",
            "{{HWPX_RELEASE_NOTE}}\n\nThese coordinates are an Unpublished candidate.",
            "stale release text: unpublished candidate",
        ),
    ],
)
def test_validator_rejects_hand_typed_or_stale_template_text(name: str, old: str, new: str, message: str) -> None:
    validator = _module("validate_hwpx_plugin")
    path = ROOT / "packaging" / "templates" / name
    text = _template(name)
    validator.validate_install_guide_template(text, path, _identity())

    broken = text.replace(old, new)
    assert broken != text
    with pytest.raises(SystemExit) as raised:
        validator.validate_install_guide_template(broken, path, _identity())
    assert message in str(raised.value)


def test_validator_rejects_a_released_guide_that_still_says_unpublished() -> None:
    validator = _module("validate_hwpx_plugin")
    identity = _identity()
    assert identity["releaseState"]["status"] == "released"
    good = BUNDLED["openclaw.mcp-install.md"].read_text(encoding="utf-8")
    validator.validate_install_guide_release_text(good, Path("INSTALL-mcp.md"), identity)

    with pytest.raises(SystemExit, match="retains stale release text"):
        validator.validate_install_guide_release_text(
            good + "\nThey are not the current public marketplace release.\n", Path("INSTALL-mcp.md"), identity
        )
    with pytest.raises(SystemExit, match="does not name the public release"):
        validator.validate_install_guide_release_text(
            good.replace("`hwpx-plugin 2.4.0`", "`hwpx-plugin`"), Path("INSTALL-mcp.md"), identity
        )


def test_docs_do_not_point_at_missing_demo_directories_or_cursor_rule_files() -> None:
    docs = [ROOT / "README.md", ROOT / "SKILL.md", *sorted((ROOT / "references").glob("*.md"))]
    import re

    for path in docs:
        text = path.read_text(encoding="utf-8")
        for target in re.findall(r"`(demo/[^`\s]+)`", text):
            assert (ROOT / target).exists(), f"{path.name} points at missing {target}"
        assert ".cursor/rules/hwpx.mdc" not in text, path.name


def test_mail_merge_example_calls_the_function_it_imports() -> None:
    api = (ROOT / "references" / "api.md").read_text(encoding="utf-8")
    start = api.index("from hwpx_automation.office.document_ops import build_mail_merge")
    block = api[start:api.index("```", start)]
    assert "report = build_mail_merge(" in block
    assert "report = mail_merge(" not in block
