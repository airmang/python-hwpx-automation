# SPDX-License-Identifier: Apache-2.0
"""The authoring owner ledger and the product-boundary gate say the same thing."""
from __future__ import annotations

import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOUNDARY = runpy.run_path(str(ROOT / "scripts" / "check_product_boundary.py"))
OWNER = json.loads(
    (ROOT / "docs" / "architecture" / "authoring-runtime-owner.json").read_text(encoding="utf-8")
)
TEMPLATE = "src/hwpx_automation/office/authoring/template_analyzer.py"


def test_ledger_imports_match_the_gate() -> None:
    assert tuple(OWNER["approvedCoreImports"]) == BOUNDARY["ALLOWED_AUTHORING_CORE_IMPORTS"]
    assert tuple(OWNER["forbiddenCoreCompatibilityImports"]) == BOUNDARY["FROZEN_CORE_AUTHORING_IMPORTS"]
    delegated = {
        f"src/{module.replace('.', '/')}.py": entry["coreOwner"]
        for module, entry in OWNER["coreDelegatedModules"].items()
    }
    assert delegated == BOUNDARY["CORE_DELEGATED_MODULES"]


def _tree(tmp_path: Path, source: str) -> Path:
    path = tmp_path / TEMPLATE
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    return tmp_path


def test_a_delegated_module_that_reads_xml_again_fails(tmp_path: Path) -> None:
    violations = BOUNDARY["_delegated_module_violations"]
    root = _tree(
        tmp_path,
        "from hwpx.tools.template_analyzer import analyze_template\n"
        "from xml.etree import ElementTree as ET\n",
    )
    assert violations(root) == [
        f"core-delegated module reads packages or XML itself: {TEMPLATE} -> xml.etree"
    ]


def test_a_delegated_module_that_drops_its_core_seam_fails(tmp_path: Path) -> None:
    violations = BOUNDARY["_delegated_module_violations"]
    root = _tree(tmp_path, "from hwpx.opc.package import HwpxPackage\n")
    assert violations(root) == [
        f"core-delegated module does not import its core seam: {TEMPLATE} -> hwpx.tools.template_analyzer",
        f"core-delegated module reads packages or XML itself: {TEMPLATE} -> hwpx.opc.package",
    ]


def test_the_shipped_tree_passes() -> None:
    assert BOUNDARY["_delegated_module_violations"](ROOT) == []
