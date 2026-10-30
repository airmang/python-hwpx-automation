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

    assert len(rows) == expected["pythonFiles"] == 3
    assert sum(int(row["loc"]) for row in rows) == expected["loc"]
    # Caption policy now has its own module over the neutral core seam.
    # Historical source/canonical anchors remain in the owner ledger.
    assert expected["manifestSha256"] == (
        "a1ea04c066d2a692af2a4533f1e1d3fd787c0f5c8605973c26c90d25bac654b9"
    )
    assert hashlib.sha256(payload).hexdigest() == expected["manifestSha256"]
    assert canonical.__all__ == [*runtime.__all__, "strip_evalplan_table_captions"]


def test_public_evalplan_bindings_use_the_automation_owner() -> None:
    for name in canonical.__all__:
        binding = getattr(canonical, name)
        assert binding.__module__ == (
            "hwpx_automation.office.evalplan.captions"
            if name == "strip_evalplan_table_captions"
            else "hwpx_automation.office.evalplan.runtime"
        ), (name, binding)
