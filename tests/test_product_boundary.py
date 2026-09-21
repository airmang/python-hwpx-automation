# SPDX-License-Identifier: Apache-2.0
"""Positive and negative fixtures for the automation ownership check."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_product_boundary.py"
SPEC = importlib.util.spec_from_file_location("check_mcp_product_boundary", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
boundary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(boundary)


def _minimal_tree(root: Path) -> Path:
    office = root / "src" / "hwpx_automation" / "office"
    office.mkdir(parents=True)
    (office / "rendering.py").write_text("VALUE = 1\n", encoding="utf-8")
    return root / "src" / "hwpx_automation"


def test_real_tree_satisfies_mcp_boundary() -> None:
    report = boundary.evaluate(ROOT)
    assert report["ok"], report["violations"]
    assert report["canonicalAgentPythonFiles"] == 21
    # 17 since the 5.0 train: report_parser joined the owner it always belonged to.
    assert report["canonicalAuthoringPythonFiles"] == 17


def test_new_direct_render_discovery_fails_closed(tmp_path) -> None:
    source = _minimal_tree(tmp_path)
    handler = source / "handlers" / "new_handler.py"
    handler.parent.mkdir()
    handler.write_text(
        "from hwpx.visual.oracle import resolve_oracle\n",
        encoding="utf-8",
    )

    report = boundary.evaluate(tmp_path)

    assert not report["ok"]
    assert any("bypasses office adapter" in item for item in report["violations"])


def test_skill_implementation_import_fails_closed(tmp_path) -> None:
    source = _minimal_tree(tmp_path)
    module = source / "office" / "bad.py"
    module.write_text("import hwpx_skill\n", encoding="utf-8")

    report = boundary.evaluate(tmp_path)

    assert not report["ok"]
    assert any("imports skill implementation" in item for item in report["violations"])


def test_frozen_core_agent_import_fails_closed(tmp_path) -> None:
    source = _minimal_tree(tmp_path)
    module = source / "agent_document.py"
    module.write_text("from hwpx.agent import HwpxAgentDocument\n", encoding="utf-8")

    report = boundary.evaluate(tmp_path)

    assert not report["ok"]
    assert any(
        "imports frozen core agent copy" in item for item in report["violations"]
    )


def test_frozen_core_authoring_import_fails_closed(tmp_path) -> None:
    source = _minimal_tree(tmp_path)
    module = source / "handlers" / "authoring.py"
    module.parent.mkdir()
    module.write_text(
        "from hwpx.authoring import create_document_from_plan\n",
        encoding="utf-8",
    )

    report = boundary.evaluate(tmp_path)

    assert not report["ok"]
    assert any(
        "imports frozen core authoring copy" in item
        for item in report["violations"]
    )


def test_canonical_authoring_unapproved_core_seam_fails_closed(tmp_path) -> None:
    source = _minimal_tree(tmp_path)
    package = source / "office" / "authoring"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from hwpx.form_fill import fill_form\n",
        encoding="utf-8",
    )

    report = boundary.evaluate(tmp_path)

    assert not report["ok"]
    assert any(
        "canonical authoring uses unapproved core seam" in item
        for item in report["violations"]
    )
