# SPDX-License-Identifier: Apache-2.0
"""Exact parity between the automation owner and frozen core 4.x policy copies.

``hwpx.tools.page_guard`` is not being removed (module-ownership ledger:
"page-guard CLI retained") — it stays imported live and compared directly.
Since #177 the automation module re-exports it, so the comparison below also
checks that the two paths hand out the same objects.

``hwpx.tools.official_lint``, ``hwpx.tools.pii``, and ``hwpx.tools.table_compute``
*are* all gone as of python-hwpx 5.0. Structural claims (exports, signatures,
the two report-version constants) compare the live automation modules'
``tests.parity_fingerprint.fingerprint()`` against
``tests/parity_fingerprints/policy.json``. Behavioural claims (the lint/PII
calls, the table computation, and the two public error shapes) compare
against ``tests/parity_fingerprints/policy.golden.json`` — both captured from
a scratch git worktree at the commit before removal (see
``scripts/freeze_parity_fingerprints.py --historical``) rather than a live
import.

Every assertion the pre-freeze version of this file made is still made here;
none needed dropping.
"""
from __future__ import annotations

import dataclasses
import importlib
import inspect
import json
from pathlib import Path
from typing import Any, Callable

from hwpx.document import HwpxDocument

from parity_fingerprint import fingerprint

core_page_guard = importlib.import_module("hwpx.tools.page_guard")
official_lint = importlib.import_module(
    "hwpx_automation.office.compliance.official_lint"
)
pii = importlib.import_module("hwpx_automation.office.compliance.pii")
page_guard = importlib.import_module(
    "hwpx_automation.office.quality.page_guard"
)
table_compute = importlib.import_module(
    "hwpx_automation.office.utilities.table_compute"
)

_FIXTURES = Path(__file__).parent / "parity_fingerprints"
FROZEN = json.loads((_FIXTURES / "policy.json").read_text(encoding="utf-8"))["modules"]
GOLDEN = json.loads((_FIXTURES / "policy.golden.json").read_text(encoding="utf-8"))["calls"]

FROZEN_MODULES = (
    ("hwpx.tools.official_lint", official_lint),
    ("hwpx.tools.pii", pii),
    ("hwpx.tools.table_compute", table_compute),
)


def _signature(value: Any) -> str | None:
    if not callable(value):
        return None
    try:
        return str(inspect.signature(value))
    except (TypeError, ValueError):
        return "<uninspectable>"


def _error(call: Callable[[], Any]) -> tuple[str, str]:
    try:
        call()
    except Exception as exc:  # noqa: BLE001 - parity projects the public error.
        return type(exc).__name__, str(exc)
    raise AssertionError("expected call to fail")


def _document(path: Path, paragraphs: list[str]) -> None:
    doc = HwpxDocument.new()
    for text in paragraphs:
        doc.add_paragraph(text)
    doc.save_to_path(path)
    doc.close()


def test_page_guard_public_exports_and_signatures_are_exact() -> None:
    assert page_guard.__all__ == core_page_guard.__all__
    for name in core_page_guard.__all__:
        core_value = getattr(core_page_guard, name)
        owner_value = getattr(page_guard, name)
        assert owner_value is core_value, name
        assert type(owner_value).__name__ == type(core_value).__name__
        if callable(core_value):
            assert str(inspect.signature(owner_value)) == str(
                inspect.signature(core_value)
            ), name


def test_frozen_policy_modules_shape_matches_frozen_core() -> None:
    for core_name, owner_module in FROZEN_MODULES:
        assert fingerprint(owner_module) == FROZEN[core_name]

    # Covered by the fingerprint comparison above too (simple string
    # constants); kept explicit because the pre-freeze version of this file
    # pinned the literal values directly.
    assert official_lint.OFFICIAL_DOCUMENT_STYLE_REPORT_VERSION == (
        "official-document-style-v1"
    )
    assert table_compute.TABLE_COMPUTE_REPORT_VERSION == "table-compute-v1"


def test_official_lint_and_pii_behavior_match_frozen_core() -> None:
    paragraphs = [
        "1. 추진 목적",
        "  가. 세부 내용",
        "일시: 2026. 7. 24.",
        "금액: 금1,000원",
        "붙임  1. 자료 1부.  끝.",
    ]
    assert official_lint.inspect_official_document_style(
        paragraphs,
        document_type="gongmun",
    ) == GOLDEN["officialLintResult"]

    text = "성명: 홍길동 / 010-1234-5678 / hong@example.com"
    assert pii.detect_pii(text) == GOLDEN["pii"]["detectPii"]
    assert pii.mask_pii(text) == GOLDEN["pii"]["maskPii"]
    for kind, value in (
        ("phone", "010-1234-5678"),
        ("email", "hong@example.com"),
        ("name", "홍길동"),
    ):
        assert pii.mask_value(value, kind) == GOLDEN["pii"]["maskValue"][kind]
    assert pii.minimize_fields(
        {"name": "홍길동", "empty": "", "score": 0},
        ["score", "empty", "name"],
        drop_empty=True,
    ) == GOLDEN["pii"]["minimizeFields"]
    assert pii.deidentify("홍길동", salt="s100") == GOLDEN["pii"]["deidentify"]


def test_page_metrics_comparison_is_exact_and_table_calculation_matches_frozen_core(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.hwpx"
    output = tmp_path / "output.hwpx"
    _document(reference, ["기준 본문", "둘째 문단"])
    _document(output, ["기준 본문", "둘째 문단이 길어졌습니다"])

    core_reference = core_page_guard.collect_metrics(reference)
    core_output = core_page_guard.collect_metrics(output)
    owner_reference = page_guard.collect_metrics(reference)
    owner_output = page_guard.collect_metrics(output)
    assert dataclasses.asdict(owner_reference) == dataclasses.asdict(
        core_reference
    )
    assert dataclasses.asdict(owner_output) == dataclasses.asdict(core_output)
    assert page_guard.compare_metrics(
        owner_reference,
        owner_output,
    ) == core_page_guard.compare_metrics(core_reference, core_output)

    table = {
        "type": "table",
        "columns": [
            {"key": "team", "label": "팀"},
            {"key": "amount", "label": "금액"},
        ],
        "rows": [
            {"team": "A", "amount": "1,000원"},
            {"team": "A", "amount": "2,000원"},
            {"team": "B", "amount": ""},
        ],
    }
    kwargs = {
        "value_columns": ["amount"],
        "operations": ["subtotal", "sum", "average"],
        "group_by": "team",
        "label_column": "team",
    }
    assert table_compute.table_compute(table, **kwargs) == GOLDEN["tableComputeResult"]


def test_public_error_type_and_message_match_frozen_core() -> None:
    assert _error(lambda: pii.PIIPolicy(mask_char="**")) == (
        GOLDEN["piiPolicyError"]["type"],
        GOLDEN["piiPolicyError"]["message"],
    )
    assert _error(
        lambda: table_compute.table_compute(
            [{"amount": 1}],
            operations=["median"],
        )
    ) == (
        GOLDEN["tableComputeError"]["type"],
        GOLDEN["tableComputeError"]["message"],
    )
