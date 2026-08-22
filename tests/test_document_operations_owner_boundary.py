# SPDX-License-Identifier: Apache-2.0
"""Canonical compare, bulk-merge, and redline application ownership."""

from __future__ import annotations

import hashlib
import importlib
import json
import runpy
from pathlib import Path

import hwpx
from hwpx_automation.handlers import authoring, specialized, tracked_changes
from hwpx_automation.office.authoring import style_profile
from hwpx_automation.tool_contract import (
    contract_hash,
    expected_tool_names,
    skill_required_tool_names,
)

ROOT = Path(__file__).resolve().parents[1]
BOUNDARY = runpy.run_path(str(ROOT / "scripts" / "check_product_boundary.py"))
OWNER = json.loads(
    (
        ROOT
        / "docs"
        / "architecture"
        / "document-operations-owner.json"
    ).read_text(encoding="utf-8")
)
RETAINED_CORE_SYMBOLS = {
    "hwpx.tools.doc_diff": (
        "diff_paragraphs",
        "doc_diff",
        "inspect_reference_consistency",
    ),
    "hwpx.tools.mail_merge": (
        "inspect_mail_merge_placeholders",
        "load_mail_merge_rows",
        "merge_template_rows",
    ),
    "hwpx.tools.redline": (
        "author_demo_redline",
        "inspect_redline_structure",
        "verify_redline",
    ),
}


def _manifest() -> list[dict[str, str | int]]:
    base = ROOT / BOUNDARY["CANONICAL_DOCUMENT_OPS_ROOT"]
    rows: list[dict[str, str | int]] = []
    for path in sorted(base.rglob("*.py")):
        data = path.read_bytes()
        rows.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "loc": len(data.splitlines()),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return rows


def test_owner_ledger_matches_source_inventory_and_contract() -> None:
    assert OWNER["source"] == {
        "head": "86e26314540a82c5a772a05012be5fb2f14f9ed4",
        "pythonFiles": 3,
        "loc": 1020,
        "manifestSha256": (
            "630469fdb286eb383262afae1a6e8e28f76d1774b86712b097b62bfd79370649"
        ),
        "qualifiedExportCount": 13,
        "qualifiedSnapshotSha256": (
            "a1b77d246543217e33df910b6ef2c021f93120c8b75975cde279f5fb695f9a0e"
        ),
    }
    assert tuple(OWNER["approvedCoreImports"]) == BOUNDARY[
        "ALLOWED_DOCUMENT_OPS_CORE_IMPORTS"
    ]
    assert {
        module: frozenset(names)
        for module, names in OWNER["forbiddenCoreCompatibilityCallables"].items()
    } == BOUNDARY["FROZEN_CORE_DOCUMENT_OPS_CALLABLES"]
    assert OWNER["memberOwners"]["core"] == sorted(
        f"{module}.{name}"
        for module, names in RETAINED_CORE_SYMBOLS.items()
        for name in names
    )
    assert set(OWNER["memberOwners"]) == {
        "automationCanonical",
        "core",
        "coreCompatibility",
    }
    assert OWNER["toolContract"] == {
        "default": 122,
        "advanced": 130,
        "skillRequired": 29,
        "hash": "8c278ebd5becba08",
    }


def test_canonical_inventory_is_exact() -> None:
    rows = _manifest()
    payload = json.dumps(
        rows,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    assert len(rows) == OWNER["canonical"]["pythonFiles"] == 4
    assert sum(int(row["loc"]) for row in rows) == OWNER["canonical"]["loc"]
    assert hashlib.sha256(payload).hexdigest() == OWNER["canonical"][
        "manifestSha256"
    ]


def test_production_bindings_use_only_the_canonical_owner() -> None:
    bindings = (
        authoring.build_hwpx_comparison_table_plan,
        specialized.build_hwpx_mail_merge,
        specialized.inspect_hwpx_mail_merge_placeholders,
        tracked_changes.verify_hwpx_redline,
        style_profile.inspect_mail_merge_placeholders,
    )
    assert all(
        binding.__module__.startswith(
            "hwpx_automation.office.document_ops"
        )
        for binding in bindings
    )


def test_retained_document_operation_symbols_have_exact_core_origins() -> None:
    core_root = Path(hwpx.__file__).resolve().parent
    for module_name, names in RETAINED_CORE_SYMBOLS.items():
        module = importlib.import_module(module_name)
        module_path = Path(module.__file__).resolve()
        assert module_path.is_relative_to(core_root)
        assert not module_path.is_relative_to(ROOT / "src" / "hwpx_automation")
        for name in names:
            value = getattr(module, name)
            assert value.__module__ == module_name


def test_boundary_rejects_frozen_callable_and_unapproved_seams() -> None:
    check = BOUNDARY["_document_ops_owner_import_violation"]
    canonical = (
        "src/hwpx_automation/office/document_ops/comparison.py"
    )

    assert check(canonical, "hwpx.tools.doc_diff") is None
    assert check(canonical, "hwpx.tools.mail_merge") is None
    assert check(canonical, "hwpx.visual.oracle") is not None
    assert check(canonical, "hwpx.authoring") is not None


def test_real_product_tree_and_tool_surface_are_exact() -> None:
    report = BOUNDARY["evaluate"](ROOT)

    assert report["ok"], report["violations"]
    assert report["canonicalDocumentOpsPythonFiles"] == 4
    assert len(expected_tool_names(advanced=False)) == 128
    assert len(expected_tool_names(advanced=True)) == 136
    assert len(skill_required_tool_names()) == 29
    assert contract_hash() == "8c278ebd5becba08"
