# SPDX-License-Identifier: Apache-2.0
"""Ingest tests gathered from python-hwpx test files that also test what stays there.

Each block names the python-hwpx test file it came from. Only the ingest tests and
assertions came; the Markdown export half of a mixed test is in the ``test_markdown_*``
files, and what tests the engine stayed with the engine.
"""

from __future__ import annotations

import io
import tracemalloc
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from lxml import etree

from hwpx import HwpxDocument
from hwpx.errors import HwpxError
from hwpx_automation.ingest import DocumentIngestor, UnsupportedDocumentFormat
from hwpx_automation.ingest.base import DocumentIngestError, DocumentSourceInfo
from hwpx_automation.ingest.hwpx_converter import (
    HwpxMarkdownConverter,
    _left_out_content,
    _python_hwpx_version,
)
from hwpx_automation.markdown import to_markdown

FIXTURES = Path(__file__).parent / "fixtures"
HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
MB = 1024 * 1024


def _ingest(document: HwpxDocument):
    return DocumentIngestor.default().convert(document.to_bytes())


# ── tests/test_markdown_export_equations.py ──────────────────────────────────


def _equation_document() -> HwpxDocument:
    doc = HwpxDocument.new()
    paragraph = doc.add_paragraph("근은 ")
    paragraph.add_equation("x = {-b +- sqrt {b ^{2} - 4ac}} over {2a}")
    paragraph.add_run("이다.")
    table = doc.add_table(1, 2)
    table.rows[0].cells[0].paragraphs[0].add_equation("{1} over {2}")
    return doc


def test_ingest_carries_equations_and_reports_nothing_left_out() -> None:
    result = DocumentIngestor.default().convert(_equation_document().to_bytes())
    assert r"\sqrt{b^{2} - 4 ac}" in result.markdown
    assert result.metadata["left_out"] == {}

    body_only = DocumentIngestor.default().convert(
        _equation_document().to_bytes(), markdown_options={"equations": False}
    )
    assert body_only.metadata["left_out"] == {"equation": 2}


# ── tests/test_markdown_export_outside_body.py ───────────────────────────────


def _with_unplaced_memo(package: bytes, memogroup_xml: str) -> bytes:
    """*package* with a memo kept only in ``hp:memogroup`` (no MEMO field), as python-hwpx 6.x wrote.

    python-hwpx 7.0 refuses to save a memo it made without a paragraph
    (``note-memo-unanchored``), so the 6.x shape is written into the section part here.
    """

    source = zipfile.ZipFile(io.BytesIO(package))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for info in source.infolist():
            data = source.read(info)
            if info.filename == "Contents/section0.xml":
                text = data.decode("utf-8")
                end = text.rindex("</hs:sec>")
                data = (text[:end] + memogroup_xml + text[end:]).encode("utf-8")
            target.writestr(info, data)
    return out.getvalue()


def _outside_body_document() -> HwpxDocument:
    doc = HwpxDocument.new()
    doc.add_paragraph("본문 첫 문단입니다.")
    reviewed = doc.add_paragraph("검토가 필요한 문장입니다.")
    doc.notes.add_memo("근거 자료를 붙여 주세요", paragraph=reviewed)
    unplaced = doc.notes.add_memo("자리 없는 메모")
    memogroup_xml = etree.tostring(doc.sections[0].memo_group.element, encoding="unicode")
    doc.notes.remove_memo(unplaced)
    doc.page.set_header(text="2026학년도 운영 계획")
    doc.page.set_footer(text="가나고등학교")
    buffer = io.BytesIO()
    doc.save(buffer)
    return HwpxDocument.open(_with_unplaced_memo(buffer.getvalue(), memogroup_xml))


def test_ingest_carries_them_and_reports_nothing_left_out() -> None:
    buffer = io.BytesIO()
    _outside_body_document().save(buffer)
    result = DocumentIngestor.default().convert(buffer.getvalue())
    for text in ("2026학년도 운영 계획", "가나고등학교", "근거 자료를 붙여 주세요", "자리 없는 메모"):
        assert text in result.markdown, text
    assert result.metadata["left_out"] == {}
    assert result.lossiness == "low"


def test_ingest_can_still_be_asked_for_the_body_only() -> None:
    buffer = io.BytesIO()
    _outside_body_document().save(buffer)
    result = DocumentIngestor.default().convert(
        buffer.getvalue(), markdown_options={"headers_and_footers": False, "memos": False}
    )
    assert "운영 계획" not in result.markdown
    assert set(result.metadata["left_out"]) == {"header", "footer", "memo"}


# ── tests/test_export_fix7_convert.py ────────────────────────────────────────


def _doc(*texts: str) -> HwpxDocument:
    document = HwpxDocument.new()
    for text in texts:
        document.add_paragraph(text)
    return document


def test_text_with_entities_and_formatting_runs_is_not_reported_missing() -> None:
    document = HwpxDocument.new()
    anchor = document.add_paragraph("본문")
    note = "과제 <살아있는 기증자> 연구 & 기준"
    document.notes.add_footnote(note, paragraph=anchor)
    box = document.add_paragraph("상자 앞")
    box.add_run("굵은", bold=True)
    box.add_run(" 뒤 글")
    result = _ingest(document)
    assert "&lt;살아있는 기증자&gt;" in result.markdown
    assert result.metadata["left_out"] == {}
    assert result.lossiness == "low"


def test_a_table_placed_in_the_section_is_checked() -> None:
    source = FIXTURES / "reader_robustness" / "irb_form_filled.hwpx"
    with ZipFile(source) as archive:
        root = etree.fromstring(archive.read("Contents/section0.xml"))
    assert [child for child in root if child.tag == f"{HP}tbl"], "시험 문서의 표는 구역에 바로 놓여 있어야 한다"
    result = DocumentIngestor.default().convert(source)
    assert "table" not in result.metadata["left_out"]


def test_left_out_checks_tables_and_captions() -> None:
    document = _doc("본문 문장")
    table = document.add_table(1, 1)
    table.cell(0, 0).text = "칸에만 있는 글"
    markdown = to_markdown(document, rich=True)
    assert _left_out_content(document, markdown) == {}
    assert _left_out_content(document, markdown.replace("칸에만 있는 글", "")) == {"table": {"count": 1, "chars": 6}}


def test_ingest_carries_list_labels() -> None:
    document = HwpxDocument.new(empty_first_line=True)
    for text in ("첫째", "둘째", "글머리"):
        document.add_paragraph(text)
    document.styles.apply_list_format(paragraphs=[1, 2], kind="number")
    document.styles.apply_list_format(paragraphs=[3], kind="bullet")
    assert "1. 첫째" not in to_markdown(document, rich=True).split("\n")
    assert "1. 첫째" in _ingest(document).markdown.split("\n")


@pytest.mark.parametrize("wrap", [bytes, io.BytesIO])
def test_ingest_keeps_the_reason_for_bytes_and_streams(wrap) -> None:
    old = b"HWP Document File V3.00 \x1a\x01\x02\x03\x04\x05" + b"\x00" * 64
    with pytest.raises(UnsupportedDocumentFormat, match="HWP 3.x"):
        DocumentIngestor.default().convert(wrap(old))
    with pytest.raises(UnsupportedDocumentFormat, match="빈 파일") as found:
        DocumentIngestor.default().convert(wrap(b""))
    assert found.value.suggestion
    assert found.value.context["cause_code"] == "hwpx-value-error"


def test_ingest_leaves_colour_spans_out() -> None:
    document = HwpxDocument.new()
    paragraph = document.add_paragraph("앞 ")
    paragraph.add_run("빨강", color="#FF0000")
    assert "<span" in to_markdown(document, rich=True)
    assert "<span" not in _ingest(document).markdown


# ── tests/test_migration_seams.py ────────────────────────────────────────────


def test_heading_callback_reaches_ingest_without_extension() -> None:
    document = HwpxDocument.new()
    document.add_paragraph("Ⅰ. 기본 제목")
    options = {"heading_detector": lambda text: "### injected" if "기본 제목" in text else None}
    result = DocumentIngestor.default().convert(io.BytesIO(document.to_bytes()), markdown_options=options)
    assert "### injected" in result.markdown and "# Ⅰ." not in result.markdown


# ── tests/test_internal_calls_skip_moved_names.py ────────────────────────────


def test_markdown_ingest_uses_no_moved_names() -> None:
    """Ingest calls no python-hwpx name that warns that it moved (recorded, not raised:
    the converter path catches ``Exception`` around some calls)."""

    doc = HwpxDocument.new()
    doc.add_paragraph("본문")
    data = doc.to_bytes()
    source = DocumentSourceInfo(extension=".hwpx", mimetype=None, filename="doc.hwpx")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        HwpxMarkdownConverter().convert(io.BytesIO(data), source)
    moved = [str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)]
    assert moved == []


# ── tests/test_lazy_tools_submodules.py ──────────────────────────────────────


def test_engine_version_is_the_installed_python_hwpx() -> None:
    from importlib.metadata import PackageNotFoundError, version

    try:
        expected = version("python-hwpx")
    except PackageNotFoundError:
        expected = "0+unknown"
    assert _python_hwpx_version() == expected


def test_missing_distribution_keeps_unknown_version_fallback() -> None:
    from importlib.metadata import PackageNotFoundError

    with patch("importlib.metadata.version", side_effect=PackageNotFoundError):
        assert _python_hwpx_version() == "0+unknown"


# ── tests/test_opc_package.py ────────────────────────────────────────────────


def test_format_sniffing_does_not_read_an_oversized_mimetype() -> None:
    """`accepts()` must reject a hostile archive without expanding `mimetype`.

    A 4 MiB `mimetype` deflates to about 4 KB, so the archive is small enough to
    look harmless while the member itself trips the compression-ratio limit.
    """

    buffer = io.BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("mimetype", b"\0" * (4 * MB))
        archive.writestr("Contents/section0.xml", b"<x/>")
    package = buffer.getvalue()
    source = DocumentSourceInfo(extension=".bin", mimetype=None, filename="x.bin")

    tracemalloc.start()
    try:
        accepted = HwpxMarkdownConverter().accepts(io.BytesIO(package), source)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()

    assert accepted is False
    assert peak < 1 * MB, f"mimetype was expanded: peak {peak / MB:.1f} MB"


# ── tests/test_public_exceptions_inherit_hwpx_error.py ───────────────────────


@pytest.mark.parametrize(
    ("error", "code"),
    [(DocumentIngestError, "ingest-failed"), (UnsupportedDocumentFormat, "ingest-format-unsupported")],
)
def test_public_exception_keeps_its_parent_and_joins_hwpx_error(error, code) -> None:
    assert issubclass(error, HwpxError)
    assert issubclass(error, RuntimeError)
    raised = error("메시지")
    assert str(raised) == "메시지"
    assert raised.code == error.default_code == code
    assert raised.to_dict()["message"] == "메시지"


def test_ingest_error_keeps_attempts() -> None:
    raised = UnsupportedDocumentFormat("없음", attempts=())
    assert raised.attempts == []
    assert raised.as_dict()["error"] == "UnsupportedDocumentFormat"
