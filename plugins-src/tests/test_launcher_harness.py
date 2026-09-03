# tests/test_launcher_harness.py
# SPDX-License-Identifier: Apache-2.0
"""The fake uv used by launcher lifecycle tests behaves like the uv subset the launcher calls."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS_BIN = ROOT / "tests" / "launcher_harness" / "bin"


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {
        "PATH": f"{HARNESS_BIN}:{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "FAKE_UV_INDEX": json.dumps({"python-hwpx": ["6.3.0", "6.3.1"], "python-hwpx-automation": ["7.0.3"]}),
    }
    env.update(extra)
    return env


def _uv(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["uv", *args], env=env, capture_output=True, text=True)


def test_python_find_returns_an_executable(tmp_path: Path) -> None:
    result = _uv(["python", "find"], _env(tmp_path))
    assert result.returncode == 0
    assert os.access(result.stdout.strip(), os.X_OK)


def test_venv_and_install_produce_importable_stubs(tmp_path: Path) -> None:
    env = _env(tmp_path)
    venv = tmp_path / "venv"
    assert _uv(["venv", "--quiet", "--relocatable", str(venv)], env).returncode == 0
    result = _uv(
        ["pip", "install", "--quiet", "--python", str(venv / "bin" / "python"),
         "python-hwpx-automation[mcp,oracle]>=7.0.3,<8", "python-hwpx[preview]>=6.3.0,<7"],
        env,
    )
    assert result.returncode == 0, result.stderr
    probe = subprocess.run(
        [str(venv / "bin" / "python"), "-c",
         "from importlib.metadata import version; import hwpx, hwpx_automation; "
         "from hwpx_automation.quality import capability_state; "
         "print(version('python-hwpx'), version('python-hwpx-automation'), capability_state()['ok'])"],
        capture_output=True, text=True, check=True,
    )
    assert probe.stdout.split() == ["6.3.1", "7.0.3", "True"]
    console = subprocess.run([str(venv / "bin" / "hwpx-automation-mcp"), "--help"], capture_output=True, text=True)
    assert console.returncode == 0 and console.stdout.startswith("usage: hwpx-automation-mcp")


def test_exact_pin_wins_over_newest(tmp_path: Path) -> None:
    env = _env(tmp_path)
    venv = tmp_path / "venv"
    _uv(["venv", str(venv)], env)
    _uv(["pip", "install", "--python", str(venv / "bin" / "python"), "python-hwpx[preview]==6.3.0"], env)
    probe = subprocess.run([str(venv / "bin" / "python"), "-c", "from importlib.metadata import version; print(version('python-hwpx'))"], capture_output=True, text=True, check=True)
    assert probe.stdout.strip() == "6.3.0"


def test_dry_run_reports_uv_shaped_lines(tmp_path: Path) -> None:
    env = _env(tmp_path)
    venv = tmp_path / "venv"
    _uv(["venv", str(venv)], env)
    _uv(["pip", "install", "--python", str(venv / "bin" / "python"), "python-hwpx==6.3.0", "python-hwpx-automation==7.0.3"], env)
    same = _uv(["pip", "install", "--dry-run", "--upgrade", "--python", str(venv / "bin" / "python"), "python-hwpx>=6.3.0,<7", "python-hwpx-automation>=7.0.3,<8"], env)
    assert same.returncode == 0
    assert " + python-hwpx==6.3.1" in same.stdout and "python-hwpx-automation" not in [l.split("==")[0].strip(" +-") for l in same.stdout.splitlines() if l.startswith(" +")]
    env["FAKE_UV_INDEX"] = json.dumps({"python-hwpx": ["6.3.0"], "python-hwpx-automation": ["7.0.3"]})
    none = _uv(["pip", "install", "--dry-run", "--upgrade", "--python", str(venv / "bin" / "python"), "python-hwpx>=6.3.0,<7", "python-hwpx-automation>=7.0.3,<8"], env)
    assert none.stdout.strip().endswith("Would make no changes")


def test_offline_fails_like_uv(tmp_path: Path) -> None:
    env = _env(tmp_path, FAKE_UV_OFFLINE="1")
    venv = tmp_path / "venv"
    _uv(["venv", str(venv)], env)
    result = _uv(["pip", "install", "--dry-run", "--upgrade", "--python", str(venv / "bin" / "python"), "python-hwpx>=6.3.0,<7"], env)
    assert result.returncode == 2 and "Network is unreachable" in result.stderr


def test_broken_version_is_not_importable(tmp_path: Path) -> None:
    env = _env(tmp_path, FAKE_UV_BROKEN_VERSION="6.3.1")
    venv = tmp_path / "venv"
    _uv(["venv", str(venv)], env)
    _uv(["pip", "install", "--python", str(venv / "bin" / "python"), "python-hwpx>=6.3.0,<7", "python-hwpx-automation>=7.0.3,<8"], env)
    probe = subprocess.run([str(venv / "bin" / "python"), "-c", "import hwpx"], capture_output=True, text=True)
    assert probe.returncode != 0 and "ImportError" in probe.stderr


def test_calls_are_recorded(tmp_path: Path) -> None:
    calls = tmp_path / "calls.jsonl"
    env = _env(tmp_path, FAKE_UV_CALLS=str(calls))
    _uv(["python", "find"], env)
    assert json.loads(calls.read_text().splitlines()[0]) == ["python", "find"]


def test_install_refuses_interpreters_the_fake_did_not_create(tmp_path: Path) -> None:
    # The fake must never write stubs anywhere but a venv it created itself:
    # neither a path that is not a venv, nor a real venv such as the developer
    # venv that may be running pytest. Never point this test at sys.executable.
    env = _env(tmp_path)
    synthetic = tmp_path / "not-a-venv" / "bin" / "python"
    result = _uv(["pip", "install", "--python", str(synthetic), "python-hwpx==6.3.0"], env)
    assert result.returncode == 64 and "did not create" in result.stderr
    foreign = tmp_path / "foreign-venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(foreign)], check=True)
    result = _uv(["pip", "install", "--python", str(foreign / "bin" / "python"), "python-hwpx==6.3.0"], env)
    assert result.returncode == 64 and "did not create" in result.stderr
    assert not list((foreign / "lib").rglob("hwpx"))
