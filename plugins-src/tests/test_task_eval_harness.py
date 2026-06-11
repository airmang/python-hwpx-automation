# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "scripts" / "task_eval_harness.py"
spec = importlib.util.spec_from_file_location("task_eval_harness", SPEC)
task_eval_harness = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = task_eval_harness
spec.loader.exec_module(task_eval_harness)


def test_task_eval_corpus_has_required_size_and_families() -> None:
    payload = json.loads((ROOT / "examples" / "eval_tasks" / "tasks.json").read_text(encoding="utf-8"))
    tasks = payload["tasks"]

    assert payload["schemaVersion"] == "hwpx.task-replay.v1"
    assert len(tasks) >= 30
    families = {task["family"] for task in tasks}
    assert {"generation", "editing", "formatting", "forms"} <= families
    for task in tasks:
        assert task["instruction"]
        assert task["toolCalls"]
        assert task["oracles"]


def test_task_eval_harness_scores_current_and_classifies_baseline(tmp_path: Path) -> None:
    report = task_eval_harness.run(
        ROOT / "examples" / "eval_tasks" / "tasks.json",
        [
            ROOT / "examples" / "eval_tasks" / "profiles" / "current-0.1.6.json",
            ROOT / "examples" / "eval_tasks" / "profiles" / "baseline-0.1.5.json",
        ],
        tmp_path / "report.json",
        tmp_path / "report.md",
        tmp_path / "work",
    )

    current, baseline = report["profiles"]
    assert current["profileId"] == "current-0.1.6"
    assert current["passed"] == report["taskCount"]
    assert baseline["failed"] > 0
    assert {
        "tool_absent",
        "tool_misbehavior",
        "skill_guidance_gap",
    } <= set(baseline["failuresByClassification"])
    assert report["comparison"]["scoreDelta"] > 0
    assert (tmp_path / "report.json").exists()
    assert (tmp_path / "report.md").exists()
