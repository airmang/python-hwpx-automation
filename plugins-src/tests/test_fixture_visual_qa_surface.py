from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "plugin_fixture_qa_e2e.py"


def _module():
    spec = importlib.util.spec_from_file_location("plugin_fixture_qa_e2e", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fixture_qa_remains_repository_internal_and_preserves_honest_boundary() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    reference = (ROOT / "references" / "workflows-visual-fixture-qa.md").read_text(
        encoding="utf-8"
    )
    assert "`visual_review_fixture`" not in skill
    assert "`visual_repair_fixture`" not in skill
    assert "references/workflows-visual-fixture-qa.md" not in skill
    assert "renderChecked=false" in reference
    assert "real_hancom_verified=false" in reference
    assert "최대 3회" in reference
    assert "repair_plan_path" in reference
    assert "append-only" in reference
    assert "primitive 편집 도구로 우회하지 않는다" in reference


def test_installed_fixture_harness_checks_three_categories_and_ledger_signals() -> None:
    module = _module()
    payload = {
        "findings": [
            {"category": "text_overlap"},
            {"category": "leftover_guidance"},
            {"category": "seal_misplacement", "severity": "critical", "target": None},
        ],
        "ledger": {
            "applied": [{"action": "replace_text"}],
            "escalations": [{"category": "seal_misplacement"}],
        },
    }

    assert len(module._categories(payload)) == 3
    assert module._has_ledger_signal(payload, {"applied"})
    assert module._has_ledger_signal(payload, {"escalations"})
    assert module._has_unsafe_finding(payload)


def test_installed_fixture_harness_rejects_any_fixture_promotion() -> None:
    module = _module()
    honest = {
        "renderChecked": False,
        "realHancomVerified": False,
        "verificationStatus": "structurally_verified_render_unverified",
    }
    module._assert_fixture_honesty(honest, "fixture")

    for key, value in (
        ("renderChecked", True),
        ("realHancomVerified", True),
        ("verificationStatus", "render_verified"),
    ):
        promoted = dict(honest, **{key: value})
        with pytest.raises(RuntimeError):
            module._assert_fixture_honesty(promoted, "fixture")


def test_fixture_harness_help_does_not_require_mcp_runtime() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "--require-tools" in result.stdout
    assert "--expected-category" in result.stdout


def test_every_host_bundle_excludes_repository_internal_fixture_qa_assets() -> None:
    bundles = sorted((ROOT / "plugins").glob("*/hwpx*"))
    assert len(bundles) == 4

    for bundle in bundles:
        skill_root = bundle / "skills" / "hwpx"
        if not skill_root.exists():
            skill_root = bundle
        assert not (skill_root / "references" / "workflows-visual-fixture-qa.md").exists()
        assert not (skill_root / "scripts" / "plugin_fixture_qa_e2e.py").exists()
        skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        assert "visual_review_fixture" not in skill
        assert "visual_repair_fixture" not in skill
