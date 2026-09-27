from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import pytest

import hwpx_automation.server as server
import hwpx_automation.form_fill as form_fill_module
from hwpx_automation.core.document import open_doc, save_doc
from hwpx_automation.fastmcp_adapter import snapshot_runtime_tools
from hwpx.tools.package_validator import validate_package
from hwpx.tools.validator import validate_document


HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def _append(parent: ET.Element, tag: str, attrs: dict[str, str] | None = None):
    child = parent.makeelement(tag, attrs or {})
    parent.append(child)
    return child


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_template(path: Path, *, duplicate: bool = False) -> None:
    server.create_document(str(path))
    server.add_heading(str(path), "교과협의회 회의록", level=1)
    server.add_table(
        str(path),
        3,
        2,
        [["일시", ""], ["장소", ""], ["참석자", ""]],
    )
    if duplicate:
        server.add_heading(str(path), "후속 회의", level=2)
        server.add_table(str(path), 1, 2, [["일시", ""]])


def _add_click_here_field(
    path: Path,
    *,
    name: str = "일시",
    prompt: str = "회의 일시",
    value: str = "입력하세요",
) -> None:
    doc = open_doc(str(path))
    paragraph = doc.add_paragraph("", include_run=False)
    p = paragraph.element
    begin_run = _append(p, f"{HP}run", {"charPrIDRef": "0"})
    ctrl = _append(begin_run, f"{HP}ctrl", {"type": "FORM", "id": f"ctrl-{name}"})
    field_begin = _append(
        ctrl,
        f"{HP}fieldBegin",
        {
            "id": f"field-{name}",
            "fieldid": f"field-{name}",
            "type": "CLICK_HERE",
            "name": name,
            "prompt": prompt,
        },
    )
    parameters = _append(field_begin, f"{HP}parameters", {"count": "2"})
    _append(parameters, f"{HP}stringParam", {"name": "FieldName"}).text = name
    _append(parameters, f"{HP}stringParam", {"name": "Instruction"}).text = prompt
    text_run = _append(p, f"{HP}run", {"charPrIDRef": "0"})
    _append(text_run, f"{HP}t").text = value
    end_run = _append(p, f"{HP}run", {"charPrIDRef": "0"})
    end_ctrl = _append(end_run, f"{HP}ctrl")
    _append(end_ctrl, f"{HP}fieldEnd", {"beginIDRef": f"field-{name}", "fieldid": f"field-{name}"})
    paragraph.section.mark_dirty()
    save_doc(doc, str(path))


def _structured_input() -> dict:
    return {
        "schemaVersion": "hwpx.formfill.v1",
        "source": {"type": "structured"},
        "fields": [
            {"key": "meeting.date", "label": "일시", "value": "2026-05-05 10:00"},
            {"key": "meeting.place", "label": "장소", "value": "AI실"},
            {"key": "meeting.attendees", "label": "참석자", "value": "김교사, 이교사"},
        ],
    }


def _write_minimal_docx(path: Path, rows: list[tuple[str, str]]) -> None:
    row_xml = []
    for label, value in rows:
        row_xml.append(
            "<w:tr>"
            f"<w:tc><w:p><w:r><w:t>{escape(label)}</w:t></w:r></w:p></w:tc>"
            f"<w:tc><w:p><w:r><w:t>{escape(value)}</w:t></w:r></w:p></w:tc>"
            "</w:tr>"
        )
    document_xml = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>"
        "<w:body><w:tbl>" + "".join(row_xml) + "</w:tbl></w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'/>")
        archive.writestr("word/document.xml", document_xml)


def test_form_fill_tools_are_exposed() -> None:
    names = set(snapshot_runtime_tools(server.mcp))

    assert {"list_form_fields", "fill_form_field", "analyze_form_fill", "apply_form_fill"}.issubset(names)


def test_list_and_fill_native_form_field_returns_open_safety(tmp_path: Path) -> None:
    source = tmp_path / "native-form.hwpx"
    server.create_document(str(source))
    _add_click_here_field(source, name="장소", prompt="회의 장소", value="미정")

    fields = server.list_form_fields(str(source))

    assert fields["fieldCount"] == 1
    assert fields["fields"][0]["name"] == "장소"
    assert fields["fields"][0]["prompt"] == "회의 장소"
    assert fields["fields"][0]["current_value"] == "미정"

    result = server.fill_form_field(str(source), "AI실", name="장소")

    assert result["field"]["current_value"] == "AI실"
    assert result["style_preserved"] is True
    assert result["openSafety"]["ok"] is True
    assert server.list_form_fields(str(source))["fields"][0]["current_value"] == "AI실"


def test_analyze_form_fill_prefers_native_form_fields(tmp_path: Path) -> None:
    source = tmp_path / "native-analysis.hwpx"
    destination = tmp_path / "native-filled.hwpx"
    server.create_document(str(source))
    _add_click_here_field(source, name="일시", prompt="회의 일시", value="입력하세요")

    analysis = server.analyze_form_fill(
        str(source),
        input_json={
            "schemaVersion": "hwpx.formfill.v1",
            "fields": [{"key": "meeting.date", "label": "일시", "value": "2026-06-11"}],
        },
        destination_filename=str(destination),
    )

    assert analysis["formFields"]["available"] is True
    assert analysis["resolved_count"] == 1
    mapping = analysis["mappings"]["resolved"][0]
    assert mapping["kind"] == "form-field"
    assert mapping["confidenceGrade"] == "label-exact"

    result = server.apply_form_fill(analysis=analysis, confirm=True)

    assert result["handoff_status"] == "ready"
    assert result["validation"]["openSafety"]["ok"] is True
    assert result["touched"][0]["kind"] == "form-field"
    assert server.list_form_fields(str(destination))["fields"][0]["current_value"] == "2026-06-11"


def test_analyze_form_fill_reports_table_label_fallback_without_form_fields(tmp_path: Path) -> None:
    source = tmp_path / "table-template.hwpx"
    destination = tmp_path / "table-filled.hwpx"
    _build_template(source)

    analysis = server.analyze_form_fill(
        str(source),
        input_json=_structured_input(),
        destination_filename=str(destination),
    )

    assert analysis["formFields"]["available"] is False
    assert analysis["formFields"]["fallback"] == "table-label"
    assert {item["confidenceGrade"] for item in analysis["mappings"]["resolved"]} == {"label-exact"}


def test_analyze_form_fill_marks_fuzzy_label_confidence(tmp_path: Path) -> None:
    source = tmp_path / "fuzzy-template.hwpx"
    server.create_document(str(source))
    server.add_table(str(source), 1, 2, [["참석자명", ""]])

    analysis = server.analyze_form_fill(
        str(source),
        input_json={
            "schemaVersion": "hwpx.formfill.v1",
            "fields": [{"key": "attendees", "label": "참석자", "value": "김교사"}],
        },
    )

    assert analysis["resolved_count"] == 1
    mapping = analysis["mappings"]["resolved"][0]
    assert mapping["method"] == "label-path-fuzzy"
    assert mapping["confidenceGrade"] == "label-fuzzy"


def test_analyze_form_fill_is_non_mutating_and_apply_preserves_source(tmp_path: Path) -> None:
    source = tmp_path / "meeting-template.hwpx"
    destination = tmp_path / "meeting-filled.hwpx"
    _build_template(source)
    source_hash_before = _sha256(source)
    source_mtime_before = source.stat().st_mtime_ns

    analysis = server.analyze_form_fill(
        str(source),
        input_json=_structured_input(),
        destination_filename=str(destination),
    )

    assert analysis["mutated"] is False
    assert analysis["source"]["unchanged_after_analysis"] is True
    assert analysis["resolved_count"] == 3
    assert analysis["unresolved_count"] == 0
    assert not destination.exists(), "analysis must not copy or fill the destination"
    assert _sha256(source) == source_hash_before

    result = server.apply_form_fill(analysis=analysis, confirm=True)

    assert result["handoff_status"] == "ready"
    assert result["source"]["preserved"] is True
    assert result["source"]["sha256_before"] == source_hash_before
    assert result["source"]["mtime_ns_before"] == source_mtime_before
    assert destination.exists()
    assert result["destination"]["changed"] is True
    assert result["validation"]["validate_structure"]["ok"] is True
    assert result["validation"]["validate_package"]["ok"] is True
    assert result["validation"]["validate_document"]["ok"] is True
    assert result["validation"]["openSafety"]["ok"] is True
    assert result["repair"]["openSafety"]["ok"] is True
    assert validate_package(destination).ok
    assert validate_document(destination).ok
    assert _sha256(source) == source_hash_before
    assert source.stat().st_mtime_ns == source_mtime_before

    filled = server.get_table_text(str(destination), 0)["data"]
    assert filled == [
        ["일시", "2026-05-05 10:00"],
        ["장소", "AI실"],
        ["참석자", "김교사, 이교사"],
    ]
    assert all(item["style_preserved"] for item in result["applied"])
    assert {item["text"] for item in result["touched"]} >= {"2026-05-05 10:00", "AI실", "김교사, 이교사"}


def test_apply_form_fill_preserves_existing_destination_when_validation_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "meeting-template.hwpx"
    destination = tmp_path / "meeting-filled.hwpx"
    _build_template(source)
    _build_template(destination)
    destination_hash_before = _sha256(destination)

    analysis = server.analyze_form_fill(
        str(source),
        input_json=_structured_input(),
        destination_filename=str(destination),
    )

    def blocked_validation(path: str) -> dict:
        return {
            "validate_structure": {"ok": True},
            "validate_package": {"ok": True},
            "validate_document": {"ok": True},
            "openSafety": {"ok": False, "summary": f"forced failure for {path}"},
        }

    monkeypatch.setattr(form_fill_module, "_runtime_validation", blocked_validation)

    result = server.apply_form_fill(analysis=analysis, confirm=True)

    assert result["handoff_status"] == "blocked"
    assert result["persisted"] is False
    assert _sha256(destination) == destination_hash_before
    assert not list(tmp_path.glob(f".{destination.stem}.*"))


def test_apply_form_fill_preserves_existing_destination_when_save_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "meeting-template.hwpx"
    destination = tmp_path / "meeting-filled.hwpx"
    _build_template(source)
    _build_template(destination)
    destination_hash_before = _sha256(destination)

    analysis = server.analyze_form_fill(
        str(source),
        input_json=_structured_input(),
        destination_filename=str(destination),
    )

    def fail_save(*args: object, **kwargs: object) -> None:
        raise RuntimeError("forced save failure")

    monkeypatch.setattr(form_fill_module, "_save_form_fill_document", fail_save)

    with pytest.raises(RuntimeError, match="forced save failure"):
        server.apply_form_fill(analysis=analysis, confirm=True)

    assert _sha256(destination) == destination_hash_before
    assert not list(tmp_path.glob(f".{destination.stem}.*"))


def test_duplicate_label_analysis_blocks_apply_until_explicit_coordinate(tmp_path: Path) -> None:
    source = tmp_path / "duplicate-template.hwpx"
    destination = tmp_path / "duplicate-filled.hwpx"
    _build_template(source, duplicate=True)

    ambiguous = server.analyze_form_fill(
        str(source),
        input_json={
            "schemaVersion": "hwpx.formfill.v1",
            "fields": [{"key": "date", "label": "일시", "value": "2026-05-05"}],
        },
        destination_filename=str(destination),
    )

    assert ambiguous["resolved_count"] == 0
    assert ambiguous["unresolved_count"] == 1
    assert ambiguous["mappings"]["unresolved"][0]["reason"] == "ambiguous label"
    assert ambiguous["mappings"]["unresolved"][0]["candidate_count"] == 2

    blocked = server.apply_form_fill(analysis=ambiguous, confirm=True)
    assert blocked["handoff_status"] == "blocked"
    assert not destination.exists()

    explicit = server.analyze_form_fill(
        str(source),
        input_json={
            "schemaVersion": "hwpx.formfill.v1",
            "fields": [
                {
                    "key": "date",
                    "label": "일시",
                    "value": "2026-05-05",
                    "target": {"kind": "cell", "table_index": 1, "row": 0, "col": 1},
                }
            ],
        },
        destination_filename=str(destination),
    )
    result = server.apply_form_fill(analysis=explicit, confirm=True)

    assert result["handoff_status"] == "ready"
    assert server.get_table_text(str(destination), 1)["data"][0][1] == "2026-05-05"
    assert server.get_table_text(str(destination), 0)["data"][0][1] == ""


def test_docx_origin_normalizes_to_same_fill_result_as_structured_json(tmp_path: Path) -> None:
    source = tmp_path / "docx-template.hwpx"
    from_json = tmp_path / "from-json.hwpx"
    from_docx = tmp_path / "from-docx.hwpx"
    docx = tmp_path / "meeting-input.docx"
    _build_template(source)
    _write_minimal_docx(
        docx,
        [("일시", "2026-05-05 10:00"), ("장소", "AI실"), ("참석자", "김교사, 이교사")],
    )

    json_analysis = server.analyze_form_fill(
        str(source),
        input_json=_structured_input(),
        destination_filename=str(from_json),
    )
    docx_analysis = server.analyze_form_fill(
        str(source),
        input_docx=str(docx),
        destination_filename=str(from_docx),
    )

    assert docx_analysis["canonicalInput"]["source"]["type"] == "docx"
    assert docx_analysis["resolved_count"] == json_analysis["resolved_count"] == 3

    json_result = server.apply_form_fill(analysis=json_analysis, confirm=True)
    docx_result = server.apply_form_fill(analysis=docx_analysis, confirm=True)

    assert json_result["handoff_status"] == "ready"
    assert docx_result["handoff_status"] == "ready"
    assert server.get_table_text(str(from_json), 0)["data"] == server.get_table_text(str(from_docx), 0)["data"]


def test_paragraph_placeholder_fill_preserves_paragraph_style(tmp_path: Path) -> None:
    source = tmp_path / "placeholder-template.hwpx"
    destination = tmp_path / "placeholder-filled.hwpx"
    _build_template(source)
    placeholder_index = server.add_paragraph(str(source), "안건: {{agenda_1}}")["paragraph_index"]
    doc = open_doc(str(source))
    ET.SubElement(doc.paragraphs[placeholder_index].element, f"{HP}lineSegArray")
    save_doc(doc, str(source))
    source_hash_before = _sha256(source)

    analysis = server.analyze_form_fill(
        str(source),
        input_json={
            "schemaVersion": "hwpx.formfill.v1",
            "source": {"type": "structured"},
            "paragraphs": [
                {
                    "key": "agenda.1",
                    "text": "AI 활용 수업 설계",
                    "target": {"kind": "placeholder", "token": "{{agenda_1}}"},
                    "stylePolicy": "preserve-placeholder",
                }
            ],
        },
        destination_filename=str(destination),
    )
    result = server.apply_form_fill(analysis=analysis, confirm=True)

    assert result["handoff_status"] == "ready"
    assert result["source"]["preserved"] is True
    assert _sha256(source) == source_hash_before
    assert result["applied"][0]["replaced_count"] == 1
    assert result["applied"][0]["style_preserved"] is True
    assert result["touched"][0]["kind"] == "placeholder"
    assert result["touched"][0]["paragraph_index"] == placeholder_index
    assert server.get_paragraph_text(str(destination), placeholder_index)["text"] == "안건: AI 활용 수업 설계"
    filled = open_doc(str(destination))
    assert filled.paragraphs[placeholder_index].element.find(f"{HP}lineSegArray") is None


def test_existing_sample_hwpx_safe_coordinate_fill_smoke(tmp_path: Path) -> None:
    source = Path("tests/sample.hwpx")
    destination = tmp_path / "sample-filled.hwpx"
    source_hash_before = _sha256(source)
    source_mtime_before = source.stat().st_mtime_ns

    analysis = server.analyze_form_fill(
        str(source),
        input_json={
            "schemaVersion": "hwpx.formfill.v1",
            "source": {"type": "structured"},
            "fields": [
                {
                    "key": "sample.a2",
                    "label": "A2",
                    "value": "샘플 회귀 검증",
                    "target": {"kind": "cell", "table_index": 0, "row": 0, "col": 1},
                }
            ],
        },
        destination_filename=str(destination),
    )
    result = server.apply_form_fill(analysis=analysis, confirm=True)

    assert result["handoff_status"] == "ready"
    assert result["source"]["preserved"] is True
    assert _sha256(source) == source_hash_before
    assert source.stat().st_mtime_ns == source_mtime_before
    assert result["validation"]["validate_structure"]["ok"] is True
    assert result["validation"]["openSafety"]["ok"] is True
    assert result["repair"]["openSafety"]["ok"] is True
    assert validate_package(destination).ok
    assert validate_document(destination).ok
    assert server.get_table_text(str(destination), 0)["data"][0][1] == "샘플 회귀 검증"


def test_invalid_docx_returns_structured_recovery_hint(tmp_path: Path) -> None:
    source = tmp_path / "template.hwpx"
    bad_docx = tmp_path / "bad.docx"
    _build_template(source)
    bad_docx.write_text("not a zip", encoding="utf-8")

    with pytest.raises(ValueError, match="provide input_json"):
        server.analyze_form_fill(str(source), input_docx=str(bad_docx))
