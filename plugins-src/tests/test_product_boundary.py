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


def test_only_unmodified_vendored_engine_source_is_exempt(tmp_path) -> None:
    import hashlib
    import json

    engine = tmp_path / "plugins" / "claude" / "hwpx-plugin" / "skills" / "hwpx" / "engine"
    (engine / "hwpx").mkdir(parents=True)
    published = engine / "hwpx" / "__init__.py"
    published.write_text("__version__ = '0'\n", encoding="utf-8")
    manifest = {"files": {"hwpx/__init__.py": hashlib.sha256(published.read_bytes()).hexdigest()}}
    (engine / "VENDOR.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert boundary.evaluate(tmp_path)["ok"]

    published.write_text("__version__ = '0'\ndef compose(): return None\n", encoding="utf-8")
    (engine / "hwpx" / "house_style.py").write_text("", encoding="utf-8")
    report = boundary.evaluate(tmp_path)
    assert not report["ok"]
    assert len(report["violations"]) == 2
