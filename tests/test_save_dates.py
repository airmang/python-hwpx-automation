# SPDX-License-Identifier: Apache-2.0
"""A document this package writes is dated with the real time (owner 8.0 23차), as Hangul dates a
save: a new document is made and modified now; a document written over keeps its ``CreatedDate``
and is modified now (Hangul's re-saves keep ``CreatedDate`` and write the save time to
``ModifiedDate``; an empty ``CreatedDate`` gets the save time). The form is Hangul's, UTC with a
``Z``. The time is fixed only in reproducibility tests (:func:`fixed_save_time`)."""

from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from hwpx import HwpxDocument

from hwpx_automation.hwpx_ops import HwpxOps
from hwpx_automation.mail_merge import merge_template_rows
from hwpx_automation.markdown import from_markdown
from hwpx_automation.office.agent import apply_document_commands
from hwpx_automation.office.authoring import create_document_from_plan
from hwpx_automation.upstream import fixed_save_time, same_but_save_dates, save_time

_META = re.compile(rb'<opf:meta name="(CreatedDate|ModifiedDate)"[^>]*?(?:/>|>([^<]*)</opf:meta>)')
_HANGUL_FORM = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_CREATED = "2025-03-02T01:02:03Z"
_MODIFIED = "2025-03-04T05:06:07Z"
pytestmark = pytest.mark.real_save_time

_PLAN = {
    "schemaVersion": "hwpx.document_plan.v1",
    "title": "도서관 휴관 안내",
    "blocks": [{"type": "paragraph", "text": "시설 점검으로 휴관합니다."}],
}


def _dates(data: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        hpf = archive.read("Contents/content.hpf")
    return {m.group(1).decode(): (m.group(2) or b"").decode() for m in _META.finditer(hpf)}


def _now_between(value: str, start: datetime) -> bool:
    assert _HANGUL_FORM.fullmatch(value), value
    moment = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return start - timedelta(seconds=1) <= moment <= datetime.now(timezone.utc) + timedelta(seconds=1)


def _old_input(path: Path) -> Path:
    document = HwpxDocument.new()
    document.sections[0].paragraphs[0].text = "{{이름}} 님, 봄 소풍 안내입니다."
    document.add_paragraph("둘째 문단")
    document.parts.set_document_metadata(created_date=_CREATED, modified_date=_MODIFIED)
    document.save(path)
    return path


def test_new_documents_are_made_and_modified_now() -> None:
    start = datetime.now(timezone.utc).replace(microsecond=0)
    made = [
        from_markdown("# 제목\n\n본문").to_bytes(),
        create_document_from_plan(_PLAN).to_bytes(),
        create_document_from_plan({**_PLAN, "metadata": {"document_type": "공문"}}).to_bytes(),
        create_document_from_plan({**_PLAN, "designProfile": "home_notice"}).to_bytes(),
    ]
    for data in made:
        dates = _dates(data)
        assert _now_between(dates["CreatedDate"], start)
        assert _now_between(dates["ModifiedDate"], start)


def test_written_over_documents_keep_their_creation_and_are_modified_now(tmp_path: Path) -> None:
    start = datetime.now(timezone.utc).replace(microsecond=0)
    source = _old_input(tmp_path / "source.hwpx")

    target = tmp_path / "ops.hwpx"
    target.write_bytes(source.read_bytes())
    HwpxOps(base_directory=tmp_path).add_paragraph(str(target), "덧붙인 문단")

    agent_out = tmp_path / "agent.hwpx"
    result = apply_document_commands(
        {
            "schemaVersion": "hwpx.agent-batch/v1",
            "input": {"filename": str(source)},
            "output": {"filename": str(agent_out), "overwrite": True},
            "commands": [
                {"commandId": "a", "op": "set", "path": '/section[1]/paragraph[@id="0"]', "properties": {"text": "바꾼 글"}}
            ],
            "expectedRevision": None,
            "idempotencyKey": None,
            "dryRun": False,
            "quality": "transparent",
            "verificationRequirements": ["package", "reopen"],
        }
    ).to_dict()
    assert result["ok"], result.get("error")

    merge_template_rows(source, [{"이름": "가람"}], output_dir=tmp_path / "merge")
    merged = next((tmp_path / "merge").glob("*.hwpx"))

    for path in (target, agent_out, merged):
        dates = _dates(path.read_bytes())
        assert dates["CreatedDate"] == _CREATED, path.name
        assert _now_between(dates["ModifiedDate"], start), path.name


def test_the_time_is_fixed_only_where_a_test_fixes_it(tmp_path: Path) -> None:
    moment = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    source = _old_input(tmp_path / "source.hwpx")
    target = tmp_path / "ops.hwpx"
    target.write_bytes(source.read_bytes())
    with fixed_save_time(moment):
        assert save_time() == moment
        HwpxOps(base_directory=tmp_path).add_paragraph(str(target), "덧붙인 문단")
        designed = create_document_from_plan({**_PLAN, "designProfile": "official_notice"}).to_bytes()
    assert _dates(target.read_bytes()) == {"CreatedDate": _CREATED, "ModifiedDate": "2026-01-02T03:04:05Z"}
    assert _dates(designed) == {"CreatedDate": "2026-01-02T03:04:05Z", "ModifiedDate": "2026-01-02T03:04:05Z"}
    assert save_time() != moment


def test_only_the_save_dates_may_differ() -> None:
    before = (
        b'<opf:metadata><opf:meta name="CreatedDate" content="text">2025-03-02T01:02:03Z</opf:meta>'
        b'<opf:meta name="ModifiedDate" content="text">2025-03-04T05:06:07Z</opf:meta>'
        b'<opf:meta name="date" content="text">x</opf:meta></opf:metadata>'
    )
    stamped = before.replace(b"2025-03-04T05:06:07Z", b"2026-11-18T01:02:03Z")
    assert same_but_save_dates(before, stamped)
    assert not same_but_save_dates(before, stamped.replace(b">x<", b">y<"))
