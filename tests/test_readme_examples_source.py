# SPDX-License-Identifier: Apache-2.0
"""README Python examples run against this source tree, and none uses a name python-hwpx 7.0 removed.

``test_readme_python_example.py`` runs the README block from wheels it builds, which needs the exact
core checkout and a core whose version meets the floor; until core 7.0.0 is tagged that gate cannot
reach the example. This one runs each block with the source tree (``src`` and the core on the path),
so an example that no longer works fails here. Every block, run or not, is also read with ``ast``:
an attribute that python-hwpx 7.0 removed from the document (``hwpx._removed_names.NAMES["doc"]``,
e.g. ``save_to_path`` -> ``save``) fails the test.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import hwpx
import pytest
from hwpx import HwpxDocument

ROOT = Path(__file__).resolve().parents[1]
PYTHON_FENCE = re.compile(r"^```(?:python|py)(?:[ \t]+[^\n]*)?\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)


def _blocks() -> list[str]:
    return PYTHON_FENCE.findall((ROOT / "README.md").read_text(encoding="utf-8"))


def _removed_document_names() -> set[str]:
    from hwpx._removed_names import NAMES

    return {name for name in NAMES.get("doc", {}) if not hasattr(HwpxDocument, name)}


def test_readme_has_python_examples() -> None:
    assert _blocks()


@pytest.mark.parametrize("index", range(len(_blocks())))
def test_readme_block_uses_no_name_core_7_removed(index: int) -> None:
    removed = _removed_document_names()
    assert "save_to_path" in removed  # the table is the one 7.0 ships
    used = {
        node.attr for node in ast.walk(ast.parse(_blocks()[index])) if isinstance(node, ast.Attribute)
    }
    assert not used & removed, f"README Python block {index} uses names python-hwpx 7.0 removed: {sorted(used & removed)}"


@pytest.mark.parametrize("index", range(len(_blocks())))
def test_readme_block_runs_against_the_source_tree(index: int, tmp_path: Path) -> None:
    core_src = Path(hwpx.__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(core_src)])
    env["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        [sys.executable, "-c", _blocks()[index]],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stderr[-4000:]
    for written in tmp_path.glob("*.hwpx"):
        with HwpxDocument.open(written) as document:
            assert document.sections
