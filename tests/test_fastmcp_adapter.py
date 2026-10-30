from __future__ import annotations

import asyncio
from typing import Annotated, Any

import mcp.types as mcp_types
import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BaseModel, ConfigDict

import hwpx_automation.fastmcp_adapter as adapter
from hwpx_automation.fastmcp_adapter import (
    AUDITED_MCP_PATCHES,
    FastMcpAdapterError,
    SUPPORTED_MCP_RANGE,
    configure_runtime,
    describe_callables,
    normalize_schema,
    register_canonical_tool,
    runtime_server_version,
    snapshot_runtime_tools,
)


class _StructuredContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str


def test_output_root_union_is_published_as_an_mcp_object_schema() -> None:
    schema = normalize_schema(
        {
            "$defs": {
                "First": {"type": "object"},
                "Second": {"type": "object"},
            },
            "anyOf": [
                {"$ref": "#/$defs/First"},
                {"$ref": "#/$defs/Second"},
            ],
        },
        input_schema=False,
    )

    assert schema["type"] == "object"
    assert len(schema["anyOf"]) == 2


def test_non_object_output_root_is_rejected_before_registration() -> None:
    with pytest.raises(
        FastMcpAdapterError,
        match="MCP output schema root must be object",
    ):
        normalize_schema({"type": "array", "items": {}}, input_schema=False)


def test_call_tool_result_requires_a_source_owned_structured_content_model() -> None:
    def bare_result() -> mcp_types.CallToolResult:
        return mcp_types.CallToolResult(content=[])

    with pytest.raises(
        FastMcpAdapterError,
        match=r"Annotated\[CallToolResult, OutputModel\]",
    ):
        describe_callables([("bare_result", bare_result, "bare", {})])


def test_annotated_call_tool_result_publishes_the_structured_content_model() -> None:
    def typed_result() -> Annotated[mcp_types.CallToolResult, _StructuredContent]:
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="ok")],
            structuredContent={"status": "ok"},
        )

    snapshot = describe_callables(
        [("typed_result", typed_result, "typed", {})]
    )["typed_result"]

    assert snapshot.output_schema["title"] == "_StructuredContent"
    assert snapshot.output_schema["required"] == ["status"]
    assert "content" not in snapshot.output_schema["properties"]


def test_implicit_none_defaults_follow_the_declared_annotation() -> None:
    def legacy(value: str = None) -> dict:  # type: ignore[assignment]
        return {"value": value}

    schema = describe_callables([("legacy", legacy, "legacy", {})])[
        "legacy"
    ].input_schema["properties"]["value"]

    assert schema["type"] == "string"
    assert schema["default"] is None
    assert "anyOf" not in schema


def test_implicit_none_is_rejected_by_the_live_argument_model() -> None:
    def legacy(value: str = None) -> dict:  # type: ignore[assignment]
        return {"value": value}

    mcp = FastMCP("implicit-none-test")
    register_canonical_tool(
        mcp,
        name="legacy",
        func=legacy,
        description="legacy",
        meta={},
    )

    with pytest.raises(ToolError, match="valid string"):
        asyncio.run(mcp.call_tool("legacy", {"value": None}))


def test_explicit_none_annotation_remains_nullable() -> None:
    def explicit(value: str | None = None) -> dict:
        return {"value": value}

    schema = describe_callables([("explicit", explicit, "explicit", {})])[
        "explicit"
    ].input_schema["properties"]["value"]

    assert {option.get("type") for option in schema["anyOf"]} == {"string", "null"}


def test_any_default_none_drops_redundant_null_union() -> None:
    def unrestricted(value: Any = None) -> dict:
        return {"value": value}

    schema = describe_callables(
        [("unrestricted", unrestricted, "unrestricted", {})]
    )["unrestricted"].input_schema["properties"]["value"]

    assert schema == {"default": None, "title": "Value"}


def test_compatibility_range_and_audited_patch_are_explicit() -> None:
    assert SUPPORTED_MCP_RANGE == "==1.30.0"
    assert AUDITED_MCP_PATCHES == ("1.30.0",)


def test_resolver_pin_and_audited_set_admit_the_same_versions() -> None:
    """Install-time admission must equal runtime admission (S-081 FR-1).

    The historical failure mode: the resolver admitted a future 1.28.x patch
    that the runtime allowlist then rejected at startup. An exact ``==`` pin to
    exactly the audited patches makes that state unrepresentable.
    """

    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - python < 3.11
        import tomli as tomllib
    from pathlib import Path

    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text("utf-8")
    )
    # mcp 핀은 [mcp] extra로 옮겼다 — 응용 계층은 MCP SDK 없이 동작하므로
    # 필수 의존이 아니다. 핀 자체는 그대로 감사 대상이라 여기서 계속 본다.
    mcp_specs = [
        d
        for d in pyproject["project"]["optional-dependencies"]["mcp"]
        if d.startswith("mcp")
    ]
    assert not [
        d for d in pyproject["project"]["dependencies"] if d.startswith("mcp")
    ], "mcp가 필수 의존으로 돌아왔다 — extra여야 한다"
    assert mcp_specs == [f"mcp{SUPPORTED_MCP_RANGE}"]
    # Exact-pin shape, and the pinned version is the audited set.
    assert SUPPORTED_MCP_RANGE.startswith("==")
    assert SUPPORTED_MCP_RANGE[2:] in AUDITED_MCP_PATCHES
    assert len(AUDITED_MCP_PATCHES) == 1


def test_runtime_configuration_exposes_owned_version_api() -> None:
    mcp = FastMCP("runtime-configuration-test")

    async def strict_handler(_request: mcp_types.CallToolRequest) -> Any:
        return None

    configure_runtime(mcp, "9.8.7", strict_handler)

    assert runtime_server_version(mcp) == "9.8.7"


@pytest.mark.parametrize("version", ["1.28.1", "1.29.0", "1.30.1", "1.31.0", "2.0.0a1"])
def test_unaudited_sdk_versions_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    version: str,
) -> None:
    monkeypatch.setattr(adapter, "_installed_mcp_version", lambda: version)

    with pytest.raises(FastMcpAdapterError, match="only audited patches"):
        snapshot_runtime_tools(FastMCP("unaudited-version-test"))


def test_runtime_configuration_rejects_incompatible_shape() -> None:
    async def strict_handler(_request: mcp_types.CallToolRequest) -> Any:
        return None

    with pytest.raises(FastMcpAdapterError, match="low-level runtime"):
        configure_runtime(object(), "1.0.0", strict_handler)


def test_runtime_snapshot_preserves_registration_order_and_is_read_only() -> None:
    mcp = FastMCP("runtime-snapshot-test")

    def second(value: str) -> dict[str, str]:
        return {"value": value}

    def first(value: str) -> dict[str, str]:
        return {"value": value}

    register_canonical_tool(
        mcp,
        name="second",
        func=second,
        description="second",
        meta={},
    )
    register_canonical_tool(
        mcp,
        name="first",
        func=first,
        description="first",
        meta={},
    )

    snapshots = snapshot_runtime_tools(mcp)

    assert tuple(snapshots) == ("second", "first")
    assert snapshots["second"].callable is second
    with pytest.raises(TypeError):
        snapshots["third"] = snapshots["second"]  # type: ignore[index]


def test_duplicate_canonical_registration_fails_closed() -> None:
    mcp = FastMCP("duplicate-registration-test")

    def tool() -> dict[str, str]:
        return {"status": "ok"}

    register_canonical_tool(
        mcp,
        name="tool",
        func=tool,
        description="tool",
        meta={},
    )

    with pytest.raises(FastMcpAdapterError, match="already contains tool"):
        register_canonical_tool(
            mcp,
            name="tool",
            func=tool,
            description="tool",
            meta={},
        )
