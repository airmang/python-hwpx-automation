# SPDX-License-Identifier: Apache-2.0
"""Exact parity between core 4.x compatibility and automation canonical owners.

``hwpx.tools.redline`` (``author_demo_redline``, ``verify_redline``) is not
being removed — the module-ownership ledger keeps it as core's tracked-change
structural contract — so it stays imported live, unchanged below.

``hwpx.tools.doc_diff.build_comparison_table_plan`` and
``hwpx.tools.mail_merge.mail_merge`` *are* both gone as of python-hwpx 5.0
(the modules themselves survive — ``doc_diff``'s other diff/reference parts
and ``mail_merge``'s now-public ``merge_template_rows`` are still core — only
these two specific wrapper functions were removed). Their expected outputs
are read from ``tests/parity_fingerprints/document_ops.golden.json``,
captured from a scratch git worktree at the commit before removal (see
``scripts/freeze_parity_fingerprints.py --historical``) rather than a live
import.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hwpx import HwpxDocument
from hwpx.tools.redline import author_demo_redline
from hwpx.tools.redline import verify_redline as compatibility_verify_redline

from hwpx_automation.office.document_ops import (
    build_comparison_table_plan,
    build_mail_merge,
    verify_redline,
)

_FIXTURES = Path(__file__).parent / "parity_fingerprints"
DOCUMENT_OPS_GOLDEN = json.loads(
    (_FIXTURES / "document_ops.golden.json").read_text(encoding="utf-8")
)["calls"]


class _UnavailableOracle:
    """A core RenderBackend that reports itself unusable."""

    def available(self) -> bool:
        return False

    def check(self, before_hwpx: Any, after_hwpx: Any, **_kwargs: Any) -> Any:
        from hwpx.quality.rendering import VisualReport

        return VisualReport(
            ok=True,
            render_checked=False,
            warnings=["test backend is unavailable; nothing was rendered"],
        )


def _template(path: Path) -> None:
    document = HwpxDocument.new()
    try:
        document.add_paragraph("name={{name}} / phone={{phone}}")
        document.save_to_path(path)
    finally:
        document.close()


def _redline_pair(tmp_path: Path) -> tuple[Path, Path]:
    document = HwpxDocument.new()
    before = tmp_path / "before.hwpx"
    after = tmp_path / "after.hwpx"
    try:
        document.add_paragraph("baseline")
        document.save_to_path(before)
        author_demo_redline(document)
        document.save_to_path(after)
    finally:
        document.close()
    return before, after


def _mail_merge_projection(report: dict[str, Any]) -> dict[str, Any]:
    row = report["rows"][0]
    return {
        "report_version": report["report_version"],
        "placeholderKeys": report["placeholderKeys"],
        "fitAware": report["fitAware"],
        "rowCount": report["rowCount"],
        "createdCount": report["createdCount"],
        "rowsWithIssues": report["rowsWithIssues"],
        "ok": report["ok"],
        "openSafety": report["openSafety"],
        "row": {
            key: row[key]
            for key in (
                "rowIndex",
                "created",
                "replacedCount",
                "missingKeys",
                "unresolvedPlaceholders",
                "openSafety",
                "fitFields",
                "maskedFields",
                "reasons",
                "ok",
            )
        },
    }


def test_comparison_plan_matches_frozen_core() -> None:
    old = ["제1조 목적", "제2조 예산"]
    new = ["제1조 목적", "제2조 예산 변경", "제3조 시행"]

    assert build_comparison_table_plan(
        old,
        new,
        title="신구대조표",
        include_equal=False,
    ) == DOCUMENT_OPS_GOLDEN["comparisonPlan"]


def test_mail_merge_policy_and_receipts_match_frozen_core(tmp_path: Path) -> None:
    template = tmp_path / "template.hwpx"
    _template(template)
    rows = [{"name": "홍길동", "phone": "010-1234-5678"}]

    canonical = build_mail_merge(
        template,
        rows,
        output_dir=tmp_path / "canonical",
    )

    # The frozen core masked the phone number it wrote into the document. The automation
    # owner now writes each value as given, which is the one intended difference.
    golden = DOCUMENT_OPS_GOLDEN["mailMerge"]
    assert golden["projection"]["row"]["maskedFields"] == ["phone"]
    assert golden["exportText"] == "name=홍길동 / phone=010-****-****"
    expected = {
        **golden["projection"],
        "row": {**golden["projection"]["row"], "maskedFields": []},
    }
    assert _mail_merge_projection(canonical) == expected
    canonical_doc = HwpxDocument.open(canonical["rows"][0]["filename"])
    try:
        assert canonical_doc.text.plain() == "name=홍길동 / phone=010-1234-5678"
    finally:
        canonical_doc.close()


def test_unavailable_oracle_redline_receipt_is_exact(tmp_path: Path) -> None:
    before, after = _redline_pair(tmp_path)
    oracle = _UnavailableOracle()

    assert verify_redline(
        before,
        after,
        oracle=oracle,
    ) == compatibility_verify_redline(
        before,
        after,
        oracle=oracle,
    )


def test_canonical_owner_injects_a_backend_instead_of_degrading(monkeypatch) -> None:
    """The owner's job is to supply a renderer, and it must actually do it.

    Core's verify_redline degrades honestly when nothing is injected. That is
    right for a library and wrong for the canonical owner: a caller reaching the
    MCP surface asked for a Hancom-backed verdict. Before this feature an import
    ban enforced the split; now that the owner delegates to core, the guard has
    to be behavioural instead.
    """

    from hwpx_automation.office.document_ops import redline as owner

    supplied: list[object] = []

    def _fake_core_verify(before, after, *, oracle=None):
        supplied.append(oracle)
        return {"report_version": "redline-verify-v1"}

    monkeypatch.setattr(owner, "_core_verify_redline", _fake_core_verify)
    owner.verify_redline("before.hwpx", "after.hwpx")

    assert len(supplied) == 1
    backend = supplied[0]
    assert backend is not None, "the owner degraded instead of supplying a backend"
    assert hasattr(backend, "available") and hasattr(backend, "check")
