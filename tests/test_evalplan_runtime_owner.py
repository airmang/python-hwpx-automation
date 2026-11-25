# SPDX-License-Identifier: Apache-2.0
"""Canonical evalplan inventory and production-routing gates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from hwpx_automation.office import evalplan as canonical
from hwpx_automation.office.evalplan import runtime

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_ROOT = ROOT / "src" / "hwpx_automation" / "office" / "evalplan"
OWNER = json.loads(
    (
        ROOT / "docs" / "architecture" / "evalplan-runtime-owner.json"
    ).read_text(encoding="utf-8")
)


def _manifest() -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    for path in sorted(CANONICAL_ROOT.rglob("*.py")):
        data = path.read_bytes()
        rows.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "loc": len(data.splitlines()),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return rows


def test_canonical_evalplan_inventory_is_complete() -> None:
    rows = _manifest()
    payload = json.dumps(
        rows,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    expected = OWNER["canonical"]

    assert len(rows) == expected["pythonFiles"] == 2
    assert sum(int(row["loc"]) for row in rows) == expected["loc"] == 3301
    # 원장과 테스트에 같은 해시를 둔 이중 잠금이다. 원장만 고쳐서 통과시키는
    # 일을 막는다. 5.0 트레인에서 패키지가 hwpx_automation으로 바뀌며 파일
    # 내용이 달라져 함께 갱신했다. 이후 fill_evalplan이 산출 바이트로
    # 영수증을 재산출하도록 고치며 LOC 2798→2833·해시를 함께 갱신했다 —
    # 구조 단계 결과를 최종 판정으로 재사용해 ok=true·채움 26건을 보고하고
    # 파일을 쓰지 않던 결함의 수리다. 정기시험이 있는 과목의 반영비율 표(#202)와
    # clean 단계의 AI 활용 상자 자리표시(#205)를 고치며 LOC 2833→3301·해시를 갱신했다.
    assert expected["manifestSha256"] == (
        "8ebb9d0c829e2a2e6943c1518df59380d3eacdf70f5c6170eaf47ee730e67724"
    )
    assert hashlib.sha256(payload).hexdigest() == expected["manifestSha256"]
    assert canonical.__all__ == runtime.__all__


def test_public_evalplan_bindings_use_the_automation_owner() -> None:
    for name in canonical.__all__:
        binding = getattr(canonical, name)
        assert binding.__module__ == (
            "hwpx_automation.office.evalplan.runtime"
        ), (name, binding)
