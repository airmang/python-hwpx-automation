# SPDX-License-Identifier: Apache-2.0
"""python-hwpx 7.0 save refusals reach the caller as DOCUMENT_SAVE_FAILED with the engine's code."""

from __future__ import annotations

from pathlib import Path

import pytest
from hwpx import HwpxDocument

from hwpx_automation.errors import CORE_SAVE_REFUSALS, core_save_refusal_payload
from hwpx_automation.hwpx_ops import HwpxOperationError, HwpxOps
from hwpx_automation.runtime import _classified_error_payload


def _unanchored_memo_error() -> BaseException:
    doc = HwpxDocument.new()
    doc.add_paragraph("본문")
    doc.notes.add_memo("걸지 않은 메모")
    with pytest.raises(Exception) as refused:
        doc.to_bytes()
    return refused.value


def test_an_unanchored_memo_save_is_a_document_save_failure() -> None:
    error = _unanchored_memo_error()
    assert getattr(error, "code", None) == "note-memo-unanchored"
    payload = _classified_error_payload(error)
    assert payload["code"] == "DOCUMENT_SAVE_FAILED"
    assert payload["details"] == {"coreCode": "note-memo-unanchored"}
    assert payload["message"] == CORE_SAVE_REFUSALS["note-memo-unanchored"]


def test_other_errors_are_not_save_refusals() -> None:
    assert core_save_refusal_payload(ValueError("x")) is None
    error = ValueError("x")
    error.code = "style-not-found"  # type: ignore[attr-defined]
    assert core_save_refusal_payload(error) is None


def test_ops_save_failure_carries_the_core_code(tmp_path: Path) -> None:
    source = tmp_path / "in.hwpx"
    doc = HwpxDocument.new()
    doc.add_paragraph("본문")
    doc.save(source)
    ops = HwpxOps(base_directory=tmp_path)
    with pytest.raises(HwpxOperationError) as refused:
        ops.add_memo(str(source), "걸지 않은 메모")
    assert refused.value.code == "DOCUMENT_SAVE_FAILED"
    assert (refused.value.details or {}).get("coreCode") == "note-memo-unanchored"
