# SPDX-License-Identifier: Apache-2.0
"""번들에 실리는 파이썬 자산이 실제 설치본에서 해석되는지 검사한다.

스킬 스위트는 81개가 통과하는데 그중 예제를 **실행하거나 import 해보는 것이
하나도 없었다.** 그래서 core 5.0에서 사라진 이름을 import하는 예제 6개가
1.0 후보 번들에 그대로 실렸다. 구조 검사는 전부 통과했다 — 파일이 있는지,
해시가 맞는지, 매니페스트가 정합한지만 봤기 때문이다.

자기 예제가 돌지 않는 스킬은 예제가 없는 것만 못하다.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: 이 스택이 소유하는 배포. 이 밖의 서드파티 import는 설치 여부가 환경 문제다.
STACK_ROOTS = ("hwpx", "hwpx_automation", "hwpx_automation")


def _stack_imports() -> list[tuple[Path, int, str, str]]:
    """(파일, 줄, 모듈, 이름) — 번들에 실리는 자산의 스택 import 전부."""
    found: list[tuple[Path, int, str, str]] = []
    for directory in ("examples", "scripts"):
        for path in sorted((ROOT / directory).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module and node.module.split(".")[0] in STACK_ROOTS:
                        for alias in node.names:
                            found.append((path, node.lineno, node.module, alias.name))
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".")[0] in STACK_ROOTS:
                            found.append((path, node.lineno, alias.name, ""))
    return found


def test_every_bundled_import_resolves_against_the_installed_stack() -> None:
    """번들 자산이 부르는 모든 스택 이름이 설치본에 실제로 있어야 한다.

    이름 하나하나를 확인한다. 모듈이 import 되는 것과 그 모듈이 예제가 쓰는
    이름을 가진 것은 다른 문제이고, 5.0에서 깨진 것은 후자다.
    """

    broken: list[str] = []
    for path, line, module, name in _stack_imports():
        try:
            spec = importlib.util.find_spec(module)
        except (ImportError, ValueError):
            spec = None
        if spec is None:
            broken.append(f"{path.relative_to(ROOT)}:{line}: 모듈 없음 — {module}")
            continue
        if not name:
            continue
        imported = importlib.import_module(module)
        if not hasattr(imported, name):
            broken.append(f"{path.relative_to(ROOT)}:{line}: {module}에 {name} 없음")

    assert not broken, (
        f"번들 자산의 import {len(broken)}건이 설치본에서 해석되지 않는다:\n  "
        + "\n  ".join(broken)
    )
