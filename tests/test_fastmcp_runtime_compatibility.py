from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from hwpx_automation.tool_contract import RELEASED_CONTRACT_HASH


ROOT = Path(__file__).resolve().parents[1]
# Pre-release: the live surface carries the pending hash (apply_evalplan_fill
# phase parameter); the frozen released receipt flips only at the release train.
EXPECTED_CONTRACT_HASH = RELEASED_CONTRACT_HASH


@pytest.mark.parametrize(
    ("advanced", "expected_count"),
    ((False, 128), (True, 136)),
)
def test_audited_patch_registration_error_and_protocol_contract(
    advanced: bool,
    expected_count: int,
) -> None:
    code = r"""
import asyncio
import json
from importlib.metadata import version

from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session

from hwpx_automation import __version__, server
from hwpx_automation.fastmcp_adapter import (
    AUDITED_MCP_PATCHES,
    runtime_server_version,
    snapshot_runtime_tools,
)
from hwpx_automation.tool_contract import (
    contract_hash,
    expected_tool_order,
    validate_registered_tools,
)


async def probe():
    advanced = server._ACTIVE_ADVANCED
    expected_order = expected_tool_order(advanced=advanced)
    expected_registry = server._TOOL_REGISTRY.by_name()
    adapter_snapshots = snapshot_runtime_tools(server.mcp)
    validation = validate_registered_tools(server.mcp, server._TOOL_REGISTRY)

    async with create_connected_server_and_client_session(server.mcp) as client:
        initialized = await client.initialize()
        listed = await client.list_tools()
        protocol_order = tuple(tool.name for tool in listed.tools)
        schemas_exact = all(
            tool.inputSchema == expected_registry[tool.name].input_schema
            and tool.outputSchema == expected_registry[tool.name].output_schema
            for tool in listed.tools
        )
        descriptions_exact = all(
            tool.description == expected_registry[tool.name].description
            for tool in listed.tools
        )
        health = await client.call_tool("mcp_server_health", {})
        try:
            await client.call_tool("get_document_info", {})
        except McpError as exc:
            typed_error = {
                "code": exc.error.code,
                "errorCode": exc.error.data.get("errorCode"),
                "schemaVersion": exc.error.data.get("error", {}).get("schemaVersion"),
                "category": exc.error.data.get("error", {}).get("category"),
                "hasArguments": "arguments" in exc.error.data,
            }
        else:
            raise AssertionError("invalid tool arguments did not produce an MCP error")

    return {
        "sdkVersion": version("mcp"),
        "auditedPatches": list(AUDITED_MCP_PATCHES),
        "initializeVersion": initialized.serverInfo.version,
        "adapterVersion": runtime_server_version(server.mcp),
        "packageVersion": __version__,
        "protocolOrderExact": protocol_order == expected_order,
        "adapterOrderExact": tuple(adapter_snapshots) == expected_order,
        "toolCount": len(protocol_order),
        "schemasExact": schemas_exact,
        "descriptionsExact": descriptions_exact,
        "callableIdentityExact": validation["callableMismatches"] == [],
        "registryValidationOk": validation["ok"],
        "contractHash": contract_hash(),
        "healthOk": health.isError is False
        and health.structuredContent["toolSurface"]["status"] == "ok",
        "typedError": typed_error,
    }


print(json.dumps(asyncio.run(probe()), ensure_ascii=False, sort_keys=True))
"""
    env = dict(
        os.environ,
        HWPX_MCP_ADVANCED="1" if advanced else "0",
        PYTHONDONTWRITEBYTECODE="1",
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["sdkVersion"] == "1.30.0"
    assert payload["auditedPatches"] == ["1.30.0"]
    assert payload["initializeVersion"] == payload["packageVersion"]
    assert payload["adapterVersion"] == payload["packageVersion"]
    assert payload["protocolOrderExact"] is True
    assert payload["adapterOrderExact"] is True
    assert payload["toolCount"] == expected_count
    assert payload["schemasExact"] is True
    assert payload["descriptionsExact"] is True
    assert payload["callableIdentityExact"] is True
    assert payload["registryValidationOk"] is True
    assert payload["contractHash"] == EXPECTED_CONTRACT_HASH
    assert payload["healthOk"] is True
    assert payload["typedError"] == {
        "category": "validation",
        "code": -32602,
        "errorCode": "INVALID_ARGUMENT",
        "hasArguments": False,
        "schemaVersion": "hwpx.mcp-error/v1",
    }
