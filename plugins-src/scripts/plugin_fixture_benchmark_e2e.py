#!/usr/bin/env python3
"""Exercise the fixture benchmark through the installed MCP launcher."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any


TOOLS = {"run_fixture_benchmark", "export_fixture_benchmark"}


def _structured(result: Any) -> dict[str, Any]:
    if bool(getattr(result, "isError", False)):
        raise RuntimeError(f"MCP tool error: {result}")
    if isinstance(getattr(result, "structuredContent", None), dict):
        return result.structuredContent
    for item in getattr(result, "content", ()):
        try:
            value = json.loads(item.text)
        except (AttributeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            return value
    return {}


def _honest(value: dict[str, Any]) -> None:
    claims = value.get("receipt") if isinstance(value.get("receipt"), dict) else value
    expected = {
        "humanControls": False,
        "humanJudges": False,
        "realAgentClients": False,
        "realHancomVerified": False,
        "replacementClaimAllowed": False,
    }
    for key, wanted in expected.items():
        if claims.get(key) is not wanted:
            raise RuntimeError(f"fixture result promoted {key}: {claims.get(key)!r}")


async def run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    manifest = args.manifest.resolve()
    temporary: tempfile.TemporaryDirectory[str] | None = None
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    runs = payload.get("runs", [])
    if runs and not (manifest.parent / runs[0]["artifact"]["path"]).is_file():
        # Compact installed bundles regenerate deterministic blind packets rather
        # than carrying hundreds of duplicated fixture files per host.
        temporary = tempfile.TemporaryDirectory(prefix="hwpx-s070-")
        generated = Path(temporary.name)
        import fixture_benchmark
        fixture_benchmark.build(generated)
        generated_manifest = json.loads((generated / "manifest.json").read_text(encoding="utf-8"))
        if payload.get("judgments"):
            generated_manifest["judgments"] = payload["judgments"]
            generated_manifest.pop("manifestHash", None)
            generated_manifest["manifestHash"] = fixture_benchmark.digest(generated_manifest)
            fixture_benchmark.write_json(generated / "final-manifest.json", generated_manifest)
            manifest = generated / "final-manifest.json"
        else:
            manifest = generated / "manifest.json"
    env = dict(
        os.environ,
        HWPX_AUTOMATION_WORKSPACE_ROOTS=json.dumps(
            [str(args.sandbox_root.resolve())]
        ),
        LOG_LEVEL="ERROR",
    )
    if args.automation_repo:
        env["HWPX_AUTOMATION_REPO"] = str(args.automation_repo.resolve())
    if args.core_repo:
        env["PYTHON_HWPX_REPO"] = str(args.core_repo.resolve())
    params = StdioServerParameters(command=str(args.launcher.resolve()), env=env, cwd=args.launcher.resolve().parent.parent)
    async with stdio_client(params, errlog=sys.stderr) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            names = {tool.name for tool in (await session.list_tools()).tools}
            missing = sorted(TOOLS - names)
            if missing:
                return {"ok": not args.require_tools, "status": "skipped", "missingTools": missing}, int(args.require_tools)
            timeout = timedelta(seconds=args.timeout)
            run_result = _structured(await session.call_tool("run_fixture_benchmark", {
                "manifest_path": str(manifest),
                "output_dir": str(args.output.resolve() / "run"),
                "strict": True,
            }, read_timeout_seconds=timeout))
            _honest(run_result)
            if run_result.get("ok") is not True:
                reasons = run_result.get("failReasons", [])
                pending_only = bool(reasons) and all("fewer_than_two_fixture_judges" in str(reason) for reason in reasons)
                if not pending_only or args.require_complete:
                    raise RuntimeError(f"fixture benchmark failed closed: {reasons}")
                return {
                    "ok": True,
                    "status": "passed_pending_independent_agent_judges",
                    "tools": sorted(TOOLS),
                    "receipt": run_result.get("receipt"),
                    "pendingJudgeArtifactCount": len(reasons),
                    "failReasonKinds": ["fewer_than_two_fixture_judges"],
                    "exportAttempted": False,
                }, 0
            result_path = run_result.get("resultManifestPath") or run_result.get("result_manifest_path")
            if not isinstance(result_path, str):
                raise RuntimeError(f"result manifest path missing: {run_result}")
            export_result = _structured(await session.call_tool("export_fixture_benchmark", {
                "result_manifest_path": result_path,
                "output_dir": str(args.output.resolve() / "public"),
                "strict": True,
            }, read_timeout_seconds=timeout))
            _honest(export_result)
            return {"ok": True, "status": "passed", "tools": sorted(TOOLS), "receipt": run_result.get("receipt"), "export": export_result}, 0


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=root / "examples/s070_fixture_benchmark/manifest.json")
    parser.add_argument("--output", type=Path, default=root / "examples/out/s070_fixture_benchmark")
    parser.add_argument(
        "--launcher",
        type=Path,
        default=(
            root
            / "plugins"
            / "codex"
            / "hwpx-plugin"
            / "scripts"
            / "hwpx-automation-mcp"
        ),
    )
    parser.add_argument("--sandbox-root", type=Path, default=root.parent)
    parser.add_argument(
        "--automation-repo",
        "--mcp-repo",
        dest="automation_repo",
        type=Path,
    )
    parser.add_argument("--core-repo", type=Path)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--require-tools", action="store_true")
    parser.add_argument("--require-complete", action="store_true", help="require two populated independent agent-judge passes and public export")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if os.environ.get("HWPX_S070_E2E_BOOTSTRAPPED") != "1":
        env = dict(os.environ, HWPX_S070_E2E_BOOTSTRAPPED="1")
        return subprocess.run(["uv", "run", "--no-project", "--with", "mcp>=1.2", "--with", "anyio>=4", "python", __file__, *sys.argv[1:]], env=env).returncode
    report, code = asyncio.run(run(args))
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text, end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
