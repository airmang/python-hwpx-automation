# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "tests" / "fixtures" / "agent_interface_baseline_tasks.json"
RUNNER_PATH = ROOT / "tests" / "agent_interface_gap_baseline.py"


def _server_src() -> Path:
    explicit = os.environ.get("HWPX_MCP_SERVER_REPO")
    if explicit:
        candidate = Path(explicit).expanduser().resolve() / "src"
        if candidate.is_dir():
            return candidate

    installed = importlib.util.find_spec("hwpx_mcp_server")
    if installed and installed.submodule_search_locations:
        return Path(next(iter(installed.submodule_search_locations))).resolve().parent

    candidate = ROOT.parent / "hwpx-mcp-server" / "src"
    if candidate.is_dir():
        return candidate.resolve()
    raise RuntimeError(
        "hwpx-mcp-server source not found; install it or set HWPX_MCP_SERVER_REPO"
    )


SERVER_SRC = _server_src()

spec = importlib.util.spec_from_file_location("agent_interface_gap_baseline", RUNNER_PATH)
runner = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)


def test_frozen_agent_interface_pack_has_required_coverage() -> None:
    payload = json.loads(TASKS.read_text(encoding="utf-8"))
    tasks = payload["tasks"]
    assert payload["schemaVersion"] == "hwpx.agent-interface-benchmark/v1"
    assert len(tasks) >= 20
    assert len({task["id"] for task in tasks}) == len(tasks)
    assert {"discovery", "mutation", "reorganization", "atomicity", "safety"} <= {
        task["family"] for task in tasks
    }
    assert {"supported", "partial", "gap", "refuse"} <= {
        task["currentCapability"] for task in tasks
    }
    assert any("NO_GENERIC_MOVE" in task["gapCodes"] for task in tasks)
    assert any("NO_GENERIC_SUBTREE_COPY" in task["gapCodes"] for task in tasks)
    assert any("NO_HETEROGENEOUS_PATH_BATCH" in task["gapCodes"] for task in tasks)
    assert payload["baseline"]["modelRunner"] is None
    assert payload["baseline"]["modelTokenStatus"] == "unmeasured"


def test_baseline_route_audit_is_honest_and_reproducible(tmp_path: Path) -> None:
    report = runner.run(TASKS, tmp_path / "baseline.json", ROOT, SERVER_SRC)
    assert report["taskCount"] == 20
    assert report["measurementScope"] == "route-contract-audit"
    assert not any(result["missingTools"] for result in report["results"])
    assert not any(result["undocumentedTools"] for result in report["results"])
    assert report["statusCounts"] == {
        "partial": 6,
        "routeable": 8,
        "capability_gap": 4,
        "safe_refusal_route": 2,
    }
    assert all(result["modelTokens"] is None for result in report["results"])
    assert all(result["tokenProxy"]["isModelTokenCount"] is False for result in report["results"])
    assert report["currentRouteToolCalls"] > report["leapARouteToolCallsProjected"]
    assert (tmp_path / "baseline.json").is_file()
