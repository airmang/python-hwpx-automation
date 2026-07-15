#!/usr/bin/env python3
"""Build clean core/MCP wheels and drive them through the installed plugin launcher."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STACK = ROOT.parent


def _copy_repo(source: Path, destination: Path) -> None:
    ignored = shutil.ignore_patterns(
        ".git",
        ".venv",
        ".pytest_cache",
        ".coverage",
        "build",
        "dist",
        "*.egg-info",
        "__pycache__",
    )
    shutil.copytree(source, destination, ignore=ignored)


def _run(
    command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None
) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def _probe_concurrent_cold_start(
    launcher: Path,
    *,
    workspace: Path,
    runtime_root: Path,
    env: dict[str, str],
) -> dict[str, object]:
    processes = [
        subprocess.Popen(
            [str(launcher), "--help"],
            cwd=workspace,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    results: list[dict[str, object]] = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=300)
        results.append(
            {
                "returncode": process.returncode,
                "stdoutTail": stdout[-500:],
                "stderrTail": stderr[-500:],
            }
        )
    if any(item["returncode"] != 0 for item in results):
        raise RuntimeError(f"concurrent launcher cold start failed: {results}")

    env_root = runtime_root / "envs"
    environments = sorted(
        path
        for path in env_root.iterdir()
        if path.is_dir() and re.fullmatch(r"[0-9a-f]{64}", path.name)
    )
    if len(environments) != 1:
        raise RuntimeError(f"expected one fingerprinted runtime, found: {environments}")
    environment = environments[0]
    marker = environment / ".hwpx-stack-fingerprint"
    if marker.read_text(encoding="utf-8").strip() != environment.name:
        raise RuntimeError(
            "launcher runtime fingerprint marker does not match its directory"
        )
    if not (environment / "bin" / "python").is_file():
        raise RuntimeError("launcher runtime is missing its Python entry point")
    leftovers = sorted(runtime_root.glob(".build-*"))
    leftovers.extend(
        path for path in runtime_root.glob("install.lock*") if path.exists()
    )
    if leftovers:
        raise RuntimeError(f"launcher left incomplete installation state: {leftovers}")
    return {
        "ok": True,
        "concurrentProcesses": len(processes),
        "fingerprint": environment.name,
        "runtimeCount": len(environments),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core-repo", type=Path, default=STACK / "python-hwpx")
    parser.add_argument("--mcp-repo", type=Path, default=STACK / "hwpx-mcp-server")
    parser.add_argument("--skill-root", type=Path, default=ROOT)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="hwpx-3stack-smoke-") as tmp:
        temp = Path(tmp)
        source_stack = temp / "stack"
        source_stack.mkdir()
        core_copy = source_stack / "python-hwpx"
        mcp_copy = source_stack / "hwpx-mcp-server"
        _copy_repo(args.core_repo.resolve(), core_copy)
        _copy_repo(args.mcp_repo.resolve(), mcp_copy)

        wheelhouse = temp / "wheelhouse"
        wheelhouse.mkdir()
        build_args = [
            "uv",
            "build",
            "--wheel",
            "--no-sources",
            "--no-build-logs",
            "--out-dir",
            str(wheelhouse),
        ]
        _run([*build_args, str(core_copy)])
        _run([*build_args, str(mcp_copy)])
        core_wheel = next(wheelhouse.glob("python_hwpx-*.whl"))
        mcp_wheel = next(wheelhouse.glob("hwpx_mcp_server-*.whl"))

        launcher = (
            args.skill_root
            / "plugins"
            / "codex"
            / "hwpx-plugin"
            / "scripts"
            / "hwpx-mcp-server"
        )
        contract = args.skill_root / "references" / "tool-contract.generated.json"
        env = dict(os.environ)
        runtime_root = temp / "plugin-runtime"
        workspace = temp / "workspace"
        workspace.mkdir()
        server_package = str(mcp_wheel)
        core_package = f"{core_wheel}[visual]"
        env.update(
            {
                "HWPX_MCP_DISABLE_LOCAL_EDITABLE": "1",
                "HWPX_MCP_SERVER_PACKAGE": server_package,
                "HWPX_PYTHON_HWPX_PACKAGE": core_package,
                "HWPX_MCP_SERVER_VERSION": "3.0.0",
                "HWPX_PYTHON_HWPX_VERSION": "3.0.0",
                "HWPX_SKILL_VERSION": "0.2.0",
                "HWPX_MCP_RUNTIME_ROOT": str(runtime_root),
                "HWPX_MCP_WORKSPACE_ROOTS": json.dumps([str(workspace)]),
            }
        )
        launcher_runtime = _probe_concurrent_cold_start(
            launcher,
            workspace=workspace,
            runtime_root=runtime_root,
            env=env,
        )
        e2e_report = temp / "plugin-e2e.json"
        e2e_command = [
            args.python,
            str(args.skill_root / "scripts" / "plugin_mcp_e2e.py"),
            "--launcher",
            str(launcher),
            "--contract",
            str(contract),
            "--server-package",
            server_package,
            "--core-package",
            core_package,
            "--server-runtime",
            str(runtime_root),
            "--skill-version",
            "0.2.0",
            "--report",
            str(e2e_report),
        ]
        _run(
            e2e_command,
            cwd=args.skill_root,
            env=env,
        )
        report = {
            "ok": True,
            "launcherRuntime": launcher_runtime,
            "protocol": json.loads(e2e_report.read_text(encoding="utf-8")),
        }
        if args.report:
            args.report.resolve().parent.mkdir(parents=True, exist_ok=True)
            args.report.resolve().write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(report, ensure_ascii=False, indent=2))
    print("[OK] clean wheel install + plugin MCP protocol smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
