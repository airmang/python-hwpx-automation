#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""소유자 원장의 ``toolContract`` 블록을 현재 도구 계약에 맞춘다.

원장 일곱 개가 도구 계약을 "기본 122·고급 130·해시 8c27…"로 적은 채 남아
있었고, 테스트가 그 낡은 값을 글자 그대로 고정했다(2026-11 점검 ARC-13).
값의 출처는 ``hwpx_automation.tool_contract`` 하나다. 계약이 바뀌면:

    python scripts/sync_owner_tool_contract.py           # 원장을 고쳐 쓴다
    python scripts/sync_owner_tool_contract.py --check   # 어긋나면 1로 끝난다

``default``·``advanced``·``skillRequired``·``hash`` 네 값만 바꾼다. 원장의
다른 키와 서식은 건드리지 않는다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hwpx_automation.tool_contract import (  # noqa: E402
    RELEASED_CONTRACT_HASH,
    expected_tool_names,
    skill_required_tool_names,
)

LEDGER_DIR = ROOT / "docs" / "architecture"


def current_tool_contract() -> dict[str, object]:
    """The four values every owner ledger records, read from the contract."""

    return {
        "default": len(expected_tool_names(advanced=False)),
        "advanced": len(expected_tool_names(advanced=True)),
        "skillRequired": len(skill_required_tool_names()),
        "hash": RELEASED_CONTRACT_HASH,
    }


def owner_ledgers() -> list[Path]:
    return sorted(
        path
        for path in LEDGER_DIR.glob("*-owner.json")
        if "toolContract" in json.loads(path.read_text(encoding="utf-8"))
    )


def _synced_text(text: str, values: dict[str, object]) -> str:
    match = re.search(r'"toolContract"\s*:\s*\{[^{}]*\}', text)
    if match is None:
        raise ValueError("ledger has no flat toolContract block")
    block = match.group(0)
    for key, value in values.items():
        literal = json.dumps(value)
        block, count = re.subn(
            rf'("{key}"\s*:\s*)("[^"]*"|-?\d+)', lambda m: m.group(1) + literal, block, count=1
        )
        if count != 1:
            raise ValueError(f"toolContract block has no {key!r}")
    return text[: match.start()] + block + text[match.end() :]


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync owner-ledger toolContract blocks.")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    values = current_tool_contract()
    stale = []
    for path in owner_ledgers():
        text = path.read_text(encoding="utf-8")
        synced = _synced_text(text, values)
        if synced == text:
            continue
        stale.append(path.relative_to(ROOT).as_posix())
        if not args.check:
            path.write_text(synced, encoding="utf-8", newline="\n")
    for name in stale:
        print(("stale: " if args.check else "updated: ") + name)
    if not stale:
        print("owner ledgers match the tool contract")
    return 1 if (args.check and stale) else 0


if __name__ == "__main__":
    raise SystemExit(main())
