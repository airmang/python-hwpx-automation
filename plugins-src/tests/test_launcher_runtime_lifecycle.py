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


def _refresh(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return _launch({**env, "HWPX_STACK_REFRESH_JOB": "1"})


def test_refresh_is_a_noop_when_nothing_newer_exists(tmp_path: Path) -> None:
    env = _env(tmp_path)
    assert _launch(env, "--help").returncode == 0
    result = _refresh(env)
    assert result.returncode == 0, result.stderr
    env_dir = _env_dir(tmp_path)
    assert _generations(env_dir) == [f"gen-{CORE}-{AUTOMATION}"]
    state = _state(env_dir)
    assert state["runtime"]["latestAvailable"] == state["runtime"]["installed"] and state["lastError"] is None
    assert not (env_dir / "refresh.lock").exists()


def test_refresh_installs_a_newer_generation_and_repoints_current(tmp_path: Path) -> None:
    env = _env(tmp_path)
    assert _launch(env, "--help").returncode == 0
    env["FAKE_UV_INDEX"] = json.dumps(INDEX_V2)
    assert _refresh(env).returncode == 0
    env_dir = _env_dir(tmp_path)
    assert _generations(env_dir) == [f"gen-{CORE}-{AUTOMATION}", f"gen-6.3.1-{AUTOMATION}"]
    assert (env_dir / "current").read_text().strip() == f"gen-6.3.1-{AUTOMATION}"
    assert _state(env_dir)["runtime"]["installed"]["python-hwpx"] == "6.3.1"
    served = _launch(env, "x")
    assert served.stdout.startswith(f"FAKE-SERVER core=6.3.1 automation={AUTOMATION} ")
    _no_leftovers(tmp_path)


def test_refresh_keeps_current_when_the_candidate_fails_the_self_check(tmp_path: Path) -> None:
    env = _env(tmp_path)
    assert _launch(env, "--help").returncode == 0
    env.update({"FAKE_UV_INDEX": json.dumps(INDEX_V2), "FAKE_UV_BROKEN_VERSION": "6.3.1"})
    assert _refresh(env).returncode == 0
    env_dir = _env_dir(tmp_path)
    assert _generations(env_dir) == [f"gen-{CORE}-{AUTOMATION}"]
    assert (env_dir / "current").read_text().strip() == f"gen-{CORE}-{AUTOMATION}"
    state = _state(env_dir)
    assert state["runtime"]["latestAvailable"]["python-hwpx"] == "6.3.1"
    assert "self-check" in state["lastError"]
    _no_leftovers(tmp_path)


def test_refresh_records_offline_failure_and_the_server_still_starts(tmp_path: Path) -> None:
    env = _env(tmp_path)
    assert _launch(env, "--help").returncode == 0
    offline = {**env, "FAKE_UV_OFFLINE": "1"}
    assert _refresh(offline).returncode == 0
    state = _state(_env_dir(tmp_path))
    assert "resolution failed" in state["lastError"]
    assert state["runtime"]["installed"]["python-hwpx"] == CORE
    started = _launch(offline, "--help")
    assert started.returncode == 0 and started.stdout.startswith("usage:")


def test_generation_gc_keeps_current_and_one_previous(tmp_path: Path) -> None:
    env = _env(tmp_path)
    assert _launch(env, "--help").returncode == 0
    for index in (INDEX_V2, INDEX_V3):
        env["FAKE_UV_INDEX"] = json.dumps(index)
        assert _refresh(env).returncode == 0
    env_dir = _env_dir(tmp_path)
    assert _generations(env_dir) == [f"gen-6.3.1-{AUTOMATION}", f"gen-6.3.2-{AUTOMATION}"]
    assert (env_dir / "current").read_text().strip() == f"gen-6.3.2-{AUTOMATION}"


def test_refresh_is_not_spawned_when_auto_update_is_off_or_request_is_exact(tmp_path: Path) -> None:
    for extra in ({"HWPX_STACK_AUTO_UPDATE": "0"}, {"HWPX_STACK_CHANNEL": "verified"}):
        root = tmp_path / ("off" if "HWPX_STACK_AUTO_UPDATE" in extra else "verified")
        env = _env(root, HWPX_STACK_UPDATE_INTERVAL_HOURS="0", **extra)
        root.mkdir()
        assert _launch(env, "--help").returncode == 0
        assert _launch(env, "--help").returncode == 0
        env_dir = _env_dir(root)
        assert not (env_dir / "refresh.log").exists() and not (env_dir / "refresh.lock").exists()
        assert _refresh(env).returncode == 0
        assert _generations(env_dir) == [f"gen-{CORE}-{AUTOMATION}"]


def test_detached_refresh_never_delays_server_start(tmp_path: Path) -> None:
    env = _env(tmp_path)
    assert _launch(env, "--help").returncode == 0
    env.update({"HWPX_STACK_UPDATE_INTERVAL_HOURS": "0", "FAKE_UV_INDEX": json.dumps(INDEX_V2), "FAKE_UV_SLEEP": "4"})
    started = time.monotonic()
    result = _launch(env, "--transport", "stdio")
    elapsed = time.monotonic() - started
    assert result.returncode == 0 and result.stdout.startswith("FAKE-SERVER")
    assert elapsed < 3.0, f"start blocked on the refresh job: {elapsed:.1f}s"
    env_dir = _env_dir(tmp_path)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and (env_dir / "current").read_text().strip() != f"gen-6.3.1-{AUTOMATION}":
        time.sleep(0.5)
    assert (env_dir / "current").read_text().strip() == f"gen-6.3.1-{AUTOMATION}"
    assert (env_dir / "refresh.log").exists()


def test_refresh_records_the_latest_plugin_bundle_from_identity(tmp_path: Path) -> None:
    identity = tmp_path / "identity.json"
    identity.write_text(json.dumps({"components": {"plugin": {"currentVersion": "9.9.9"}}}))
    env = _env(tmp_path, HWPX_STACK_IDENTITY_URL=identity.as_uri())
    assert _launch(env, "--help").returncode == 0
    assert _refresh(env).returncode == 0
    state = _state(_env_dir(tmp_path))
    assert state["pluginBundle"] == {"installed": IDENTITY["components"]["plugin"]["currentVersion"], "latestKnown": "9.9.9"}


def test_cold_start_replaces_a_generation_whose_console_is_missing(tmp_path: Path) -> None:
    env = _env(tmp_path)
    assert _launch(env, "--help").returncode == 0
    env_dir = _env_dir(tmp_path)
    gen = env_dir / f"gen-{CORE}-{AUTOMATION}"
    (gen / "bin" / "hwpx-automation-mcp").unlink()
    result = _launch(env, "--help")
    assert result.returncode == 0, result.stderr
    assert (gen / "bin" / "hwpx-automation-mcp").exists()
    assert _generations(env_dir) == [f"gen-{CORE}-{AUTOMATION}"]
    assert not list(env_dir.glob("gen-*.broken.*"))
    _no_leftovers(tmp_path)
