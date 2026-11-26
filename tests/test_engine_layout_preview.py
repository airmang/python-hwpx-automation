"""Exercise engine page placement through the HTML preview entry point."""

import io
import re
from zipfile import ZipFile

import pytest
from lxml import etree

from hwpx import HwpxDocument, experimental
from hwpx_automation.preview import render_layout_preview

HH = "{http://www.hancom.co.kr/hwpml/2011/head}"


@pytest.mark.parametrize("mode", ["pages", "long"])
def test_the_preview_uses_engine_pages_and_text_ranges(mode: str) -> None:
    estimate_layout = getattr(experimental, "estimate_layout", None)
    if estimate_layout is None:
        pytest.skip("needs the core placement API")
    document = HwpxDocument.new()
    document.add_paragraph("엔진이 끊는 여러 줄의 문장 🙂 " * 400)
    payload = document.to_bytes()
    layout = estimate_layout(payload)

    preview = render_layout_preview(payload, mode=mode)

    assert len(preview.pages) == layout.estimate.pages > 1
    assert preview.fidelity_tier == "engine-estimated-pagination"
    for index, fragment in enumerate(preview.page_fragments):
        expected = [
            (line.text_start, line.text_end)
            for paragraph in layout.paragraphs
            for line in paragraph.lines if line.position.page == index and not line.hidden
        ]
        actual = re.findall(r'data-text-start="(\d+)" data-text-end="(\d+)"', fragment)
        assert [(int(start), int(end)) for start, end in actual] == expected
    assert "white-space: pre;" in preview.html
    assert not preview.limitations


@pytest.mark.parametrize("mode", ["pages", "long"])
def test_declined_estimate_keeps_legacy_page_fragments(mode: str, monkeypatch) -> None:
    if not hasattr(experimental, "estimate_layout"):
        pytest.skip("needs the core placement API")
    document = HwpxDocument.new()
    document.add_paragraph("첫 페이지")
    document.add_paragraph("다음 페이지").element.set("pageBreak", "1")
    output = io.BytesIO()
    with ZipFile(io.BytesIO(document.to_bytes())) as source, ZipFile(output, "w") as target:
        for member in source.namelist():
            data = source.read(member)
            if member == "Contents/header.xml":
                header = etree.fromstring(data)
                compatible = header.find(f"{HH}compatibleDocument")
                if compatible is None:
                    compatible = etree.SubElement(header, f"{HH}compatibleDocument")
                compatible.set("targetProgram", "MS_WORD")
                data = etree.tostring(header)
            target.writestr(member, data)
    payload = output.getvalue()

    preview = render_layout_preview(payload, mode=mode)
    monkeypatch.setattr(experimental, "estimate_layout", None)
    legacy = render_layout_preview(payload, mode=mode)

    assert preview.fidelity_tier == "text-approx-pagination"
    assert preview.pages == legacy.pages
    assert preview.page_fragments == legacy.page_fragments
    assert any("MS Word" in warning for warning in preview.warnings)


def test_table_without_row_placement_is_reported() -> None:
    estimate_layout = getattr(experimental, "estimate_layout", None)
    if estimate_layout is None:
        pytest.skip("needs the core placement API")
    document = HwpxDocument.new()
    table = document.add_paragraph("").add_table(3, 2)
    table.cell(0, 0).text = "표 내용"
    payload = document.to_bytes()

    preview = render_layout_preview(payload)

    assert len(preview.pages) == estimate_layout(payload).estimate.pages
    assert preview.fidelity_tier == "partial-engine-estimated-pagination"
    assert "표 내용" in preview.html
    assert {"kind": "table", "reason": "row and cell placement is unavailable", "count": 1} in (
        preview.as_dict()["limitations"]
    )
