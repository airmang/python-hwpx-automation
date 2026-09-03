# SPDX-License-Identifier: Apache-2.0
"""The launcher's expected stack versions derive from its package requests.

2.0.1 and 2.0.2 shipped ``EXPECTED_CORE_VERSION`` as a hand-advanced literal
that lagged the ``python-hwpx==`` pin, so every fresh Claude Code runtime build
failed its own self-check (hwpx-plugins #26). The clean-install smoke did not
catch it because it injected the expectation through the environment. These
tests pin the structural fix: no literal default may reappear, the derivation
must read both exact pins and local wheel paths (the shape the smoke installs),
and per-start ``uvx`` wiring must not refresh exact pins (hwpx-plugins #23).
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "packaging" / "templates" / "hwpx-automation-mcp"
BUNDLED_LAUNCHERS = sorted(ROOT.glob("plugins/*/hwpx-plugin/scripts/hwpx-automation-mcp"))
LITERAL_DEFAULT = re.compile(r'EXPECTED_(CORE|SERVER)_VERSION="\$\{[A-Z_]+:-(\$\{[A-Z_]+:-)?[0-9]')


def _function_source() -> str:
    match = re.search(r"^_pinned_version\(\) \{\n.*?^\}\n", TEMPLATE.read_text(encoding="utf-8"), re.S | re.M)
    assert match, "launcher template lost _pinned_version()"
    return match.group(0)


def _pinned_version(spec: str) -> str:
    script = _function_source() + '\n_pinned_version "$1"\n'
    result = subprocess.run(
        ["bash", "-c", script, "_", spec], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _default(name: str, text: str) -> str:
    match = re.search(rf'^{name}="(.+)"$', text, re.M)
    assert match, f"{name} default missing"
    return match.group(1)


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("python-hwpx[preview]==6.3.0", "6.3.0"),
        ("python-hwpx-automation[mcp,oracle]==7.0.3", "7.0.3"),
        ("python-hwpx==6.3.0", "6.3.0"),
        ("/tmp/dist/python_hwpx-6.3.0-py3-none-any.whl[preview]", "6.3.0"),
        ("/x/python_hwpx_automation-7.0.3-py3-none-any.whl[mcp,oracle]", "7.0.3"),
        ("python-hwpx", ""),
        ("python-hwpx>=6.3.0,<7", ""),
    ],
)
def test_pinned_version_reads_exact_pins_and_wheel_paths(spec: str, expected: str) -> None:
    assert _pinned_version(spec) == expected


def test_expected_versions_are_derived_not_literal() -> None:
    for path in (TEMPLATE, *BUNDLED_LAUNCHERS):
        text = path.read_text(encoding="utf-8")
        assert LITERAL_DEFAULT.search(text) is None, f"{path}: hand-advanced expected version literal"
        assert (
            'EXPECTED_CORE_VERSION="${HWPX_PYTHON_HWPX_VERSION:-$(_pinned_version "${CORE_PACKAGE}")}"'
            in text
        ), path
        assert (
            'EXPECTED_SERVER_VERSION="${HWPX_AUTOMATION_VERSION:-${HWPX_MCP_SERVER_VERSION:-$(_pinned_version "${SERVER_PACKAGE}")}}"'
            in text
        ), path


def test_verified_and_constraint_literals_derive_from_product_identity() -> None:
    identity = json.loads((ROOT / "packaging" / "product-identity.json").read_text(encoding="utf-8"))
    core = identity["components"]["core"]["currentVersion"]
    automation = identity["components"]["automation"]["currentVersion"]
    text = TEMPLATE.read_text(encoding="utf-8")
    assert _default("VERIFIED_CORE_PACKAGE", text) == f"python-hwpx[preview]=={core}"
    assert _default("VERIFIED_SERVER_PACKAGE", text) == f"python-hwpx-automation[mcp,oracle]=={automation}"
    assert _default("CONSTRAINT_CORE_PACKAGE", text) == identity["installConstraint"]["core"]
    assert _default("CONSTRAINT_SERVER_PACKAGE", text) == identity["installConstraint"]["automation"]
    assert identity["installConstraint"]["core"] == f"python-hwpx[preview]>={core},<{int(core.split('.')[0]) + 1}"
    assert _pinned_version(_default("VERIFIED_CORE_PACKAGE", text)) == core
    assert _pinned_version(_default("VERIFIED_SERVER_PACKAGE", text)) == automation
    assert _pinned_version(_default("CONSTRAINT_CORE_PACKAGE", text)) == ""
    assert _pinned_version(_default("CONSTRAINT_SERVER_PACKAGE", text)) == ""


def test_self_check_skips_packages_without_an_expectation() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    check = re.search(r'"\$\{dir\}/bin/python" - "\$\{EXPECTED_SERVER_VERSION\}" "\$\{EXPECTED_CORE_VERSION\}" <<\'PY\'\n(.*?)\nPY\n', text, re.S)
    assert check, "post-install self-check missing"
    body = check.group(1)
    assert "if value" in body and "mismatched" in body
    # The check must still fail closed on a real mismatch.
    assert "installed HWPX stack version mismatch" in body


def test_per_start_paths_do_not_refresh_exact_pins() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    uvx_block = re.search(r"exec uvx \\\n(?:.*\n)*?\s+hwpx-automation-mcp \"\$@\"", text)
    assert uvx_block, "uvx fallback exec missing"
    assert "--refresh-package" not in uvx_block.group(0)
    build_block = re.search(r"uv pip install --quiet \\\n(?:.*\n)*?\s+\"\$\{CORE_PACKAGE\}\"", text)
    assert build_block, "one-time venv build missing"
    assert "--refresh-package python-hwpx-automation" in build_block.group(0)
    for path in (
        ROOT / "packaging" / "templates" / "codex.mcp.json",
        ROOT / "packaging" / "templates" / "openclaw.mcp-install.md",
        ROOT / "packaging" / "templates" / "hermes.mcp-install.md",
        *sorted(ROOT.glob("plugins/*/hwpx-plugin/.mcp.json")),
    ):
        assert "--refresh-package" not in path.read_text(encoding="utf-8"), path


def test_clean_install_smoke_exercises_the_derivation() -> None:
    text = (ROOT / "scripts" / "clean_install_smoke.py").read_text(encoding="utf-8")
    assert "HWPX_PYTHON_HWPX_VERSION" not in text
    assert "HWPX_AUTOMATION_VERSION" not in text
