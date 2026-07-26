# SPDX-License-Identifier: Apache-2.0
"""Positive and negative fixtures for the skill responsibility gate."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_product_boundary.py"
SPEC = importlib.util.spec_from_file_location("check_skill_product_boundary", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
boundary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(boundary)


def test_real_bundles_contain_only_approved_python_roles() -> None:
    report = boundary.evaluate(ROOT)
    assert report["ok"], report["violations"]
    assert "detect_hwpx_viewer.py" in report["approvedSupportScripts"]
    assert "visual_review_batch.py" in report["approvedSupportScripts"]


def test_new_skill_runtime_implementation_fails_closed(tmp_path) -> None:
    module = (
        tmp_path
        / "plugins"
        / "codex"
        / "hwpx-plugin"
        / "skills"
        / "hwpx"
        / "house_style.py"
    )
    module.parent.mkdir(parents=True)
    module.write_text("def compose(): return None\n", encoding="utf-8")

    report = boundary.evaluate(tmp_path)

    assert not report["ok"]
    assert any("unapproved Python implementation" in item for item in report["violations"])
