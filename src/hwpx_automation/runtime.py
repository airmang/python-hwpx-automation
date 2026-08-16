# SPDX-License-Identifier: Apache-2.0
"""FastMCP runtime adapter for the canonical automation application."""

from __future__ import annotations

import json
import re
from typing import Any, cast

import mcp.types as mcp_types
from mcp.server.fastmcp import FastMCP
from hwpx_automation.office.agent import AgentContractError

from . import __version__
from .configuration import env_value
from . import quality as quality_contract
from .errors import build_error_payload, mcp_code_for_error
from .hwpx_ops import HwpxOperationError
from .network_policy import NetworkPolicyError
from .tool_contract import (
    register_fastmcp_tools,
)
from .workspace import (
    WorkspaceConfigurationError,
    WorkspacePathError,
)
from .fastmcp_adapter import configure_runtime
from .runtime_services import RUNTIME_SERVICES
from .tool_bindings import TOOL_BINDINGS


def _error_data(
    payload: dict[str, Any],
    *,
    tool_name: str | None = None,
    extra_data: dict | None = None,
) -> mcp_types.ErrorData:
    error_code = str(payload["code"])
    data: dict[str, object] = {
        "errorCode": error_code,
        "error": payload,
    }
    if tool_name is not None:
        data["tool"] = tool_name
    if extra_data:
        data.update(extra_data)
    return mcp_types.ErrorData(
        code=mcp_code_for_error(error_code),
        message=f"{error_code}: {payload['message']}",
        data=data,
    )


def _first_text_content(content: object) -> str | None:
    if not isinstance(content, list):
        return None
    for item in content:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            stripped = text.strip()
            if stripped:
                return stripped
        if isinstance(item, dict):
            value = item.get("text")
            if isinstance(value, str):
                stripped = value.strip()
                if stripped:
                    return stripped
    return None


def _exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _classified_error_payload(exc: BaseException | None) -> dict[str, Any]:
    if exc is not None:
        for item in _exception_chain(exc):
            if isinstance(item, HwpxOperationError):
                return item.to_payload()
            if isinstance(item, AgentContractError):
                return build_error_payload(
                    code=item.code,
                    message="문서 에이전트 계약을 안전하게 해석할 수 없습니다.",
                )
            if isinstance(item, WorkspacePathError):
                message = (
                    "대화에 업로드된 파일의 내부 경로는 로컬 MCP 서버에서 접근할 수 없습니다."
                    if item.code == "CLIENT_UPLOAD_PATH_UNAVAILABLE"
                    else "요청한 경로가 허용된 HWPX 작업공간 경계를 벗어났습니다."
                )
                return build_error_payload(
                    code=item.code,
                    message=message,
                    details=item.safe_details(),
                )
            if isinstance(item, WorkspaceConfigurationError):
                return build_error_payload(
                    code=item.code,
                    message="HWPX 작업공간 루트 구성이 유효하지 않습니다.",
                )
            if isinstance(item, NetworkPolicyError):
                return build_error_payload(
                    code=item.code,
                    message="기본 네트워크 정책이 요청한 대상을 차단했습니다.",
                    details=item.safe_details(),
                )
            if isinstance(item, FileNotFoundError):
                return build_error_payload(
                    code="DOCUMENT_NOT_FOUND",
                    message="요청한 문서를 허용된 작업공간에서 찾을 수 없습니다.",
                )
            if isinstance(item, PermissionError):
                return build_error_payload(
                    code="PERMISSION_DENIED",
                    message="요청한 문서에 접근할 권한이 없습니다.",
                )
            if isinstance(item, ValueError):
                return build_error_payload(
                    code="INVALID_ARGUMENT",
                    message="도구 인자가 스키마 또는 값 제약을 만족하지 않습니다.",
                )
    return build_error_payload(
        code="TOOL_EXECUTION_FAILED",
        message="도구 실행이 안전하게 완료되지 않았습니다.",
    )


def _gate_or_plain_error(
    tool_name: str,
    *,
    exc: BaseException | None = None,
) -> mcp_types.ErrorData:
    """Rebuild a structured gate/skew error from the stash, else a plain error."""

    gate = quality_contract.take_last_gate_error()
    if isinstance(gate, quality_contract.CapabilitySkewError):
        return _error_data(
            build_error_payload(
                code=gate.code,
                message="설치된 core/automation/plugin 기능 계약이 일치하지 않아 쓰기를 차단했습니다.",
                details={"capability": gate.state},
            ),
            tool_name=tool_name,
            extra_data={"errorCode": gate.code, "capability": gate.state},
        )
    if isinstance(gate, quality_contract.QualityGateError):
        return _error_data(
            build_error_payload(
                code=gate.code,
                message="문서 품질 게이트가 출력을 거부했습니다.",
                details={"visualComplete": gate.block},
                retryable=True,
            ),
            tool_name=tool_name,
            extra_data={
                "errorCode": gate.code,
                "visualComplete": gate.block,
                "suggestedRetry": gate.block.get("suggestedRetry"),
            },
        )
    return _error_data(_classified_error_payload(exc), tool_name=tool_name)


def _failure_code_from_payload(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    failed = payload.get("ok") is False or payload.get("success") is False
    failed = failed or payload.get("isError") is True
    if not failed:
        return None
    candidates: list[object] = [payload.get("errorCode"), payload.get("code")]
    nested_error = payload.get("error")
    if isinstance(nested_error, dict):
        candidates.extend([nested_error.get("errorCode"), nested_error.get("code")])
    nested_errors = payload.get("errors")
    if (
        isinstance(nested_errors, list)
        and nested_errors
        and isinstance(nested_errors[0], dict)
    ):
        candidates.extend(
            [nested_errors[0].get("errorCode"), nested_errors[0].get("code")]
        )
    for candidate in candidates:
        if isinstance(candidate, str) and re.fullmatch(
            r"[A-Z][A-Z0-9_]{2,63}", candidate
        ):
            return candidate
    return "TOOL_EXECUTION_FAILED"


def _result_failure_error(
    tool_name: str, payload: object
) -> mcp_types.ErrorData | None:
    error_code = _failure_code_from_payload(payload)
    if error_code is None:
        return None
    gate_error = _gate_or_plain_error(tool_name)
    if cast(dict[str, Any], gate_error.data).get("errorCode") != "TOOL_EXECUTION_FAILED":
        return gate_error
    return _error_data(
        build_error_payload(
            code=error_code,
            message="도구가 요청을 안전하게 완료하지 못했습니다.",
        ),
        tool_name=tool_name,
    )


async def _strict_call_tool_handler(req: mcp_types.CallToolRequest):
    tool_name = req.params.name
    arguments = req.params.arguments or {}
    quality_contract.clear_last_gate_error()
    try:
        result = await RUNTIME_SERVICES.require_mcp().call_tool(tool_name, arguments)
    except Exception as exc:
        # FastMCP wraps a tool's exception in ToolError, so the structured gate/
        # skew error never matches a specific `except` here — recover it from the
        # stash the exception left on construction (plan §2 Phase F).
        return _gate_or_plain_error(tool_name, exc=exc)

    if isinstance(result, mcp_types.CreateTaskResult):
        return mcp_types.ServerResult(result)

    if isinstance(result, mcp_types.CallToolResult):
        if bool(result.isError):
            return _gate_or_plain_error(tool_name)
        embedded_failure = _result_failure_error(tool_name, result.structuredContent)
        if embedded_failure is not None:
            return embedded_failure
        return mcp_types.ServerResult(result)

    if isinstance(result, tuple) and len(result) == 2:
        unstructured_content = list(result[0])
        structured_content = result[1]
    elif isinstance(result, dict):
        structured_content = result
        unstructured_content = [
            mcp_types.TextContent(
                type="text", text=json.dumps(result, ensure_ascii=False, indent=2)
            )
        ]
    elif isinstance(result, str):
        structured_content = None
        unstructured_content = [mcp_types.TextContent(type="text", text=result)]
    elif hasattr(result, "__iter__"):
        structured_content = None
        unstructured_content = list(result)
    else:
        return _error_data(
            build_error_payload(
                code="TOOL_EXECUTION_FAILED",
                message="도구가 지원되지 않는 결과 형식을 반환했습니다.",
                details={"resultType": type(result).__name__},
            ),
            tool_name=tool_name,
        )

    embedded_failure = _result_failure_error(tool_name, structured_content)
    if embedded_failure is not None:
        return embedded_failure

    return mcp_types.ServerResult(
        mcp_types.CallToolResult(
            content=cast(list[mcp_types.ContentBlock], unstructured_content),
            structuredContent=cast(dict[str, Any] | None, structured_content),
            isError=False,
        )
    )


def _advanced_enabled() -> bool:
    return env_value("ADVANCED", "0") == "1"


def _compose_runtime(*, advanced: bool, replace: bool) -> tuple[FastMCP, Any]:
    composed = FastMCP("python-hwpx-automation")
    if replace:
        RUNTIME_SERVICES.reconfigure_runtime(
            mcp=composed,
            active_advanced=advanced,
            tool_bindings=TOOL_BINDINGS,
        )
    else:
        RUNTIME_SERVICES.configure_runtime(
            mcp=composed,
            active_advanced=advanced,
            tool_bindings=TOOL_BINDINGS,
        )
    configure_runtime(composed, __version__, _strict_call_tool_handler)
    registry = register_fastmcp_tools(composed, TOOL_BINDINGS, advanced=advanced)
    from .resources import register_canonical_resources

    register_canonical_resources(composed)
    RUNTIME_SERVICES.install_registry(registry)
    return composed, registry


def refresh_runtime_for_environment() -> None:
    """Recompose only when the released import-time profile flag changed."""

    global ACTIVE_ADVANCED, TOOL_REGISTRY, mcp
    requested = _advanced_enabled()
    if requested == ACTIVE_ADVANCED:
        return
    mcp, TOOL_REGISTRY = _compose_runtime(advanced=requested, replace=True)
    ACTIVE_ADVANCED = requested


ACTIVE_ADVANCED = _advanced_enabled()
mcp, TOOL_REGISTRY = _compose_runtime(
    advanced=ACTIVE_ADVANCED,
    replace=RUNTIME_SERVICES.mcp is not None,
)


__all__ = [
    "ACTIVE_ADVANCED",
    "TOOL_REGISTRY",
    "mcp",
    "refresh_runtime_for_environment",
    "_strict_call_tool_handler",
]
