# SPDX-License-Identifier: Apache-2.0
"""Every host installs the equation renderer, not only the Claude bundle.

The preview moved from python-hwpx to python-hwpx-automation in 8.0, and with it the optional
``latex2mathml`` (automation's ``preview`` extra): the core ``preview`` extra brings nothing.
The Claude locked runtime was corrected to install ``python-hwpx-automation[mcp,preview]``, but
the managed launcher (Codex) and the OpenClaw and Hermes install guides still asked for
``[mcp,oracle]`` only, so ``render_preview`` showed every equation as a LaTeX code block there
(reliability audit CS-11).
"""

import copy
import importlib.util
import json
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "packaging" / "templates"
LAUNCHER = TEMPLATES / "hwpx-automation-mcp"
GUIDES = ("openclaw.mcp-install.md", "hermes.mcp-install.md")
EXTRA = "preview"


def _module(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


validator = _module("validate_hwpx_plugin")
builder = _module("build_hwpx_plugins")


def _identity() -> dict:
    return json.loads((ROOT / "packaging" / "product-identity.json").read_text(encoding="utf-8"))


def _automation_extras(requirement: str) -> list[str]:
    match = re.search(r"python-hwpx-automation\[([^\]]*)\]", requirement)
    assert match is not None, requirement
    return match.group(1).split(",")


def test_the_extra_is_the_one_that_declares_the_renderer() -> None:
    project = tomllib.loads((ROOT.parent / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    declared = project["optional-dependencies"][EXTRA]
    assert any(spec.startswith(validator.CLAUDE_EQUATION_RENDERER) for spec in declared)


def test_identity_install_coordinates_carry_the_preview_extra() -> None:
    identity = _identity()
    extras = identity["components"]["automation"]["pluginInstallExtras"]
    assert EXTRA in extras
    assert _automation_extras(identity["installConstraint"]["automation"]) == extras
    assert identity["installConstraint"] == validator.install_constraints(identity)


def test_managed_launcher_installs_the_preview_extra() -> None:
    """The launcher Codex embeds: both channels and the editable checkout path."""

    text = LAUNCHER.read_text(encoding="utf-8")
    for name in ("VERIFIED_SERVER_PACKAGE", "CONSTRAINT_SERVER_PACKAGE"):
        match = re.search(rf'^{name}="(.+)"$', text, re.M)
        assert match is not None, name
        assert EXTRA in _automation_extras(match.group(1)), name
    editable = re.search(r'--with-editable "\$\{MCP_REPO\}\[([^\]]*)\]"', text)
    assert editable is not None
    assert EXTRA in editable.group(1).split(",")


@pytest.mark.parametrize("name", GUIDES)
def test_direct_host_install_guides_install_the_preview_extra(name: str) -> None:
    """OpenClaw and Hermes: ``uv tool install`` takes the coordinates printed in the guide."""

    rendered = builder.render_install_guide((TEMPLATES / name).read_text(encoding="utf-8"), _identity())
    install = next(line for line in rendered.splitlines() if line.startswith("uv tool install"))
    assert EXTRA in _automation_extras(install)


def test_validator_rejects_install_extras_without_the_renderer() -> None:
    hosts = json.loads((ROOT / "packaging" / "hosts.json").read_text(encoding="utf-8"))
    identity = copy.deepcopy(_identity())
    validator.validate_product_identity(hosts, identity)  # as committed: accepted

    automation = identity["components"]["automation"]
    automation["pluginInstallExtras"] = [extra for extra in automation["pluginInstallExtras"] if extra != EXTRA]
    identity["installConstraint"] = validator.install_constraints(identity)
    with pytest.raises(SystemExit, match="latex2mathml"):
        validator.validate_product_identity(hosts, identity)
