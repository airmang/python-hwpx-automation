# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import mcp.types as mcp_types
import pytest

from hwpx_automation import server
from hwpx_automation.workspace import WorkspacePathError


def _request(arguments: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        params=SimpleNamespace(name="get_document_info", arguments=arguments or {})
    )


def test_protocol_workspace_denial_is_typed_and_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def deny(_tool_name: str, _arguments: dict):
        raise WorkspacePathError(
            "outside /workspace/private/secret.hwpx",
            code="WORKSPACE_OUTSIDE_ROOT",
            reason="outside_authorized_roots",
        )

    monkeypatch.setattr(server.mcp, "call_tool", deny)
    error = asyncio.run(
        server._strict_call_tool_handler(
            _request({"filename": "/workspace/private/secret.hwpx"})
        )
    )

    assert isinstance(error, mcp_types.ErrorData)
    assert error.code == -32043
    assert error.data["errorCode"] == "WORKSPACE_OUTSIDE_ROOT"
    assert error.data["error"]["schemaVersion"] == "hwpx.mcp-error/v1"
    assert error.data["error"]["category"] == "permission"
    encoded = json.dumps(error.data, ensure_ascii=False)
    assert "secret.hwpx" not in encoded
    assert "arguments" not in error.data


def test_protocol_client_upload_path_has_local_save_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def reject_upload(_tool_name: str, _arguments: dict):
        raise WorkspacePathError(
            "client upload path",
            code="CLIENT_UPLOAD_PATH_UNAVAILABLE",
            reason="client_upload_path",
        )

    monkeypatch.setattr(server.mcp, "call_tool", reject_upload)
    error = asyncio.run(
        server._strict_call_tool_handler(
            _request({"filename": "/mnt/user-data/uploads/document.hwpx"})
        )
    )

    assert isinstance(error, mcp_types.ErrorData)
    assert error.code == -32602
    assert error.data["errorCode"] == "CLIENT_UPLOAD_PATH_UNAVAILABLE"
    payload = error.data["error"]
    assert payload["category"] == "validation"
    assert "PC" in payload["suggestion"]
    assert payload["details"] == {"reason": "client_upload_path"}
    assert "document.hwpx" not in json.dumps(error.data, ensure_ascii=False)


def test_protocol_validation_failure_uses_invalid_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def reject(_tool_name: str, _arguments: dict):
        raise ValueError("raw validator detail")

    monkeypatch.setattr(server.mcp, "call_tool", reject)
    error = asyncio.run(server._strict_call_tool_handler(_request({"filename": "x"})))

    assert error.code == -32602
    assert error.data["errorCode"] == "INVALID_ARGUMENT"
    assert error.data["error"]["category"] == "validation"
    assert "raw validator detail" not in json.dumps(error.data)


def test_result_error_body_is_promoted_to_json_rpc_error_without_echo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def embedded(_tool_name: str, _arguments: dict):
        return mcp_types.CallToolResult(
            content=[
                mcp_types.TextContent(
                    type="text",
                    text="failed for /workspace/private/secret.hwpx",
                )
            ],
            isError=True,
        )

    monkeypatch.setattr(server.mcp, "call_tool", embedded)
    error = asyncio.run(
        server._strict_call_tool_handler(
            _request({"filename": "/workspace/private/secret.hwpx"})
        )
    )

    assert isinstance(error, mcp_types.ErrorData)
    assert error.data["errorCode"] == "TOOL_EXECUTION_FAILED"
    assert "secret.hwpx" not in json.dumps(error.data)


def test_structured_failure_payload_is_promoted_with_stable_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def embedded(_tool_name: str, _arguments: dict):
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="private detail")],
            structuredContent={
                "ok": False,
                "code": "DOCUMENT_NOT_FOUND",
                "error": "/private/workspace/secret.hwpx",
            },
            isError=False,
        )

    monkeypatch.setattr(server.mcp, "call_tool", embedded)
    error = asyncio.run(server._strict_call_tool_handler(_request()))

    assert isinstance(error, mcp_types.ErrorData)
    assert error.data["errorCode"] == "DOCUMENT_NOT_FOUND"
    assert error.data["error"]["category"] == "not_found"
    assert "secret.hwpx" not in json.dumps(error.data)
