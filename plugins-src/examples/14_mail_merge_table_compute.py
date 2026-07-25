#!/usr/bin/env python3
"""Create mail-merge and table-compute examples and verify open safety."""

from __future__ import annotations

import csv
from pathlib import Path
from zipfile import ZipFile

from hwpx import HwpxDocument, inspect_mail_merge_placeholders, validate_editor_open_safety
from hwpx_automation.office.authoring import create_document_from_plan, validate_document_plan
from hwpx_automation.office.document_ops import mail_merge
from hwpx_automation.office.utilities import table_compute


OUTPUT_DIR = Path(__file__).resolve().parent / "out" / "14_mail_merge_table_compute"


def _write_template(path: Path) -> None:
    doc = HwpxDocument.new()
    doc.add_paragraph("{{student}} 보호자님께")
    doc.add_paragraph("학급: {{class_name}}")
    doc.add_paragraph("담당 교사: ${teacher}")
    doc.add_paragraph("안내: <<notice>>")
    doc.save_to_path(path)
    doc.close()


def _write_rows(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["student", "class_name", "teacher", "notice"])
        writer.writeheader()
        writer.writerow(
            {
                "student": "김하나",
                "class_name": "1-1",
                "teacher": "이교사",
                "notice": "체험학습 동의서를 제출해 주세요.",
            }
        )
        writer.writerow(
            {
                "student": "박두리",
                "class_name": "1-2",
                "teacher": "최교사",
                "notice": "방과후 수강 신청 기간입니다.",
            }
        )


def run_mail_merge() -> Path:
    template = OUTPUT_DIR / "notice-template.hwpx"
    data = OUTPUT_DIR / "notice-rows.csv"
    zip_path = OUTPUT_DIR / "notices.zip"
    _write_template(template)
    _write_rows(data)

    placeholders = inspect_mail_merge_placeholders(template)
    if placeholders["keys"] != ["class_name", "notice", "student", "teacher"]:
        raise RuntimeError(f"unexpected placeholders: {placeholders['keys']}")

    report = mail_merge(
        template,
        data,
        output_dir=OUTPUT_DIR / "notices",
        filename_pattern="{index:03d}-{student}.hwpx",
        zip_path=zip_path,
    )
    if not report["ok"]:
        raise RuntimeError(f"mail merge reported row issues: {report['rowsWithIssues']}")
    if not all(row["openSafety"]["ok"] for row in report["rows"]):
        raise RuntimeError("mail merge openSafety failed")
    with ZipFile(zip_path) as archive:
        if len(archive.namelist()) != report["createdCount"]:
            raise RuntimeError("zip entry count does not match createdCount")
    print(f"[OK] mail-merge: created={report['createdCount']} zip={zip_path}")
    return zip_path


def run_table_compute() -> Path:
    source_table = {
        "type": "table",
        "columns": [
            {"key": "dept", "label": "부서"},
            {"key": "item", "label": "항목"},
            {"key": "amount", "label": "금액"},
        ],
        "rows": [
            {"dept": "교육", "item": "연수", "amount": "1,000"},
            {"dept": "교육", "item": "교재", "amount": "500"},
            {"dept": "시설", "item": "수선", "amount": "2,000"},
        ],
    }
    computed = table_compute(
        source_table,
        value_columns=["amount"],
        operations=["subtotal", "sum", "average"],
        group_by="dept",
        label_column="item",
    )
    if not computed["evidence"]:
        raise RuntimeError("table_compute returned no evidence")

    plan = {
        "schemaVersion": "hwpx.document_plan.v2",
        "preset": "government_report",
        "title": "예산 계산표",
        "sections": [
            {
                "blocks": [
                    {"type": "heading", "level": 1, "text": "예산 계산표"},
                    computed["computedTable"],
                ]
            }
        ],
    }
    validation = validate_document_plan(plan)
    if not validation.ok:
        raise RuntimeError(f"computed plan failed validation: {validation.to_dict()['issues']}")
    target = OUTPUT_DIR / "computed-budget.hwpx"
    document = create_document_from_plan(plan)
    try:
        document.save_to_path(target)
    finally:
        document.close()
    open_safety = validate_editor_open_safety(target)
    if not open_safety.ok:
        raise RuntimeError(f"table compute openSafety failed: {open_safety.summary}")
    print(f"[OK] table-compute: evidence={len(computed['evidence'])} path={target}")
    return target


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_mail_merge()
    run_table_compute()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
