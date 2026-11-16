# SPDX-License-Identifier: Apache-2.0
"""Mail merge (``hwpx_automation.mail_merge``), moved with the code from python-hwpx.

From python-hwpx tests: test_mail_merge_placeholders_everywhere.py (whole file),
test_mail_merge_xlsx.py (whole file), test_export_text_boxes.py
(``test_mail_merge_fills_placeholders_in_text_boxes``), test_export_captions_dutmal.py
(``test_mail_merge_fills_captions_and_dutmal``) and test_document_ops_runtime_boundary.py
(``test_generic_merge_uses_only_the_injected_sanitizer``,
``test_merge_template_rows_does_not_use_a_deprecated_internal_api``).
"""

from __future__ import annotations

import inspect
import warnings
from pathlib import Path

import pytest

from hwpx import HwpxDocument
from hwpx_automation.mail_merge import (
    MAIL_MERGE_REPORT_VERSION,
    inspect_mail_merge_placeholders,
    load_mail_merge_rows,
    merge_template_rows,
)


def _template(tmp_path: Path) -> Path:
    doc = HwpxDocument.new()
    doc.add_paragraph("이름: {{성명}} / {{name}} / ${학교명} / <<반>>")
    doc.page.set_header(text="머리말 {{school}}")
    doc.page.set_footer(text="꼬리말 {{쪽}}")
    path = tmp_path / "tpl.hwpx"
    doc.save_to_path(path)
    return path


def _everywhere_text(path: Path) -> str:
    from hwpx_automation.mail_merge import _template_text

    doc = HwpxDocument.open(path)
    try:
        return _template_text(doc)
    finally:
        doc.close()


def test_inspect_finds_korean_keys_and_header_footer_placeholders(tmp_path: Path) -> None:
    report = inspect_mail_merge_placeholders(_template(tmp_path))

    assert report["report_version"] == MAIL_MERGE_REPORT_VERSION
    assert report["keys"] == sorted(["name", "school", "성명", "쪽", "학교명", "반"])


def test_merge_replaces_korean_keys_and_header_footer(tmp_path: Path) -> None:
    row = {"성명": "홍길동", "name": "Hong", "학교명": "가나고", "반": "3", "school": "다라고", "쪽": "1"}
    report = merge_template_rows(_template(tmp_path), [row], output_dir=tmp_path / "out")

    assert report["ok"] is True
    assert report["rows"][0]["unresolvedPlaceholders"] == []
    assert report["rows"][0]["openSafety"]["ok"] is True
    text = _everywhere_text(Path(report["rows"][0]["filename"]))
    assert "홍길동" in text and "가나고" in text and "다라고" in text and "꼬리말 1" in text
    assert "{{" not in text and "${" not in text and "<<" not in text


def test_row_with_placeholder_left_is_not_ok(tmp_path: Path) -> None:
    # The value brings in a new placeholder, so the output still has one after replacing.
    row = {"성명": "{{남은칸}}", "name": "Hong", "학교명": "가", "반": "1", "school": "s", "쪽": "1"}
    report = merge_template_rows(_template(tmp_path), [row], output_dir=tmp_path / "out")

    assert report["ok"] is False
    assert report["rows"][0]["unresolvedPlaceholders"] == ["{{남은칸}}"]
    assert "unresolved_placeholder" in report["rows"][0]["reasons"]


def test_header_placeholder_left_in_output_fails_the_row(tmp_path: Path) -> None:
    # A key the data lacks keeps its header placeholder; the row reports it instead of passing.
    report = merge_template_rows(_template(tmp_path), [{"name": "Hong"}], output_dir=tmp_path / "out")

    row = report["rows"][0]
    assert report["ok"] is False
    assert set(row["missingKeys"]) == {"school", "성명", "쪽", "학교명", "반"}


def test_digit_first_text_is_not_a_placeholder(tmp_path: Path) -> None:
    doc = HwpxDocument.new()
    doc.add_paragraph("{{1번}} {{ }} {{a b}}")
    path = tmp_path / "t.hwpx"
    doc.save_to_path(path)

    assert inspect_mail_merge_placeholders(path)["keys"] == []


# --- from tests/test_mail_merge_xlsx.py ---------------------------------------


def _write_xlsx(path, header, rows):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_load_rows_from_xlsx_uses_header_as_keys(tmp_path):
    path = tmp_path / "roster.xlsx"
    _write_xlsx(path, ["name", "class"], [["홍길동", "3-1"], ["김영수", "3-2"]])

    rows = load_mail_merge_rows(path)

    assert rows == [
        {"name": "홍길동", "class": "3-1"},
        {"name": "김영수", "class": "3-2"},
    ]


def test_load_rows_from_xlsx_coerces_cells_to_str_and_skips_blank_rows(tmp_path):
    path = tmp_path / "roster2.xlsx"
    _write_xlsx(path, ["name", "no"], [["홍길동", 7], [None, None], ["김영수", 12]])

    rows = load_mail_merge_rows(path)

    # numbers become strings; the fully-empty row is dropped
    assert rows == [{"name": "홍길동", "no": "7"}, {"name": "김영수", "no": "12"}]


def test_xlsx_without_openpyxl_names_this_packages_extra(tmp_path, monkeypatch):
    import sys

    path = tmp_path / "roster3.xlsx"
    path.write_bytes(b"PK\x03\x04")  # never opened: the import fails first
    monkeypatch.setitem(sys.modules, "openpyxl", None)

    with pytest.raises(ImportError) as raised:
        load_mail_merge_rows(path)
    assert 'pip install "python-hwpx-automation[xlsx]"' in str(raised.value)


# --- from tests/test_export_text_boxes.py and tests/test_export_captions_dutmal.py


def test_mail_merge_fills_placeholders_in_text_boxes(tmp_path) -> None:
    from hwpx.tools.exporter import export_text

    document = HwpxDocument.new(empty_first_line=True)
    document.add_paragraph("이름: {{name}}")
    holder = document.add_paragraph("상자 담은 문단")
    document.shapes.add_rectangle(paragraph=holder).set_draw_text("상자: {{name}}")
    cell = document.add_table(1, 1).cell(0, 0)
    cell.text = "칸"
    document.shapes.add_rectangle(paragraph=cell.paragraphs[0]).set_draw_text("칸 상자: {{name}}")
    template = tmp_path / "tpl.hwpx"
    document.save_to_path(template)

    report = merge_template_rows(template, [{"name": "홍길동"}], output_dir=tmp_path / "out")

    (row,) = report["rows"]
    assert row["ok"], row
    assert row["replacedCount"] == 3
    text = export_text(HwpxDocument.open(row["filename"]))
    assert "상자: 홍길동" in text and "칸 상자: 홍길동" in text and "{{name}}" not in text


def test_mail_merge_fills_captions_and_dutmal(tmp_path) -> None:
    from hwpx.tools.exporter import export_text

    doc = HwpxDocument.new(empty_first_line=True)
    doc.add_paragraph("이름: {{name}}")
    paragraph = doc.sections[0].add_paragraph("표 담은 문단")
    table = paragraph.add_table(1, 1)
    table.set_cell_text(0, 0, "칸")
    table.set_caption("캡션: {{title}}")
    doc.shapes.add_dutmal("{{who}}", "덧말", paragraph=doc.add_paragraph(""))
    template = tmp_path / "tpl.hwpx"
    doc.save_to_path(template)

    report = merge_template_rows(template, [{"name": "홍길동", "title": "요약", "who": "김"}], output_dir=tmp_path / "out")

    (row,) = report["rows"]
    assert row["ok"], row
    assert row["replacedCount"] == 3 and row["unresolvedPlaceholders"] == []
    text = export_text(HwpxDocument.open(row["filename"]))
    assert "캡션: 요약" in text and "김(덧말:덧말)" in text and "{{" not in text


# --- from tests/test_document_ops_runtime_boundary.py -------------------------


def test_generic_merge_uses_only_the_injected_sanitizer(tmp_path: Path) -> None:
    template = tmp_path / "template.hwpx"
    document = HwpxDocument.new()
    try:
        document.add_paragraph("student={{student}}")
        document.save_to_path(template)
    finally:
        document.close()

    report = merge_template_rows(
        template,
        [{"student": "private"}],
        output_dir=tmp_path / "out",
        value_sanitizer=lambda value: value.upper(),
    )

    assert report["ok"] is True
    assert report["rows"][0]["maskedFields"] == ["student"]
    merged = HwpxDocument.open(report["rows"][0]["filename"])
    try:
        assert "PRIVATE" in merged.text.plain()
    finally:
        merged.close()

    source = inspect.getsource(merge_template_rows)
    assert "mask_pii" not in source


def test_merge_template_rows_does_not_use_a_deprecated_internal_api(tmp_path: Path) -> None:
    template = HwpxDocument.new()
    try:
        template.add_paragraph("body: {{org}}")
        table = template.add_table(rows=1, cols=1)
        table.cell(0, 0).text = "cell: {{dept}}"
        template_path = tmp_path / "template.hwpx"
        template.save_to_path(template_path)
    finally:
        template.close()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        report = merge_template_rows(
            template_path,
            [{"org": "테스트조직", "dept": "테스트부서"}],
            output_dir=tmp_path / "out",
        )

    deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert not deprecation_warnings, [str(w.message) for w in deprecation_warnings]

    assert report["ok"] is True
    merged = HwpxDocument.open(report["rows"][0]["filename"])
    try:
        text = merged.text.plain()
        assert "테스트조직" in text
        assert "테스트부서" in text
    finally:
        merged.close()


def test_rows_load_from_mappings_the_same_way() -> None:
    assert load_mail_merge_rows([{"name": "A", "score": 0}]) == [{"name": "A", "score": 0}]
    assert load_mail_merge_rows({"rows": [{"a": 1}]}) == [{"a": 1}]
    with pytest.raises(TypeError):
        load_mail_merge_rows([1])  # type: ignore[list-item]
