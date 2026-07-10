#!/usr/bin/env python3
"""Build clean core/MCP wheels and drive them through the installed plugin launcher."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STACK = ROOT.parent


def _copy_repo(source: Path, destination: Path) -> None:
    ignored = shutil.ignore_patterns(
        ".git", ".venv", ".pytest_cache", ".coverage", "build", "dist", "*.egg-info", "__pycache__"
    )
    shutil.copytree(source, destination, ignore=ignored)


def _run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core-repo", type=Path, default=STACK / "python-hwpx")
    parser.add_argument("--mcp-repo", type=Path, default=STACK / "hwpx-mcp-server")
    parser.add_argument("--skill-root", type=Path, default=ROOT)
    parser.add_argument("--python", default=sys.executable)
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
        build_args = ["uv", "build", "--wheel", "--no-sources", "--no-build-logs", "--out-dir", str(wheelhouse)]
        _run([*build_args, str(core_copy)])
        _run([*build_args, str(mcp_copy)])
        core_wheel = next(wheelhouse.glob("python_hwpx-*.whl"))
        mcp_wheel = next(wheelhouse.glob("hwpx_mcp_server-*.whl"))

        plugin_venv = temp / "plugin-venv"
        _run(["uv", "venv", "--quiet", "--python", args.python, str(plugin_venv)])
        _run(
            [
                "uv", "pip", "install", "--quiet", "--python", str(plugin_venv / "bin" / "python"),
                str(core_wheel), str(mcp_wheel),
            ]
        )
        marker_value = str(mcp_wheel)
        (plugin_venv / ".hwpx-mcp-server-package").write_text(marker_value + "\n", encoding="utf-8")

        launcher = args.skill_root / "plugins" / "codex" / "hwpx-plugin" / "scripts" / "hwpx-mcp-server"
        contract = args.skill_root / "references" / "tool-contract.generated.json"
        env = dict(os.environ)
        _run(
            [
                str(plugin_venv / "bin" / "python"),
                str(args.skill_root / "scripts" / "plugin_mcp_e2e.py"),
                "--launcher", str(launcher),
                "--contract", str(contract),
                "--server-package", marker_value,
                "--server-venv", str(plugin_venv),
                "--skill-version", "0.1.25",
            ],
            cwd=args.skill_root,
            env=env,
        )
    print("[OK] clean wheel install + plugin MCP protocol smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
