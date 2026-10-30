# SPDX-License-Identifier: Apache-2.0
"""Canonical policy-owner inventory and production-routing gates."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from hwpx_automation import form_fill
from hwpx_automation.handlers import (
    content_edit,
    quality_render,
    read_export,
    specialized,
)
from hwpx_automation.office import authoring, compliance, quality, utilities

ROOT = Path(__file__).resolve().parents[1]
OFFICE = ROOT / "src" / "hwpx_automation" / "office"


def _manifest() -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    for name in ("compliance", "quality", "utilities"):
        for path in sorted((OFFICE / name).rglob("*.py")):
            data = path.read_bytes()
            rows.append(
                {
                    "path": path.relative_to(ROOT).as_posix(),
                    "loc": len(data.splitlines()),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
    return rows


def test_canonical_policy_owner_inventory_is_complete() -> None:
    rows = _manifest()
    canonical = json.loads(
        (
            ROOT
            / "docs"
            / "architecture"
            / "compliance-quality-utilities-owner.json"
        ).read_text(encoding="utf-8")
    )["canonical"]
    payload = json.dumps(
        rows,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    assert len(rows) == canonical["pythonFiles"] == 8
    # Reference policy joins compliance; page metrics remain delegated to core.
    assert sum(int(row["loc"]) for row in rows) == canonical["loc"]
    assert hashlib.sha256(payload).hexdigest() == canonical[
        "manifestSha256"
    ]
    assert len(compliance.__all__) == 16
    assert len(quality.__all__) == 3
    assert len(utilities.__all__) == 2


def test_all_policy_production_bindings_use_the_automation_owner() -> None:
    bindings = (
        quality_render.inspect_hwpx_official_document_style,
        specialized.DEFAULT_POLICY.__class__,
        specialized.detect_pii,
        specialized.mask_value,
        read_export.mask_pii,
        form_fill.mask_pii,
        content_edit.build_hwpx_table_compute,
    )
    expected_prefixes = (
        "hwpx_automation.office.compliance",
        "hwpx_automation.office.compliance",
        "hwpx_automation.office.compliance",
        "hwpx_automation.office.compliance",
        "hwpx_automation.office.compliance",
        "hwpx_automation.office.compliance",
        "hwpx_automation.office.utilities",
    )
    for binding, expected in zip(bindings, expected_prefixes):
        assert binding.__module__.startswith(expected), binding

    source = Path(authoring.__file__).read_text(encoding="utf-8")
    assert "from ..compliance import" in source
    assert "hwpx.tools.official_lint" not in source
