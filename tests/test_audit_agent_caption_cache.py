# SPDX-License-Identifier: Apache-2.0
"""Audit ENG-08: agent caption edits and paragraph copy/move leave no line cache.

A caption or paragraph keeps ``hp:linesegarray`` from the text Hancom measured.
Rewriting the text under that cache makes Hancom squeeze the new text into the
old lines, so the cache must go; ``"\n"`` must become ``hp:lineBreak``.
"""
from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path
from typing import Any

from hwpx import HwpxDocument
from lxml import etree

from hwpx_automation.office.agent import HwpxAgentDocument, apply_document_commands

_HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def _add_cache(paragraph_element: Any) -> None:
    cache = etree.SubElement(paragraph_element, _HP + "linesegarray")
    etree.SubElement(
        cache,
        _HP + "lineseg",
        {
            "textpos": "0", "vertpos": "0", "vertsize": "1000", "textheight": "1000",
            "baseline": "850", "spacing": "600", "horzpos": "0", "horzsize": "8504",
            "flags": "393216",
        },
    )


def _fixture(path: Path) -> None:
    doc = HwpxDocument.new()
    doc.paragraphs[0].runs[0].text = "첫 문단"
    long_paragraph = doc.add_paragraph("복사하고 옮길 문단입니다")
    _add_cache(long_paragraph.element)
    holder = doc.add_paragraph("")
    table = holder.add_table(1, 2)
    caption = table.set_caption("원래 캡션")
    _add_cache(caption.paragraphs[0].element)
    doc.add_paragraph("끝 문단")
    doc.save_to_path(str(path))
    doc.close()


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
        "verificationRequirements": [],
    }


def _section(path: Path) -> Any:
    with zipfile.ZipFile(io.BytesIO(path.read_bytes())) as archive:
        return etree.fromstring(archive.read("Contents/section0.xml"))


def _records(path: Path, kind: str) -> list[Any]:
    with HwpxAgentDocument.open(path) as agent:
        return [record for record in agent.records if record.kind == kind]


def _body_paragraphs(root: Any) -> list[Any]:
    return [child for child in root if child.tag == _HP + "p"]


def test_fixture_really_carries_the_caches(tmp_path: Path) -> None:
    source = tmp_path / "in.hwpx"
    _fixture(source)
    root = _section(source)
    caption = next(root.iter(_HP + "caption"))
    assert caption.find(f".//{_HP}linesegarray") is not None
    assert _body_paragraphs(root)[1].find(_HP + "linesegarray") is not None


def test_set_caption_drops_cache_and_writes_line_break(tmp_path: Path) -> None:
    source, output = tmp_path / "in.hwpx", tmp_path / "out.hwpx"
    _fixture(source)
    table = _records(source, "table")[0]

    result = apply_document_commands(
        _batch(source, output, [
            {"commandId": "c1", "op": "set", "path": table.path,
             "properties": {"caption": "새 캡션 첫 줄\n둘째 줄\t끝"}},
        ])
    )
    assert result.ok, result.to_dict()

    caption = next(_section(output).iter(_HP + "caption"))
    assert caption.find(f".//{_HP}linesegarray") is None
    texts = list(caption.iter(_HP + "t"))
    assert len(texts) == 1
    assert "\n" not in "".join(texts[0].itertext())
    assert [child.tag for child in texts[0]] == [_HP + "lineBreak", _HP + "tab"]
    doc = HwpxDocument.open(str(output))
    try:
        tables = [t for p in doc.paragraphs for t in p.tables]
        assert tables[0].caption.text == "새 캡션 첫 줄\n둘째 줄\t끝"
    finally:
        doc.close()


def test_add_table_with_caption_uses_engine_caption(tmp_path: Path) -> None:
    source, output = tmp_path / "in.hwpx", tmp_path / "out.hwpx"
    _fixture(source)
    first = _records(source, "paragraph")[0]
    result = apply_document_commands(
        _batch(source, output, [
            {"commandId": "t", "op": "add", "parent": first.path, "kind": "table",
             "properties": {"rowCount": 1, "columnCount": 2, "caption": "추가\n표"}},
        ])
    )
    assert result.ok, result.to_dict()
    captions = list(_section(output).iter(_HP + "caption"))
    assert len(captions) == 2
    new_caption = next(c for c in captions if "추가" in "".join(c.itertext()))
    assert new_caption.find(f".//{_HP}lineBreak") is not None
    assert new_caption.find(f".//{_HP}linesegarray") is None


def test_copy_and_move_paragraph_drop_the_copied_cache(tmp_path: Path) -> None:
    source, copied, moved = tmp_path / "in.hwpx", tmp_path / "copy.hwpx", tmp_path / "move.hwpx"
    _fixture(source)
    paragraphs = _records(source, "paragraph")
    target = next(r for r in paragraphs if "복사하고" in (r.summary.get("text") or ""))
    section = _records(source, "section")[0]

    result = apply_document_commands(
        _batch(source, copied, [
            {"commandId": "c1", "op": "copy", "path": target.path, "parent": section.path,
             "position": {"mode": "append"}},
        ])
    )
    assert result.ok, result.to_dict()
    body = _body_paragraphs(_section(copied))
    twins = [p for p in body if "복사하고" in "".join(p.itertext())]
    assert len(twins) == 2
    # The untouched source paragraph keeps the cache Hancom wrote; the copy has none.
    assert twins[0].find(_HP + "linesegarray") is not None
    assert twins[1].find(_HP + "linesegarray") is None

    result = apply_document_commands(
        _batch(source, moved, [
            {"commandId": "m1", "op": "move", "path": target.path, "parent": section.path,
             "position": {"mode": "append"}},
        ])
    )
    assert result.ok, result.to_dict()
    body = _body_paragraphs(_section(moved))
    only = [p for p in body if "복사하고" in "".join(p.itertext())]
    assert len(only) == 1 and only[0] is body[-1]
    assert only[0].find(_HP + "linesegarray") is None
