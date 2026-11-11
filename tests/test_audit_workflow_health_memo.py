# SPDX-License-Identifier: Apache-2.0
"""Workflow tools do not rerun the full server health check on every call."""

from __future__ import annotations

import pytest

from hwpx_automation.handlers import workflow as workflow_handler
from hwpx_automation.runtime_services import RUNTIME_SERVICES
from hwpx_automation.tool_bindings import TOOL_BINDINGS
from hwpx_automation.tool_contract import contract_hash


class _ServiceProbe:
    created: list[dict] = []

    def __init__(self, namespace, **kwargs) -> None:
        type(self).created.append(kwargs)


@pytest.fixture
def probes(monkeypatch: pytest.MonkeyPatch) -> dict:
    state = {"calls": 0, "now": 5000.0}
    real = workflow_handler._probe_tool_surface

    def counting_probe():
        state["calls"] += 1
        return real()

    _ServiceProbe.created = []
    monkeypatch.setattr(workflow_handler, "_probe_tool_surface", counting_probe)
    monkeypatch.setattr(workflow_handler, "_clock", lambda: state["now"])
    monkeypatch.setattr(workflow_handler, "WorkflowService", _ServiceProbe)
    workflow_handler._reset_tool_surface_memo()
    yield state
    workflow_handler._reset_tool_surface_memo()


def test_repeated_calls_probe_once_and_keep_the_same_answer(probes) -> None:
    for _ in range(5):
        workflow_handler._workflow_service()

    assert probes["calls"] == 1
    assert len(_ServiceProbe.created) == 5
    capability = TOOL_BINDINGS["mcp_server_health"]()["capability"]
    for kwargs in _ServiceProbe.created:
        assert kwargs["capability_ok"] is bool(capability["ok"])
        assert kwargs["tool_spec_hash"] == contract_hash()


def test_probe_is_repeated_after_the_memo_ages_out(probes) -> None:
    workflow_handler._workflow_service()
    probes["now"] += workflow_handler._TOOL_SURFACE_MEMO_SECONDS + 1
    workflow_handler._workflow_service()

    assert probes["calls"] == 2


def test_probe_is_repeated_when_the_runtime_changes(
    probes, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow_handler._workflow_service()
    monkeypatch.setattr(
        RUNTIME_SERVICES, "active_advanced", not RUNTIME_SERVICES.active_advanced
    )
    workflow_handler._workflow_service()

    assert probes["calls"] == 2
