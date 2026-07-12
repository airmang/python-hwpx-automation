#!/usr/bin/env python3
"""Installed-plugin leap demo for fixture visual review and bounded repair.

The harness deliberately uses MCP stdio through the generated plugin launcher.  A
server that predates the two fixture tools is reported as skipped unless
``--require-tools`` is supplied, so ordinary older-stack checks remain honest.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


TOOLS = {"visual_review_fixture", "visual_repair_fixture"}


def _structured(result: Any) -> dict[str, Any]:
    if bool(getattr(result, "isError", False)):
        raise RuntimeError(f"MCP tool returned isError: {result}")
    payload = getattr(result, "structuredContent", None)
    if isinstance(payload, dict):
        return payload
    for content in getattr(result, "content", ()):
        text = getattr(content, "text", None)
        if isinstance(text, str):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return {}


def _walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _categories(payload: dict[str, Any]) -> set[str]:
    return {
        value["category"]
        for value in _walk(payload)
        if isinstance(value, dict) and isinstance(value.get("category"), str)
    }


def _has_ledger_signal(payload: dict[str, Any], wanted: set[str]) -> bool:
    for value in _walk(payload):
        if not isinstance(value, dict):
            continue
        for key, child in value.items():
            normalized_key = key.replace("_", "").lower()
            if normalized_key in wanted and child not in (None, False, [], {}):
                return True
        status = (
            value.get("status")
            or value.get("outcome")
            or value.get("decision")
            or value.get("handoffStatus")
            or value.get("verdict")
        )
        if isinstance(status, str) and status.replace("_", "").lower() in wanted:
            return True
    return False


def _assert_fixture_honesty(payload: dict[str, Any], label: str) -> None:
    if payload.get("renderChecked") is not False:
        raise RuntimeError(f"{label} must explicitly keep renderChecked=false: {payload}")
    if payload.get("realHancomVerified") is not False:
        raise RuntimeError(f"{label} must explicitly keep realHancomVerified=false: {payload}")
    if payload.get("verificationStatus") != "structurally_verified_render_unverified":
        raise RuntimeError(f"{label} promoted fixture evidence: {payload}")


def _revision(payload: dict[str, Any]) -> str:
    for key in ("documentRevision", "document_revision", "revision"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    raise RuntimeError(f"document revision missing from get_document_map: {payload}")


def _default_launcher() -> Path:
    here = Path(__file__).resolve()
    canonical = here.parents[1] / "plugins" / "codex" / "hwpx-plugin" / "scripts" / "hwpx-mcp-server"
    if canonical.is_file():
        return canonical
    for parent in here.parents:
        candidate = parent / "scripts" / "hwpx-mcp-server"
        if candidate.is_file() and candidate != here:
            return candidate
    return canonical


async def _run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    from datetime import timedelta

    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    manifest = args.manifest.resolve()
    filename = args.filename.resolve()
    repair_plan = args.repair_plan.resolve()
    output = args.output.resolve()
    output_dir = args.output_dir.resolve()
    sandbox_root = args.sandbox_root.resolve()
    env = dict(os.environ)
    env.update(
        {
            "HWPX_MCP_SANDBOX_ROOT": str(sandbox_root),
            "HWPX_MCP_ADVANCED": "0",
            "LOG_LEVEL": "ERROR",
        }
    )
    if args.mcp_repo:
        env["HWPX_MCP_SERVER_REPO"] = str(args.mcp_repo.resolve())
    if args.core_repo:
        env["PYTHON_HWPX_REPO"] = str(args.core_repo.resolve())

    params = StdioServerParameters(
        command=str(args.launcher.resolve()),
        args=[],
        env=env,
        cwd=args.launcher.resolve().parent.parent,
    )
    timeout = timedelta(seconds=args.timeout)
    async with stdio_client(params, errlog=sys.stderr) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            names = {tool.name for tool in (await session.list_tools()).tools}
            missing = sorted(TOOLS - names)
            if missing:
                report = {
                    "ok": not args.require_tools,
                    "status": "skipped",
                    "reason": "fixture visual-QA tools are not installed",
                    "missingTools": missing,
                }
                return report, 1 if args.require_tools else 0

            review_arguments: dict[str, Any] = {
                "manifest_path": str(manifest),
                "output_dir": str(output_dir / "before"),
                "strict": True,
            }
            if args.case_id:
                review_arguments["case_id"] = args.case_id
            if args.adapter_evidence:
                review_arguments["adapter_evidence_path"] = str(args.adapter_evidence.resolve())
            review = _structured(
                await session.call_tool(
                    "visual_review_fixture",
                    review_arguments,
                    read_timeout_seconds=timeout,
                )
            )
            _assert_fixture_honesty(review, "review receipt")
            categories = _categories(review)
            expected = set(args.expected_category)
            if len(categories) < 3 or not expected.issubset(categories):
                raise RuntimeError(
                    f"fixture review must localize three categories; detected={sorted(categories)}, "
                    f"expected={sorted(expected)}"
                )

            document_map = _structured(
                await session.call_tool(
                    "get_document_map", {"filename": str(filename)}, read_timeout_seconds=timeout
                )
            )
            repair = _structured(
                await session.call_tool(
                    "visual_repair_fixture",
                    {
                        "filename": str(filename),
                        "manifest_path": str(manifest),
                        "repair_plan_path": str(repair_plan),
                        "output_path": str(output),
                        "expected_revision": _revision(document_map),
                        "idempotency_key": args.idempotency_key,
                        "output_dir": str(output_dir / "after"),
                        "max_rounds": 3,
                        **({"case_id": args.case_id} if args.case_id else {}),
                    },
                    read_timeout_seconds=timeout,
                )
            )
            _assert_fixture_honesty(repair, "repair receipt")
            if not isinstance(repair.get("ledger"), (dict, list)) or not repair["ledger"]:
                raise RuntimeError(f"repair receipt has no evidence ledger: {repair}")
            applied = _has_ledger_signal(
                repair, {"applied", "repaired", "safefixes", "saferepairs", "completed"}
            )
            escalated = _has_ledger_signal(
                repair,
                {"unsafe", "escalated", "escalations", "unresolved", "needsreview", "rejected"},
            )
            if not applied or not escalated:
                raise RuntimeError(
                    f"leap demo must apply a safe fix and escalate an unsafe finding: {repair}"
                )
            if not output.is_file():
                raise RuntimeError(f"repair output was not created: {output}")

            return (
                {
                    "ok": True,
                    "status": "passed",
                    "tools": sorted(TOOLS),
                    "categories": sorted(categories),
                    "safeFixApplied": applied,
                    "unsafeEscalated": escalated,
                    "renderChecked": False,
                    "realHancomVerified": False,
                    "verificationStatus": "structurally_verified_render_unverified",
                    "outputPath": str(output),
                    "review": review,
                    "repair": repair,
                },
                0,
            )


def _bootstrap(argv: list[str]) -> int:
    env = dict(os.environ, HWPX_FIXTURE_E2E_BOOTSTRAPPED="1")
    return subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--with",
            "mcp>=1.2",
            "--with",
            "anyio>=4",
            "python",
            __file__,
            *argv,
        ],
        env=env,
        check=False,
    ).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--filename", type=Path, required=True)
    parser.add_argument("--repair-plan", type=Path, required=True)
    parser.add_argument("--case-id")
    parser.add_argument("--adapter-evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sandbox-root", type=Path, required=True)
    parser.add_argument("--launcher", type=Path, default=_default_launcher())
    parser.add_argument("--mcp-repo", type=Path)
    parser.add_argument("--core-repo", type=Path)
    parser.add_argument("--expected-category", action="append", default=[])
    parser.add_argument("--idempotency-key", default="installed-fixture-leap-demo")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--require-tools", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    inputs = [
        (args.manifest, "manifest"),
        (args.filename, "filename"),
        (args.repair_plan, "repair plan"),
        (args.launcher, "launcher"),
    ]
    if args.adapter_evidence:
        inputs.append((args.adapter_evidence, "adapter evidence"))
    for path, label in inputs:
        if not path.is_file():
            parser.error(f"{label} not found: {path}")
    if len(args.expected_category) not in (0,) and len(set(args.expected_category)) < 3:
        parser.error("provide either zero or at least three distinct --expected-category values")

    try:
        import anyio
        import mcp  # noqa: F401
    except ModuleNotFoundError:
        if os.environ.get("HWPX_FIXTURE_E2E_BOOTSTRAPPED") == "1":
            raise
        return _bootstrap(sys.argv[1:] if argv is None else argv)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report, returncode = anyio.run(_run, args)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
