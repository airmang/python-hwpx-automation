# SPDX-License-Identifier: Apache-2.0
"""Audit ARC-13: identity documents and owner ledgers state the current contract.

README, the hardening guide and seven owner ledgers carried coordinates from
three different release trains, and tests pinned the stale ledger values as
literals. Every number checked here is read from ``tool_contract`` or
``identity.json``; none is repeated in this file.
"""
from __future__ import annotations

import json
import re
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
STATUS = IDENTITY["releaseState"]["status"]


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
    if STATUS == "released":
        # The promoted README names one train: verified and public at once.
        line = next(line for line in readme.splitlines() if "검증·공개 트레인:" in line)
    else:
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
    label = "공개 릴리스" if STATUS == "released" else "후보"
    assert f"{CANDIDATE['canonicalAutomation']} {label}" in flat


# Reliability audit CS-03: docs/use-cases.md told readers to install a release
# two majors old (inside the range of a published security advisory) while
# README, guarded by a test, named the current one. An exact install pin in a
# public document is a release coordinate like any other, so it is read from
# identity.json too.
_EXACT_PIN = re.compile(
    r"(?<![\w.-])(python-hwpx(?:-automation)?)(?:\[[^\]\n]*\])?==([0-9][0-9A-Za-z.+!-]*)"
)
#: Records of a past release name the versions of their own day.
_PAST_RELEASE_RECORDS = ("docs/releases/", "docs/product-boundary-migration-3.0.0.md")
#: Built or cached copies under plugins-src (not committed; see plugins-src/.gitignore).
_GENERATED = ("plugins-src/plugins/", "plugins-src/dist/", "plugins-src/.cache/")


def _public_documents() -> list[Path]:
    documents = [
        ROOT / "README.md",
        *sorted((ROOT / "docs").glob("*.md")),
        *sorted((ROOT / "plugins-src").rglob("*.md")),
    ]
    kept = []
    for path in documents:
        relative = path.relative_to(ROOT).as_posix()
        if path.name == "CHANGELOG.md" or relative.startswith(_PAST_RELEASE_RECORDS + _GENERATED):
            continue
        if "/examples/out/" in relative:
            continue
        kept.append(path)
    return kept


def _exact_pins(path: Path) -> list[tuple[str, str, str]]:
    """``(where, distribution, version)`` for every ``python-hwpx(-automation)[...]==X.Y.Z``."""

    relative = path.relative_to(ROOT).as_posix()
    return [
        (f"{relative}:{number}", match.group(1), match.group(2))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        for match in _EXACT_PIN.finditer(line)
    ]


def test_public_documents_pin_only_the_public_coordinates() -> None:
    # The same rule as the README host config (test_readme_mcp_config): an
    # installable pin follows what is observed public; promotion advances it.
    public = IDENTITY["releaseState"]["currentPublic"]
    expected = {
        "python-hwpx": public["pythonHwpx"],
        "python-hwpx-automation": public["primaryApplication"],
    }
    pins = [pin for path in _public_documents() for pin in _exact_pins(path)]

    assert any(where.startswith("README.md:") for where, _, _ in pins)  # the pattern still finds pins
    assert any(where.startswith("docs/use-cases.md:") for where, _, _ in pins)
    stale = [
        f"{where}: {distribution}=={version} (public is {expected[distribution]})"
        for where, distribution, version in pins
        if version != expected[distribution]
    ]
    assert not stale, "\n".join(stale)


def test_the_pin_pattern_reads_extras_and_skips_other_distributions() -> None:
    line = (
        'uvx --from "python-hwpx-automation[mcp,oracle]==1.2.3" x; pip install python-hwpx==4.5.6 '
        "my-python-hwpx==9.9.9 python-hwpx-live==8.8.8 python-hwpx>=7.0.0"
    )
    assert [(m.group(1), m.group(2)) for m in _EXACT_PIN.finditer(line)] == [
        ("python-hwpx-automation", "1.2.3"),
        ("python-hwpx", "4.5.6"),
    ]
