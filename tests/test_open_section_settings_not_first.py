# SPDX-License-Identifier: Apache-2.0
"""A document whose section settings sit in a later paragraph is opened, read and repaired by a save.

python-hwpx 6.x's ``section.insert_paragraphs(0, ...)`` left ``hp:secPr`` in the old first paragraph.
Hancom reads a section's settings only from its first paragraph, so python-hwpx reports the shape
(``section-properties-not-first``), and from 7.0.2 a save moves the settings back. The open gate here
refused such a file before any tool could read it or save it (reliability audit M13). It now admits
this one shape and keeps refusing every other open-safety error, with an error code and the repair
tool named.
"""
from __future__ import annotations

import io
import warnings
import zipfile
from pathlib import Path

import pytest
from lxml import etree

from hwpx import HwpxDocument
from hwpx._document import persistence
from hwpx.oxml._paragraph_text_edit import move_section_settings

from hwpx_automation import server
from hwpx_automation import storage as storage_module
from hwpx_automation.core.document import open_doc
from hwpx_automation.errors import HwpDocumentError
from hwpx_automation.runtime import _classified_error_payload
from hwpx_automation.storage import (
    LocalDocumentStorage,
    build_hwpx_open_safety_report,
    require_hwpx_editor_open_safe,
)

_HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
LEFT, TOP = 11339, 8504  # 40 mm, 30 mm: not the defaults (8504, 5668)
TEXTS = ["ALPHA synthetic one", "BETA synthetic two", "GAMMA synthetic three"]

#: python-hwpx 7.0.2 moves the settings on saving; 7.0.1 refuses the save.
core_moves_on_save = pytest.mark.skipif(
    not hasattr(persistence, "_move_section_properties_to_first"),
    reason="python-hwpx < 7.0.2 refuses to save this shape",
)


def _rewrite_section(data: bytes, change) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
        infos = {info.filename: info for info in archive.infolist()}
    root = etree.fromstring(parts["Contents/section0.xml"])
    change(root)
    parts["Contents/section0.xml"] = etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, payload in parts.items():
            archive.writestr(infos[name], payload)
    return out.getvalue()


def _good_bytes() -> bytes:
    doc = HwpxDocument.new()
    doc.add_paragraph(TEXTS[0])
    doc.page.set_margins(left=LEFT, top=TOP)
    doc.add_paragraph(TEXTS[1])
    doc.add_paragraph(TEXTS[2])
    try:
        return doc.to_bytes()
    finally:
        doc.close()


def _settings_to_second_paragraph(root) -> None:
    paragraphs = root.findall(f"{_HP}p")
    assert move_section_settings(paragraphs[0], paragraphs[1])


def _made_by_6x(path: Path) -> Path:
    """The shape 6.x left: ``hp:secPr`` in the section's second paragraph."""

    path.write_bytes(_rewrite_section(_good_bytes(), _settings_to_second_paragraph))
    return path


def _holders(path: Path) -> list[int]:
    doc = HwpxDocument.open(path)
    try:
        paragraphs = doc.sections[0].element.findall(f"{_HP}p")
        return [
            index
            for index, paragraph in enumerate(paragraphs)
            if paragraph.find(f"{_HP}run/{_HP}secPr") is not None
        ]
    finally:
        doc.close()


def _margins(path: Path) -> tuple[int, int]:
    doc = HwpxDocument.open(path)
    try:
        margins = doc.sections[0].properties.page_margins
        return margins.left, margins.top
    finally:
        doc.close()


def test_the_shape_is_still_reported_by_the_open_safety_report(tmp_path: Path) -> None:
    source = _made_by_6x(tmp_path / "made-by-6x.hwpx")

    report = build_hwpx_open_safety_report(source)

    assert report["ok"] is False
    assert report["summary"] == "package validation failed"
    assert report["validatePackage"]["errors"]
    assert all(
        "(section-properties-not-first)" in error for error in report["validatePackage"]["errors"]
    )
    assert report["reopen"]["ok"] is True


def test_the_open_gate_admits_the_shape(tmp_path: Path) -> None:
    source = _made_by_6x(tmp_path / "made-by-6x.hwpx")

    report = require_hwpx_editor_open_safe(source, role="test open")
    assert report["ok"] is False  # admitted, not called safe

    doc = open_doc(str(source))
    try:
        assert [paragraph.text for paragraph in doc.paragraphs][:3] == TEXTS
    finally:
        doc.close()

    storage = LocalDocumentStorage(base_directory=tmp_path, auto_backup=False)
    opened, resolved = storage.open_document(source.name)
    opened.close()
    assert resolved == source


def test_read_tools_read_the_document(tmp_path: Path) -> None:
    source = _made_by_6x(tmp_path / "made-by-6x.hwpx")
    before = source.read_bytes()

    text = server.get_document_text(str(source))
    assert all(line in text["text"] for line in TEXTS)
    info = server.get_document_info(str(source))
    assert info["paragraphs"] >= 3
    found = server.find_text(str(source), "BETA")
    assert found["total_matches"] == 1
    paragraph = server.get_paragraph_text(str(source), 1)
    assert TEXTS[1] in str(paragraph)

    assert source.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == [source.name]


@core_moves_on_save
def test_an_edit_tool_saves_and_the_settings_return_to_the_first_paragraph(tmp_path: Path) -> None:
    source = _made_by_6x(tmp_path / "made-by-6x.hwpx")
    original = source.read_bytes()
    assert _holders(source) == [1]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)  # core says what its save moved
        replaced = server.search_and_replace(str(source), "BETA", "DELTA")

    assert replaced["replaced_count"] == 1
    assert _holders(source) == [0]
    assert _margins(source) == (LEFT, TOP)
    assert build_hwpx_open_safety_report(source)["ok"] is True
    doc = open_doc(str(source))
    try:
        assert [p.text for p in doc.paragraphs][:3] == [TEXTS[0], "DELTA synthetic two", TEXTS[2]]
    finally:
        doc.close()
    # the original is kept beside it, as the file was
    assert (tmp_path / "made-by-6x.hwpx.bak").read_bytes() == original


@core_moves_on_save
def test_the_save_result_says_the_settings_moved(tmp_path: Path) -> None:
    source = _made_by_6x(tmp_path / "made-by-6x.hwpx")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        added = server.add_paragraph(str(source), "DELTA synthetic four")

    notes = added["verificationReport"]["visualComplete"]["warnings"]
    moved = [note for note in notes if "(section-properties-not-first)" in note]
    assert len(moved) == 1
    assert "section 0" in moved[0] and "first paragraph" in moved[0]

    # a document that never had the shape says nothing
    clean = tmp_path / "clean.hwpx"
    clean.write_bytes(_good_bytes())
    again = server.add_paragraph(str(clean), "DELTA synthetic four")
    assert not [
        note
        for note in again["verificationReport"]["visualComplete"]["warnings"]
        if "section-properties-not-first" in note
    ]


@core_moves_on_save
def test_undo_restores_the_file_as_it_was(tmp_path: Path) -> None:
    source = _made_by_6x(tmp_path / "made-by-6x.hwpx")
    original = source.read_bytes()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        server.search_and_replace(str(source), "BETA", "DELTA")
    assert source.read_bytes() != original

    server.undo_last_edit(str(source))
    assert source.read_bytes() == original


def _stale_line_cache(root) -> None:
    paragraph = root.findall(f"{_HP}p")[-1]  # plain text: the validator checks its cache
    for cache in paragraph.findall(f"{_HP}linesegarray"):
        paragraph.remove(cache)
    cache = etree.SubElement(paragraph, f"{_HP}linesegarray")
    etree.SubElement(cache, f"{_HP}lineseg", {"textpos": "4000"})


def _refusal(call) -> dict:
    with pytest.raises(Exception) as raised:
        call()
    return _classified_error_payload(raised.value)


def test_other_open_safety_errors_are_refused_with_a_code_and_the_repair_tool(tmp_path: Path) -> None:
    broken = tmp_path / "stale.hwpx"
    broken.write_bytes(_rewrite_section(_good_bytes(), _stale_line_cache))
    assert build_hwpx_open_safety_report(broken)["validatePackage"]["ok"] is False
    before = broken.read_bytes()

    with pytest.raises(HwpDocumentError) as refused:
        require_hwpx_editor_open_safe(broken, role="test open")
    assert refused.value.code == "DOCUMENT_OPEN_FAILED"
    assert "package validation failed" in str(refused.value)

    for call in (
        lambda: server.get_document_text(str(broken)),
        lambda: server.find_text(str(broken), "BETA"),
        lambda: server.search_and_replace(str(broken), "BETA", "DELTA"),
        lambda: server.add_paragraph(str(broken), "DELTA synthetic four"),
    ):
        payload = _refusal(call)
        assert payload["code"] == "DOCUMENT_OPEN_FAILED"
        assert "repair_hwpx" in payload["suggestion"]
        assert payload["details"]["failedChecks"] == ["validatePackage"]
        assert str(tmp_path) not in payload["message"]

    assert broken.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == [broken.name]


def test_the_shape_beside_another_error_is_still_refused(tmp_path: Path) -> None:
    def both(root) -> None:
        _settings_to_second_paragraph(root)
        _stale_line_cache(root)

    broken = tmp_path / "both.hwpx"
    broken.write_bytes(_rewrite_section(_good_bytes(), both))
    errors = build_hwpx_open_safety_report(broken)["validatePackage"]["errors"]
    assert any("(section-properties-not-first)" in error for error in errors)
    assert any("(section-properties-not-first)" not in error for error in errors)

    with pytest.raises(HwpDocumentError) as refused:
        open_doc(str(broken))
    assert refused.value.code == "DOCUMENT_OPEN_FAILED"


def test_a_file_that_does_not_reopen_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _made_by_6x(tmp_path / "made-by-6x.hwpx")

    def fail_reopen(_source):
        raise RuntimeError("cannot reopen")

    monkeypatch.setattr(storage_module, "open_document", fail_reopen)
    with pytest.raises(HwpDocumentError) as refused:
        require_hwpx_editor_open_safe(source, role="test open")
    assert refused.value.details["failedChecks"] == ["validatePackage", "reopen"]


def test_the_marker_is_the_one_python_hwpx_reports() -> None:
    from hwpx.tools import package_validator

    message = getattr(package_validator, "SECTION_PROPERTIES_NOT_FIRST_MESSAGE", None)
    if message is None:
        pytest.skip("python-hwpx < 7.0.2 has no named message")
    assert storage_module._SECTION_SETTINGS_NOT_FIRST_MARKER in message


def test_a_core_that_refuses_the_save_gives_a_save_failure_naming_the_repair() -> None:
    """python-hwpx 7.0.0 and 7.0.1 raise this from the save; it is not a bad tool argument."""

    refused = ValueError("section 0's settings (hp:secPr) are in its paragraph 1, not its first")
    refused.code = "section-properties-not-first"  # type: ignore[attr-defined]

    payload = _classified_error_payload(refused)

    assert payload["code"] == "DOCUMENT_SAVE_FAILED"
    assert payload["details"] == {"coreCode": "section-properties-not-first"}
    assert "repair_hwpx" in payload["message"]
