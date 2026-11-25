# SPDX-License-Identifier: Apache-2.0
"""A write does not erase a document that was already at its output name.

Owner decisions 2026-11-25:

* an ``.hwp`` already on disk is never overwritten, by any tool or by the ``hwpx``
  command line (``HWP_OVERWRITE_EXISTING``); a new ``.hwp`` name is written as before;
* an ``.hwpx`` already at an output name is replaced only after its bytes are kept as
  ``.bak`` (a tool with an ``overwrite`` argument refuses without it).

The table walks the document-writing tools that take an output name. Each one is run
with another document already at that name, once as ``.hwpx`` and once as ``.hwp``.
Every document here is synthetic.
"""

from __future__ import annotations

import base64
import io
import json
import struct
import warnings
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import hwpx
import pytest
from test_evalplan_fill_mcp import BLANK as EVALPLAN_BLANK
from test_evalplan_fill_mcp import SYNTHETIC_MD as EVALPLAN_MD
from test_form_fill_mcp_e2e import _build_template, _structured_input

from hwpx_automation import api, server
from hwpx_automation.errors import HwpDocumentError
from hwpx_automation.hwpx_ops import HwpxOperationError, HwpxOps
from hwpx_automation.mail_merge import merge_template_rows
from hwpx_automation.office.agent import HwpxAgentDocument
from hwpx_automation.office.agent import cli as agent_cli
from hwpx_automation.office.rendering import oracle as rendering_oracle
from hwpx_automation.runtime import _classified_error_payload
from hwpx_automation.upstream import HwpxDocument
from hwpx_automation.workspace import (
    BackupReport,
    backup_replaced_output,
    keeping_replaced_output,
)

OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
EXAM_FIXTURES = Path(hwpx.__file__).resolve().parents[2] / "tests" / "fixtures" / "exam"
EXAM_FORM = EXAM_FIXTURES / "A_form.hwpx"
EXAM_MD = EXAM_FIXTURES / "sample_exam.md"


def _png_base64() -> str:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
        + chunk(b"IEND", b"")
    )
    return base64.b64encode(png).decode()


PNG = _png_base64()
PLAN = {
    "schemaVersion": "hwpx.document_plan.v1",
    "title": "synthetic plan",
    "blocks": [{"type": "paragraph", "text": "synthetic plan body"}],
}


def _source(path: Path) -> Path:
    """The document a tool reads: three lines, a 2x2 table, and one picture."""

    with HwpxDocument.new() as document:
        first = document.sections[0].paragraphs[0]
        first.element.set("id", "101")
        first.text = "ALPHA synthetic line one"
        document.add_paragraph("BETA synthetic line two")
        table = document.add_paragraph("GAMMA synthetic line three").add_table(2, 2)
        table.rows[0].cells[0].text = "label"
        table.rows[0].cells[1].text = "value"
        document.save(path)
    server.insert_picture(str(path), PNG)
    for backup in path.parent.glob(path.name + ".bak*"):
        backup.unlink()
    return path


def _other_document(path: Path) -> Path:
    """Another document: the one a wrong output name would erase."""

    if path.suffix.lower() == ".hwp":
        document = HwpxDocument.new()
        document.add_paragraph("OTHER synthetic hwp document")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            document.save(str(path))
        document.close()
        assert path.read_bytes()[:8] == OLE2_MAGIC
    elif path.suffix.lower() == ".hwpx":
        with HwpxDocument.new() as document:
            document.add_paragraph("OTHER synthetic hwpx document")
            document.save(path)
    else:
        path.write_bytes(b"OTHER synthetic bytes")
    return path


def _first_paragraph_path(path: Path) -> str:
    with HwpxAgentDocument.open(path) as document:
        return next(
            record.path
            for record in document.records
            if record.kind == "paragraph" and record.attributes.get("id") == "101"
        )


def _set_command(source: Path) -> list[dict[str, Any]]:
    return [
        {
            "commandId": "set",
            "op": "set",
            "path": _first_paragraph_path(source),
            "properties": {"text": "DELTA synthetic edit"},
        }
    ]


def _edit_plan(source: Path, output: Path) -> dict[str, Any]:
    return {
        "schemaVersion": "hwpx.edit-plan/v1",
        "source": str(source),
        "output": str(output),
        "steps": [
            {
                "id": "s1",
                "op": "paragraph_patch",
                "args": {"patches": [{"paragraphIndex": 0, "text": "DELTA synthetic patch"}]},
            }
        ],
    }


def _mail_merge(source: Path, target: Path) -> Any:
    template = source.with_name("template.hwpx")
    with HwpxDocument.new() as document:
        document.add_paragraph("name: {{name}}")
        document.save(template)
    return server.mail_merge(
        str(template),
        data_rows=[{"name": target.stem}],
        output_dir=str(target.parent),
        filename_pattern="{name}" + target.suffix,
    )


def _mail_merge_zip(source: Path, target: Path) -> Any:
    template = source.with_name("template.hwpx")
    with HwpxDocument.new() as document:
        document.add_paragraph("name: {{name}}")
        document.save(template)
    return server.mail_merge(
        str(template),
        data_rows=[{"name": "kim"}],
        output_dir=str(target.parent / "merged"),
        zip_filename=str(target),
    )


def _apply_form_fill(source: Path, target: Path) -> Any:
    template = source.with_name("form-template.hwpx")
    _build_template(template)
    analysis = server.analyze_form_fill(
        str(template), input_json=_structured_input(), destination_filename=str(target)
    )
    return server.apply_form_fill(analysis=analysis, confirm=True)


def _apply_evalplan_fill(source: Path, target: Path) -> Any:
    review = source.with_name("review.md")
    review.write_text(EVALPLAN_MD, encoding="utf-8")
    return server.apply_evalplan_fill(str(EVALPLAN_BLANK), str(review), output=str(target))


def _replay(source: Path, target: Path, *, overwrite: bool) -> Any:
    bundle = source.with_name("paragraph.hwpxbp")
    dumped = server.dump_document_blueprint(
        str(source), path=_first_paragraph_path(source), output=str(bundle), overwrite=True
    )
    return server.replay_document_blueprint(
        {
            "schemaVersion": "hwpx.agent-blueprint-replay/v1",
            "bundle": {"filename": str(bundle), "blueprintHash": dumped["blueprintHash"]},
            "target": {"input": str(source), "output": str(target), "overwrite": overwrite},
            "targetParent": "/section[1]",
            "position": {"mode": "append"},
            "mode": "portable",
            "mappingPolicy": {"strict": True},
            "expectedRevision": None,
            "idempotencyKey": None,
            "dryRun": False,
            "quality": "transparent",
            "verificationRequirements": ["package", "reopen", "openSafety"],
        }
    )


@dataclass(frozen=True)
class _Tool:
    """One tool, run with ``(source, output name)``.

    ``hwpx`` says what the tool does with another ``.hwpx`` already at the output: ``backup``
    (replaces it, old bytes in ``.bak``) or ``refused`` (leaves it). ``hwp`` says the same for
    an ``.hwp``: ``refused``, or ``untouched`` for a tool that writes beside it without refusing.
    """

    name: str
    call: Callable[[Path, Path], Any]
    hwpx: str = "backup"
    hwp: str = "refused"
    output_stem: str = "report"
    needs: Path | None = None


TOOLS = (
    _Tool("create_document", lambda s, t: server.create_document(str(t))),
    _Tool("create_document_from_plan", lambda s, t: server.create_document_from_plan(str(t), PLAN)),
    _Tool(
        "create_government_report_document",
        lambda s, t: server.create_government_report_document(str(t), PLAN),
    ),
    _Tool(
        "create_comparison_table_document",
        lambda s, t: server.create_comparison_table_document(
            str(t), old_paragraphs=["a", "b"], new_paragraphs=["a", "c"], title="t"
        ),
    ),
    _Tool(
        "create_proposal_document",
        lambda s, t: server.create_proposal_document(
            str(t), {"title": "synthetic proposal", "sections": [{"title": "s1", "body": "b1"}]}
        ),
    ),
    _Tool("copy_document", lambda s, t: server.copy_document(str(s), str(t))),
    _Tool(
        "copy_document(default name)",
        lambda s, t: server.copy_document(str(s)),
        output_stem="source_copy",
        hwp="skip",  # the default name takes the source's extension: an .hwpx source has no .hwp case
    ),
    _Tool(
        "add_tracked_edit",
        lambda s, t: server.add_tracked_edit(
            str(s), str(t), [{"type": "insert", "paragraph_index": 0, "text": " inserted"}]
        ),
    ),
    _Tool(
        "apply_table_ops(output=)",
        lambda s, t: server.apply_table_ops(
            str(s),
            [{"op": "fill_cell", "tableIndex": 0, "row": 1, "col": 1, "text": "v"}],
            output=str(t),
        ),
    ),
    _Tool(
        "apply_body_ops(output=)",
        lambda s, t: server.apply_body_ops(
            str(s), [{"op": "replace_text", "find": "ALPHA", "replace": "DELTA"}], output=str(t)
        ),
    ),
    _Tool("apply_evalplan_fill(output=)", _apply_evalplan_fill, needs=EVALPLAN_BLANK),
    _Tool("run_edit_plan(plan.output)", lambda s, t: server.run_edit_plan(_edit_plan(s, t))),
    _Tool("apply_form_fill(destination_filename)", _apply_form_fill),
    _Tool(
        "compose_exam(output)",
        lambda s, t: server.compose_exam(
            str(EXAM_FORM), str(t), exam_md_filename=str(EXAM_MD), verify=False
        ),
        needs=EXAM_FORM,
    ),
    # mail_merge names its files .hwpx whatever the pattern says: an .hwp of that stem is left alone.
    _Tool("mail_merge(filename_pattern)", _mail_merge, hwp="untouched"),
    _Tool("mail_merge(zip_filename)", _mail_merge_zip),
    _Tool("insert_picture(output=)", lambda s, t: server.insert_picture(str(s), PNG, output=str(t))),
    _Tool(
        "replace_picture(output=)",
        lambda s, t: server.replace_picture(str(s), image_base64=PNG, output=str(t)),
    ),
    _Tool(
        "byte_preserving_patch(output=)",
        lambda s, t: server.byte_preserving_patch(
            str(s), [{"paragraphIndex": 0, "text": "DELTA synthetic patch"}], output=str(t)
        ),
    ),
    # Tools with an overwrite argument: without it another document at the output is refused.
    _Tool("repair_hwpx", lambda s, t: server.repair_hwpx(str(s), str(t)), hwpx="refused"),
    _Tool(
        "repair_hwpx(overwrite=True)",
        lambda s, t: server.repair_hwpx(str(s), str(t), overwrite=True),
        hwpx="skip",  # asked for by name; not a wrong output name
    ),
    _Tool(
        "apply_document_commands",
        lambda s, t: server.apply_document_commands(str(s), str(t), _set_command(s)),
        hwpx="refused",
    ),
    _Tool(
        "apply_document_commands(overwrite=True)",
        lambda s, t: server.apply_document_commands(str(s), str(t), _set_command(s), overwrite=True),
        hwpx="skip",
    ),
    _Tool(
        "replay_document_blueprint",
        lambda s, t: _replay(s, t, overwrite=False),
        hwpx="refused",
    ),
    _Tool(
        "replay_document_blueprint(overwrite=True)",
        lambda s, t: _replay(s, t, overwrite=True),
        hwpx="skip",
    ),
)


@pytest.fixture(autouse=True)
def _no_live_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rendering_oracle.WindowsComOracle, "available", lambda self: False)
    monkeypatch.setattr(rendering_oracle.MacHancomOracle, "available", lambda self: False)


def _run(call: Callable[[], Any]) -> tuple[Any, dict[str, Any] | None]:
    try:
        result = call()
    except Exception as exc:  # noqa: BLE001 - every refusal counts, whatever its type
        return None, _classified_error_payload(exc)
    if hasattr(result, "model_dump"):
        result = result.model_dump(by_alias=True)
    return result, None


def _refused(result: Any, error: dict[str, Any] | None) -> bool:
    if error is not None:
        return True
    return isinstance(result, dict) and (
        result.get("ok") is False
        or result.get("created") is False
        or result.get("handoff_status") == "blocked"
    )


def _backups(target: Path) -> list[Path]:
    return sorted(target.parent.glob(target.name + ".bak*"))


def _ids(tools: tuple[_Tool, ...]) -> list[str]:
    return [tool.name for tool in tools]


_HWPX_CASES = tuple(tool for tool in TOOLS if tool.hwpx != "skip")
_HWP_CASES = tuple(tool for tool in TOOLS if tool.hwp != "skip")


@pytest.mark.parametrize("tool", _HWPX_CASES, ids=_ids(_HWPX_CASES))
def test_another_hwpx_at_the_output_is_refused_or_kept_as_bak(tool: _Tool, tmp_path: Path) -> None:
    if tool.needs is not None and not tool.needs.is_file():
        pytest.skip(f"fixture unavailable: {tool.needs.name}")
    source = _source(tmp_path / "source.hwpx")
    suffix = ".zip" if "zip" in tool.name else ".hwpx"
    target = _other_document(tmp_path / f"{tool.output_stem}{suffix}")
    old = target.read_bytes()
    source_before = source.read_bytes()

    result, error = _run(lambda: tool.call(source, target))

    assert source.read_bytes() == source_before
    if target.read_bytes() == old:
        # Not replaced: that has to be a refusal, not a success that did nothing.
        assert _refused(result, error), (tool.name, result, error)
        assert tool.hwpx == "refused", f"{tool.name} was expected to replace the output"
        assert _backups(target) == []
        return
    # Replaced: the old document is still on disk, beside the new one.
    assert tool.hwpx == "backup", f"{tool.name} was expected to refuse"
    assert error is None and not _refused(result, error), (tool.name, result, error)
    backup = target.with_name(target.name + ".bak")
    assert backup.is_file(), f"{tool.name} replaced {target.name} and left no .bak"
    assert backup.read_bytes() == old
    reported = result.get("backup") if isinstance(result, dict) else None
    if reported is not None:  # tools whose result has room for it name the backup
        assert reported["created"] is True and Path(reported["path"]) == backup


@pytest.mark.parametrize("tool", _HWP_CASES, ids=_ids(_HWP_CASES))
def test_an_hwp_at_the_output_is_refused_and_keeps_its_bytes(tool: _Tool, tmp_path: Path) -> None:
    if tool.needs is not None and not tool.needs.is_file():
        pytest.skip(f"fixture unavailable: {tool.needs.name}")
    source = _source(tmp_path / "source.hwpx")
    target = _other_document(tmp_path / f"{tool.output_stem}.hwp")
    old = target.read_bytes()
    listing_before = sorted(path.name for path in tmp_path.iterdir() if path.suffix != ".lock")

    result, error = _run(lambda: tool.call(source, target))

    assert target.read_bytes() == old, f"{tool.name} wrote over an existing .hwp"
    assert _backups(target) == []
    if tool.hwp == "untouched":
        return
    assert _refused(result, error), (tool.name, result)
    # A refusal for the .hwp writes nothing else beside it (the helper documents of a case aside).
    made = set(path.name for path in tmp_path.iterdir()) - set(listing_before)
    assert not any(name.endswith((".bak", ".hwpx")) and "report" in name for name in made), made


@pytest.mark.parametrize(
    "tool",
    [tool for tool in TOOLS if tool.name in {"create_comparison_table_document", "create_proposal_document"}],
    ids=["create_comparison_table_document", "create_proposal_document"],
)
def test_generated_documents_name_the_overwrite_refusal_and_still_write_a_new_hwp_name(
    tool: _Tool, tmp_path: Path
) -> None:
    # The proposal tool used to return an error after it had already replaced the .hwp.
    target = _other_document(tmp_path / "report.hwp")
    old = target.read_bytes()
    result, error = _run(lambda: tool.call(tmp_path / "unused.hwpx", target))
    assert result is None and error is not None
    assert error["code"] == "HWP_OVERWRITE_EXISTING"
    assert target.read_bytes() == old
    assert sorted(path.name for path in tmp_path.iterdir() if path.suffix != ".lock") == ["report.hwp"]


@pytest.mark.parametrize(
    ("label", "call"),
    [
        ("run_edit_plan", lambda s, t: server.run_edit_plan(_edit_plan(s, t))),
        ("run_edit_plan(dry_run)", lambda s, t: server.run_edit_plan(_edit_plan(s, t), dry_run=True)),
        ("repair_hwpx(overwrite)", lambda s, t: server.repair_hwpx(str(s), str(t), overwrite=True)),
        ("mail_merge(zip_filename)", _mail_merge_zip),
    ],
)
def test_core_executors_and_archives_refuse_an_existing_hwp_before_they_run(
    label: str, call: Callable[[Path, Path], Any], tmp_path: Path
) -> None:
    source = _source(tmp_path / "source.hwpx")
    target = _other_document(tmp_path / "report.hwp")
    old = target.read_bytes()
    result, error = _run(lambda: call(source, target))
    assert result is None and error is not None, label
    assert error["code"] == "HWP_OVERWRITE_EXISTING", label
    assert target.read_bytes() == old


def test_hwpx_ops_api_refuses_an_existing_hwp_for_plan_and_repair(tmp_path: Path) -> None:
    # The same two refusals for a direct HwpxOps caller (no MCP handler in front).
    source = _source(tmp_path / "source.hwpx")
    target = _other_document(tmp_path / "report.hwp")
    old = target.read_bytes()
    ops = HwpxOps(base_directory=tmp_path)
    for call in (
        lambda: ops.run_edit_plan(_edit_plan(source, target)),
        lambda: ops.repair_hwpx(str(source), str(target), overwrite=True),
    ):
        with pytest.raises(HwpxOperationError) as refused:
            call()
        assert refused.value.code == "HWP_OVERWRITE_EXISTING"
    assert target.read_bytes() == old


def test_a_new_hwp_name_is_still_written(tmp_path: Path) -> None:
    # Owner decision: only an .hwp that is already there is protected.
    result = server.create_comparison_table_document(
        str(tmp_path / "new.hwp"), old_paragraphs=["a"], new_paragraphs=["b"], title="t"
    )
    assert result["created"] is True
    assert (tmp_path / "new.hwp").read_bytes()[:8] == OLE2_MAGIC


def _cli(arguments: list[str]) -> tuple[int, str]:
    stdout = io.StringIO()
    code = agent_cli.main(arguments, stdin=io.StringIO(""), stdout=stdout, stderr=io.StringIO())
    return code, stdout.getvalue()


@pytest.mark.parametrize("extra", [["--overwrite"], ["--overwrite", "--dry-run"], []])
def test_hwpx_command_line_does_not_write_over_an_existing_hwp(extra: list[str], tmp_path: Path) -> None:
    source = _source(tmp_path / "source.hwpx")
    target = _other_document(tmp_path / "report.hwp")
    old = target.read_bytes()
    code, out = _cli(
        [
            "set",
            str(source),
            str(target),
            _first_paragraph_path(source),
            "--properties",
            '{"text": "DELTA synthetic edit"}',
            *extra,
        ]
    )
    assert code != agent_cli.EXIT_OK
    payload = json.loads(out)
    assert payload["ok"] is False and payload["rolledBack"] is True
    assert payload["error"]["code"] == "invariant_violation"
    assert ".hwp" in payload["error"]["message"]
    assert target.read_bytes() == old
    assert sorted(path.name for path in tmp_path.iterdir() if path.suffix != ".lock") == [
        "report.hwp",
        "source.hwpx",
    ]

    # A new .hwpx output beside it is written as before.
    code, _ = _cli(
        [
            "set",
            str(source),
            str(tmp_path / "edited.hwpx"),
            _first_paragraph_path(source),
            "--properties",
            '{"text": "DELTA synthetic edit"}',
        ]
    )
    assert code == agent_cli.EXIT_OK and (tmp_path / "edited.hwpx").is_file()


def test_hwpx_replay_command_does_not_write_over_an_existing_hwp(tmp_path: Path) -> None:
    source = _source(tmp_path / "source.hwpx")
    target = _other_document(tmp_path / "report.hwp")
    old = target.read_bytes()
    bundle = tmp_path / "paragraph.hwpxbp"
    code, out = _cli(
        ["dump", str(source), "--path", _first_paragraph_path(source), "--output", str(bundle)]
    )
    assert code == agent_cli.EXIT_OK
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "schemaVersion": "hwpx.agent-blueprint-replay/v1",
                "bundle": {"filename": str(bundle), "blueprintHash": json.loads(out)["blueprintHash"]},
                "target": {"input": str(source), "output": str(target), "overwrite": True},
                "targetParent": "/section[1]",
                "position": {"mode": "append"},
                "mode": "portable",
                "mappingPolicy": {"strict": True},
                "expectedRevision": None,
                "idempotencyKey": None,
                "dryRun": False,
                "quality": "transparent",
                "verificationRequirements": ["package", "reopen", "openSafety"],
            }
        ),
        encoding="utf-8",
    )
    code, out = _cli(["replay", str(request)])
    payload = json.loads(out)
    assert code != agent_cli.EXIT_OK and payload["ok"] is False
    assert payload["error"]["code"] == "invariant_violation"
    assert target.read_bytes() == old


def test_library_calls_refuse_or_back_up_too(tmp_path: Path) -> None:
    # compose_exam's refusal comes before the form or the markdown is read.
    target = _other_document(tmp_path / "exam.hwp")
    old = target.read_bytes()
    with pytest.raises(HwpDocumentError) as refused:
        api.compose_exam_into_form(str(tmp_path / "no-form.hwpx"), "not parsed", str(target))
    assert refused.value.code == "HWP_OVERWRITE_EXISTING"
    assert target.read_bytes() == old

    # merge_template_rows (no MCP handler) keeps a file already at the archive name.
    template = tmp_path / "template.hwpx"
    with HwpxDocument.new() as document:
        document.add_paragraph("name: {{name}}")
        document.save(template)
    archive = tmp_path / "bundle.zip"
    archive.write_bytes(b"OTHER synthetic bytes")
    merge_template_rows(template, [{"name": "kim"}], output_dir=tmp_path / "out", zip_path=archive)
    assert (tmp_path / "bundle.zip.bak").read_bytes() == b"OTHER synthetic bytes"


def test_in_place_edits_keep_their_own_backup_rule(tmp_path: Path) -> None:
    # output= naming the source itself is an edit in place, not a replaced other document:
    # these writers made no .bak for it before and make none now (tracked apart, #242).
    source = _source(tmp_path / "source.hwpx")
    result = server.apply_table_ops(
        str(source),
        [{"op": "fill_cell", "tableIndex": 0, "row": 1, "col": 1, "text": "v"}],
        output=str(source),
    )
    assert result["ok"] is True
    assert server.run_edit_plan(_edit_plan(source, source))["ok"] is True
    assert _backups(source) == []


def test_a_backup_that_cannot_be_made_puts_the_old_document_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The byte-preserving writers and core's plan executor publish before the .bak is written.
    # If the .bak then fails, the call fails and the other document is back at its name.
    from hwpx_automation import mixed_form as mixed_form_module
    from hwpx_automation import workspace as workspace_module

    def no_backup(*args: Any, **kwargs: Any) -> BackupReport:
        raise OSError("disk full")

    monkeypatch.setattr(mixed_form_module, "backup_replaced_output", no_backup)
    monkeypatch.setattr(workspace_module, "backup_replaced_output", no_backup)
    source = _source(tmp_path / "source.hwpx")
    target = _other_document(tmp_path / "report.hwpx")
    old = target.read_bytes()
    for call in (
        lambda: server.apply_table_ops(
            str(source),
            [{"op": "fill_cell", "tableIndex": 0, "row": 1, "col": 1, "text": "v"}],
            output=str(target),
        ),
        lambda: server.run_edit_plan(_edit_plan(source, target)),
    ):
        result, error = _run(call)
        assert result is None and error is not None
        assert target.read_bytes() == old


def test_replaced_output_backups_rotate_and_do_not_depend_on_autobackup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # AUTOBACKUP only governs the second copy the document save makes; the rotating .bak of an
    # edit (insert_picture, byte_preserving_patch) never depended on it, and neither does this one.
    monkeypatch.setenv("HWPX_AUTOMATION_AUTOBACKUP", "0")
    source = _source(tmp_path / "source.hwpx")
    target = _other_document(tmp_path / "report.hwpx")
    first = target.read_bytes()
    server.copy_document(str(source), str(target))
    second = target.read_bytes()
    server.create_document_from_plan(str(target), PLAN)
    assert (tmp_path / "report.hwpx.bak").read_bytes() == second
    assert (tmp_path / "report.hwpx.bak.1").read_bytes() == first


def test_backup_replaced_output_rule(tmp_path: Path) -> None:
    target = tmp_path / "a.hwpx"
    assert backup_replaced_output(target) == BackupReport(None)  # nothing there: nothing to keep
    target.write_bytes(b"one")
    report = backup_replaced_output(target)
    assert report.to_dict() == {"created": True, "path": str(tmp_path / "a.hwpx.bak"), "rotatedPaths": []}
    target.write_bytes(b"two")
    rotated = backup_replaced_output(target, preimage=b"one-and-a-half")
    assert rotated.rotated_paths == (tmp_path / "a.hwpx.bak.1",)
    assert (tmp_path / "a.hwpx.bak").read_bytes() == b"one-and-a-half"
    assert (tmp_path / "a.hwpx.bak.1").read_bytes() == b"one"
    assert target.read_bytes() == b"two"
    assert sorted(path.name for path in tmp_path.iterdir() if path.suffix != ".lock") == [
        "a.hwpx",
        "a.hwpx.bak",
        "a.hwpx.bak.1",
    ]


def test_keeping_replaced_output_backs_up_only_what_a_writer_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "a.hwpx"
    target.write_bytes(b"old")

    with keeping_replaced_output(target):
        pass  # the writer wrote nothing
    assert _backups(target) == []

    with keeping_replaced_output(target, source=target):
        target.write_bytes(b"edited in place")
    assert _backups(target) == []
    target.write_bytes(b"old")

    with pytest.raises(RuntimeError), keeping_replaced_output(target):
        target.write_bytes(b"new")
        raise RuntimeError("the writer failed after it had replaced the file")
    assert (tmp_path / "a.hwpx.bak").read_bytes() == b"old"

    # The backup itself cannot be made: the old document goes back to its name.
    target.write_bytes(b"old")
    (tmp_path / "a.hwpx.bak").unlink()
    from hwpx_automation import workspace as workspace_module

    def no_backup(*args: Any, **kwargs: Any) -> BackupReport:
        raise OSError("disk full")

    monkeypatch.setattr(workspace_module, "backup_replaced_output", no_backup)
    with pytest.raises(OSError), keeping_replaced_output(target):
        target.write_bytes(b"new")
    assert target.read_bytes() == b"old"
