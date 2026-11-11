# SPDX-License-Identifier: Apache-2.0
"""Audit ARC-13: identity documents and owner ledgers state the current contract.

README, the hardening guide and seven owner ledgers carried coordinates from
three different release trains, and tests pinned the stale ledger values as
literals. Every number checked here is read from ``tool_contract`` or
``identity.json``; none is repeated in this file.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from sync_owner_tool_contract import current_tool_contract, owner_ledgers

from hwpx_automation.tool_contract import (
    MIN_AUTOMATION_VERSION,
    MIN_PYTHON_HWPX,
    MIN_SKILL_VERSION,
    RELEASED_CONTRACT_HASH,
    contract_hash,
)

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = json.loads((ROOT / "src" / "hwpx_automation" / "identity.json").read_text(encoding="utf-8"))
CANDIDATE = IDENTITY["releaseState"]["candidate"]


def test_every_owner_ledger_records_the_current_tool_contract() -> None:
    ledgers = owner_ledgers()
    assert len(ledgers) == 7
    expected = current_tool_contract()
    assert expected["hash"] == RELEASED_CONTRACT_HASH
    for path in ledgers:
        recorded = json.loads(path.read_text(encoding="utf-8"))["toolContract"]
        assert {key: recorded[key] for key in expected} == expected, path.name


def test_ledger_sync_script_reports_no_drift() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/sync_owner_tool_contract.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_identity_candidate_carries_the_live_contract_hash() -> None:
    import hwpx_automation.server  # noqa: F401 - binds the registry

    assert CANDIDATE["contractHash"] == RELEASED_CONTRACT_HASH == contract_hash()


def test_readme_candidate_line_matches_identity() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    train = (
        f"`python-hwpx {CANDIDATE['pythonHwpx']} → python-hwpx-automation "
        f"{CANDIDATE['canonicalAutomation']} → hwpx-plugin {CANDIDATE['plugin']}` "
        f"(`{CANDIDATE['contractHash']}`)"
    )
    line = next(line for line in readme.splitlines() if "발행이 승인된" in line and "후보 (" in line)
    assert train in line


def test_hardening_guide_states_the_current_contract() -> None:
    guide = (ROOT / "docs" / "hardening_guide_ko.md").read_text(encoding="utf-8")
    current = guide[guide.index("현재 소스(") : guide.index("는 역사적 계약입니다.")]
    flat = " ".join(current.split())
    contract = current_tool_contract()
    assert f"기본 {contract['default']}개" in flat
    assert f"고급 모드 포함 {contract['advanced']}개" in flat
    assert f"{contract['skillRequired']}개 skill-required" in flat
    assert f"`{contract['hash']}`" in flat
    assert f"core `{MIN_PYTHON_HWPX}`" in flat
    assert f"automation `{MIN_AUTOMATION_VERSION}`" in flat
    assert f"skill `{MIN_SKILL_VERSION}`" in flat
    assert f"{CANDIDATE['canonicalAutomation']} 후보" in flat
