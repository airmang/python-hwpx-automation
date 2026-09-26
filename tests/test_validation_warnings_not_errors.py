"""python-hwpx's validation warnings are reported, but only its errors fail a document."""
from __future__ import annotations

from hwpx.document import HwpxDocument
from hwpx.tools.validator import ValidationIssue, ValidationReport

from hwpx_automation import form_fill
from hwpx_automation.hwpx_ops import HwpxOps
from hwpx_automation.ops_services import package_validation


def _report(*severities: str) -> ValidationReport:
    return ValidationReport(
        validated_parts=("Contents/section0.xml",),
        issues=tuple(
            ValidationIssue("Contents/section0.xml", f"issue {index}", severity=severity)
            for index, severity in enumerate(severities)
        ),
    )


def _document(tmp_path):
    path = tmp_path / "doc.hwpx"
    document = HwpxDocument.new()
    document.add_paragraph("본문")
    document.save_to_path(path)
    return path


def test_validate_structure_passes_a_document_with_only_warnings(tmp_path, monkeypatch) -> None:
    path = _document(tmp_path)
    monkeypatch.setattr(package_validation, "validate_document_path", lambda _path: _report("warning"))

    result = HwpxOps(base_directory=tmp_path).validate_structure(path.name)

    assert result["ok"] is True
    assert result["issues"] == [
        {"part": "Contents/section0.xml", "message": "issue 0", "severity": "warning"}
    ]


def test_validate_structure_fails_on_an_error(tmp_path, monkeypatch) -> None:
    path = _document(tmp_path)
    monkeypatch.setattr(package_validation, "validate_document_path", lambda _path: _report("warning", "error"))

    result = HwpxOps(base_directory=tmp_path).validate_structure(path.name)

    assert result["ok"] is False
    assert [issue["severity"] for issue in result["issues"]] == ["warning", "error"]


def test_form_fill_validation_does_not_block_on_a_warning(tmp_path, monkeypatch) -> None:
    path = _document(tmp_path)
    monkeypatch.setattr(form_fill, "validate_document_path", lambda _path: _report("warning"))

    validation = form_fill._runtime_validation(str(path))

    assert validation["validate_structure"]["ok"] is True
    assert validation["validate_structure"]["issues"][0]["severity"] == "warning"
    assert validation["validate_document"]["ok"] is True
    assert validation["validate_document"]["issues"][0]["level"] == "warning"


def test_form_fill_validation_blocks_on_an_error(tmp_path, monkeypatch) -> None:
    path = _document(tmp_path)
    monkeypatch.setattr(form_fill, "validate_document_path", lambda _path: _report("error"))

    validation = form_fill._runtime_validation(str(path))

    assert validation["validate_structure"]["ok"] is False
    assert validation["validate_document"]["issues"][0]["level"] == "error"
