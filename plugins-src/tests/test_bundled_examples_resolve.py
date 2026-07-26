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

ROOT = Path(__file__).resolve().parents[1]

#: 이 스택이 소유하는 배포. 이 밖의 서드파티 import는 설치 여부가 환경 문제다.
#: 이 스택이 소유하는 배포. 옛 root ``hwpx_mcp_server``도 넣는다 — 호환 셸이
#: 살려두는 이름이라 번들이 실수로 쓸 수 있고, 그러면 잡아야 한다.
#: (일괄 재명명이 이 튜플을 ("hwpx", "hwpx_automation", "hwpx_automation")로
#: 만들어 옛 root가 검사에서 빠져 있었다.)
STACK_ROOTS = ("hwpx", "hwpx_automation", "hwpx_mcp_server")


def _stack_imports() -> list[tuple[Path, int, str, str, bool]]:
    """(파일, 줄, 모듈, 이름, 직접호출) — 배송 자산의 스택 import 전부."""
    found: list[tuple[Path, int, str, str, bool]] = []
    broken_syntax: list[str] = []
    for directory in ("examples", "scripts"):
        for path in sorted((ROOT / directory).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError as exc:
                # 조용히 넘기면 안 된다. 번들 자산의 문법이 깨졌다는 건 그
                # 자산이 아예 실행 불가라는 뜻이고, 실제로 이 게이트를 쓰던
                # 재배선 작업이 다섯 파일의 들여쓰기를 부순 적이 있다.
                broken_syntax.append(f"{path.relative_to(ROOT)}:{exc.lineno}: {exc.msg}")
                continue
            called_names = {
                node.func.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module and node.module.split(".")[0] in STACK_ROOTS:
                        for alias in node.names:
                            local_name = alias.asname or alias.name
                            found.append(
                                (
                                    path,
                                    node.lineno,
                                    node.module,
                                    alias.name,
                                    local_name in called_names,
                                )
                            )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".")[0] in STACK_ROOTS:
                            found.append((path, node.lineno, alias.name, "", False))
    assert not broken_syntax, (
        "번들 자산의 문법이 깨졌다 — 해석 이전의 문제다:\n  "
        + "\n  ".join(broken_syntax)
    )
    return found


def test_every_bundled_import_resolves_against_the_installed_stack() -> None:
    """번들 자산이 부르는 모든 스택 이름이 설치본에 실제로 있어야 한다.

    이름 하나하나를 확인한다. 모듈이 import 되는 것과 그 모듈이 예제가 쓰는
    이름을 가진 것은 다른 문제이고, 5.0에서 깨진 것은 후자다.
    """

    broken: list[str] = []
    for path, line, module, name, used_as_call in _stack_imports():
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
        elif used_as_call and not callable(getattr(imported, name)):
            broken.append(
                f"{path.relative_to(ROOT)}:{line}: {module}.{name}은 호출 불가"
            )

    assert not broken, (
        f"번들 자산의 import {len(broken)}건이 설치본에서 해석되지 않는다:\n  "
        + "\n  ".join(broken)
    )
