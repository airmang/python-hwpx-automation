# SPDX-License-Identifier: Apache-2.0
"""Agent-document automation handlers for the optional MCP adapter."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any


from ..document_state import document_state_payload
from ..errors import HwpDocumentError
from ..storage import require_hwpx_package
from ..agent_document import (
    AgentChildLimit,
    AgentCommandList,
    AgentQueryLimit,
    AgentRevision,
    AgentSelector,
    AgentViewDepth,
    BlueprintMode,
    BlueprintPath,
    BlueprintReplayRequest,
    ScopedIdempotencyStore,
    apply_document_command_batch,
    batch_error_payload as agent_batch_error_payload,
    blueprint_replay_error_payload,
    dump_blueprint_document,
    error_payload as agent_error_payload,
    query_document_node_records,
    read_document_node,
    replay_blueprint_document,
    tool_help as agent_tool_help,
)
from .. import quality as quality_contract
from ..utils.helpers import resolve_path
from ..runtime_services import RUNTIME_SERVICES


def get_document_node(
    filename: str,
    path: str = "/",
    depth: AgentViewDepth = 1,
    child_limit: AgentChildLimit = 50,
    expected_revision: AgentRevision = None,
) -> dict:
    """Generated from the shared python-hwpx agent catalog."""
    try:
        resolved = resolve_path(filename)
        payload = read_document_node(
            resolved,
            path=path,
            depth=depth,
            child_limit=child_limit,
            expected_revision=expected_revision,
        )
        payload.update(document_state_payload(resolved))
        return payload
    except Exception as exc:
        return agent_error_payload(exc, target=path or "filename")


def query_document_nodes(
    filename: str,
    selector: AgentSelector,
    limit: AgentQueryLimit = 20,
    node_depth: AgentViewDepth = 0,
    child_limit: AgentChildLimit = 20,
    expected_revision: AgentRevision = None,
) -> dict:
    """Generated from the shared python-hwpx agent catalog."""
    try:
        resolved = resolve_path(filename)
        payload = query_document_node_records(
            resolved,
            selector=selector,
            limit=limit,
            node_depth=node_depth,
            child_limit=child_limit,
            expected_revision=expected_revision,
        )
        payload.update(document_state_payload(resolved))
        return payload
    except Exception as exc:
        return agent_error_payload(exc, target=selector or "filename")


def apply_document_commands(
    filename: str,
    output: str,
    commands: AgentCommandList,
    expected_revision: AgentRevision = None,
    idempotency_key: str = None,
    dry_run: bool = False,
    quality: str | dict[str, Any] | None = "transparent",
    verification_requirements: list[str] | None = None,
    overwrite: bool = False,
) -> dict:
    """Generated from the shared python-hwpx agent catalog."""
    resolved_input = filename
    resolved_output = output
    try:
        resolved_input = resolve_path(filename)
        resolved_output = resolve_path(output)
        require_hwpx_package(resolved_input, output=resolved_output)
        quality_contract.assert_write_capability()
        store = ScopedIdempotencyStore(
            RUNTIME_SERVICES.idempotency_cache,
            namespace=str(Path(resolved_input).resolve()),
        )
        payload = apply_document_command_batch(
            filename=resolved_input,
            output=resolved_output,
            commands=commands,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            dry_run=dry_run,
            quality=quality,
            verification_requirements=verification_requirements,
            overwrite=overwrite,
            idempotency_store=store,
        )
        while (
            len(RUNTIME_SERVICES.idempotency_cache)
            > RUNTIME_SERVICES.max_idempotency_cache_entries
        ):
            RUNTIME_SERVICES.idempotency_cache.pop(
                next(iter(RUNTIME_SERVICES.idempotency_cache))
            )
        state_path = (
            resolved_output
            if payload.get("ok") and not dry_run and Path(resolved_output).exists()
            else resolved_input
        )
        if Path(state_path).exists():
            payload.update(document_state_payload(state_path))
        return payload
    except HwpDocumentError:
        raise
    except Exception as exc:
        return agent_batch_error_payload(
            exc,
            input_filename=resolved_input,
            output_filename=resolved_output,
            dry_run=dry_run,
        )


def dump_document_blueprint(
    filename: str,
    path: BlueprintPath = "/",
    mode: BlueprintMode = "portable",
    expected_revision: AgentRevision = None,
    output: str = None,
    overwrite: bool = False,
    include_assets: bool = True,
    require_replayable: bool = True,
    include_manifest: bool = True,
) -> dict:
    """Generated from the shared python-hwpx blueprint catalog."""
    target = path or filename
    try:
        resolved_input = resolve_path(filename)
        resolved_output = resolve_path(output) if output else None
        if resolved_output is not None:
            quality_contract.assert_write_capability()
        payload = dump_blueprint_document(
            filename=resolved_input,
            path=path,
            mode=mode,
            expected_revision=expected_revision,
            output=resolved_output,
            overwrite=overwrite,
            include_assets=include_assets,
            require_replayable=require_replayable,
            include_manifest=include_manifest,
        )
        payload.update(document_state_payload(resolved_input))
        return payload
    except Exception as exc:
        return agent_error_payload(exc, target=target)


def replay_document_blueprint(request: BlueprintReplayRequest) -> dict:
    """Generated from the shared python-hwpx blueprint catalog."""
    normalized = copy.deepcopy(request)
    try:
        bundle = normalized.get("bundle")
        target = normalized.get("target")
        if not isinstance(bundle, dict) or not isinstance(target, dict):
            raise ValueError("request bundle and target must be objects")
        bundle["filename"] = resolve_path(str(bundle.get("filename") or ""))
        target["input"] = resolve_path(str(target.get("input") or ""))
        target["output"] = resolve_path(str(target.get("output") or ""))
        quality_contract.assert_write_capability()
        store = ScopedIdempotencyStore(
            RUNTIME_SERVICES.idempotency_cache,
            namespace=str(Path(target["input"]).resolve()),
            family="agent-blueprint",
        )
        payload = replay_blueprint_document(normalized, idempotency_store=store)
        while (
            len(RUNTIME_SERVICES.idempotency_cache)
            > RUNTIME_SERVICES.max_idempotency_cache_entries
        ):
            RUNTIME_SERVICES.idempotency_cache.pop(
                next(iter(RUNTIME_SERVICES.idempotency_cache))
            )
        state_path = (
            target["output"]
            if payload.get("ok")
            and not payload.get("dryRun")
            and Path(target["output"]).exists()
            else target["input"]
        )
        if Path(state_path).exists():
            payload.update(document_state_payload(state_path))
        return payload
    except Exception as exc:
        return blueprint_replay_error_payload(exc, request=normalized)


_AGENT_TOOL_HELP = agent_tool_help()


get_document_node.__doc__ = _AGENT_TOOL_HELP["get"]


query_document_nodes.__doc__ = _AGENT_TOOL_HELP["query"]


apply_document_commands.__doc__ = _AGENT_TOOL_HELP["apply"]


dump_document_blueprint.__doc__ = _AGENT_TOOL_HELP["dumpBlueprint"]


replay_document_blueprint.__doc__ = _AGENT_TOOL_HELP["replayBlueprint"]


get_document_node.__doc__ = _AGENT_TOOL_HELP["get"]


query_document_nodes.__doc__ = _AGENT_TOOL_HELP["query"]


apply_document_commands.__doc__ = _AGENT_TOOL_HELP["apply"]


dump_document_blueprint.__doc__ = _AGENT_TOOL_HELP["dumpBlueprint"]


replay_document_blueprint.__doc__ = _AGENT_TOOL_HELP["replayBlueprint"]


__all__ = [
    "get_document_node",
    "query_document_nodes",
    "apply_document_commands",
    "dump_document_blueprint",
    "replay_document_blueprint",
]
