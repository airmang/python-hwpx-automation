#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Measure the pre-Leap route contract for the frozen interface gap pack.

This is deliberately a route/capability audit, not an LLM benchmark.  Model
tokens remain null; the UTF-8/4 value is a labelled comparison proxy only.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import sys
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TASKS = ROOT / "tests" / "fixtures" / "agent_interface_baseline_tasks.json"

READ_ONLY_TOOLS = {
    "find_text",
    "get_document_info",
    "get_document_map",
    "get_document_outline",
    "get_document_text",
    "get_paragraph_text",
    "get_paragraphs_text",
    "get_table_map",
    "get_table_text",
    "list_form_fields",
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _bundle_text(skill_root: Path) -> str:
    paths = [skill_root / "SKILL.md", *sorted((skill_root / "references").glob("*.md"))]
    return "\n".join(path.read_text(encoding="utf-8") for path in paths if path.is_file())


def _mentions(text: str, token: str) -> bool:
    return re.search(rf"(?<![0-9A-Za-z_]){re.escape(token)}(?![0-9A-Za-z_])", text) is not None


def _load_tool_contract(server_src: Path) -> tuple[set[str], str]:
    sys.path.insert(0, str(server_src))
    try:
        # Feature 025 binds the canonical registry during explicit runtime
        # composition.  Older snapshots composed from ``server`` directly, so
        # retain that compatibility path for reproducible historical audits.
        try:
            importlib.import_module("hwpx_mcp_server.runtime")
        except ModuleNotFoundError as exc:
            if exc.name != "hwpx_mcp_server.runtime":
                raise
            importlib.import_module("hwpx_mcp_server.server")
        from hwpx_mcp_server.tool_contract import contract_hash, expected_tool_names

        return expected_tool_names(advanced=False), contract_hash()
    finally:
        sys.path.remove(str(server_src))


def run(tasks_path: Path, output: Path, skill_root: Path, server_src: Path) -> dict[str, Any]:
    task_bytes = tasks_path.read_bytes()
    payload = json.loads(task_bytes)
    if payload.get("schemaVersion") != "hwpx.agent-interface-benchmark/v1":
        raise ValueError("unsupported benchmark schema")
    tools, tool_spec_hash = _load_tool_contract(server_src)
    bundle = _bundle_text(skill_root)

    tracemalloc.start()
    started = time.perf_counter_ns()
    results: list[dict[str, Any]] = []
    for task in payload["tasks"]:
        task_started = time.perf_counter_ns()
        route = list(task["currentRoute"])
        missing_tools = sorted(set(route) - tools)
        undocumented_tools = sorted(tool for tool in route if not _mentions(bundle, tool))
        capability = task["currentCapability"]
        if missing_tools:
            status = "tool_absent"
        elif undocumented_tools:
            status = "guidance_gap"
        elif capability == "supported":
            status = "routeable"
        elif capability == "partial":
            status = "partial"
        elif capability == "gap":
            status = "capability_gap"
        elif capability == "refuse":
            status = "safe_refusal_route" if set(route) <= READ_ONLY_TOOLS else "unsafe_refusal_route"
        else:
            raise ValueError(f"unknown currentCapability: {capability}")

        instruction_bytes = task["instruction"].encode("utf-8")
        results.append(
            {
                "taskId": task["id"],
                "family": task["family"],
                "expectedTerminalState": task["expectedTerminalState"],
                "currentCapability": capability,
                "status": status,
                "currentRoute": route,
                "currentRouteToolCalls": len(route),
                "leapARouteToolCalls": len(task["leapARoute"]),
                "targeting": task["currentTargeting"],
                "gapCodes": list(task["gapCodes"]),
                "missingTools": missing_tools,
                "undocumentedTools": undocumented_tools,
                "instructionChars": len(task["instruction"]),
                "instructionUtf8Bytes": len(instruction_bytes),
                "tokenProxy": {
                    "value": (len(instruction_bytes) + 3) // 4,
                    "method": "ceil(utf8-bytes/4)",
                    "isModelTokenCount": False,
                },
                "modelTokens": None,
                "modelTokenStatus": "unmeasured-no-model-runner",
                "auditElapsedMicroseconds": (time.perf_counter_ns() - task_started) // 1000,
            }
        )
    elapsed_ns = time.perf_counter_ns() - started
    _, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    by_status: dict[str, int] = {}
    for result in results:
        by_status[result["status"]] = by_status.get(result["status"], 0) + 1
    report = {
        "schemaVersion": "hwpx.agent-interface-baseline-report/v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "measurementScope": "route-contract-audit",
        "executionLimitations": [
            "No LLM was invoked; model tokens, model retries, and model targeting errors are unmeasured.",
            "Elapsed time and peak memory cover route/catalog audit only, not HWPX mutation execution.",
            "Actual pre-Leap document execution is recorded separately by the existing task-eval harness.",
        ],
        "baseline": payload["baseline"],
        "taskSpecSha256": _sha256_bytes(task_bytes),
        "skillBundleSha256": _sha256_bytes(bundle.encode("utf-8")),
        "toolSpecHash": tool_spec_hash,
        "taskCount": len(results),
        "statusCounts": by_status,
        "currentRouteToolCalls": sum(item["currentRouteToolCalls"] for item in results),
        "leapARouteToolCallsProjected": sum(item["leapARouteToolCalls"] for item in results),
        "auditElapsedMicroseconds": elapsed_ns // 1000,
        "auditPeakMemoryBytes": peak_memory,
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skill-root", type=Path, default=ROOT)
    parser.add_argument("--server-src", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run(args.tasks, args.output, args.skill_root, args.server_src)
    print(
        f"[OK] {report['taskCount']} tasks; statuses={report['statusCounts']}; "
        f"current_calls={report['currentRouteToolCalls']}; projected_calls={report['leapARouteToolCallsProjected']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
