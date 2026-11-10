# SPDX-License-Identifier: Apache-2.0
"""Audit ENG-19: tabs, line breaks and control characters on the direct text paths."""
from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path
from typing import Any

import pytest
from hwpx import HwpxDocument
from lxml import etree

from hwpx_automation.office.agent import HwpxAgentDocument, apply_document_commands
from hwpx_automation.office.form_fill.split_run import fill_section_bytes

_HP_URI = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_HP = "{" + _HP_URI + "}"


def _batch(source: Path, output: Path, commands: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schemaVersion": "hwpx.agent-batch/v1",
        "input": {"filename": str(source)},
        "output": {"filename": str(output), "overwrite": True},
        "commands": commands,
        "expectedRevision": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
        "idempotencyKey": None,
        "dryRun": False,
        "quality": "transparent",
        "verificationRequirements": ["package", "reopen", "openSafety", "semanticDiff"],
    }


def _section(path: Path) -> Any:
    with zipfile.ZipFile(io.BytesIO(path.read_bytes())) as archive:
        return etree.fromstring(archive.read("Contents/section0.xml"))


@pytest.mark.parametrize(
    ("value", "marks"),
    [
        ("가나다\t라마바", ["tab"]),
        ("가나다\n라마바", ["lineBreak"]),
        ("가\t나\n다", ["tab", "lineBreak"]),
        ("가나다 라마바", []),
    ],
)
def test_agent_paragraph_text_with_tab_or_line_break_passes_verification(
    tmp_path: Path, value: str, marks: list[str]
) -> None:
    source, output = tmp_path / "in.hwpx", tmp_path / "out.hwpx"
    doc = HwpxDocument.new()
    doc.paragraphs[0].runs[0].text = "첫 문단"
    doc.add_paragraph("바꿀 문단")
    doc.save_to_path(str(source))
    doc.close()
    with HwpxAgentDocument.open(source) as agent:
        target = next(
            r for r in agent.records
            if r.kind == "paragraph" and "바꿀" in (r.summary.get("text") or "")
        )

    result = apply_document_commands(
        _batch(source, output, [
            {"commandId": "c1", "op": "set", "path": target.path, "properties": {"text": value}},
        ])
    )

    payload = result.to_dict()
    assert result.ok, payload
    assert payload["verificationReport"]["scopePreservation"]["ok"] is True
    paragraph = next(
        p for p in _section(output).iter(_HP + "p") if "가" in "".join(p.itertext())
    )
    found = [n.tag.rsplit("}", 1)[-1] for n in paragraph.iter() if n.tag in (_HP + "tab", _HP + "lineBreak")]
    assert found == marks
    assert "\t" not in "".join(paragraph.itertext()) and "\n" not in "".join(paragraph.itertext())
    reopened = HwpxDocument.open(str(output))
    try:
        assert reopened.paragraphs[1].text == value
    finally:
        reopened.close()


def _section_bytes(body: str) -> bytes:
    return (
        f'<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="{_HP_URI}">'
        f"{body}</hs:sec>"
    ).encode("utf-8")


def test_split_run_fill_drops_control_characters_instead_of_raising() -> None:
    section = _section_bytes(
        '<hp:p><hp:run charPrIDRef="1"><hp:t>이름: {{name}} 님</hp:t></hp:run></hp:p>'
    )
    filled, report = fill_section_bytes(section, {"{{name}}":"홍\x01길\x0b동"})
    assert report.replacements == 1
    text = etree.fromstring(filled).find(f".//{_HP}t")
    assert text.text == "이름: 홍길동 님"


def test_split_run_fill_writes_line_break_and_tab_elements() -> None:
    section = _section_bytes(
        '<hp:p><hp:run charPrIDRef="1"><hp:t>{{a}} / 주소: {{addr}} 끝</hp:t></hp:run>'
        "<hp:linesegarray/></hp:p>"
    )
    filled, report = fill_section_bytes(section, {"{{a}}": "갑", "{{addr}}":"서울\n종로\t1가"})
    assert report.replacements == 2
    root = etree.fromstring(filled)
    text = root.find(f".//{_HP}t")
    assert text.text == "갑 / 주소: 서울"
    assert [(c.tag.rsplit("}", 1)[-1], c.tail) for c in text] == [
        ("lineBreak", "종로"),
        ("tab", "1가 끝"),
    ]
    assert root.find(f".//{_HP}linesegarray") is None
