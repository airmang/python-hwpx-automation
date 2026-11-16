#!/usr/bin/env python3
"""Start the Claude bundle's MCP server exactly as its .mcp.json declares.

The Claude bundle runs ``uv run --frozen`` against ``server/uv.lock``. This smoke
copies the bundle into a temporary plugin root (Claude Code installs a copy under
``~/.claude/plugins/cache``), substitutes ``${CLAUDE_PLUGIN_ROOT}`` and
``${CLAUDE_PLUGIN_DATA}`` the way Claude Code does, starts the server from an
empty user project, and checks the MCP handshake, the default tool count from
the tool contract, the reported engine versions, that the runtime environment
was created inside the plugin copy, and that nothing was written to the user's
project. Needs ``uv`` and network access for the first install.

Usage::

    python3 scripts/claude_locked_runtime_smoke.py [--report out.json]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "plugins" / "claude" / "hwpx-plugin"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--timeout", type=int, default=900, help="seconds allowed for the first install and handshake")
    args = parser.parse_args(argv)

    identity = json.loads((ROOT / "packaging" / "product-identity.json").read_text(encoding="utf-8"))["components"]
    contract = json.loads((ROOT / "references" / "tool-contract.generated.json").read_text(encoding="utf-8"))
    server = json.loads((BUNDLE / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["hwpx"]
    # The locked pair is whatever server/pyproject.toml pins: the refresh bot may move it
    # ahead of the identity's verified coordinates inside the install window.
    pins = dict(re.findall(r'"(python-hwpx(?:-automation)?)\[[^\]]*\]==([^"]+)"',
                           (BUNDLE / "server" / "pyproject.toml").read_text(encoding="utf-8")))
    expected_automation = pins[identity["automation"]["distribution"]]
    expected_core = pins[identity["core"]["distribution"]]

    cache = Path(tempfile.mkdtemp(prefix="claude-plugin-cache-"))
    plugin_root = cache / "hwpx-plugin"
    shutil.copytree(BUNDLE, plugin_root)
    data = Path(tempfile.mkdtemp(prefix="claude-plugin-data-"))
    project = Path(tempfile.mkdtemp(prefix="claude-user-project-"))

    def sub(value: str) -> str:
        return value.replace("${CLAUDE_PLUGIN_ROOT}", str(plugin_root)).replace("${CLAUDE_PLUGIN_DATA}", str(data))

    command = [sub(server["command"]), *[sub(a) for a in server.get("args", [])]]
    env = {**os.environ, **{k: sub(v) for k, v in server.get("env", {}).items()}}
    env.update(CLAUDE_PLUGIN_ROOT=str(plugin_root), CLAUDE_PLUGIN_DATA=str(data))
    for key in ("VIRTUAL_ENV", "UV_PYTHON", "HWPX_AUTOMATION_REPO", "PYTHON_HWPX_REPO"):
        env.pop(key, None)

    started = time.time()
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env=env, cwd=project)
    result: dict = {"command": command, "ok": False}
    try:
        def send(message: dict) -> None:
            assert proc.stdin is not None
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()

        def receive(request_id: int) -> dict:
            assert proc.stdout is not None
            while True:
                if time.time() - started > args.timeout:
                    raise TimeoutError(f"no response within {args.timeout}s")
                line = proc.stdout.readline()
                if not line:
                    raise RuntimeError("server exited: " + (proc.stderr.read() if proc.stderr else "")[-2000:])
                message = json.loads(line)
                if message.get("id") == request_id:
                    if "error" in message:
                        raise RuntimeError(f"request {request_id} failed: {message['error']}")
                    return message["result"]

        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "claude-locked-runtime-smoke", "version": "1"}}})
        info = receive(1)["serverInfo"]
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = receive(2)["tools"]
        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "mcp_server_health", "arguments": {}}})
        health_text = json.dumps(receive(3), ensure_ascii=False)

        checks = {
            "serverVersion": info.get("version") == expected_automation,
            "defaultToolCount": len(tools) == contract["defaultToolCount"],
            "coreVersionReported": expected_core in re.findall(r'pythonHwpxVersion\\*"\s*:\s*\\*"([^"\\]+)', health_text),
            "runtimeInsidePluginCopy": (plugin_root / "server" / ".venv").is_dir(),
            "userProjectUntouched": not any(project.iterdir()),
        }
        result.update(
            ok=all(checks.values()),
            checks=checks,
            serverInfo=info,
            tools=len(tools),
            expectedTools=contract["defaultToolCount"],
            seconds=round(time.time() - started, 1),
        )
    except Exception as exc:  # report every failure as a record, then exit non-zero
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(data, ignore_errors=True)
        shutil.rmtree(cache, ignore_errors=True)
        shutil.rmtree(project, ignore_errors=True)

    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.write_text(text + "\n", encoding="utf-8")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
