# SPDX-License-Identifier: Apache-2.0
"""HWP 5.0 (``.hwp``) documents go through python-hwpx's own reader and writer.

The fixture is a file Hancom Office saved (see ``fixtures/hwp5/NOTICE.md``).
Saving keeps the input format unless the output path picks another extension.
"""

from __future__ import annotations

import shutil
import struct
import warnings
from pathlib import Path

import pytest

from hwpx_automation import server
from hwpx_automation.hwpx_ops import HwpxOperationError, HwpxOps
from hwpx_automation.ops_services import context as context_module
from hwpx_automation.runtime import _classified_error_payload
from hwpx_automation import storage as storage_module
from hwpx_automation.upstream import HwpxDocument, native_hwp5_supported

FIXTURE = Path(__file__).parent / "fixtures" / "hwp5" / "border_3d.hwp"
TEXT = "가나다라 ABC abc 123"
OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

native = pytest.mark.skipif(
    not native_hwp5_supported(), reason="python-hwpx < 6.6.0 cannot open .hwp"
)


@pytest.fixture
def hwp_path(tmp_path: Path) -> Path:
    target = tmp_path / "form.hwp"
    shutil.copy2(FIXTURE, target)
    return target


def _reopen_texts(path: Path) -> list[str]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        document = HwpxDocument.open(path)
    try:
        texts = [paragraph.text for paragraph in document.paragraphs]
        for paragraph in document.paragraphs:
            for table in paragraph.tables:
                texts.extend(cell.text for row in table.rows for cell in row.cells)
        return texts
    finally:
        document.close()


def _refusal(call) -> dict:
    with pytest.raises(Exception) as raised:
        call()
    return _classified_error_payload(raised.value)


@native
def test_mcp_tools_read_hwp_text_tables_and_conversion_report(hwp_path: Path) -> None:
    text = server.get_document_text(str(hwp_path))
    assert TEXT in text["text"]

    info = server.get_document_info(str(hwp_path))
    assert info["format"] == "hwp"
    assert info["tables"] == 1
    assert info["hwpConversion"] == {"unconverted": {}, "dropped": {}}

    table = server.get_table_text(str(hwp_path), table_index=0)
    assert (table["rows"], table["cols"]) == (1, 1)


@native
def test_hwp_edits_are_saved_back_as_hwp(hwp_path: Path) -> None:
    replaced = server.search_and_replace(str(hwp_path), "ABC", "XYZ")
    assert replaced["replaced_count"] == 1
    assert replaced["verificationReport"]["format"] == "hwp"
    assert replaced["openSafety"]["ok"] is True

    filled = server.set_table_cell_text(str(hwp_path), 0, 0, 0, "채움")
    assert filled["verificationReport"]["ok"] is True

    assert hwp_path.read_bytes()[:8] == OLE2_MAGIC
    texts = _reopen_texts(hwp_path)
    assert any("가나다라 XYZ abc" in text for text in texts)
    assert "채움" in texts


@native
def test_hwp_dry_run_writes_nothing(hwp_path: Path) -> None:
    before = hwp_path.read_bytes()
    result = server.search_and_replace(str(hwp_path), "ABC", "XYZ", dry_run=True)
    assert result["wouldSave"] is True
    assert result["verificationReport"]["format"] == "hwp"
    assert hwp_path.read_bytes() == before


@native
def test_copy_document_extension_picks_the_format(hwp_path: Path, tmp_path: Path) -> None:
    as_hwpx = tmp_path / "form.hwpx"
    server.copy_document(str(hwp_path), str(as_hwpx))
    assert as_hwpx.read_bytes()[:2] == b"PK"
    assert any(TEXT in text for text in _reopen_texts(as_hwpx))

    back = tmp_path / "back.hwp"
    server.copy_document(str(as_hwpx), str(back))
    assert back.read_bytes()[:8] == OLE2_MAGIC
    assert any(TEXT in text for text in _reopen_texts(back))


@native
def test_operations_service_reads_and_edits_hwp(hwp_path: Path) -> None:
    ops = HwpxOps(base_directory=hwp_path.parent, auto_backup=False)

    info = ops.open_info(hwp_path.name)
    assert info["meta"]["format"] == "hwp"
    assert info["meta"]["hwpConversion"] == {"unconverted": {}, "dropped": {}}
    assert TEXT in ops.read_text(hwp_path.name)["textChunk"]
    assert ops.find(hwp_path.name, "ABC")["matches"][0]["paragraphIndex"] == 1

    assert ops.replace_text_in_runs(hwp_path.name, "ABC", "XYZ")["replacedCount"] == 1
    assert hwp_path.read_bytes()[:8] == OLE2_MAGIC
    assert ops.find(hwp_path.name, "XYZ")["matches"]


@native
@pytest.mark.parametrize(
    ("flag", "hwp5_code"),
    [(2, "hwp5-password"), (4, "hwp5-distribution"), (16, "hwp5-drm")],
)
def test_protected_hwp_is_refused_clearly(
    tmp_path: Path, flag: int, hwp5_code: str
) -> None:
    data = bytearray(FIXTURE.read_bytes())
    header = data.find(b"HWP Document File")
    properties = struct.unpack_from("<I", data, header + 36)[0]
    struct.pack_into("<I", data, header + 36, properties | flag)
    protected = tmp_path / "protected.hwp"
    protected.write_bytes(bytes(data))

    payload = _refusal(lambda: server.get_document_text(str(protected)))
    assert payload["code"] == "HWP_ENCRYPTED_DOCUMENT"
    assert payload["details"] == {"hwp5Code": hwp5_code}
    assert payload["suggestion"]


@native
def test_content_hwp_cannot_hold_is_refused_before_writing(tmp_path: Path) -> None:
    from lxml import etree

    hp = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
    document = HwpxDocument.new()
    document.add_paragraph("양식 개체가 있는 문서")
    run = list(document.sections[0].element.iter(f"{hp}run"))[-1]
    combo = etree.SubElement(run, f"{hp}comboBox")
    for value in ("가", "나"):  # an HWP combo box keeps one value, not a list
        etree.SubElement(combo, f"{hp}listItem", displayText=value, value=value)
    document.sections[0].mark_dirty()
    source = tmp_path / "combo.hwpx"
    document.save_to_path(source)

    target = tmp_path / "combo.hwp"
    payload = _refusal(lambda: server.copy_document(str(source), str(target)))
    assert payload["code"] == "HWP_WRITE_UNSUPPORTED"
    assert payload["details"] == {"hwp5Code": "hwp5-write-unsupported"}
    assert ".hwpx" in payload["suggestion"]
    assert not target.exists()


@native
def test_byte_preserving_editors_refuse_hwp_with_a_route(hwp_path: Path) -> None:
    before = hwp_path.read_bytes()
    table_ops = _refusal(
        lambda: server.apply_table_ops(
            str(hwp_path),
            [{"op": "fill_cell", "table_index": 0, "row": 0, "col": 0, "text": "칸"}],
        )
    )
    assert table_ops["code"] == "HWPX_PACKAGE_REQUIRED"
    assert "copy_document" in table_ops["suggestion"]

    plan = {
        "schemaVersion": "hwpx.mixed-form-plan/v1",
        "source": str(hwp_path),
        "output": str(hwp_path.with_name("filled.hwp")),
        "expectedRevision": None,
        "idempotencyKey": None,
        "dryRun": True,
        "overwrite": True,
        "quality": "transparent",
        "verificationRequirements": ["package"],
        "operations": [
            {
                "operationId": "body",
                "target": {
                    "kind": "bodyAnchor",
                    "sectionPath": "/section[1]",
                    "anchor": "ABC",
                    "expectedCount": 1,
                },
                "value": "XYZ",
            }
        ],
    }
    mixed = _refusal(lambda: server.analyze_form_fill(plan=plan))
    assert mixed["code"] == "HWPX_PACKAGE_REQUIRED"
    assert hwp_path.read_bytes() == before


def test_core_without_hwp_support_is_named_not_a_missing_tool(
    hwp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(storage_module, "native_hwp5_supported", lambda: False)
    monkeypatch.setattr(context_module, "native_hwp5_supported", lambda: False)

    payload = _refusal(lambda: server.get_document_text(str(hwp_path)))
    assert payload["code"] == "READ_ONLY_HWP_DOCUMENT"
    assert "6.6.0" in payload["suggestion"]

    ops = HwpxOps(base_directory=hwp_path.parent, auto_backup=False)
    with pytest.raises(HwpxOperationError) as refused:
        ops.replace_text_in_runs(hwp_path.name, "ABC", "XYZ")
    assert refused.value.code == "READ_ONLY_HWP_DOCUMENT"
    assert "convert_hwp_to_hwpx" not in str(refused.value)
