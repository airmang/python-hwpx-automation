from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples/s070_fixture_benchmark"


def _module():
    spec = importlib.util.spec_from_file_location("fixture_benchmark", ROOT / "scripts/fixture_benchmark.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_fixture_has_six_families_three_profiles_and_abstentions() -> None:
    module = _module()
    report = module.validate(FIXTURE)
    manifest = json.loads((FIXTURE / "manifest.json").read_text())
    orders = json.loads((FIXTURE / "work-orders.json").read_text())["orders"]

    assert report == {
        "ok": True,
        "manifestHash": manifest["manifestHash"],
        "workOrders": 72,
        "artifacts": 216,
    }
    assert len({order["family"] for order in orders}) == 6
    assert sum(order["mustAbstain"] for order in orders) == 12
    assert len(manifest["profilePaths"]) == 3


def test_fixture_never_claims_human_real_agent_hancom_or_replacement() -> None:
    manifest = json.loads((FIXTURE / "manifest.json").read_text())
    result = json.loads((FIXTURE / "result-manifest.json").read_text())
    for value in (manifest, result):
        assert value["humanLabels"] is False
        assert value["humanControls"] is False
        assert value["humanJudges"] is False
        assert value["realAgentClientsVerified"] is False
        assert value["realHancomVerified"] is False
        assert value["replacementClaimAllowed"] is False
    assert result["metrics"] is None
    assert result["judgePassesAccepted"] == 0
    assert result["status"] == "awaiting_two_independent_agent_judge_passes"


def test_judge_passes_are_empty_independent_templates_not_fabricated_labels() -> None:
    passes = [json.loads(path.read_text()) for path in sorted((FIXTURE / "judge-templates").glob("*.json"))]
    assert [value["passId"] for value in passes] == ["judge-a", "judge-b"]
    assert all(value["judgeType"] == "agent_judge" for value in passes)
    assert all(value["independentInvocationRequired"] is True for value in passes)
    assert all(value["status"] == "unscored_template" and value["judgments"] == [] for value in passes)


def test_hash_tamper_and_projection_drift_fail_closed(tmp_path: Path) -> None:
    module = _module()
    copied = tmp_path / "fixture"
    import shutil
    shutil.copytree(FIXTURE, copied)
    manifest = json.loads((copied / "manifest.json").read_text())
    manifest["workOrderCount"] = 71
    (copied / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="hash mismatch"):
        module.validate(copied)

    (copied / "public/fixture-report.md").write_text("hand edited")
    with pytest.raises(ValueError, match="projection drift"):
        module.check_drift(copied / "result-manifest.json", copied / "public")


def test_skill_and_installed_runner_use_generated_fixture_tools() -> None:
    skill = (ROOT / "SKILL.md").read_text()
    runner = (ROOT / "scripts/plugin_fixture_benchmark_e2e.py").read_text()
    assert "`run_fixture_benchmark`" in skill
    assert "`export_fixture_benchmark`" in skill
    assert '"run_fixture_benchmark"' in runner
    assert '"export_fixture_benchmark"' in runner


def test_every_host_bundle_contains_compact_fixture_generator_and_runner() -> None:
    bundles = sorted((ROOT / "plugins").glob("*/hwpx*"))
    assert len(bundles) == 4
    for bundle in bundles:
        skill_root = bundle / "skills/hwpx"
        if not skill_root.exists():
            skill_root = bundle
        assert (skill_root / "scripts/plugin_fixture_benchmark_e2e.py").is_file()
        assert (skill_root / "scripts/fixture_benchmark.py").is_file()
        assert not (skill_root / "examples/s070_fixture_benchmark/private-routing.json").exists()
        assert not (skill_root / "examples/s070_fixture_benchmark/blind").exists()
