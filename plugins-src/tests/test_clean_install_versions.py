# SPDX-License-Identifier: Apache-2.0
"""Candidate gates compare independently supplied versions, with strict defaults."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from test_plugin_bundle_validation import _clean_smoke_module


def _payload(core: str, server: str, *, root: Path | None = None) -> dict:
    return {
        "versions": {"python-hwpx": core, "python-hwpx-automation": server},
        "origins": {
            "hwpx": str((root / "core" if root else Path("/runtime/site-packages")) / "hwpx/__init__.py"),
            "hwpx_automation": str((root / "automation" if root else Path("/runtime/site-packages")) / "hwpx_automation/__init__.py"),
        },
        "capabilities": {"mcp": True, "previewMath": True},
    }


@pytest.mark.parametrize("editable", [False, True])
def test_candidate_version_override_is_explicit_and_mismatch_still_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, editable: bool
) -> None:
    smoke = _clean_smoke_module()
    next_major = int(smoke.EXPECTED_STACK_VERSIONS["python-hwpx"].split(".")[0]) + 1
    core = f"{next_major}.0.0"
    server = smoke.EXPECTED_STACK_VERSIONS["python-hwpx-automation"]
    payload = _payload(core, server, root=tmp_path if editable else None)
    monkeypatch.setattr(
        smoke.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, json.dumps(payload), "")
    )

    def probe(**kwargs):
        if editable:
            return smoke._probe_editable_runtime(
                tmp_path / "launcher", core_repo=tmp_path / "core", automation_repo=tmp_path / "automation",
                workspace=tmp_path, **kwargs,
            )
        return smoke._probe_installed_runtime(tmp_path / "python", excluded_source_roots=[], **kwargs)

    # The public/released identity remains the default; no auto-adoption of
    # whatever version the runtime happened to report is allowed.
    with pytest.raises(RuntimeError, match="candidate version mismatch"):
        probe()
    expected = {"python-hwpx": core, "python-hwpx-automation": server}
    assert probe(expected_versions=expected)["ok"] is True
    with pytest.raises(RuntimeError, match="candidate version mismatch"):
        probe(expected_versions={**expected, "python-hwpx": f"{next_major + 1}.0.0"})
    assert smoke.EXPECTED_STACK_VERSIONS["python-hwpx"] != core


def test_smoke_defaults_still_accept_the_declared_identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    smoke = _clean_smoke_module()
    versions = smoke.EXPECTED_STACK_VERSIONS
    payload = _payload(versions["python-hwpx"], versions["python-hwpx-automation"])
    monkeypatch.setattr(
        smoke.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, json.dumps(payload), "")
    )
    assert smoke._probe_installed_runtime(tmp_path / "python", excluded_source_roots=[])["ok"] is True


def test_ci_expected_versions_come_from_selected_checkout_metadata(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/tests.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["plugin-contract"]["steps"]
    derive = next(step for step in steps if step.get("id") == "runtime_versions")
    for directory, version in (("python-hwpx", "6.10.0"), ("python-hwpx-automation", "7.3.1")):
        project = tmp_path / directory
        project.mkdir()
        (project / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n', encoding="utf-8")
    output = tmp_path / "outputs"
    script = "\n".join(derive["run"].splitlines()[1:-1])
    subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, check=True,
        env={**os.environ, "GITHUB_OUTPUT": str(output)},
    )
    assert output.read_text(encoding="utf-8").splitlines() == ["core=6.10.0", "automation=7.3.1"]
    for name in ("Plugin launcher protocol E2E (editable stack)", "Clean wheel 3-stack smoke"):
        step = next(step for step in steps if step.get("name") == name)
        assert steps.index(derive) < steps.index(step)
        assert '--expected-core-version "${{ steps.runtime_versions.outputs.core }}"' in step["run"]
        assert '--expected-server-version "${{ steps.runtime_versions.outputs.automation }}"' in step["run"]
