# SPDX-License-Identifier: Apache-2.0
"""What a builder save writes and reports: package metadata, schema lint, anchors."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pytest
from hwpx.document import HwpxDocument
from hwpx.tools.validator import validate_document

import hwpx_automation.office.authoring.builder.core as builder_core
from hwpx_automation.office.authoring.builder import (
    Document,
    Heading,
    Metadata,
    PageSize,
    Paragraph,
    Run,
    Section,
    Table,
)
from hwpx_automation.office.authoring.builder.core import NativeToc


def _body_texts(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        section = archive.read("Contents/section0.xml").decode("utf-8")
    return re.findall(r"<hp:t>([^<]*)</hp:t>", section)


# --- metadata goes to the package, not the body ---------------------------------


def test_metadata_is_written_to_package_properties_not_body(tmp_path: Path) -> None:
    body = [Paragraph(children=[Run("본문")])]
    plain = tmp_path / "plain.hwpx"
    with_metadata = tmp_path / "metadata.hwpx"
    Document(sections=[Section(page=PageSize.A4, children=body)]).save_to_path(plain)
    report = Document(
        metadata=Metadata(title="T", author="A", organization="O"),
        sections=[Section(page=PageSize.A4, children=body)],
    ).save_to_path(with_metadata)

    assert _body_texts(with_metadata) == _body_texts(plain) == ["본문"]
    reopened = HwpxDocument.open(with_metadata)
    try:
        assert len(reopened.paragraphs) == len(HwpxDocument.open(plain).paragraphs)
        metadata = reopened.parts.metadata
    finally:
        reopened.close()
    assert metadata is not None
    assert metadata.title == "T"
    assert metadata.creator == "A"
    # Stamped at build time, not the blank template's fixture dates.
    assert metadata.created_date is not None
    assert not metadata.created_date.startswith("2025-09-17")
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", metadata.modified_date or "")
    # OPF has no organization field; the report keeps what was asked for.
    assert report.metadata == {"title": "T", "author": "A", "organization": "O"}


def test_document_without_metadata_keeps_template_properties(tmp_path: Path) -> None:
    path = tmp_path / "plain.hwpx"
    Document(sections=[Section(children=[Paragraph(text="x")])]).save_to_path(path)
    reopened = HwpxDocument.open(path)
    try:
        metadata = reopened.parts.metadata
    finally:
        reopened.close()
    assert metadata is not None
    assert metadata.title is None


# --- schema_lint reports what was actually checked ------------------------------


def _with_landscape(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every lowered document carry ``hp:pagePr@landscape=value``."""

    original = builder_core.Document.lower

    def lower(self: Document) -> HwpxDocument:
        document = original(self)
        section = document.oxml.sections[0]
        page_pr = section.element.find(".//{*}pagePr")
        assert page_pr is not None
        page_pr.set("landscape", value)
        section.mark_dirty()
        return document

    monkeypatch.setattr(builder_core.Document, "lower", lower)


def _document() -> Document:
    return Document(sections=[Section(page=PageSize.A4, children=[Paragraph(text="x")])])


def test_schema_lint_passes_only_a_schema_clean_document(tmp_path: Path) -> None:
    report = _document().save_to_path(tmp_path / "clean.hwpx")
    assert report.hard_gates["schema_lint"] == "pass"


def test_schema_lint_reports_an_out_of_schema_enum_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with_landscape("PORTRAIT", monkeypatch)
    report = _document().save_to_path(tmp_path / "bad.hwpx")

    assert report.hard_gates["schema_lint"] == "warning"
    assert report.hard_gates["document_errors"] == "pass"
    assert any("pagePr@landscape" in str(issue) for issue in report.validate_document.warnings)


def test_schema_lint_is_not_checked_without_a_full_schema_validator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # python-hwpx before 6.6 checks sections against a lax stub only.
    def stub_only(source: object) -> object:
        return validate_document(source, full_schema=False)  # type: ignore[arg-type]

    monkeypatch.setattr(builder_core, "validate_document", stub_only)
    _with_landscape("PORTRAIT", monkeypatch)
    report = _document().save_to_path(tmp_path / "unchecked.hwpx")

    assert report.hard_gates["schema_lint"] == "not_checked"


# --- keyed nodes map to saved paragraphs ------------------------------------------


def test_keyed_nodes_report_their_saved_paragraph(tmp_path: Path) -> None:
    path = tmp_path / "anchors.hwpx"
    report = Document(
        metadata=Metadata(title="T"),
        sections=[
            Section(
                children=[
                    Heading(level=1, text="제목"),
                    Paragraph(text="같은 문장", key="first"),
                    Paragraph(text="같은 문장"),
                    Paragraph(text="", key="blank"),
                    Table(header=["a"], rows=[["1"]], key="box"),
                    Paragraph(children=[Run("끝")], key="last"),
                ]
            )
        ],
    ).save_to_path(path)

    assert set(report.anchors) == {"first", "blank", "box", "last"}
    assert report.to_dict()["anchors"] == report.anchors
    reopened = HwpxDocument.open(path)
    try:
        paragraphs = reopened.sections[0].paragraphs

        def at(key: str) -> object:
            anchor = report.anchors[key]
            assert anchor["section"] == 0
            return paragraphs[anchor["paragraph"]]

        assert at("first").text == "같은 문장"
        assert report.anchors["first"]["paragraph"] + 1 < report.anchors["blank"]["paragraph"]
        assert at("blank").text == ""
        assert len(at("box").tables) == 1
        assert at("last").text == "끝"
    finally:
        reopened.close()


def test_anchors_account_for_a_native_toc_inserted_before_them(tmp_path: Path) -> None:
    path = tmp_path / "toc.hwpx"
    report = Document(
        sections=[
            Section(
                children=[
                    NativeToc(),
                    Heading(level=1, text="개요"),
                    Paragraph(text="뒤 문단", key="after"),
                ]
            )
        ],
    ).save_to_path(path)

    reopened = HwpxDocument.open(path)
    try:
        anchor = report.anchors["after"]
        assert reopened.sections[anchor["section"]].paragraphs[anchor["paragraph"]].text == "뒤 문단"
    finally:
        reopened.close()


def test_unkeyed_documents_report_no_anchors(tmp_path: Path) -> None:
    report = _document().save_to_path(tmp_path / "none.hwpx")
    assert report.anchors == {}


def test_duplicate_keys_are_rejected() -> None:
    document = Document(
        sections=[Section(children=[Paragraph(text="a", key="k"), Table(header=["x"], key="k")])]
    )
    with pytest.raises(ValueError, match="duplicate builder node key"):
        document.lower()
