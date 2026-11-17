# SPDX-License-Identifier: Apache-2.0
"""agent-command v2 (hwpx-automation 8.0): text ranges, character-offset places, and the
``contract_changed`` refusals of the v1 forms whose meaning changed."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from hwpx import HwpxDocument

from hwpx_automation.office.agent import HwpxAgentDocument, apply_document_commands
from hwpx_automation.office.agent.model import (
    AGENT_BATCH_SCHEMA,
    AGENT_BATCH_SCHEMA_V1,
    AgentContractError,
    validate_agent_command,
)


def _write(path: Path) -> None:
    with HwpxDocument.new() as document:
        first = document.sections[0].paragraphs[0]
        first.element.set("id", "11")
        first.text = "가나다라마바"
        second = document.add_paragraph("하나둘셋")
        second.element.set("id", "12")
        document.save(path)


def _batch(source: Path, output: Path, commands: list[dict[str, Any]], *, schema: str = AGENT_BATCH_SCHEMA) -> dict[str, Any]:
    return {
        "schemaVersion": schema,
        "input": {"filename": str(source)},
        "output": {"filename": str(output), "overwrite": True},
        "commands": commands,
        "expectedRevision": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
        "idempotencyKey": None,
        "dryRun": False,
        "quality": "transparent",
        "verificationRequirements": ["package", "reopen", "openSafety", "semanticDiff"],
    }


def _paths(source: Path) -> tuple[str, str]:
    with HwpxAgentDocument.open(source) as agent:
        paragraphs = [record.path for record in agent.records if record.kind == "paragraph"]
    return paragraphs[0], paragraphs[1]


def _texts(path: Path) -> list[str]:
    with HwpxDocument.open(path) as document:
        return [paragraph.text for paragraph in document.paragraphs]


def _apply(tmp_path: Path, commands: list[dict[str, Any]], **kwargs: Any):
    source, output = tmp_path / "input.hwpx", tmp_path / "output.hwpx"
    if not source.exists():
        _write(source)
    return apply_document_commands(_batch(source, output, commands, **kwargs)), output


def test_text_add_at_an_offset_returns_its_range_and_place(tmp_path: Path) -> None:
    _write(tmp_path / "input.hwpx")
    first, _ = _paths(tmp_path / "input.hwpx")
    result, output = _apply(tmp_path, [{
        "commandId": "add", "op": "add", "kind": "text", "parent": first,
        "position": {"mode": "offset", "offset": 2}, "properties": {"text": "XY", "bold": True},
    }])
    assert result.ok, result.to_dict()
    item = result.command_results[0]
    assert item["path"] == f"{first}/text[2:4]"
    assert item["place"] == {"paragraph": first, "offset": 2, "length": 2}
    assert _texts(output)[0] == "가나XY다라마바"
    with HwpxAgentDocument.open(output) as agent:
        bold_runs = [
            record for record in agent.records
            if record.kind == "run" and record.parent_path == first and record.summary.get("bold")
        ]
        assert [record.summary["text"] for record in bold_runs] == ["XY"]


def test_text_set_remove_move_copy_follow_the_paragraph_text(tmp_path: Path) -> None:
    _write(tmp_path / "input.hwpx")
    first, second = _paths(tmp_path / "input.hwpx")
    cases = [
        ({"commandId": "s", "op": "set", "path": f"{first}/text[1:3]", "properties": {"text": "QQQ"}},
         ["가QQQ라마바", "하나둘셋"], f"{first}/text[1:4]"),
        ({"commandId": "r", "op": "remove", "path": f"{first}/text[0:2]"}, ["다라마바", "하나둘셋"], None),
        ({"commandId": "m", "op": "move", "path": f"{first}/text[0:2]", "parent": second,
          "position": {"mode": "offset", "offset": 1}}, ["다라마바", "하가나나둘셋"], f"{second}/text[1:3]"),
        ({"commandId": "c", "op": "copy", "path": f"{first}/text[2:4]", "parent": second,
          "position": {"mode": "append"}}, ["가나다라마바", "하나둘셋다라"], f"{second}/text[4:6]"),
    ]
    for index, (command, texts, path) in enumerate(cases):
        output = tmp_path / f"out-{index}.hwpx"
        result = apply_document_commands(_batch(tmp_path / "input.hwpx", output, [command]))
        assert result.ok, result.to_dict()
        assert _texts(output) == texts
        if path is not None:
            assert result.command_results[0]["path"] == path


def test_text_node_reads_its_range_and_the_runs_it_spans(tmp_path: Path) -> None:
    _write(tmp_path / "input.hwpx")
    first, _ = _paths(tmp_path / "input.hwpx")
    with HwpxAgentDocument.open(tmp_path / "input.hwpx") as agent:
        node = agent.get(f"{first}/text[1:4]").to_dict()
        run = next(record for record in agent.records if record.kind == "run" and record.parent_path == first)
        run_node = agent.get(run.path).to_dict()
        with pytest.raises(AgentContractError) as past_end:
            agent.get(f"{first}/text[1:40]")
    assert node["kind"] == "text"
    assert node["summary"]["text"] == "나다라"
    assert node["summary"]["runs"] == [run.path]
    assert node["operations"] == ["set", "add", "remove", "move", "copy"]
    assert run_node["operations"] == ["set"]
    assert run_node["summary"]["place"] == {"paragraph": first, "offset": 0, "length": 6}
    assert past_end.value.code == "not_found"


def test_table_goes_to_an_offset_and_a_copy_before_it(tmp_path: Path) -> None:
    _write(tmp_path / "input.hwpx")
    first, _ = _paths(tmp_path / "input.hwpx")
    result, output = _apply(tmp_path, [
        {"commandId": "t", "op": "add", "kind": "table", "parent": first,
         "position": {"mode": "offset", "offset": 3}, "properties": {"rowCount": 1, "columnCount": 2}},
        {"commandId": "c", "op": "copy", "path": "$t.path", "parent": first,
         "position": {"mode": "before", "path": "$t.path"}},
    ])
    assert result.ok, result.to_dict()
    original, copied = result.command_results
    assert original["place"]["offset"] == 3 and copied["place"]["offset"] == 3
    assert copied["generatedIdentities"] and copied["path"] != original["path"]
    with HwpxDocument.open(output) as document:
        tables = document.paragraphs[0].tables
        ids = [table.element.get("id") for table in tables]
    copy_id = copied["path"].split('"')[-2]
    original_id = original["path"].split('"')[-2]
    assert ids == [copy_id, original_id]
    assert _texts(output)[0] == "가나다라마바"


@pytest.mark.parametrize(
    ("command", "message"),
    [
        ({"commandId": "a", "op": "add", "kind": "run", "parent": "{first}", "properties": {"text": "x"}},
         "run add/remove/copy was replaced"),
        ({"commandId": "a", "op": "remove", "path": "{first}/run[1]"}, "run add/remove/copy was replaced"),
        ({"commandId": "a", "op": "copy", "path": "{first}/run[1]", "parent": "{second}"},
         "run add/remove/copy was replaced"),
        ({"commandId": "a", "op": "add", "kind": "table", "parent": "{first}",
          "position": {"mode": "index", "index": 1}, "properties": {"rowCount": 1, "columnCount": 1}},
         'position.mode "index" is not taken inside a paragraph'),
        ({"commandId": "a", "op": "add", "kind": "table", "parent": "{first}",
          "position": {"mode": "before", "path": "{first}/run[1]"}, "properties": {"rowCount": 1, "columnCount": 1}},
         "position.path names a run"),
    ],
)
def test_v1_forms_whose_meaning_changed_are_refused_with_a_suggestion(
    tmp_path: Path, command: dict[str, Any], message: str
) -> None:
    _write(tmp_path / "input.hwpx")
    first, second = _paths(tmp_path / "input.hwpx")

    def fill(value: Any) -> Any:
        if isinstance(value, str):
            return value.replace("{first}", first).replace("{second}", second)
        if isinstance(value, dict):
            return {key: fill(item) for key, item in value.items()}
        return value

    result, output = _apply(tmp_path, [fill(command)], schema=AGENT_BATCH_SCHEMA_V1)
    assert not result.ok and result.error is not None
    assert result.error.code == "contract_changed"
    assert message in result.error.message
    assert result.error.recoverability == "needs-review"
    assert result.error.suggestion
    assert not output.exists()


def test_a_v1_command_with_a_v2_form_is_refused_as_mixed() -> None:
    command = {"commandId": "a", "op": "add", "kind": "text", "parent": "/section[1]/paragraph[1]",
               "properties": {"text": "x"}, "schemaVersion": "hwpx.agent-command/v1"}
    with pytest.raises(AgentContractError) as caught:
        validate_agent_command(command)
    assert caught.value.code == "contract_changed"
    assert caught.value.suggestion == 'Send schemaVersion "hwpx.agent-command/v2"'
    normalized = validate_agent_command({**command, "schemaVersion": "hwpx.agent-command/v2"})
    assert normalized["schemaVersion"] == "hwpx.agent-command/v2"


def test_v1_batch_whose_meaning_did_not_change_is_taken(tmp_path: Path) -> None:
    _write(tmp_path / "input.hwpx")
    first, _ = _paths(tmp_path / "input.hwpx")
    result, output = _apply(
        tmp_path,
        [{"commandId": "s", "op": "set", "path": first, "properties": {"text": "탭\t줄\n끝"}}],
        schema=AGENT_BATCH_SCHEMA_V1,
    )
    assert result.ok, result.to_dict()
    assert result.verification_report["schemaVersion"] == AGENT_BATCH_SCHEMA
    assert _texts(output)[0] == "탭\t줄\n끝"


def test_offset_outside_a_paragraph_is_refused(tmp_path: Path) -> None:
    _write(tmp_path / "input.hwpx")
    first, _ = _paths(tmp_path / "input.hwpx")
    result, _output = _apply(tmp_path, [{
        "commandId": "p", "op": "add", "kind": "paragraph", "parent": "/section[1]",
        "position": {"mode": "offset", "offset": 0}, "properties": {"text": "x"},
    }])
    assert not result.ok and result.error is not None and result.error.code == "invalid_syntax"
    past_end, _ = _apply(tmp_path, [{
        "commandId": "t", "op": "add", "kind": "text", "parent": first,
        "position": {"mode": "offset", "offset": 99}, "properties": {"text": "x"},
    }])
    assert not past_end.ok and past_end.error is not None and past_end.error.code == "not_found"


def _with_table(path: Path, *, text_after: bool) -> None:
    with HwpxDocument.new() as document:
        first = document.sections[0].paragraphs[0]
        first.element.set("id", "11")
        first.text = "앞글"
        first.add_table(1, 1)
        if text_after:
            first.add_run("뒷글")
        document.save(path)


@pytest.mark.parametrize(
    ("mode", "text_after", "taken"),
    [
        ("append", False, True),   # v1 (after the last table) = v2 (end of the text)
        ("append", True, False),   # text after the last table: the two places differ
        ("prepend", False, False),  # v1 before the first table, v2 at offset 0
    ],
)
def test_v1_append_prepend_in_a_paragraph_is_taken_only_where_it_means_the_same(
    tmp_path: Path, mode: str, text_after: bool, taken: bool
) -> None:
    source = tmp_path / "input.hwpx"
    _with_table(source, text_after=text_after)
    first, = [p for p in _paths_all(source)]
    command = {"commandId": "t", "op": "add", "kind": "table", "parent": first,
               "position": {"mode": mode}, "properties": {"rowCount": 1, "columnCount": 1}}
    result = apply_document_commands(_batch(source, tmp_path / "v1.hwpx", [command], schema=AGENT_BATCH_SCHEMA_V1))
    if taken:
        assert result.ok, result.to_dict()
    else:
        assert not result.ok and result.error is not None
        assert result.error.code == "contract_changed"
        assert '"mode": "offset"' in (result.error.suggestion or "")
    v2 = apply_document_commands(_batch(source, tmp_path / "v2.hwpx", [command]))
    assert v2.ok, v2.to_dict()


def _paths_all(source: Path) -> list[str]:
    with HwpxAgentDocument.open(source) as agent:
        return [record.path for record in agent.records if record.kind == "paragraph" and record.parent_path == "/section[1]"]


def test_same_file_and_commands_give_the_same_bytes(tmp_path: Path) -> None:
    _write(tmp_path / "input.hwpx")
    first, second = _paths(tmp_path / "input.hwpx")
    commands = [
        {"commandId": "p", "op": "add", "kind": "paragraph", "parent": "/section[1]", "properties": {"text": "새 문단"}},
        {"commandId": "t", "op": "add", "kind": "table", "parent": first,
         "position": {"mode": "offset", "offset": 2}, "properties": {"rowCount": 2, "columnCount": 2}},
        {"commandId": "c", "op": "copy", "path": "$t.path", "parent": second},
        {"commandId": "q", "op": "copy", "path": first, "parent": "/section[1]"},
    ]
    outputs = []
    for run in range(2):
        output = tmp_path / f"out-{run}.hwpx"
        result = apply_document_commands(_batch(tmp_path / "input.hwpx", output, commands))
        assert result.ok, result.to_dict()
        outputs.append(output.read_bytes())
    assert outputs[0] == outputs[1]
