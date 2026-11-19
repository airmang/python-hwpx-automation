# SPDX-License-Identifier: Apache-2.0
"""Same input, same request, same document (owner 18차): the ids python-hwpx mints on the way come
from the input file's sha256 (a path that rewrites a file) or from the request (a path that makes a
new one). The save time (``content.hpf`` CreatedDate/ModifiedDate) is the real time (owner 23차,
``test_save_dates.py``), so it is masked and documents are compared part by part; the command path
keeps the input's entries but its save dates and is compared in
``agent_runtime_parity/test_agent_command_v2.py``."""

from __future__ import annotations

import io
import re
import shutil
import zipfile
from pathlib import Path

from hwpx import HwpxDocument

from hwpx_automation.hwpx_ops import HwpxOps
from hwpx_automation.mail_merge import merge_template_rows
from hwpx_automation.markdown import from_markdown
from hwpx_automation.office.authoring import create_document_from_plan
from hwpx_automation.upstream import content_seed, request_seed, source_seed


_STAMP = re.compile(rb"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")


#: A memo carries the time it was written twice: ``CreateDateTime`` and, as two numbers, in its command.
_MEMO_TIME = re.compile(rb"(MEMO/\d+/\d+/)\d+/\d+/")
_MEMO_STAMP = re.compile(rb'(name="CreateDateTime">)[^<]*')


def _masked(name: str, part: bytes) -> bytes:
    """*part* without the times that follow the clock: the save dates of ``content.hpf`` and a memo's
    writing time. Two documents made a second apart differ in nothing else (the test compared them raw
    and failed whenever the clock ticked between the two, as on CI)."""

    if name.endswith("content.hpf"):
        return _STAMP.sub(b"<time>", part)
    return _MEMO_STAMP.sub(rb"\1<time>", _MEMO_TIME.sub(rb"\1<time>/", part))


def _parts(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: _masked(name, archive.read(name)) for name in archive.namelist()}


def _source(path: Path, text: str = "소풍 안내 {{이름}}") -> None:
    with HwpxDocument.new() as document:
        document.sections[0].paragraphs[0].text = text
        document.add_paragraph("둘째 문단")
        document.save(path)


def test_seeds_follow_the_bytes_and_the_request(tmp_path: Path) -> None:
    path = tmp_path / "a.hwpx"
    _source(path)
    data = path.read_bytes()
    assert source_seed(path) == source_seed(data) == source_seed(io.BytesIO(data)) == content_seed(data)
    assert content_seed(data) == int(__import__("hashlib").sha256(data).hexdigest()[:8], 16)
    assert request_seed({"b": 1, "a": [1, 2]}) == request_seed({"a": [1, 2], "b": 1})
    assert request_seed("가") != request_seed("나")


def test_rewriting_a_file_twice_writes_the_same_parts(tmp_path: Path) -> None:
    _source(tmp_path / "source.hwpx")
    results = []
    for run in range(2):
        target = tmp_path / f"run{run}" / "doc.hwpx"
        target.parent.mkdir()
        shutil.copyfile(tmp_path / "source.hwpx", target)
        ops = HwpxOps(base_directory=target.parent)
        ops.add_table(str(target), 2, 2)
        ops.add_paragraph(str(target), "덧붙인 문단")
        results.append(_parts(target.read_bytes()))
    assert results[0] == results[1]


def test_mail_merge_twice_writes_the_same_parts(tmp_path: Path) -> None:
    _source(tmp_path / "template.hwpx")
    rows = [{"이름": "가람"}, {"이름": "나래"}]
    outputs = []
    for run in range(2):
        folder = tmp_path / f"merge{run}"
        merge_template_rows(tmp_path / "template.hwpx", rows, output_dir=folder)
        outputs.append({path.name: _parts(path.read_bytes()) for path in sorted(folder.glob("*.hwpx"))})
    assert outputs[0] and outputs[0] == outputs[1]


def test_new_documents_from_the_same_request_have_the_same_parts() -> None:
    text = "# 봄 소풍\n\n| 항목 | 내용 |\n|---|---|\n| 날짜 | 5월 2일 |\n"
    assert _parts(from_markdown(text).to_bytes()) == _parts(from_markdown(text).to_bytes())
    plan = {
        "schemaVersion": "hwpx.document_plan.v1",
        "title": "봄 소풍 안내",
        "blocks": [
            {"type": "heading", "level": 1, "text": "준비물"},
            {"type": "paragraph", "text": "도시락"},
            {"type": "memo", "text": "모이는 곳", "memo": "정문 앞"},
            {"type": "table", "columns": [{"key": "a", "label": "항목"}], "rows": [{"a": "물"}]},
        ],
    }
    assert _parts(create_document_from_plan(plan).to_bytes()) == _parts(create_document_from_plan(plan).to_bytes())


def test_markdown_seed_is_the_request_seed_of_its_text() -> None:
    import hashlib

    text = "# 제목\n\n본문"
    assert int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16) == request_seed(text)


def test_a_memo_written_a_second_later_differs_only_in_its_time(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """What the comparison above masks is the memo's time and nothing else of the memo."""

    plan = {
        "schemaVersion": "hwpx.document_plan.v1",
        "title": "봄 소풍 안내",
        "blocks": [{"type": "memo", "text": "모이는 곳", "memo": "정문 앞"}],
    }
    first = create_document_from_plan(plan).to_bytes()
    raw = {name: zipfile.ZipFile(io.BytesIO(first)).read(name) for name in zipfile.ZipFile(io.BytesIO(first)).namelist()}
    section = raw["Contents/section0.xml"]
    assert _MEMO_TIME.search(section) and _MEMO_STAMP.search(section)
    later = _MEMO_STAMP.sub(rb"\g<1>2099-01-01T00:00:00Z", _MEMO_TIME.sub(rb"\g<1>1/2/", section))
    assert later != section
    assert _masked("Contents/section0.xml", later) == _masked("Contents/section0.xml", section)
    assert b"\xec\xa0\x95\xeb\xac\xb8 \xec\x95\x9e" in _masked("Contents/section0.xml", section)  # "정문 앞" stays

