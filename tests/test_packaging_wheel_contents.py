# SPDX-License-Identifier: Apache-2.0
"""빌드된 wheel이 선언한 것만 담는지 검사한다.

setuptools는 ``build/lib``를 재사용한다. 그 트리에는 이전 빌드의 결과가 남아
있어서, 패키지를 지우거나 이름을 바꿔도 옛 것이 새 wheel에 그대로 실린다.
같은 방식으로 세 번 당했다.

1. python-hwpx 5.0 첫 wheel이 제거한 모듈 50개를 전부 싣고 나왔다.
2. 그걸 고친 wheel은 필요한 패키지가 빠져 import조차 안 됐다 — 감사가 "없어야
   할 것"만 보고 "있어야 할 것"은 안 봤기 때문이다.
3. 패키지를 ``hwpx_automation``으로 바꾼 뒤에도 옛 ``hwpx_mcp_server`` 197개
   항목이 같이 실렸다.

세 번 다 "지웠으니 없겠지"라고 믿어서 생겼다. 이 검사는 믿지 않고 연다.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from repo_build_lock import repo_build_lock

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]


def test_the_build_tree_is_clean_before_anything_else() -> None:
    """더러운 ``build/``를 발견하면 여기서 멈춘다.

    아래 두 검사는 각각 build/를 지우거나 일부러 더럽힌다. 그래서 **이미**
    오염된 트리에서 돌려도 둘 다 통과한다 — 실제 사고 상태가 감지되지 않는
    것이다. 세 번 당한 그 상태를 잡는 건 이 검사다.

    빌드 산출물은 재생성 가능하므로 지우라고 말하는 것으로 충분하다.
    """
    stale = ROOT / "build" / "lib"
    if not stale.is_dir():
        return
    declared_prefix = "hwpx_automation"
    ghosts = sorted(
        child.name
        for child in stale.iterdir()
        if child.is_dir() and not child.name.startswith(declared_prefix)
    )
    assert not ghosts, (
        "build/lib에 선언되지 않은 패키지가 남아 있다 — 이 상태로 빌드하면 "
        f"wheel에 실린다:\n  {', '.join(ghosts)}\n"
        "  rm -rf build 후 다시 빌드할 것."
    )


@pytest.mark.parametrize("distribution", ["wheel"])
def test_wheel_top_level_matches_the_declaration(tmp_path: Path, distribution: str) -> None:
    """wheel의 최상위 이름이 pyproject가 선언한 것과 **정확히** 같아야 한다.

    양방향으로 본다. 빠진 것은 import 불가를, 남는 것은 유령 패키지를 뜻하고,
    둘 중 하나만 보는 감사는 지난 세 번 모두 통과했다.
    """
    pytest.importorskip("build")

    # 빌드 캐시를 쓰지 않는다. 재사용하는 그 트리가 문제의 원인이다.
    with repo_build_lock():  # one build of the repository root at a time (xdist workers)
        stale = ROOT / "build"
        if stale.exists():
            shutil.rmtree(stale)

        completed = subprocess.run(
            [sys.executable, "-m", "build", f"--{distribution}", "--outdir", str(tmp_path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
    assert completed.returncode == 0, (
        f"python -m build --{distribution} 실패({completed.returncode}):\n"
        f"{completed.stdout[-2000:]}\n{completed.stderr[-4000:]}"
    )

    built = sorted(tmp_path.glob("*.whl"))
    assert built, "wheel이 만들어지지 않았다"
    top_level = {
        name.split("/")[0]
        for name in zipfile.ZipFile(built[-1]).namelist()
        if "/" in name
    }
    top_level -= {n for n in top_level if n.endswith(".dist-info")}

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    include = project["tool"]["setuptools"]["packages"]["find"].get("include")
    if include:
        declared = {name.split(".")[0].rstrip("*") for name in include}
    else:
        # include를 안 적으면 선언은 "src 안의 전부"다. 그때는 소스 트리가 곧
        # 선언이므로 거기서 읽는다 — 그리고 그 형태가 stale 트리에 취약하다.
        declared = {
            child.name
            for child in (ROOT / "src").iterdir()
            if child.is_dir() and not child.name.endswith(".egg-info")
        }

    assert top_level == declared, (
        f"wheel 최상위 {sorted(top_level)} != 선언 {sorted(declared)}\n"
        f"남는 것: {sorted(top_level - declared)}\n"
        f"빠진 것: {sorted(declared - top_level)}"
    )


def test_a_stale_build_tree_leaks_which_is_why_builds_must_be_clean(tmp_path: Path) -> None:
    """더러운 ``build/``가 wheel을 오염시킨다는 사실 자체를 고정한다.

    위 검사는 ``build/``를 지우고 빌드하므로 세 번 당한 그 상황을 재현하지
    못한다 — 깨끗한 빌드가 깨끗하다는 것만 보여준다. 사고는 늘 더러운 트리에서
    났고, 명시적 ``include``를 적어도 막히지 않는다(실측).

    그래서 이 검사는 방어가 아니라 **특성 고정**이다. 유령을 심고 빌드해서
    실제로 새는지 확인한다. CI는 새 체크아웃에서 빌드하므로 발행물은 안전하고,
    위험은 로컬 빌드에만 있다 — 릴리스 절차가 ``build/``를 지워야 하는 이유가
    이것이다.

    setuptools가 언젠데 이 동작을 고치면 이 검사가 실패한다. 그건 좋은 소식이고
    그때 절차에서 청소 단계를 뺄 수 있다.
    """
    pytest.importorskip("build")

    planted = ROOT / "build" / "lib" / "hwpx_stale_ghost"
    planted.mkdir(parents=True, exist_ok=True)
    (planted / "__init__.py").write_text("GHOST = True\n", encoding="utf-8")
    try:
        subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path)],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
        names = zipfile.ZipFile(sorted(tmp_path.glob("*.whl"))[-1]).namelist()
        leaked = [name for name in names if name.startswith("hwpx_stale_ghost")]
        assert leaked, (
            "stale build/lib가 더 이상 새지 않는다 — setuptools가 고쳤을 수 있다. "
            "릴리스 절차의 build/ 청소 단계를 재검토할 것."
        )
    finally:
        shutil.rmtree(ROOT / "build", ignore_errors=True)
