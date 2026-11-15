# SPDX-License-Identifier: Apache-2.0
"""``.hwp`` -> ``.hwpx`` conversion goes through python-hwpx's own HWP 5.0 reader.

The fixture is a file Hancom Office saved (see ``fixtures/hwp5/NOTICE.md``).
"""

from __future__ import annotations

import shutil
import subprocess
import warnings
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest
from hwpx.document import HwpxDocument

from hwpx_automation import hwp_converter
from hwpx_automation.hwp_converter import HwpConversionError, convert_hwp_to_hwpx
from hwpx_automation.hwpx_ops import HwpxOps

FIXTURE = Path(__file__).parent / "fixtures" / "hwp5" / "border_3d.hwp"
TEXT = "가나다라 ABC abc 123"


def _open(path: Path) -> HwpxDocument:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return HwpxDocument.open(path)


def _texts(document: HwpxDocument) -> list[str]:
    texts = [paragraph.text for paragraph in document.paragraphs]
    for paragraph in document.paragraphs:
        for table in paragraph.tables:
            texts.extend(cell.text for row in table.rows for cell in row.cells)
    return texts


def _tables(document: HwpxDocument) -> int:
    return sum(len(list(paragraph.tables)) for paragraph in document.paragraphs)


@pytest.fixture
def hwp_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "form.hwp"
    shutil.copy2(FIXTURE, target)
    return target


def test_conversion_keeps_text_and_tables_from_the_core_reader(hwp_source: Path) -> None:
    output = hwp_source.with_name("form.hwpx")

    result = convert_hwp_to_hwpx(str(hwp_source), str(output))

    original = _open(hwp_source)
    try:
        expected_tables = _tables(original)
        expected_texts = _texts(original)
    finally:
        original.close()
    assert result.success is True
    assert result.output_path == str(output.resolve())
    assert result.tables_converted == expected_tables
    assert result.open_safety["ok"] is True
    assert result.verification["openSafety"]["ok"] is True

    assert output.read_bytes()[:2] == b"PK"  # an HWPX package, not the OLE2 input
    converted = _open(output)
    try:
        assert any(TEXT in text for text in _texts(converted))
        assert _texts(converted) == expected_texts
        assert _tables(converted) == expected_tables
        assert converted.validate().ok
    finally:
        converted.close()


def test_conversion_does_not_run_external_programs(hwp_source: Path, monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("the converter must not start hwp5proc or any other program")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)

    result = convert_hwp_to_hwpx(str(hwp_source), str(hwp_source.with_name("out.hwpx")))

    assert result.success is True


def test_conversion_report_becomes_skipped_elements_and_warnings(
    hwp_source: Path, monkeypatch
) -> None:
    report = SimpleNamespace(
        unconverted=MappingProxyType({"track-changes": 1}),
        dropped=MappingProxyType({"range-tag-0": 3}),
    )
    real_open = HwpxDocument.open

    def open_with_report(source, *args, **kwargs):
        document = real_open(source, *args, **kwargs)
        monkeypatch.setattr(type(document), "conversion_report", property(lambda _self: report))
        return document

    monkeypatch.setattr(hwp_converter.HwpxDocument, "open", staticmethod(open_with_report))

    result = convert_hwp_to_hwpx(str(hwp_source), str(hwp_source.with_name("out.hwpx")))

    assert result.skipped_elements == ["track-changes (1)", "range-tag-0 (3)"]
    assert any("track-changes 1개" in item for item in result.warnings)
    assert any("range-tag-0 3개" in item for item in result.warnings)
    assert any(item.startswith("변환 제외 요소") for item in result.warnings)


def test_unreadable_hwp_is_a_conversion_error_and_writes_nothing(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "broken.hwp"
    source.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)
    output = tmp_path / "broken.hwpx"

    with pytest.raises(HwpConversionError, match="python-hwpx"):
        convert_hwp_to_hwpx(str(source), str(output))

    assert not output.exists()


def test_source_must_be_hwp(tmp_path) -> None:
    source = tmp_path / "x.hwpx"
    source.write_bytes(b"PK")
    with pytest.raises(HwpConversionError, match=".hwp"):
        convert_hwp_to_hwpx(str(source), str(tmp_path / "y.hwpx"))


def test_convert_hwp_to_hwpx_preserves_existing_output_when_open_safety_fails(
    hwp_source: Path,
    monkeypatch,
) -> None:
    output = hwp_source.with_name("existing.hwpx")
    HwpxDocument.new().save_to_path(output)
    original_output = output.read_bytes()
    monkeypatch.setattr(
        "hwpx_automation.storage.build_hwpx_open_safety_report",
        lambda path: {
            "ok": False,
            "summary": "forced conversion safety failure",
            "validatePackage": {
                "ok": False,
                "errors": ["forced conversion safety failure"],
                "warnings": [],
            },
            "validateDocument": {"ok": True, "errors": [], "warnings": []},
            "reopen": {"ok": True, "error": None},
        },
    )

    with pytest.raises(RuntimeError, match="open-safety"):
        convert_hwp_to_hwpx(str(hwp_source), str(output))

    assert output.read_bytes() == original_output


def test_hwp_ops_convert_hwp_to_hwpx_keeps_its_result_keys(hwp_source: Path) -> None:
    ops = HwpxOps(base_directory=hwp_source.parent)

    result = ops.convert_hwp_to_hwpx(hwp_source.name, "ops.hwpx")

    assert set(result) == {
        "success",
        "outputPath",
        "paragraphsConverted",
        "tablesConverted",
        "skippedElements",
        "warnings",
        "verification",
        "openSafety",
    }
    assert result["success"] is True
    assert result["openSafety"]["ok"] is True
    assert result["verification"]["openSafety"]["ok"] is True
    validation = ops.validate_structure("ops.hwpx")
    assert validation["ok"] is True
