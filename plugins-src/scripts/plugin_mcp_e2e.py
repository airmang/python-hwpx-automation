#!/usr/bin/env python3
"""Protocol-level E2E through the generated Codex plugin launcher."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any

try:
    import anyio
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
except ModuleNotFoundError:
    if os.environ.get("HWPX_E2E_BOOTSTRAPPED") == "1":
        raise
    env = dict(os.environ, HWPX_E2E_BOOTSTRAPPED="1")
    raise SystemExit(
        subprocess.run(
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
                *sys.argv[1:],
            ],
            env=env,
            check=False,
        ).returncode
    )


ROOT = Path(__file__).resolve().parents[1]


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


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    required = set(contract["skillRequiredTools"])
    with tempfile.TemporaryDirectory(prefix="hwpx-plugin-e2e-") as tmp:
        sandbox = Path(tmp)
        env = dict(os.environ)
        env.update(
            {
                "HWPX_MCP_SANDBOX_ROOT": str(sandbox),
                "HWPX_SKILL_VERSION": args.skill_version,
                "HWPX_MCP_ADVANCED": "0",
                "LOG_LEVEL": "ERROR",
            }
        )
        if args.mcp_repo:
            env["HWPX_MCP_SERVER_REPO"] = str(args.mcp_repo.resolve())
        if args.core_repo:
            env["PYTHON_HWPX_REPO"] = str(args.core_repo.resolve())
        if args.server_package:
            env["HWPX_MCP_SERVER_PACKAGE"] = args.server_package
            env["HWPX_MCP_DISABLE_LOCAL_EDITABLE"] = "1"
        if args.server_venv:
            env["HWPX_MCP_SERVER_VENV"] = str(args.server_venv)

        params = StdioServerParameters(
            command=str(args.launcher),
            args=[],
            env=env,
            cwd=args.launcher.parent.parent,
        )
        async with stdio_client(params, errlog=sys.stderr) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                listed = await session.list_tools()
                names = {tool.name for tool in listed.tools}
                missing = sorted(required - names)
                if missing:
                    raise RuntimeError(f"installed plugin missing skill-required tools: {missing}")
                if len(names) != int(contract["defaultToolCount"]):
                    raise RuntimeError(
                        f"installed plugin tool count {len(names)} != contract {contract['defaultToolCount']}"
                    )

                document = sandbox / "plugin-e2e.hwpx"
                timeout = timedelta(seconds=90)
                _structured(
                    await session.call_tool(
                        "create_document", {"filename": str(document)}, read_timeout_seconds=timeout
                    )
                )
                _structured(
                    await session.call_tool(
                        "add_paragraph",
                        {"filename": str(document), "text": "PLUGIN_E2E"},
                        read_timeout_seconds=timeout,
                    )
                )
                dry_run = _structured(
                    await session.call_tool(
                        "apply_body_ops",
                        {
                            "filename": str(document),
                            "ops": [
                                {
                                    "op": "replace_text",
                                    "find": "PLUGIN_E2E",
                                    "replace": "PLUGIN_E2E_OK",
                                    "count": 1,
                                }
                            ],
                            "dry_run": True,
                        },
                        read_timeout_seconds=timeout,
                    )
                )
                if dry_run.get("dryRun") is not True:
                    raise RuntimeError(f"apply_body_ops dry-run contract failed: {dry_run}")
                health = _structured(await session.call_tool("mcp_server_health", {}, read_timeout_seconds=timeout))
                if health.get("toolSurface", {}).get("status") != "ok":
                    raise RuntimeError(f"plugin health is not ok: {health}")
                return {
                    "ok": True,
                    "toolCount": len(names),
                    "contractHash": contract["contractHash"],
                    "requiredTools": sorted(required),
                    "applyBodyOpsDryRun": True,
                    "versions": health.get("capability", {}).get("versions"),
                }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--launcher",
        type=Path,
        default=ROOT / "plugins" / "codex" / "hwpx-plugin" / "scripts" / "hwpx-mcp-server",
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=ROOT / "references" / "tool-contract.generated.json",
    )
    parser.add_argument("--mcp-repo", type=Path)
    parser.add_argument("--core-repo", type=Path)
    parser.add_argument("--server-package")
    parser.add_argument("--server-venv", type=Path)
    parser.add_argument("--skill-version", default="0.1.25")
    args = parser.parse_args()
    if not args.launcher.is_file():
        parser.error(f"launcher not found: {args.launcher}")
    report = anyio.run(_run, args)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
