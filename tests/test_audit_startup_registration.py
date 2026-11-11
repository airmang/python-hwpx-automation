# SPDX-License-Identifier: Apache-2.0
"""Audit EFF-03: one registration per tool and one SDK version lookup per process.

Server start used to register every active tool twice (a throwaway FastMCP for
the schemas, then the real one) and to read ``importlib.metadata.version("mcp")``
795 times. The single-pass registration must stay equivalent to the
independent throwaway derivation; that self-comparison now runs here, at test
time, instead of on every start.
"""
from __future__ import annotations

from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

import hwpx_automation.fastmcp_adapter as adapter
import hwpx_automation.server as server
from hwpx_automation.fastmcp_adapter import FastMcpAdapterError, snapshot_runtime_tools
from hwpx_automation.tool_contract import (
    TOOL_SPECS,
    active_tool_specs,
    bind_tool_specs,
    bound_tool_registry,
    register_fastmcp_tools,
    validate_registered_tools,
)


def _namespace() -> dict[str, Any]:
    return dict(server._SERVER_TOOL_BINDINGS)


def test_single_pass_registration_equals_independent_schema_derivation() -> None:
    """The contract check that used to run at every start, kept at full strength."""

    independent = bind_tool_specs(_namespace(), advanced=None).by_name()
    canonical = bound_tool_registry().by_name()
    assert list(independent) == list(canonical) == [spec.name for spec in TOOL_SPECS]
    for name, expected in independent.items():
        bound = canonical[name]
        assert bound.function is expected.function, name
        assert bound.description == expected.description, name
        assert bound.input_schema == expected.input_schema, name
        assert bound.output_schema == expected.output_schema, name
        assert bound.signature == expected.signature, name

    live = snapshot_runtime_tools(server.mcp)
    assert validate_registered_tools(server.mcp, server._TOOL_REGISTRY)["ok"] is True
    for name, snapshot in live.items():
        expected = independent[name]
        assert snapshot.callable is expected.function, name
        assert snapshot.description == expected.description, name
        assert snapshot.input_schema == expected.input_schema, name
        assert snapshot.output_schema == expected.output_schema, name


@pytest.mark.parametrize("advanced", [False, True])
def test_each_active_tool_is_registered_exactly_once(
    monkeypatch: pytest.MonkeyPatch, advanced: bool
) -> None:
    registered: list[tuple[str, str]] = []
    original = adapter._register

    def counting(mcp: Any, *, name: str, **kwargs: Any) -> Any:
        registered.append((mcp.name, name))
        return original(mcp, name=name, **kwargs)

    monkeypatch.setattr(adapter, "_register", counting)
    previous = bound_tool_registry()
    target = FastMCP("audit-eff03-live")
    try:
        active = register_fastmcp_tools(target, _namespace(), advanced=advanced)
    finally:
        import hwpx_automation.tool_contract as contract

        contract._BOUND_TOOL_REGISTRY = previous

    expected_active = [spec.name for spec in active_tool_specs(advanced=advanced)]
    assert list(active.names) == expected_active
    assert list(snapshot_runtime_tools(target)) == expected_active  # contract order
    live = [name for server_name, name in registered if server_name == "audit-eff03-live"]
    assert live == expected_active
    # Every spec is described once. Only a deprecated active tool is registered
    # a second time: its schema comes from the plain callable, the live server
    # serves the wrapper that adds the deprecation notice.
    from collections import Counter

    from hwpx_automation.tool_contract import ToolClassification

    wrapped = {
        spec.name
        for spec in active_tool_specs(advanced=advanced)
        if spec.classification is ToolClassification.DEPRECATED
    }
    counts = Counter(name for _server, name in registered)
    assert set(counts) == {spec.name for spec in TOOL_SPECS}
    assert {name for name, count in counts.items() if count == 2} == wrapped
    assert all(count in (1, 2) for count in counts.values())
    assert validate_registered_tools(target, active)["ok"] is True


def test_missing_binding_fails_before_anything_reaches_the_live_server() -> None:
    namespace = _namespace()
    namespace.pop("apply_document_commands")
    target = FastMCP("audit-eff03-missing")
    with pytest.raises(RuntimeError, match="apply_document_commands: missing callable"):
        bind_tool_specs(namespace, advanced=None, live_server=target, live_advanced=False)
    assert list(snapshot_runtime_tools(target)) == []


def test_sdk_version_is_read_once_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_version(name: str) -> str:
        calls.append(name)
        return adapter.AUDITED_MCP_PATCHES[0]

    monkeypatch.setattr(adapter, "distribution_version", fake_version)
    monkeypatch.setattr(adapter, "_MCP_VERSION_MEMO", None)
    for _ in range(50):
        adapter._require_audited_mcp_patch()
    assert calls == ["mcp"]


def test_version_memo_never_hides_an_unaudited_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter._require_audited_mcp_patch()  # memo warmed with the real, audited version

    monkeypatch.setattr(adapter, "distribution_version", lambda _name: "1.28.1")

    with pytest.raises(FastMcpAdapterError, match="only audited patches"):
        snapshot_runtime_tools(FastMCP("audit-eff03-unaudited"))
