# SPDX-License-Identifier: Apache-2.0
"""Workflow automation handlers for the optional MCP adapter."""

from __future__ import annotations


import os
import threading
import time

from ..workflow.service import WorkflowService
from ..runtime_services import RUNTIME_SERVICES
from ..tool_contract import contract_hash
from ._shared import (
    _render_client,
)

# The health check compares every registered tool schema against the contract.
# Its answer only changes when the runtime is recomposed, so workflow tools
# reuse it for a short while instead of recomputing it on every call.
_TOOL_SURFACE_MEMO_SECONDS = 30.0
_tool_surface_memo: tuple[tuple[object, ...], float, tuple[bool, str]] | None = None
_tool_surface_lock = threading.Lock()
_clock = time.monotonic


def _probe_tool_surface() -> tuple[bool, str]:
    capability = RUNTIME_SERVICES.require_tool_bindings()["mcp_server_health"]()[
        "capability"
    ]
    return bool(capability["ok"]), contract_hash()


def _tool_surface_identity() -> tuple[object, ...]:
    return (
        RUNTIME_SERVICES.require_tool_bindings(),
        RUNTIME_SERVICES.mcp,
        RUNTIME_SERVICES.tool_registry,
        RUNTIME_SERVICES.active_advanced,
        os.environ.get("HWPX_SKILL_VERSION"),
    )


def _same_identity(left: tuple[object, ...], right: tuple[object, ...]) -> bool:
    return len(left) == len(right) and all(
        a is b or (isinstance(a, (bool, str)) and a == b)
        for a, b in zip(left, right)
    )


def _tool_surface_state() -> tuple[bool, str]:
    global _tool_surface_memo
    identity = _tool_surface_identity()
    now = _clock()
    with _tool_surface_lock:
        memo = _tool_surface_memo
        if (
            memo is not None
            and _same_identity(memo[0], identity)
            and 0 <= now - memo[1] < _TOOL_SURFACE_MEMO_SECONDS
        ):
            return memo[2]
    state = _probe_tool_surface()
    with _tool_surface_lock:
        _tool_surface_memo = (identity, now, state)
    return state


def _reset_tool_surface_memo() -> None:
    global _tool_surface_memo
    with _tool_surface_lock:
        _tool_surface_memo = None


def _workflow_service() -> WorkflowService:
    """Build a request-scoped service over the durable configured store."""

    capability_ok, tool_spec_hash = _tool_surface_state()
    return WorkflowService(
        RUNTIME_SERVICES.require_tool_bindings(),
        capability_ok=capability_ok,
        render_client=_render_client(),
        tool_spec_hash=tool_spec_hash,
    )


def start_workflow(
    family: str,
    idempotency_key: str,
    source_path: str = None,
    output_path: str = None,
    expected_revision: str = None,
    parameters: dict = None,
    budget: dict = None,
    policy: dict = None,
) -> dict:
    """타입화된 작업을 서버 강제 durable workflow로 시작합니다."""

    return _workflow_service().start(
        family=family,
        idempotency_key=idempotency_key,
        source_path=source_path,
        output_path=output_path,
        expected_revision=expected_revision,
        parameters=parameters,
        budget=budget,
        policy=policy,
    )


def get_workflow(workflow_id: str) -> dict:
    """현재 상태와 증거를 구조화된 workflow receipt로 조회합니다."""

    return _workflow_service().get(workflow_id)


def get_workflow_result(workflow_id: str, action_hash: str = None) -> dict:
    """암호화 저장된 workflow primitive 결과를 content hash와 함께 조회합니다."""

    return _workflow_service().workflow_result(workflow_id, action_hash=action_hash)


def continue_workflow(workflow_id: str) -> dict:
    """서버 정책에 따라 workflow를 다음 durable 경계까지 진행합니다."""

    return _workflow_service().continue_workflow(workflow_id)


def approve_workflow_decision(
    workflow_id: str,
    approved: bool,
    action_hash: str = None,
) -> dict:
    """decision 상태의 정확한 계획 action을 승인하거나 거절합니다."""

    return _workflow_service().approve_decision(
        workflow_id,
        approved=approved,
        action_hash=action_hash,
    )


def cancel_workflow(workflow_id: str, reason: str = "CLIENT_CANCELLED") -> dict:
    """아직 terminal이 아닌 workflow를 취소합니다."""

    return _workflow_service().cancel(workflow_id, reason=reason)


def resume_workflow(workflow_id: str) -> dict:
    """재시작 후 durable receipt를 기준으로 안전하게 workflow를 재개합니다."""

    return _workflow_service().resume(workflow_id)


__all__ = [
    "start_workflow",
    "get_workflow",
    "get_workflow_result",
    "continue_workflow",
    "approve_workflow_decision",
    "cancel_workflow",
    "resume_workflow",
]
