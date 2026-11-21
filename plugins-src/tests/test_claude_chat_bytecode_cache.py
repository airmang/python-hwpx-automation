# SPDX-License-Identifier: Apache-2.0
"""The no-MCP start block caches bytecode outside the skill folder (audit EFF-12).

It used to set ``sys.dont_write_bytecode``, so every process recompiled the
432-file engine. It now points ``sys.pycache_prefix`` at a per-user temp folder
and never writes into the (possibly read-only) skill folder.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "plugins" / "claude" / "hwpx-plugin"
GUIDE = BUNDLE / "skills" / "hwpx" / "chat-engine.md"


def _start_block() -> str:
    guide = GUIDE.read_text(encoding="utf-8")
    start = guide.index("```python\nimport glob, importlib.util, json, os, sys")
    return guide[start + len("```python\n"):guide.index("\n```", start)]


def test_start_block_prefers_a_private_cache_and_falls_back_to_no_bytecode() -> None:
    block = _start_block()
    assert "sys.pycache_prefix = PYCACHE" in block
    assert "tempfile.gettempdir()" in block
    assert "mode=0o700" in block and "st_uid != UID" in block  # shared /tmp must not feed us bytecode
    assert block.index("sys.pycache_prefix = PYCACHE") < block.index("sys.path.insert(0, ENGINE)")
    # Only as the fallback when no private cache folder can be made.
    fallback = block[block.index("except OSError:"):]
    assert fallback.split("\n")[1].strip() == "sys.dont_write_bytecode = True"
    assert block.count("sys.dont_write_bytecode = True") == 1


@pytest.mark.skipif(importlib.util.find_spec("lxml") is None, reason="the vendored engine needs lxml")
def test_start_block_writes_bytecode_to_the_temp_cache_not_the_skill_folder(tmp_path: Path, request) -> None:
    # The cache mirrors the full source path under the prefix. Copying the bundle
    # below pytest's tmp_path would push that past Windows' 260-character limit
    # (where the write is skipped silently), so read the built bundle in place
    # and, on Windows, keep the temp folder short.
    skill = BUNDLE / "skills" / "hwpx"
    assert not [path for path in skill.rglob("__pycache__")]
    if os.name == "nt":
        try:
            temp = Path(tempfile.mkdtemp(prefix="hp", dir=tmp_path.anchor))
        except OSError:
            pytest.skip("cannot create a short temp folder at the drive root")
        request.addfinalizer(lambda: shutil.rmtree(temp, ignore_errors=True))
    else:
        temp = tmp_path / "temp"
        temp.mkdir()
    script = tmp_path / "start.py"
    block = _start_block().replace("SKILL_DIR = None\n", f"SKILL_DIR = {str(skill)!r}\n", 1)
    script.write_text(block + "\nprint('PYCACHE_PREFIX', sys.pycache_prefix)\n", encoding="utf-8")
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONPYCACHEPREFIX", "PYTHONDONTWRITEBYTECODE"}
    }
    env.update({"TMPDIR": str(temp), "TEMP": str(temp), "TMP": str(temp), "PYTHONUTF8": "1"})

    for _ in range(2):  # the second run reads the cache the first one wrote
        result = subprocess.run(
            [sys.executable, str(script)],
            env=env,
            cwd=tmp_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    prefix_line = next(line for line in result.stdout.splitlines() if line.startswith("PYCACHE_PREFIX "))
    prefix = Path(prefix_line.split(" ", 1)[1])
    assert prefix.parent.resolve() == temp.resolve()
    assert prefix.name.startswith("hwpx-pyc-")
    cached = list(prefix.rglob("*.pyc"))
    engine_cached = [path for path in cached if {"engine", "hwpx"} <= set(path.parts)]
    assert len(engine_cached) > 20, [path.name for path in cached[:5]]
    assert not [path for path in skill.rglob("*") if path.name == "__pycache__" or path.suffix == ".pyc"]
