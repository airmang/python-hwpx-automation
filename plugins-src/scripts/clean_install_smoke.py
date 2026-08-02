#!/usr/bin/env python3
"""Build candidate wheels and drive them through a clean installed plugin runtime."""

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

# 후보 정확 좌표의 단일 진실 원천은 product identity다 — 하드코딩 리터럴이
# 트레인마다 뒤처져 CI를 잡아먹던 이력(1.1.0 기본값·6.3.1 동결) 재발 방지.
_IDENTITY = json.loads(
    (ROOT / "packaging" / "product-identity.json").read_text(encoding="utf-8")
)
EXPECTED_STACK_VERSIONS = {
    "python-hwpx": _IDENTITY["components"]["core"]["currentVersion"],
    "python-hwpx-automation": _IDENTITY["components"]["automation"]["currentVersion"],
}
_SOURCE_AFFECTING_ENV = ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")
_RUNTIME_PROBE = r"""
import importlib.util
import json
from importlib.metadata import version
from pathlib import Path

import hwpx
import hwpx_automation

payload = {
    "versions": {
        "python-hwpx": version("python-hwpx"),
        "python-hwpx-automation": version("python-hwpx-automation"),
    },
    "origins": {
        "hwpx": str(Path(hwpx.__file__).resolve()),
        "hwpx_automation": str(Path(hwpx_automation.__file__).resolve()),
    },
    "capabilities": {
        "mcp": importlib.util.find_spec("mcp") is not None,
        "pymupdf": importlib.util.find_spec("fitz") is not None,
        "pillow": importlib.util.find_spec("PIL") is not None,
        "numpy": importlib.util.find_spec("numpy") is not None,
        "previewMath": importlib.util.find_spec("latex2mathml") is not None,
    },
}
print(json.dumps(payload))
"""


def _sanitized_environment(
    base: dict[str, str] | None = None,
) -> dict[str, str]:
    """Remove ambient selectors that can substitute checkout code for wheels."""

    env = dict(os.environ if base is None else base)
    for name in _SOURCE_AFFECTING_ENV:
        env.pop(name, None)
    return env


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
        "out",
    )
    shutil.copytree(source, destination, ignore=ignored)


def _run(
    command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None
) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(
        command,
        cwd=cwd,
        env=_sanitized_environment(env),
        check=True,
    )


def _probe_concurrent_cold_start(
    launcher: Path,
    *,
    workspace: Path,
    runtime_root: Path,
    env: dict[str, str],
) -> dict[str, object]:
    clean_env = _sanitized_environment(env)
    processes = [
        subprocess.Popen(
            [str(launcher), "--help"],
            cwd=workspace,
            env=clean_env,
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
        "runtimePython": str(environment / "bin" / "python"),
    }


def _probe_installed_runtime(
    runtime_python: Path,
    *,
    excluded_source_roots: list[Path],
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    completed = subprocess.run(
        [str(runtime_python), "-c", _RUNTIME_PROBE],
        env=_sanitized_environment(env),
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    expected_versions = dict(EXPECTED_STACK_VERSIONS)
    if payload.get("versions") != expected_versions:
        raise RuntimeError(
            f"installed candidate version mismatch: {payload.get('versions')}"
        )
    roots = [root.resolve() for root in excluded_source_roots]
    for module, raw_origin in payload.get("origins", {}).items():
        origin = Path(raw_origin).resolve()
        if "site-packages" not in origin.as_posix():
            raise RuntimeError(f"{module} did not load from site-packages: {origin}")
        if any(origin == root or root in origin.parents for root in roots):
            raise RuntimeError(f"{module} leaked from source checkout: {origin}")
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, dict) or not all(capabilities.values()):
        raise RuntimeError(f"installed runtime extras are incomplete: {capabilities}")
    payload["ok"] = True
    return payload


def _probe_editable_runtime(
    launcher: Path,
    *,
    core_repo: Path,
    automation_repo: Path,
    workspace: Path,
) -> dict[str, object]:
    """Prove the opt-in editable launcher and its declared extras are usable."""

    env = _sanitized_environment()
    env.update(
        {
            "PYTHON_HWPX_REPO": str(core_repo),
            "HWPX_AUTOMATION_REPO": str(automation_repo),
            "HWPX_AUTOMATION_DISABLE_LOCAL_EDITABLE": "0",
            "HWPX_AUTOMATION_WORKSPACE_ROOTS": json.dumps([str(workspace)]),
            "HWPX_SKILL_VERSION": "1.6.0",
        }
    )
    help_probe = subprocess.run(
        [str(launcher), "--help"],
        cwd=workspace,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    completed = subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--no-sources",
            "--with-editable",
            f"{core_repo}[preview]",
            "--with-editable",
            f"{automation_repo}[mcp,oracle]",
            "python",
            "-c",
            _RUNTIME_PROBE,
        ],
        cwd=workspace,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    expected_versions = dict(EXPECTED_STACK_VERSIONS)
    if payload.get("versions") != expected_versions:
        raise RuntimeError(
            f"editable candidate version mismatch: {payload.get('versions')}"
        )
    expected_roots = {
        "hwpx": core_repo.resolve(),
        "hwpx_automation": automation_repo.resolve(),
    }
    for module, expected_root in expected_roots.items():
        origin = Path(payload["origins"][module]).resolve()
        if origin != expected_root and expected_root not in origin.parents:
            raise RuntimeError(
                f"{module} did not load from the selected editable checkout: {origin}"
            )
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, dict) or not all(capabilities.values()):
        raise RuntimeError(f"editable runtime extras are incomplete: {capabilities}")
    payload.update(
        {
            "ok": True,
            "mode": "explicit-editable",
            "launcherHelp": bool(help_probe.stdout or help_probe.stderr),
        }
    )
    return payload


def _candidate_repo(
    supplied: Path | None,
    *,
    env_name: str,
    option_name: str,
    label: str,
) -> Path:
    raw = supplied or (Path(os.environ[env_name]) if os.environ.get(env_name) else None)
    if raw is None:
        raise SystemExit(
            f"{label} candidate checkout is required. Pass {option_name} or set "
            f"{env_name}; no sibling or private worktree is selected implicitly."
        )
    candidate = raw.resolve()
    if not (candidate / "pyproject.toml").is_file():
        raise SystemExit(
            f"{label} candidate checkout not found: {candidate}. "
            f"Pass {option_name} or set {env_name}; no sibling or private worktree "
            "is selected implicitly."
        )
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core-repo", type=Path)
    parser.add_argument(
        "--automation-repo",
        "--mcp-repo",
        dest="automation_repo",
        type=Path,
    )
    parser.add_argument("--skill-root", type=Path, default=ROOT)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    core_repo = _candidate_repo(
        args.core_repo,
        env_name="PYTHON_HWPX_CANDIDATE_REPO",
        option_name="--core-repo",
        label="core",
    )
    automation_repo = _candidate_repo(
        args.automation_repo,
        env_name="HWPX_AUTOMATION_CANDIDATE_REPO",
        option_name="--automation-repo",
        label="automation",
    )

    with tempfile.TemporaryDirectory(prefix="hwpx-3stack-smoke-") as tmp:
        temp = Path(tmp)
        source_stack = temp / "stack"
        source_stack.mkdir()
        core_copy = source_stack / "python-hwpx"
        automation_copy = source_stack / "python-hwpx-automation"
        skill_copy = source_stack / "hwpx-skill"
        _copy_repo(core_repo, core_copy)
        _copy_repo(automation_repo, automation_copy)
        _copy_repo(args.skill_root.resolve(), skill_copy)

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
        _run([*build_args, str(automation_copy)])
        core_wheel = next(wheelhouse.glob("python_hwpx-*.whl"))
        automation_wheel = next(wheelhouse.glob("python_hwpx_automation-*.whl"))

        launcher = (
            skill_copy
            / "plugins"
            / "codex"
            / "hwpx-plugin"
            / "scripts"
            / "hwpx-automation-mcp"
        )
        compatibility_launcher = launcher.with_name("hwpx-mcp-server")
        contract = skill_copy / "references" / "tool-contract.generated.json"
        env = _sanitized_environment()
        runtime_root = temp / "plugin-runtime"
        workspace = temp / "workspace"
        workspace.mkdir()
        editable_runtime = _probe_editable_runtime(
            launcher,
            core_repo=core_copy,
            automation_repo=automation_copy,
            workspace=workspace,
        )
        server_package = f"{automation_wheel}[mcp,oracle]"
        core_package = f"{core_wheel}[preview]"
        env.update(
            {
                "HWPX_AUTOMATION_DISABLE_LOCAL_EDITABLE": "1",
                "HWPX_AUTOMATION_PACKAGE": server_package,
                "HWPX_PYTHON_HWPX_PACKAGE": core_package,
                "HWPX_AUTOMATION_VERSION": "6.6.0",
                "HWPX_PYTHON_HWPX_VERSION": "5.6.0",
                "HWPX_SKILL_VERSION": "1.6.0",
                "HWPX_AUTOMATION_RUNTIME_ROOT": str(runtime_root),
                "HWPX_AUTOMATION_WORKSPACE_ROOTS": json.dumps([str(workspace)]),
            }
        )
        poison_root = temp / "poison-python-environment"
        for package in ("hwpx", "hwpx_automation"):
            package_dir = poison_root / package
            package_dir.mkdir(parents=True)
            (package_dir / "__init__.py").write_text(
                'raise RuntimeError("ambient PYTHONPATH leaked into clean smoke")\n',
                encoding="utf-8",
            )
        # Every installed/cold-start/E2E subprocess receives this deliberately
        # poisoned input. Each execution boundary must strip it before launch.
        env.update(
            {
                "PYTHONPATH": str(poison_root),
                "PYTHONHOME": str(poison_root),
                "VIRTUAL_ENV": str(poison_root / "venv"),
            }
        )
        launcher_runtime = _probe_concurrent_cold_start(
            launcher,
            workspace=workspace,
            runtime_root=runtime_root,
            env=env,
        )
        runtime_python = Path(str(launcher_runtime["runtimePython"]))
        installed_runtime = _probe_installed_runtime(
            runtime_python,
            excluded_source_roots=[core_repo, automation_repo, core_copy, automation_copy],
            env=env,
        )
        _run(
            [str(compatibility_launcher), "--help"],
            cwd=workspace,
            env=env,
        )
        _run(
            [
                str(runtime_python),
                str(skill_copy / "scripts" / "quickcheck.py"),
                "--government-report",
                "--visual-review-batch",
            ],
            cwd=skill_copy,
            env=env,
        )
        _run(
            [
                str(runtime_python),
                str(skill_copy / "examples" / "14_mail_merge_table_compute.py"),
            ],
            cwd=skill_copy,
            env=env,
        )
        e2e_report = temp / "plugin-e2e.json"
        canonical_mcp_config = (
            skill_copy / "plugins" / "claude" / "hwpx-plugin" / ".mcp.json"
        )
        e2e_command = [
            args.python,
            str(skill_copy / "scripts" / "plugin_mcp_e2e.py"),
            "--mcp-config",
            str(canonical_mcp_config),
            "--contract",
            str(contract),
            "--server-package",
            server_package,
            "--core-package",
            core_package,
            "--server-runtime",
            str(runtime_root),
            "--skill-version",
            "1.6.0",
            "--report",
            str(e2e_report),
        ]
        _run(
            e2e_command,
            cwd=skill_copy,
            env=env,
        )
        legacy_mcp_config = temp / "legacy-mcp-config.json"
        legacy_mcp_config.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "hwpx-mcp-server": {
                            "command": str(compatibility_launcher),
                            "args": [],
                            "env": {
                                "HWPX_SKILL_VERSION": "1.6.0",
                            },
                        }
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        legacy_e2e_report = temp / "plugin-e2e-legacy-override.json"
        _run(
            [
                args.python,
                str(skill_copy / "scripts" / "plugin_mcp_e2e.py"),
                "--mcp-config",
                str(legacy_mcp_config),
                "--mcp-server-name",
                "hwpx-mcp-server",
                "--contract",
                str(contract),
                "--server-package",
                server_package,
                "--core-package",
                core_package,
                "--server-runtime",
                str(runtime_root),
                "--skill-version",
                "1.6.0",
                "--report",
                str(legacy_e2e_report),
            ],
            cwd=skill_copy,
            env=env,
        )
        canonical_protocol = json.loads(e2e_report.read_text(encoding="utf-8"))
        legacy_protocol = json.loads(
            legacy_e2e_report.read_text(encoding="utf-8")
        )
        report = {
            "ok": True,
            "candidateSources": {
                "core": str(core_repo),
                "automation": str(automation_repo),
            },
            "launcherRuntime": launcher_runtime,
            "editableRuntime": editable_runtime,
            "installedRuntime": installed_runtime,
            "environmentIsolation": {
                "ok": True,
                "poisonedVariables": list(_SOURCE_AFFECTING_ENV),
                "poisonRoot": str(poison_root),
                "installedOrigins": installed_runtime["origins"],
            },
            "compatibilityLauncher": {
                "ok": True,
                "path": str(compatibility_launcher),
                "delegatesTo": str(launcher),
            },
            "hostConfigIdentity": {
                "canonical": canonical_protocol["identity"],
                "legacyExplicitOverride": legacy_protocol["identity"],
            },
            "exampleCoverage": [
                "quickcheck.py --government-report --visual-review-batch",
                "14_mail_merge_table_compute.py",
            ],
            "protocol": canonical_protocol,
            "legacyOverrideProtocol": {
                "ok": legacy_protocol["ok"],
                "toolCount": legacy_protocol["toolCount"],
                "contractHash": legacy_protocol["contractHash"],
                "identity": legacy_protocol["identity"],
                "launchSurface": legacy_protocol["launchSurface"],
            },
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
