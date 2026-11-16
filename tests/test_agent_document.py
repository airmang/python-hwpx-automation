from __future__ import annotations

import hashlib
from pathlib import Path

import anyio

from hwpx import HwpxDocument
from hwpx_automation.office.agent import (
    AGENT_BATCH_RESULT_SCHEMA,
    HwpxAgentDocument,
    agent_json_schemas,
)
from hwpx_automation.office.agent.blueprint import (
    BLUEPRINT_REPLAY_RESULT_SCHEMA,
    blueprint_json_schemas,
)
from hwpx.oxml import HwpxOxmlDocument
from hwpx_automation import server


def _fixture(path: Path) -> None:
    with HwpxDocument.new() as document:
        first = document.sections[0].paragraphs[0]
        first.element.set("id", "101")
        first.text = "평가 계획"
        second = document.add_paragraph("평가 방법")
        second.element.set("id", "102")
        table = second.add_table(1, 2)
        table.element.set("id", "201")
        table.rows[0].cells[0].text = "항목"
        table.rows[0].cells[1].text = "내용"
        document.save(path)


def _multi_story_fixture(path: Path) -> tuple[str, str]:
    with HwpxDocument.new() as document:
        section = document.sections[0]
        section.paragraphs[0].text = "S-080 MCP 본문 원본"
        table_paragraph = document.add_paragraph("표 문단")
        table = table_paragraph.add_table(1, 1)
        table.rows[0].cells[0].text = "S-080 MCP 셀 원본"
        document.page.set_header(
            text="S-080 MCP 머리글 원본",
            section=section,
            page_type="BOTH",
        )
        document.save(path)
    with HwpxAgentDocument.open(path) as view:
        body_path = next(
            record.path
            for record in view.records
            if record.kind == "paragraph"
            and record.summary.get("text") == "S-080 MCP 본문 원본"
        )
        cell_path = next(
            record.path
            for record in view.records
            if record.kind == "cell"
            and record.summary.get("text") == "S-080 MCP 셀 원본"
        )
    return body_path, cell_path


def _revision(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _paragraph_path(path: Path, identity: str = "101") -> str:
    with HwpxAgentDocument.open(path) as document:
        return next(
            record.path
            for record in document.records
            if record.kind == "paragraph" and record.attributes.get("id") == identity
        )


def _replay_request(bundle: Path, blueprint_hash: str, target: Path, output: Path) -> dict:
    return {
        "schemaVersion": "hwpx.agent-blueprint-replay/v1",
        "bundle": {"filename": str(bundle), "blueprintHash": blueprint_hash},
        "target": {"input": str(target), "output": str(output), "overwrite": False},
        "targetParent": "/section[1]",
        "position": {"mode": "append"},
        "mode": "portable",
        "mappingPolicy": {"strict": True},
        "expectedRevision": _revision(target),
        "idempotencyKey": "mcp-blueprint-1",
        "dryRun": False,
        "quality": "transparent",
        "verificationRequirements": [
            "package",
            "reopen",
            "openSafety",
            "semanticDiff",
            "bytePreservation",
        ],
    }


def test_read_tools_return_shared_nodes_paths_and_document_state(tmp_path: Path) -> None:
    source = tmp_path / "input.hwpx"
    _fixture(source)
    revision = _revision(source)

    root = server.get_document_node(
        str(source),
        path="/",
        depth=2,
        expected_revision=revision,
    )
    assert root["kind"] == "document"
    assert root["revision"] == revision
    assert root["document_revision"] == revision
    assert root["children"][0]["path"] == "/section[1]"

    result = server.query_document_nodes(
        str(source),
        'paragraph:contains("평가")',
        limit=10,
        expected_revision=revision,
    )
    assert result["revision"] == revision
    assert [node["summary"]["text"] for node in result["nodes"]] == [
        "평가 계획",
        "평가 방법",
    ]


def test_read_tools_fail_with_shared_structured_errors(tmp_path: Path) -> None:
    missing = server.get_document_node(str(tmp_path / "missing.hwpx"))
    assert missing["ok"] is False
    assert missing["error"]["code"] == "not_found"
    assert missing["error"]["schemaVersion"] == "hwpx.agent-error/v1"

    source = tmp_path / "input.hwpx"
    _fixture(source)
    stale = server.query_document_nodes(
        str(source),
        "paragraph",
        expected_revision="sha256:" + "0" * 64,
    )
    assert stale["ok"] is False
    assert stale["error"]["code"] == "stale_revision"
    assert stale["error"]["recoverability"] == "retryable"


def test_atomic_apply_reuses_core_verification_revision_and_idempotency(tmp_path: Path) -> None:
    source = tmp_path / "input.hwpx"
    output = tmp_path / "output.hwpx"
    _fixture(source)
    paragraph = _paragraph_path(source)
    kwargs = {
        "filename": str(source),
        "output": str(output),
        "commands": [
            {
                "commandId": "set-heading",
                "op": "set",
                "path": paragraph,
                "properties": {"text": "MCP 수정", "alignment": "CENTER"},
            },
            {
                "commandId": "copy-heading",
                "op": "copy",
                "path": paragraph,
                "parent": "/section[1]",
            },
        ],
        "expected_revision": _revision(source),
        "idempotency_key": "agent-mcp-replay-1",
        "overwrite": False,
    }

    first = server.apply_document_commands(**kwargs)
    replay = server.apply_document_commands(**kwargs)

    assert first["schemaVersion"] == AGENT_BATCH_RESULT_SCHEMA
    assert first["ok"] is True and first["rolledBack"] is False
    assert first["verificationReport"]["savePipeline"]["ok"] is True
    assert first["verificationReport"]["openSafety"]["ok"] is True
    assert first["verificationReport"]["idempotency"]["replayed"] is False
    assert replay["ok"] is True
    assert replay["verificationReport"]["idempotency"]["replayed"] is True
    assert replay["documentRevision"] == first["documentRevision"]
    assert replay["document_revision"] == first["document_revision"]
    with HwpxAgentDocument.open(output) as document:
        texts = [
            record.summary.get("text")
            for record in document.records
            if record.kind == "paragraph"
        ]
    assert texts.count("MCP 수정") == 2


def test_apply_document_commands_routes_body_table_header_transaction_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "multi-story-input.hwpx"
    output = tmp_path / "multi-story-output.hwpx"
    body_path, cell_path = _multi_story_fixture(source)
    serialize_calls = 0
    original_serialize = HwpxOxmlDocument.serialize

    def counted_serialize(document: HwpxOxmlDocument) -> dict[str, bytes]:
        nonlocal serialize_calls
        serialize_calls += 1
        return original_serialize(document)

    monkeypatch.setattr(HwpxOxmlDocument, "serialize", counted_serialize)
    result = server.apply_document_commands(
        str(source),
        str(output),
        [
            {
                "commandId": "body",
                "op": "set",
                "path": body_path,
                "properties": {"text": "S-080 MCP 본문 수정"},
            },
            {
                "commandId": "cell",
                "op": "set",
                "path": cell_path,
                "properties": {"text": "S-080 MCP 셀 수정"},
            },
            {
                "commandId": "header",
                "op": "set",
                "path": '/section[1]/header[@page-type="BOTH"]',
                "properties": {"text": "S-080 MCP 머리글 수정"},
            },
        ],
        expected_revision=_revision(source),
        idempotency_key="s080-mcp-multi-story",
    )

    assert result["ok"] is True and result["rolledBack"] is False
    assert serialize_calls == 1
    assert result["verificationReport"]["storyPreservation"]["ok"] is True
    assert result["verificationReport"]["storyPreservation"]["storyCount"] == 1
    assert result["verificationReport"]["bytePreservation"]["changedMembers"] == [
        "Contents/section0.xml"
    ]
    assert result["verificationReport"]["openSafety"]["ok"] is True
    with HwpxDocument.open(output) as reopened:
        header = reopened.sections[0].properties.header("BOTH")
        assert header is not None and header.text == "S-080 MCP 머리글 수정"
    with HwpxAgentDocument.open(output) as view:
        texts = {
            record.summary.get("text")
            for record in view.records
            if record.kind in {"paragraph", "cell"}
        }
    assert {"S-080 MCP 본문 수정", "S-080 MCP 셀 수정"} <= texts


def test_apply_stale_and_capability_skew_fail_closed_without_output(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "input.hwpx"
    stale_output = tmp_path / "stale.hwpx"
    skew_output = tmp_path / "skew.hwpx"
    _fixture(source)
    paragraph = _paragraph_path(source)
    command = {
        "commandId": "set",
        "op": "set",
        "path": paragraph,
        "properties": {"text": "금지"},
    }
    stale = server.apply_document_commands(
        str(source),
        str(stale_output),
        [command],
        expected_revision="sha256:" + "0" * 64,
    )
    assert stale["ok"] is False and stale["rolledBack"] is True
    assert stale["error"]["code"] == "stale_revision"
    assert not stale_output.exists()

    def blocked() -> None:
        raise RuntimeError("capability skew")

    monkeypatch.setattr(server.quality_contract, "assert_write_capability", blocked)
    skew = server.apply_document_commands(str(source), str(skew_output), [command])
    assert skew["schemaVersion"] == AGENT_BATCH_RESULT_SCHEMA
    assert skew["ok"] is False and skew["rolledBack"] is True
    assert skew["error"]["code"] == "verification_failed"
    assert skew["verificationReport"]["boundary"] == "mcp-capability-and-locator"
    assert not skew_output.exists()


def test_dry_run_does_not_publish_and_uses_input_state(tmp_path: Path) -> None:
    source = tmp_path / "input.hwpx"
    output = tmp_path / "dry.hwpx"
    _fixture(source)
    result = server.apply_document_commands(
        str(source),
        str(output),
        [
            {
                "commandId": "set",
                "op": "set",
                "path": _paragraph_path(source),
                "properties": {"text": "미리보기"},
            }
        ],
        dry_run=True,
    )
    assert result["ok"] is True and result["dryRun"] is True
    assert result["document_revision"] == _revision(source)
    assert not output.exists()


def test_blueprint_dump_and_replay_are_thin_stateless_core_facades(tmp_path: Path) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    bundle = tmp_path / "paragraph.hwpxbp"
    output = tmp_path / "output.hwpx"
    _fixture(source)
    with HwpxDocument.new() as document:
        document.sections[0].paragraphs[0].text = "TARGET"
        document.save(target)

    dumped = server.dump_document_blueprint(
        str(source),
        path=_paragraph_path(source),
        expected_revision=_revision(source),
        output=str(bundle),
    )
    assert dumped["ok"] is True
    assert dumped["manifest"]["blueprintHash"] == dumped["blueprintHash"]
    assert dumped["manifest"]["unsupported"] == []
    assert bundle.exists()

    request = _replay_request(bundle, dumped["blueprintHash"], target, output)
    first = server.replay_document_blueprint(request)
    replayed = server.replay_document_blueprint(request)
    assert first["schemaVersion"] == BLUEPRINT_REPLAY_RESULT_SCHEMA
    assert first["ok"] is True and first["rolledBack"] is False
    assert first["verificationReport"]["openSafety"]["ok"] is True
    assert first["verificationReport"]["savePipeline"]["ok"] is True
    assert replayed["ok"] is True
    assert replayed["verificationReport"]["idempotency"]["replayed"] is True
    assert replayed["documentRevision"] == first["documentRevision"]
    with HwpxAgentDocument.open(output) as document:
        texts = [
            record.summary.get("text")
            for record in document.records
            if record.kind == "paragraph"
        ]
    assert "평가 계획" in texts


def test_blueprint_adapter_capability_failure_is_atomic(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    bundle = tmp_path / "paragraph.hwpxbp"
    output = tmp_path / "output.hwpx"
    _fixture(source)
    _fixture(target)
    dumped = server.dump_document_blueprint(
        str(source), path=_paragraph_path(source), output=str(bundle)
    )

    def blocked() -> None:
        raise RuntimeError("capability skew")

    monkeypatch.setattr(server.quality_contract, "assert_write_capability", blocked)
    result = server.replay_document_blueprint(
        _replay_request(bundle, dumped["blueprintHash"], target, output)
    )
    assert result["schemaVersion"] == BLUEPRINT_REPLAY_RESULT_SCHEMA
    assert result["ok"] is False and result["rolledBack"] is True
    assert result["verificationReport"]["boundary"] == "mcp-capability-and-locator"
    assert not output.exists()


def test_fastmcp_schema_and_help_are_generated_from_core_catalog() -> None:
    async def tools_by_name():
        return {tool.name: tool for tool in await server.mcp.list_tools()}

    tools = anyio.run(tools_by_name)
    command_schema = tools["apply_document_commands"].inputSchema["properties"]["commands"]
    assert command_schema["items"] == agent_json_schemas()["command"]
    assert command_schema["minItems"] == 1
    assert command_schema["maxItems"] == 100
    get_schema = tools["get_document_node"].inputSchema["properties"]
    query_schema = tools["query_document_nodes"].inputSchema["properties"]
    assert get_schema["depth"]["minimum"] == 0
    assert get_schema["depth"]["maximum"] == 8
    assert get_schema["child_limit"]["maximum"] == 200
    assert query_schema["selector"]["maxLength"] == 512
    assert query_schema["limit"]["maximum"] == 100
    assert "Shared catalog sha256:" in tools["get_document_node"].description
    assert ":contains" in tools["query_document_nodes"].description
    assert "set/add/remove/move/copy" in tools["apply_document_commands"].description
    dump_schema = tools["dump_document_blueprint"].inputSchema["properties"]
    replay_schema = tools["replay_document_blueprint"].inputSchema["properties"]["request"]
    assert dump_schema["path"]["maxLength"] == 4096
    assert dump_schema["mode"]["enum"] == ["portable", "source-bound"]
    assert replay_schema["properties"] == blueprint_json_schemas()["replay"]["properties"]
    assert "Shared blueprint catalog sha256:" in tools["dump_document_blueprint"].description
    assert "one save" in tools["replay_document_blueprint"].description


def test_agent_document_tools_execute_over_stdio_protocol(
    mcp_server_factory, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "input.hwpx"
    output = workspace / "output.hwpx"
    _fixture(source)
    client = mcp_server_factory(cwd=workspace)
    tools = {tool["name"]: tool for tool in client.list_tools()}

    assert {
        "get_document_node",
        "query_document_nodes",
        "apply_document_commands",
        "dump_document_blueprint",
        "replay_document_blueprint",
    } <= set(tools)
    root = client.parse_tool_result_payload(
        client.call_tool(
            "get_document_node",
            {"filename": "input.hwpx", "path": "/", "depth": 2},
        )
    )
    assert root["kind"] == "document"

    query = client.parse_tool_result_payload(
        client.call_tool(
            "query_document_nodes",
            {
                "filename": "input.hwpx",
                "selector": 'paragraph:contains("평가 계획")',
                "limit": 5,
            },
        )
    )
    target = query["nodes"][0]["path"]
    result = client.parse_tool_result_payload(
        client.call_tool(
            "apply_document_commands",
            {
                "filename": "input.hwpx",
                "output": "output.hwpx",
                "commands": [
                    {
                        "commandId": "set",
                        "op": "set",
                        "path": target,
                        "properties": {"text": "프로토콜 수정"},
                    }
                ],
                "expected_revision": root["revision"],
                "idempotency_key": "stdio-agent-document-1",
            },
        )
    )
    assert result["ok"] is True
    assert result["verificationReport"]["openSafety"]["ok"] is True
    assert output.exists()
    with HwpxAgentDocument.open(output) as document:
        assert document.resolve_record(target).summary["text"] == "프로토콜 수정"

    bundle = workspace / "protocol.hwpxbp"
    blueprint_output = workspace / "blueprint-output.hwpx"
    dumped = client.parse_tool_result_payload(
        client.call_tool(
            "dump_document_blueprint",
            {
                "filename": "input.hwpx",
                "path": target,
                "output": "protocol.hwpxbp",
            },
        )
    )
    assert dumped["ok"] is True and bundle.exists()
    replayed = client.parse_tool_result_payload(
        client.call_tool(
            "replay_document_blueprint",
            {
                "request": _replay_request(
                    bundle,
                    dumped["blueprintHash"],
                    source,
                    blueprint_output,
                )
            },
        )
    )
    assert replayed["ok"] is True
    assert replayed["verificationReport"]["openSafety"]["ok"] is True
    assert blueprint_output.exists()
