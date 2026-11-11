# SPDX-License-Identifier: Apache-2.0
"""M5/S-059: MCP PII-masking surface (extract default-ON masking + audit)."""
from __future__ import annotations

import json
from pathlib import Path

from hwpx_automation.core.document import open_doc, save_doc
from hwpx_automation.server import (
    add_table,
    analyze_form_fill,
    apply_form_fill,
    create_document,
    get_document_text,
    get_table_text,
    scan_personal_info,
)

RRN, MASKED_RRN = "900101-2345678", "900101-2******"
PHONE, MASKED_PHONE = "010-1234-5678", "010-****-****"


def _doc_with_pii(tmp_path: Path) -> Path:
    target = tmp_path / "pii.hwpx"
    create_document(str(target))
    doc = open_doc(str(target))
    doc.add_paragraph(f"주민등록번호 {RRN} 연락처 {PHONE}")
    save_doc(doc, str(target))
    return target


def test_get_document_text_masks_machine_pii_by_default(tmp_path: Path) -> None:
    masked = get_document_text(str(_doc_with_pii(tmp_path)))["text"]
    assert MASKED_RRN in masked and MASKED_PHONE in masked
    assert RRN not in masked and PHONE not in masked


def test_get_document_text_mask_opt_out_returns_raw(tmp_path: Path) -> None:
    raw = get_document_text(str(_doc_with_pii(tmp_path)), mask=False)["text"]
    assert RRN in raw and PHONE in raw


def test_scan_personal_info_returns_masked_examples_only(tmp_path: Path) -> None:
    report = scan_personal_info(text=f"주민 {RRN} 폰 {PHONE} 메일 a.b@example.com")
    assert report["total"] == 3
    types = {bucket["type"] for bucket in report["byType"]}
    assert {"rrn", "phone", "email"} <= types
    # the report must NEVER contain raw PII values
    blob = json.dumps(report, ensure_ascii=False)
    assert RRN not in blob and PHONE not in blob and "a.b@example.com" not in blob


def test_form_fill_writes_the_given_value_and_masks_only_its_report(tmp_path: Path) -> None:
    source, destination = tmp_path / "form.hwpx", tmp_path / "filled.hwpx"
    create_document(str(source))
    add_table(str(source), 2, 2, [["연락처", ""], ["주민등록번호", ""]])
    analysis = analyze_form_fill(
        str(source),
        input_json={
            "schemaVersion": "hwpx.formfill.v1",
            "fields": [
                {"key": "phone", "label": "연락처", "value": PHONE},
                {"key": "rrn", "label": "주민등록번호", "value": RRN},
            ],
        },
        destination_filename=str(destination),
    )

    result = apply_form_fill(analysis=analysis, confirm=True)

    assert result["handoff_status"] == "ready"
    written = get_table_text(str(destination), 0)["data"]
    assert [row[1] for row in written] == [PHONE, RRN]
    assert result["responseMasked"] is True
    blob = json.dumps(result, ensure_ascii=False)
    assert PHONE not in blob and RRN not in blob
    assert MASKED_PHONE in blob and MASKED_RRN in blob
