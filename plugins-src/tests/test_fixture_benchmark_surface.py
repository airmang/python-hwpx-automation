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


def _built_fixture(tmp_path: Path) -> tuple[object, Path]:
    module = _module()
    root = tmp_path / "fixture"
    module.build(root)
    return module, root


def test_frozen_fixture_has_six_families_three_profiles_and_abstentions(tmp_path: Path) -> None:
    module, root = _built_fixture(tmp_path)
    report = module.validate(root)
    manifest = json.loads((root / "manifest.json").read_text())
    orders = json.loads((root / "work-orders.json").read_text())["orders"]

    assert report == {
        "ok": True,
        "manifestHash": manifest["manifestHash"],
        "workOrders": 72,
        "artifacts": 216,
    }
    assert len({order["family"] for order in orders}) == 6
    assert sum(order["mustAbstain"] for order in orders) == 12
    assert len(manifest["profilePaths"]) == 3


def test_fixture_never_claims_human_real_agent_hancom_or_replacement(tmp_path: Path) -> None:
    _, root = _built_fixture(tmp_path)
    manifest = json.loads((root / "manifest.json").read_text())
    result = json.loads((root / "result-manifest.json").read_text())
    for value in (manifest, result):
        assert value["humanLabels"] is False
        assert value["humanControls"] is False
        assert value["humanJudges"] is False
        assert value["realAgentClientsVerified"] is False
        assert value["realHancomVerified"] is False
        assert value["replacementClaimAllowed"] is False
    assert result["status"] == "awaiting_two_independent_agent_judge_passes"
    assert result["metrics"] is None
    assert result["judgePassesAccepted"] == 0


def test_committed_seed_matches_generated_inputs_and_has_blank_judges(tmp_path: Path) -> None:
    _, root = _built_fixture(tmp_path)
    relatives = [
        Path("rubric-v1.json"),
        Path("work-orders.json"),
        *(path.relative_to(FIXTURE) for path in sorted((FIXTURE / "profiles").glob("*.json"))),
    ]
    for relative in relatives:
        assert (FIXTURE / relative).read_bytes() == (root / relative).read_bytes()

    passes = [json.loads(path.read_text()) for path in sorted((root / "judge-templates").glob("*.json"))]
    assert [value["passId"] for value in passes] == ["judge-a", "judge-b"]
    assert all(value["judgeType"] == "agent_judge" for value in passes)
    assert all(value["independentInvocationRequired"] is True for value in passes)
    assert all(value["status"] == "unscored_template" and value["judgments"] == [] for value in passes)
    assert all(value["humanLabels"] is False for value in passes)
    for relative in (Path("judge-templates/judge-a.json"), Path("judge-templates/judge-b.json")):
        committed = json.loads((FIXTURE / relative).read_text())
        assert committed["status"] == "unscored_template"
        assert committed["judgments"] == []


def test_hash_tamper_and_projection_drift_fail_closed(tmp_path: Path) -> None:
    module, copied = _built_fixture(tmp_path)
    manifest = json.loads((copied / "manifest.json").read_text())
    manifest["workOrderCount"] = 71
    (copied / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="hash mismatch"):
        module.validate(copied)

    (copied / "public/fixture-report.md").write_text("hand edited")
    with pytest.raises(ValueError, match="projection drift"):
        module.check_drift(copied / "result-manifest.json", copied / "public")


def test_fixture_benchmark_tools_remain_repository_internal() -> None:
    skill = (ROOT / "SKILL.md").read_text()
    runner = (ROOT / "scripts/plugin_fixture_benchmark_e2e.py").read_text()
    assert "`run_fixture_benchmark`" not in skill
    assert "`export_fixture_benchmark`" not in skill
    assert '"run_fixture_benchmark"' in runner
    assert '"export_fixture_benchmark"' in runner


def test_host_bundles_exclude_repository_only_fixture_corpus_and_runner() -> None:
    bundles = sorted((ROOT / "plugins").glob("*/hwpx*"))
    assert len(bundles) == 4
    for bundle in bundles:
        skill_root = bundle / "skills/hwpx"
        if not skill_root.exists():
            skill_root = bundle
        assert not (skill_root / "scripts/plugin_fixture_benchmark_e2e.py").exists()
        assert not (skill_root / "scripts/fixture_benchmark.py").exists()
        assert not (skill_root / "examples/s070_fixture_benchmark").exists()
        assert not (skill_root / "references/workflows-fixture-benchmark.md").exists()
