# SPDX-License-Identifier: Apache-2.0
"""Audit ARC-12: the CI gates this repository relies on stay wired."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import yaml

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]


def test_tests_workflow_runs_the_suite_with_a_coverage_floor() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["test"]["steps"]
    runs = [str(step.get("run", "")).strip() for step in steps]
    assert any(run.startswith("python -m pytest -q --cov") for run in runs)
    assert "python -m pytest -q" in runs  # the other Python versions still run everything

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    coverage = pyproject["tool"]["coverage"]
    assert coverage["run"]["source"] == ["hwpx_automation"]
    floor = coverage["report"]["fail_under"]
    # A real floor, a little under the audited 79.73%, never a token value.
    assert 75 <= floor < 80


def test_gitattributes_keeps_text_files_lf() -> None:
    lines = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "* text=auto eol=lf" in lines


def test_result_truth_module_collects_without_pymupdf() -> None:
    """No module-level import of the optional PDF stack in that test file."""

    tree = ast.parse((ROOT / "tests" / "test_feature072_result_truth.py").read_text(encoding="utf-8"))
    top_level = {
        alias.name.split(".")[0]
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(name=node.module or "")])
    }
    assert "pymupdf" not in top_level and "fitz" not in top_level
