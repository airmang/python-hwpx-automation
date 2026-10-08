"""Commands that change a paragraph's inline content drop that paragraph's line layout cache.

``hp:linesegarray`` records where each line starts in its paragraph's content. Moving a picture out of a
paragraph of three pictures left the cache's ``textpos`` 0, 8 and 16 behind for one picture, and Hancom
reported the saved file as damaged (python-hwpx-automation #167). Only the paragraphs a command changes lose
their cache; every other paragraph keeps the one Hancom wrote.
"""
from __future__ import annotations

import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from hwpx import HwpxDocument
from hwpx.oxml.namespaces import HP
from hwpx_automation.office.agent import HwpxAgentDocument, apply_document_commands

from .test_agent_commands import _batch, _record

IMAGE = (
    Path(__file__).parent
    / "fixtures/fuzz_regressions/visual_review_seed_000000_000999_screenshots/seed-000003-710dbd610d8d.png"
)


def _cache(paragraph: Any, *starts: int) -> None:
    for old in paragraph.element.findall(f"{HP}linesegarray"):
        paragraph.element.remove(old)
    array = paragraph.element.makeelement(f"{HP}linesegarray", {})
    for start in starts:
        array.append(array.makeelement(f"{HP}lineseg", {
            "textpos": str(start), "vertpos": "0", "vertsize": "1000", "textheight": "1000",
            "baseline": "850", "spacing": "600", "horzpos": "0", "horzsize": "42520", "flags": "393216",
        }))
    paragraph.element.append(array)


def _write(path: Path) -> None:
    """Paragraph 701 holds three pictures (cache 0, 8, 16) and a run of text, 702 and 703 are empty
    (cache 0), and 704 is text nothing touches (cache 0)."""

    with HwpxDocument.new() as document:
        first = document.sections[0].paragraphs[0]
        first.element.set("id", "701")
        image = document.media.add_image(IMAGE.read_bytes(), "png")
        for identity in ("801", "802", "803"):
            picture = first.add_picture(image, width=7200, height=3600)
            picture.element.set("id", identity)
            picture.element.set("instid", identity)
        first.add_run("글")
        _cache(first, 0, 8, 16)
        for identity in ("702", "703"):
            empty = document.add_paragraph("")
            empty.element.set("id", identity)
            _cache(empty, 0)
        kept = document.add_paragraph("그대로")
        kept.element.set("id", "704")
        _cache(kept, 0)
        first.section.mark_dirty()
        document.save_to_path(path)


def _caches(path: Path) -> dict[str, list[str]]:
    """Each paragraph id of the saved section and the ``textpos`` of its cached lines (absent: no cache)."""

    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("Contents/section0.xml"))
    caches = {}
    for paragraph in root.iter(f"{HP}p"):
        array = paragraph.find(f"{HP}linesegarray")
        if array is not None:
            caches[paragraph.get("id")] = [line.get("textpos") for line in array]
    return caches


def _run(source: Path, output: Path, commands: list[dict[str, Any]]) -> dict[str, list[str]]:
    result = apply_document_commands(_batch(source, output, commands))
    assert result.ok, result.to_dict()
    return _caches(output)


def test_the_fixture_carries_its_caches(tmp_path: Path) -> None:
    source = tmp_path / "input.hwpx"
    _write(source)
    assert _caches(source) == {"701": ["0", "8", "16"], "702": ["0"], "703": ["0"], "704": ["0"]}


def test_moving_pictures_out_drops_the_cache_of_both_paragraphs(tmp_path: Path) -> None:
    source, output = tmp_path / "input.hwpx", tmp_path / "output.hwpx"
    _write(source)
    with HwpxAgentDocument.open(source) as agent:
        first, second = _record(agent, "picture", "801"), _record(agent, "picture", "802")
        to_702, to_703 = _record(agent, "paragraph", "702"), _record(agent, "paragraph", "703")
    caches = _run(source, output, [
        {"commandId": "m1", "op": "move", "path": first.path, "parent": to_702.path},
        {"commandId": "m2", "op": "move", "path": second.path, "parent": to_703.path},
    ])
    assert caches == {"704": ["0"]}


def test_reordering_a_picture_inside_its_paragraph_drops_its_cache(tmp_path: Path) -> None:
    source, output = tmp_path / "input.hwpx", tmp_path / "output.hwpx"
    _write(source)
    with HwpxAgentDocument.open(source) as agent:
        last, home = _record(agent, "picture", "803"), _record(agent, "paragraph", "701")
    caches = _run(source, output, [
        {"commandId": "m", "op": "move", "path": last.path, "parent": home.path,
         "position": {"mode": "index", "index": 1}},
    ])
    assert caches == {"702": ["0"], "703": ["0"], "704": ["0"]}


def test_removing_or_copying_a_picture_drops_only_the_changed_paragraph_cache(tmp_path: Path) -> None:
    source = tmp_path / "input.hwpx"
    _write(source)
    with HwpxAgentDocument.open(source) as agent:
        picture, target = _record(agent, "picture", "801"), _record(agent, "paragraph", "702")
    removed = _run(source, tmp_path / "removed.hwpx", [
        {"commandId": "r", "op": "remove", "path": picture.path},
    ])
    assert removed == {"702": ["0"], "703": ["0"], "704": ["0"]}
    copied = _run(source, tmp_path / "copied.hwpx", [
        {"commandId": "c", "op": "copy", "path": picture.path, "parent": target.path},
    ])
    assert copied == {"701": ["0", "8", "16"], "703": ["0"], "704": ["0"]}


def test_removing_a_run_drops_the_cache_of_its_paragraph(tmp_path: Path) -> None:
    source = tmp_path / "input.hwpx"
    _write(source)
    with HwpxAgentDocument.open(source) as agent:
        run = next(record for record in agent.records if record.kind == "run" and record.summary.get("text") == "글")
    removed = _run(source, tmp_path / "removed.hwpx", [
        {"commandId": "r", "op": "remove", "path": run.path},
    ])
    assert removed == {"702": ["0"], "703": ["0"], "704": ["0"]}
