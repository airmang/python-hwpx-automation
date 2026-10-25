# SPDX-License-Identifier: Apache-2.0
"""Automation's side of python-hwpx's known-leak migration contract (#565).

python-hwpx keeps docs/architecture/known-leak-migration.json: four groups of
genre/policy logic still in core, each with the automation owner it moves to.
docs/architecture/core-known-leak-moves.json is this repository's record of the
same groups. These checks keep the two in step and keep the owners and
consumers they name real. Nothing has moved yet.
"""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

import hwpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
MOVES = json.loads((ROOT / "docs" / "architecture" / "core-known-leak-moves.json").read_text(encoding="utf-8"))
DOCUMENT_OPS = json.loads(
    (ROOT / "docs" / "architecture" / "document-operations-owner.json").read_text(encoding="utf-8")
)
GROUP_IDS = [
    "official-reference-policy",
    "document-plan-input",
    "report-heading-guess",
    "evalplan-caption-cleanup",
]


def _core_contract() -> dict | None:
    explicit = os.environ.get("PYTHON_HWPX_REPO")
    repo = Path(explicit).expanduser().resolve() if explicit else Path(hwpx.__file__).resolve().parents[2]
    path = repo / "docs" / "architecture" / "known-leak-migration.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _resolve(dotted: str) -> object:
    parts = dotted.split(" ", 1)[0].split(".")
    for split in range(len(parts), 0, -1):
        try:
            target: object = importlib.import_module(".".join(parts[:split]))
        except ImportError:
            continue
        for name in parts[split:]:
            target = getattr(target, name)
        return target
    raise ImportError(dotted)


def test_groups_owners_and_consumers_are_real() -> None:
    assert [group["id"] for group in MOVES["groups"]] == GROUP_IDS
    for group in MOVES["groups"]:
        _resolve(group["canonicalOwner"])
        for consumer in group["consumers"]:
            _resolve(consumer)
        assert group["coreCallsUntilMoved"] and group["plannedEntryPoint"].strip()


def test_document_ops_ledger_marks_its_core_members_that_will_move() -> None:
    known = DOCUMENT_OPS["coreKnownLeakMembers"]
    assert set(known) <= set(DOCUMENT_OPS["memberOwners"]["core"])
    by_group = {group["id"]: group for group in MOVES["groups"]}
    for member, entry in known.items():
        for group_id, owner in zip(entry["groups"], entry["plannedOwners"]):
            assert by_group[group_id]["canonicalOwner"] == owner, member
            assert member in by_group[group_id]["coreCallsUntilMoved"], member


def test_matches_the_core_contract_when_the_core_checkout_has_it() -> None:
    contract = _core_contract()
    if contract is None:
        pytest.skip("core checkout has no docs/architecture/known-leak-migration.json (python-hwpx #565)")
    core = {group["id"]: group for group in contract["groups"]}
    assert list(core) == GROUP_IDS
    for group in MOVES["groups"]:
        assert core[group["id"]]["canonicalOwner"] == group["canonicalOwner"], group["id"]
    assert contract["compatibility"]["decision"] == "pending-owner"
