# SPDX-License-Identifier: Apache-2.0
"""Canonical exam owner, production routing, and contract receipts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from hwpx_automation.handlers import specialized
from hwpx_automation.office import exam
from hwpx_automation.tool_bindings import TOOL_BINDINGS
from hwpx_automation.tool_contract import (
    contract_hash,
    expected_tool_names,
    skill_required_tool_names,
)

ROOT = Path(__file__).resolve().parents[1]
OWNER_ROOT = ROOT / "src" / "hwpx_automation" / "office" / "exam"
OWNER = json.loads(
    (ROOT / "docs" / "architecture" / "exam-runtime-owner.json").read_text(
        encoding="utf-8"
    )
)


def _manifest() -> tuple[list[dict[str, object]], str]:
    entries: list[dict[str, object]] = []
    for path in sorted(OWNER_ROOT.glob("*.py")):
        payload = path.read_bytes()
        entries.append(
            {
                "path": path.name,
                "loc": len(payload.decode("utf-8").splitlines()),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    canonical = json.dumps(
        entries,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return entries, hashlib.sha256(canonical).hexdigest()


def test_canonical_inventory_and_provenance_are_exact() -> None:
    entries, manifest_sha256 = _manifest()
    assert [entry["path"] for entry in entries] == OWNER["packageFiles"]
    assert len(entries) == OWNER["canonical"]["pythonFiles"] == 6
    assert sum(int(entry["loc"]) for entry in entries) == OWNER["canonical"]["loc"]
    assert manifest_sha256 == OWNER["canonical"]["manifestSha256"]
    assert OWNER["canonical"]["status"] == "canonical"


def test_production_handler_is_bound_to_automation_owner() -> None:
    assert specialized.compose_exam_into_form is exam.compose_exam_into_form
    assert specialized.measure_question_splits is exam.measure_question_splits
    assert specialized.ExamParseError is exam.ExamParseError
    assert specialized.FormProfileError is exam.FormProfileError
    assert TOOL_BINDINGS["compose_exam"] is specialized.compose_exam
    assert exam.compose_exam_into_form.__module__ == (
        "hwpx_automation.office.exam.compose"
    )


def test_tool_contract_is_exactly_unchanged() -> None:
    assert len(expected_tool_names(advanced=False)) == 128
    assert len(expected_tool_names(advanced=True)) == 136
    assert len(skill_required_tool_names()) == 29
    assert contract_hash() == "8c278ebd5becba08"
