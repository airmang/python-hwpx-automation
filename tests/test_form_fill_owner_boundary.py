# SPDX-License-Identifier: Apache-2.0
"""Machine-check the planned canonical form-fill owner boundary."""

from __future__ import annotations

import importlib
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import hwpx

ROOT = Path(__file__).resolve().parents[1]
BOUNDARY = runpy.run_path(str(ROOT / "scripts" / "check_product_boundary.py"))
OWNER = json.loads(
    (ROOT / "docs" / "architecture" / "form-fill-runtime-owner.json").read_text(
        encoding="utf-8"
    )
)
RETAINED_CORE_SYMBOLS = {
    "hwpx.form_fit.apply": ("fit_cell_text",),
    "hwpx.form_fit.engine": ("FitEngine",),
    "hwpx.form_fit.measure": (
        "Confidence",
        "DEFAULT_LINE_SPACING_RATIO",
        "DEFAULT_SAFETY",
        "GROSS_ROW_GROWTH_FACTOR",
        "MIN_LINE_SPACING_RATIO",
        "MIN_ROW_GROWTH_LINES",
        "Measurement",
        "SlotMetrics",
        "char_advance",
        "classify_char",
        "estimate_lines",
        "estimate_text_width",
        "measure",
        "resolve_slot_metrics",
    ),
    "hwpx.form_fit.policy": ("FitMode", "FitPolicy", "OverflowAction"),
    "hwpx.form_fit.report": ("FIELD_OVERFLOW", "FitResult", "to_form_report"),
}


def test_owner_ledger_matches_frozen_source_and_contract() -> None:
    assert OWNER["source"] == {
        "head": "5054b50665296a0970823765d753de3d3ff612b5",
        "pythonFiles": 13,
        "loc": 5745,
        "manifestSha256": (
            "9fa54af13942549af74600a841117589fac4eb21c12c659c0b345c48746aae6e"
        ),
    }
    assert (
        tuple(OWNER["approvedCoreImports"])
        == BOUNDARY["ALLOWED_FORM_FILL_CORE_IMPORTS"]
    )
    assert (
        tuple(OWNER["forbiddenCoreCompatibilityImports"])
        == BOUNDARY["FROZEN_CORE_FORM_FILL_IMPORTS"]
    )
    assert {
        module: tuple(names)
        for module, names in OWNER["retainedCoreSymbols"].items()
    } == RETAINED_CORE_SYMBOLS
    assert OWNER["toolContract"] == {
        "default": 122,
        "advanced": 130,
        "skillRequired": 29,
        "hash": "8c278ebd5becba08",
    }


def test_canonical_owner_rejects_frozen_and_unapproved_core_seams() -> None:
    check = BOUNDARY["_form_fill_owner_import_violation"]
    canonical = "src/hwpx_automation/office/form_fill/quality.py"
    assert check(canonical, "hwpx.formfill_quality") is not None
    assert check(canonical, "hwpx.visual.oracle") is not None
    assert check(canonical, "hwpx.table_patch") is None
    assert check(canonical, "hwpx.evalplan_fill") is not None


def test_neutral_fit_wrappers_are_exact_core_objects_with_core_origins() -> None:
    core_root = Path(hwpx.__file__).resolve().parent
    for core_name, names in RETAINED_CORE_SYMBOLS.items():
        wrapper_name = core_name.replace(
            "hwpx.form_fit",
            "hwpx_automation.office.form_fill.fit",
            1,
        )
        core_module = importlib.import_module(core_name)
        wrapper_module = importlib.import_module(wrapper_name)
        core_path = Path(core_module.__file__).resolve()
        assert core_path.is_relative_to(core_root)
        assert not core_path.is_relative_to(ROOT / "src" / "hwpx_automation")
        assert tuple(wrapper_module.__all__) == names
        for name in names:
            assert getattr(wrapper_module, name) is getattr(core_module, name)


def test_all_base_imports_transitively_avoid_removed_core_fit_modules() -> None:
    script = r"""
import importlib
import importlib.abc
import json
import sys
from importlib.resources import files

REMOVED = ("hwpx.form_fit.seal", "hwpx.form_fit.wordbox")
attempted = []

class BlockRemovedCoreFit(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + ".") for name in REMOVED):
            attempted.append(fullname)
            raise ModuleNotFoundError(
                "removed core fit module intentionally blocked",
                name=fullname,
            )
        return None

sys.meta_path.insert(0, BlockRemovedCoreFit())
manifest = json.loads(
    files("hwpx_automation").joinpath("public-modules.json").read_text(
        encoding="utf-8"
    )
)
for module in manifest["basePublicModules"]:
    importlib.import_module(module)
assert not attempted, attempted
loaded = sorted(
    name
    for name in sys.modules
    if any(name == removed or name.startswith(removed + ".") for removed in REMOVED)
)
assert not loaded, loaded
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "src"), env.get("PYTHONPATH", "")]
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_real_tree_declares_the_form_fill_boundary() -> None:
    report = BOUNDARY["evaluate"](ROOT)
    assert report["ok"], report["violations"]
    assert report["canonicalFormFillRoot"] == ("src/hwpx_automation/office/form_fill")
    assert report["canonicalFormFillPythonFiles"] == 15
