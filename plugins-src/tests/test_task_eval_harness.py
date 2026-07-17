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
    assert len(tasks) >= 38
    families = {task["family"] for task in tasks}
    assert {
        "generation",
        "editing",
        "formatting",
        "forms",
        "media",
        "compare",
        "inspection",
    } <= families
    for task in tasks:
        assert task["instruction"]
        assert task["toolCalls"]
        assert task["oracles"]


def test_explicit_stack_checkouts_precede_sibling_defaults(tmp_path: Path, monkeypatch) -> None:
    skill_root = tmp_path / "workspace" / "hwpx-skill-s076"
    explicit_mcp = tmp_path / "release" / "hwpx-mcp-server-s076"
    explicit_core = tmp_path / "release" / "python-hwpx-s076"
    default_mcp = skill_root.parent / "hwpx-mcp-server" / "src"
    default_core = skill_root.parent / "python-hwpx" / "src"
    for source in (explicit_mcp / "src", explicit_core / "src", default_mcp, default_core):
        source.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(task_eval_harness, "ROOT", skill_root)
    monkeypatch.setenv("HWPX_MCP_SERVER_REPO", str(explicit_mcp))
    monkeypatch.setenv("PYTHON_HWPX_REPO", str(explicit_core))
    monkeypatch.setattr(sys, "path", list(sys.path))

    task_eval_harness._ensure_stack_imports()

    assert sys.path.index(str((explicit_mcp / "src").resolve())) < sys.path.index(str(default_mcp.resolve()))
    assert sys.path.index(str((explicit_core / "src").resolve())) < sys.path.index(str(default_core.resolve()))


def test_task_eval_harness_scores_current_and_classifies_baseline(tmp_path: Path) -> None:
    report = task_eval_harness.run(
        ROOT / "examples" / "eval_tasks" / "tasks.json",
        [
            ROOT / "examples" / "eval_tasks" / "profiles" / "current-0.4.0.json",
            ROOT / "examples" / "eval_tasks" / "profiles" / "current-0.1.6.json",
            ROOT / "examples" / "eval_tasks" / "profiles" / "baseline-0.1.5.json",
        ],
        tmp_path / "report.json",
        tmp_path / "report.md",
        tmp_path / "work",
    )

    current, previous, baseline = report["profiles"]
    assert current["profileId"] == "current-0.4.0"
    assert current["passed"] == report["taskCount"]
    assert previous["profileId"] == "current-0.1.6"
    assert previous["failed"] > 0
    assert "skill_guidance_gap" in previous["failuresByClassification"]
    assert baseline["failed"] > 0
    assert {
        "tool_absent",
        "tool_misbehavior",
        "skill_guidance_gap",
    } <= set(baseline["failuresByClassification"])
    assert report["guidanceVerification"]["mode"] == "bundle-body"
    assert report["schemaVersion"] == "hwpx.deterministic-task-replay-report.v1"
    assert report["evaluationKind"] == "deterministic-direct-tool-replay"
    assert report["instructionSelectionUsed"] is False
    assert report["liveAgentEvidence"] is False
    assert report["routingMeasured"] is False
    assert report["recoveryMeasured"] is False
    assert report["unnecessaryCallsMeasured"] is False
    assert report["comparison"]["scoreDelta"] > 0
    assert any(
        entry["profileId"] == "current-0.1.6" and entry["passedDelta"] > 0
        for entry in report["comparison"]["againstProfiles"]
    )
    assert (tmp_path / "report.json").exists()
    assert (tmp_path / "report.md").exists()
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Deterministic Direct-Call Replay" in markdown
    assert "not live-agent" in markdown


def test_task_eval_harness_normalizes_relative_work_dir(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    report = task_eval_harness.run(
        ROOT / "examples" / "eval_tasks" / "tasks.json",
        [ROOT / "examples" / "eval_tasks" / "profiles" / "current-0.4.0.json"],
        tmp_path / "relative-report.json",
        None,
        Path("relative-work"),
    )

    assert report["profiles"][0]["passed"] == report["taskCount"]


def test_current_profile_resolves_default_tools_from_generated_contract() -> None:
    profile = task_eval_harness.Profile.from_path(
        ROOT / "examples" / "eval_tasks" / "profiles" / "current-0.4.0.json"
    )
    contract = json.loads(
        (ROOT / "references" / "tool-contract.generated.json").read_text(
            encoding="utf-8"
        )
    )
    expected = {
        tool["name"] for tool in contract["tools"] if tool["profile"] == "default"
    }

    assert profile.available_tools == expected
    assert profile.plugin_version == "0.4.0"


def test_preflight_fails_when_bundle_body_lacks_guidance_keywords() -> None:
    profile = task_eval_harness.Profile(
        profile_id="synthetic",
        label="synthetic",
        plugin_version="0.0.0",
        available_tools=None,
        broken_tools=set(),
        guidance_tags={"transaction-edits"},
    )
    task = {
        "id": "synthetic-task",
        "family": "editing",
        "requiredGuidance": ["transaction-edits"],
        "requiredTools": ["apply_edits"],
        "toolCalls": [],
        "oracles": [],
    }

    # The profile claims the tag, but the bundle body lacks the required
    # keywords, so the tag alone must NOT be enough to pass preflight.
    incomplete_bundle = "apply_edits dry_run expected_revision"
    result = task_eval_harness._preflight(task, profile, incomplete_bundle)
    assert result is not None
    assert result["classification"] == task_eval_harness.FAIL_SKILL_GUIDANCE_GAP
    missing = result["missingGuidanceEvidence"]["transaction-edits"]
    assert "idempotency_key" in missing
    assert "undo_last_edit" in missing

    complete_bundle = (
        "apply_edits dry_run expected_revision idempotency_key undo_last_edit"
    )
    assert task_eval_harness._preflight(task, profile, complete_bundle) is None


def test_preflight_fails_when_bundle_body_does_not_document_required_tools() -> None:
    profile = task_eval_harness.Profile(
        profile_id="synthetic",
        label="synthetic",
        plugin_version="0.0.0",
        available_tools=None,
        broken_tools=set(),
        guidance_tags=set(),
    )
    task = {
        "id": "synthetic-task",
        "family": "editing",
        "requiredTools": ["set_paragraph_format"],
        "toolCalls": [],
        "oracles": [],
    }

    result = task_eval_harness._preflight(task, profile, "no editing tools documented")
    assert result is not None
    assert result["classification"] == task_eval_harness.FAIL_SKILL_GUIDANCE_GAP
    assert result["missingBundleTools"] == ["set_paragraph_format"]

    # Substring mentions such as create_document_from_plan must not count as
    # documenting create_document.
    assert not task_eval_harness._bundle_mentions(
        "create_document_from_plan", "create_document"
    )
    assert task_eval_harness._bundle_mentions(
        "use create_document first", "create_document"
    )


def test_repo_skill_bundle_documents_all_replayed_tools() -> None:
    bundle_text = task_eval_harness._load_skill_bundle_text(ROOT)
    payload = json.loads((ROOT / "examples" / "eval_tasks" / "tasks.json").read_text(encoding="utf-8"))
    undocumented: set[str] = set()
    for task in payload["tasks"]:
        for tool in task_eval_harness._tool_required_by_task(task):
            if not task_eval_harness._bundle_mentions(bundle_text, tool):
                undocumented.add(tool)
    assert not undocumented, f"skill bundle does not document: {sorted(undocumented)}"


def test_authored_guidance_loader_excludes_generated_contract_inventory(tmp_path: Path) -> None:
    (tmp_path / "references").mkdir()
    (tmp_path / "SKILL.md").write_text("authored-route\n", encoding="utf-8")
    (tmp_path / "references" / "workflow.md").write_text(
        "authored-tool\n", encoding="utf-8"
    )
    (tmp_path / "references" / "tool-contract.generated.md").write_text(
        "inventory-only-tool\n", encoding="utf-8"
    )

    body = task_eval_harness._load_skill_bundle_text(tmp_path)

    assert "authored-route" in body
    assert "authored-tool" in body
    assert "inventory-only-tool" not in body
