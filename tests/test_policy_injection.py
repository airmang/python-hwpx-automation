# SPDX-License-Identifier: Apache-2.0
"""PII policy injection remains explicit at automation-owned workflow seams."""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from hwpx_automation import form_fill
from hwpx_automation.handlers import specialized
from hwpx_automation.office.compliance import DEFAULT_POLICY, mask_pii


def test_mail_merge_passes_no_value_masker_to_the_core(
    monkeypatch,
    tmp_path: Path,
) -> None:
    mail_merge_owner = importlib.import_module(
        "hwpx_automation.office.document_ops.mail_merge"
    )
    captured: dict[str, Any] = {}

    def fake_mail_merge(*args: Any, **kwargs: Any) -> dict[str, Any]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"createdCount": 0, "rowCount": 0, "rows": []}

    template = tmp_path / "template.hwpx"
    template.touch()
    monkeypatch.setattr(mail_merge_owner, "merge_template_rows", fake_mail_merge)

    report = mail_merge_owner.build_mail_merge(template, [])

    assert report["createdCount"] == 0
    # Generated documents must hold the row values as given, so no masker is injected.
    assert "value_sanitizer" not in captured["kwargs"]


def test_mail_merge_handler_routes_to_the_document_ops_owner(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    def fake_mail_merge(*args: Any, **kwargs: Any) -> dict[str, Any]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"createdCount": 0, "rowCount": 0, "rows": []}

    template = tmp_path / "template.hwpx"
    template.touch()
    monkeypatch.setattr(specialized, "build_hwpx_mail_merge", fake_mail_merge)

    report = specialized.mail_merge(str(template), data_rows=[])

    assert report["openSafety"]["ok"] is True
    assert captured["kwargs"]["fit_mode"] is None
    assert "masking_policy" not in captured["kwargs"]


def test_form_fill_binds_the_canonical_mcp_masker_and_policy() -> None:
    assert form_fill.mask_pii is mask_pii
    assert form_fill.DEFAULT_POLICY is DEFAULT_POLICY
