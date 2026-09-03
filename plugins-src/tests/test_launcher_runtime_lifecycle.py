# tests/test_launcher_runtime_lifecycle.py
# SPDX-License-Identifier: Apache-2.0
"""Runs the real bundled launcher template against the offline fake uv.

Covers Feature 066 D2: generation/pointer layout, verified vs floor channel,
state file, fail-closed self-check, concurrency, and (Task 3) the refresh job.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "packaging" / "templates" / "hwpx-automation-mcp"
HARNESS_BIN = ROOT / "tests" / "launcher_harness" / "bin"
INDEX_V1 = {"python-hwpx": ["6.3.0"], "python-hwpx-automation": ["7.0.3"]}
INDEX_V2 = {"python-hwpx": ["6.3.0", "6.3.1"], "python-hwpx-automation": ["7.0.3"]}
INDEX_V3 = {"python-hwpx": ["6.3.0", "6.3.1", "6.3.2"], "python-hwpx-automation": ["7.0.3"]}
IDENTITY = json.loads((ROOT / "packaging" / "product-identity.json").read_text(encoding="utf-8"))
CORE = IDENTITY["components"]["core"]["currentVersion"]
AUTOMATION = IDENTITY["components"]["automation"]["currentVersion"]


def _env(tmp_path: Path, index: dict | None = None, **extra: str) -> dict[str, str]:
    env = {
        "PATH": f"{HARNESS_BIN}:{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "FAKE_UV_INDEX": json.dumps(index or INDEX_V1),
        "FAKE_UV_CALLS": str(tmp_path / "uv-calls.jsonl"),
        "HWPX_AUTOMATION_DISABLE_LOCAL_EDITABLE": "1",
        "HWPX_AUTOMATION_RUNTIME_ROOT": str(tmp_path / "runtime"),
        # Fresh stamp after a cold start is not due at 24h; refresh tests
        # invoke the job synchronously or set the interval to 0 explicitly.
        "HWPX_STACK_UPDATE_INTERVAL_HOURS": "24",
    }
    env.update(extra)
    return env


def _launch(env: dict[str, str], *args: str, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(TEMPLATE), *args], env=env, capture_output=True, text=True, timeout=timeout)


def _env_dir(tmp_path: Path) -> Path:
    dirs = [p for p in (tmp_path / "runtime" / "envs").iterdir() if p.is_dir()]
    assert len(dirs) == 1, dirs
    return dirs[0]


def _generations(env_dir: Path) -> list[str]:
    return sorted(p.name for p in env_dir.glob("gen-*") if p.is_dir())


def _state(env_dir: Path) -> dict:
    return json.loads((env_dir / "update-state.json").read_text(encoding="utf-8"))


def _uv_calls(env: dict[str, str]) -> list[list[str]]:
    path = Path(env["FAKE_UV_CALLS"])
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def _no_leftovers(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    assert not list(runtime.glob(".build-*"))
    assert not list(runtime.glob("install.lock*"))


def test_cold_start_builds_one_generation_and_points_current(tmp_path: Path) -> None:
    env = _env(tmp_path)
    result = _launch(env, "--help")
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("usage: hwpx-automation-mcp")
    env_dir = _env_dir(tmp_path)
    assert _generations(env_dir) == [f"gen-{CORE}-{AUTOMATION}"]
    assert (env_dir / "current").read_text().strip() == f"gen-{CORE}-{AUTOMATION}"
    assert (env_dir / "last-check").exists()
    state = _state(env_dir)
    assert state["schemaVersion"] == "hwpx.stack-update-state.v1"
    assert state["runtime"]["installed"] == {"python-hwpx": CORE, "python-hwpx-automation": AUTOMATION}
    assert state["runtime"]["latestAvailable"] == state["runtime"]["installed"]
    assert state["autoUpdate"] is True and state["channel"] == "floor" and state["lastError"] is None
    assert state["pluginBundle"]["installed"] == IDENTITY["components"]["plugin"]["currentVersion"]
    _no_leftovers(tmp_path)


def test_warm_start_execs_server_without_touching_the_index(tmp_path: Path) -> None:
    env = _env(tmp_path)
    assert _launch(env, "--help").returncode == 0
    Path(env["FAKE_UV_CALLS"]).unlink()
    result = _launch(env, "--transport", "stdio")
    assert result.returncode == 0, result.stderr
    env_dir = _env_dir(tmp_path)
    assert result.stdout.strip() == (
        f"FAKE-SERVER core={CORE} automation={AUTOMATION} "
        f"state={env_dir / 'update-state.json'} args=--transport stdio"
    )
    assert all(call[:2] != ["pip", "install"] for call in _uv_calls(env))


def test_floor_channel_installs_newest_inside_the_major_window(tmp_path: Path) -> None:
    index = {"python-hwpx": ["6.3.0", "6.3.1", "7.0.0"], "python-hwpx-automation": ["7.0.3", "8.0.0"]}
    env = _env(tmp_path, index)
    assert _launch(env, "--help").returncode == 0
    assert _generations(_env_dir(tmp_path)) == ["gen-6.3.1-7.0.3"]
    specs = [arg for call in _uv_calls(env) if call[:2] == ["pip", "install"] for arg in call if arg.startswith("python-hwpx")]
    assert "python-hwpx[preview]>=6.3.0,<7" in specs and "python-hwpx-automation[mcp,oracle]>=7.0.3,<8" in specs


def test_verified_channel_requests_the_exact_verified_pair(tmp_path: Path) -> None:
    env = _env(tmp_path, INDEX_V2, HWPX_STACK_CHANNEL="verified")
    assert _launch(env, "--help").returncode == 0
    env_dir = _env_dir(tmp_path)
    assert _generations(env_dir) == [f"gen-{CORE}-{AUTOMATION}"]
    assert _state(env_dir)["channel"] == "verified"
    specs = [arg for call in _uv_calls(env) if call[:2] == ["pip", "install"] for arg in call if arg.startswith("python-hwpx")]
    assert f"python-hwpx[preview]=={CORE}" in specs and f"python-hwpx-automation[mcp,oracle]=={AUTOMATION}" in specs


def test_invalid_channel_fails_closed(tmp_path: Path) -> None:
    result = _launch(_env(tmp_path, HWPX_STACK_CHANNEL="nightly"), "--help")
    assert result.returncode == 64 and "HWPX_STACK_CHANNEL" in result.stderr


def test_cold_start_rejects_a_runtime_that_fails_the_capability_handshake(tmp_path: Path) -> None:
    env = _env(tmp_path, FAKE_UV_CAPABILITY_OK="0")
    result = _launch(env, "--help")
    assert result.returncode != 0
    assert "capability handshake" in result.stderr
    env_dir = _env_dir(tmp_path)
    assert not (env_dir / "current").exists() and _generations(env_dir) == []
    _no_leftovers(tmp_path)


def test_concurrent_cold_start_yields_one_generation(tmp_path: Path) -> None:
    env = _env(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: _launch(env, "--help"), range(2)))
    assert all(r.returncode == 0 for r in results), [r.stderr for r in results]
    assert _generations(_env_dir(tmp_path)) == [f"gen-{CORE}-{AUTOMATION}"]
    _no_leftovers(tmp_path)
