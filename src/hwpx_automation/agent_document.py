# SPDX-License-Identifier: Apache-2.0
"""Thin MCP transport adapter for the canonical automation agent runtime.

This module deliberately owns no path grammar, selector parser, document
projection, or mutation compiler. Those semantics live in
``hwpx_automation.office.agent``; the frozen core 4.x compatibility copy is
verified against it by the parity corpus.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Annotated, Any, Iterator, Literal

from pydantic import Field

from hwpx_automation.office.agent import (
    AGENT_BATCH_SCHEMA,
    AgentBatchResult,
    AgentContractError,
    AgentError,
    HwpxAgentDocument,
    agent_catalog,
    agent_json_schemas,
    apply_document_commands as apply_core_document_commands,
    catalog_hash,
    human_help,
)
from hwpx_automation.office.agent.blueprint import (
    BLUEPRINT_REPLAY_RESULT_SCHEMA,
    BlueprintReplayResult,
    blueprint_catalog,
    blueprint_catalog_hash,
    blueprint_human_help,
    blueprint_json_schemas,
    dump_document_blueprint as dump_core_document_blueprint,
    replay_document_blueprint as replay_core_document_blueprint,
)

_EMPTY_REVISION = "sha256:" + hashlib.sha256(b"").hexdigest()
_DEFAULT_REQUIREMENTS = ("package", "reopen", "openSafety", "semanticDiff", "bytePreservation")
_SCHEMAS = agent_json_schemas()
_CATALOG = agent_catalog()
_BLUEPRINT_SCHEMAS = blueprint_json_schemas()
_BLUEPRINT_CATALOG = blueprint_catalog()

# FastMCP builds its input JSON Schema from the public function annotation.
# Supplying the core-generated command union here prevents a second handwritten
# MCP command schema from becoming an independent source of truth.
AgentCommandList = Annotated[
    list[dict[str, Any]],
    Field(
        min_length=1,
        max_length=int(_CATALOG["limits"]["maxCommands"]),
        json_schema_extra={"items": _SCHEMAS["command"]},
    ),
]
AgentViewDepth = Annotated[
    int,
    Field(ge=0, le=int(_CATALOG["limits"]["maxViewDepth"])),
]
AgentChildLimit = Annotated[
    int,
    Field(ge=1, le=int(_CATALOG["limits"]["maxChildrenPerNode"])),
]
AgentQueryLimit = Annotated[
    int,
    Field(ge=1, le=int(_CATALOG["limits"]["maxQueryResults"])),
]
AgentSelector = Annotated[
    str,
    Field(min_length=1, max_length=int(_CATALOG["limits"]["maxSelectorChars"])),
]
AgentRevision = Annotated[
    str | None,
    Field(pattern=r"^sha256:[a-f0-9]{64}$"),
]
BlueprintPath = Annotated[
    str,
    Field(min_length=1, max_length=4096),
]
BlueprintReplayRequest = Annotated[
    dict[str, Any],
    Field(json_schema_extra=_BLUEPRINT_SCHEMAS["replay"]),
]
BlueprintMode = Literal["portable", "source-bound"]


def _suggestion(code: str) -> str:
    suggestions = {
        "not_found": "Check the document path, then retry.",
        "stale_revision": "Read the document again and retry with its current revision.",
        "ambiguous_target": "Query again and choose one unique canonical path.",
        "volatile_target": "Refresh the positional path from the current document revision.",
        "verification_failed": "Do not publish the output; inspect the verification evidence.",
    }
    return suggestions.get(code, "Inspect the target and the shared agent catalog before retrying.")


def _agent_error(exc: BaseException, *, target: str) -> AgentError:
    if isinstance(exc, AgentContractError):
        code = exc.code
        message = str(exc)
        resolved_target = exc.target or target
    elif isinstance(exc, FileNotFoundError):
        code = "not_found"
        message = str(exc)
        resolved_target = target
    elif isinstance(exc, (PermissionError, OSError)):
        code = "verification_failed"
        message = f"{type(exc).__name__}: {exc}"
        resolved_target = target
    else:
        code = "verification_failed"
        message = f"{type(exc).__name__}: {exc}"
        resolved_target = target
    recoverability = "retryable" if code == "stale_revision" else "terminal"
    if code in {"not_found", "ambiguous_target", "volatile_target", "unsupported_content", "contract_changed"}:
        recoverability = "needs-review"
    return AgentError(
        code=code,
        message=message[:4096],
        target=resolved_target,
        recoverability=recoverability,
        suggestion=getattr(exc, "suggestion", None) or _suggestion(code),
    )


def error_payload(exc: BaseException, *, target: str) -> dict[str, Any]:
    """Return the shared structured error shape for read-side failures."""

    return {"ok": False, "error": _agent_error(exc, target=target).to_dict()}


def batch_error_payload(
    exc: BaseException,
    *,
    input_filename: str,
    output_filename: str,
    dry_run: bool,
) -> dict[str, Any]:
    """Return a valid batch-result failure when the MCP boundary blocks a write."""

    revision = _EMPTY_REVISION
    try:
        data = Path(input_filename).read_bytes()
    except OSError:
        pass
    else:
        revision = "sha256:" + hashlib.sha256(data).hexdigest()
    return AgentBatchResult(
        ok=False,
        rolled_back=True,
        dry_run=dry_run,
        input_revision=revision,
        document_revision=revision,
        output_filename=output_filename,
        verification_report={
            "schemaVersion": AGENT_BATCH_SCHEMA,
            "catalogHash": catalog_hash(),
            "boundary": "mcp-capability-and-locator",
        },
        error=_agent_error(exc, target="batch"),
    ).to_dict()


class ScopedIdempotencyStore(MutableMapping[str, Any]):
    """Namespace a core caller-owned store inside the server's bounded cache."""

    def __init__(
        self,
        backing: MutableMapping[str, Any],
        namespace: str,
        *,
        family: str = "agent-document",
    ) -> None:
        self._backing = backing
        self._prefix = f"{family}:{namespace}:"

    def _key(self, key: str) -> str:
        return self._prefix + key

    def __getitem__(self, key: str) -> Any:
        return self._backing[self._key(key)]

    def __setitem__(self, key: str, value: Any) -> None:
        self._backing[self._key(key)] = value

    def __delitem__(self, key: str) -> None:
        del self._backing[self._key(key)]

    def __iter__(self) -> Iterator[str]:
        for key in self._backing:
            if key.startswith(self._prefix):
                yield key[len(self._prefix) :]

    def __len__(self) -> int:
        return sum(1 for _ in self)


def read_document_node(
    filename: str,
    *,
    path: str,
    depth: int,
    child_limit: int,
    expected_revision: str | None,
) -> dict[str, Any]:
    with HwpxAgentDocument.open(filename) as document:
        return document.get(
            path,
            depth=depth,
            child_limit=child_limit,
            expected_revision=expected_revision,
        ).to_dict()


def query_document_node_records(
    filename: str,
    *,
    selector: str,
    limit: int,
    node_depth: int,
    child_limit: int,
    expected_revision: str | None,
) -> dict[str, Any]:
    with HwpxAgentDocument.open(filename) as document:
        return document.query(
            selector,
            limit=limit,
            node_depth=node_depth,
            child_limit=child_limit,
            expected_revision=expected_revision,
        ).to_dict()


def apply_document_command_batch(
    *,
    filename: str,
    output: str,
    commands: list[Mapping[str, Any]],
    expected_revision: str | None,
    idempotency_key: str | None,
    dry_run: bool,
    quality: str | Mapping[str, Any] | None,
    verification_requirements: list[str] | None,
    overwrite: bool,
    idempotency_store: MutableMapping[str, Any],
) -> dict[str, Any]:
    batch = {
        "schemaVersion": AGENT_BATCH_SCHEMA,
        "input": {"filename": filename},
        "output": {"filename": output, "overwrite": overwrite},
        "commands": [dict(command) for command in commands],
        "expectedRevision": expected_revision,
        "idempotencyKey": idempotency_key,
        "dryRun": dry_run,
        "quality": quality,
        "verificationRequirements": list(
            verification_requirements or _DEFAULT_REQUIREMENTS
        ),
    }
    return apply_core_document_commands(
        batch,
        idempotency_store=idempotency_store,
    ).to_dict()


def dump_blueprint_document(
    *,
    filename: str,
    path: str,
    mode: str,
    expected_revision: str | None,
    output: str | None,
    overwrite: bool,
    include_assets: bool,
    require_replayable: bool,
    include_manifest: bool,
) -> dict[str, Any]:
    result = dump_core_document_blueprint(
        filename,
        path=path,
        mode=mode,
        expected_revision=expected_revision,
        output=output,
        overwrite=overwrite,
        include_assets=include_assets,
        require_replayable=require_replayable,
    )
    return result.to_dict(include_manifest=include_manifest)


def replay_blueprint_document(
    request: Mapping[str, Any],
    *,
    idempotency_store: MutableMapping[str, Any],
) -> dict[str, Any]:
    return replay_core_document_blueprint(
        dict(request),
        idempotency_store=idempotency_store,
    ).to_dict()


def blueprint_replay_error_payload(
    exc: BaseException,
    *,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    target = request.get("target") if isinstance(request.get("target"), Mapping) else {}
    bundle = request.get("bundle") if isinstance(request.get("bundle"), Mapping) else {}
    input_filename = str(target.get("input") or "")
    output_filename = str(target.get("output") or "")
    revision = _EMPTY_REVISION
    try:
        revision = "sha256:" + hashlib.sha256(Path(input_filename).read_bytes()).hexdigest()
    except OSError:
        pass
    blueprint_hash = str(bundle.get("blueprintHash") or "")
    if not blueprint_hash.startswith("sha256:") or len(blueprint_hash) != 71:
        blueprint_hash = "sha256:" + "0" * 64
    return BlueprintReplayResult(
        ok=False,
        rolled_back=True,
        dry_run=bool(request.get("dryRun", False)),
        input_revision=revision,
        document_revision=revision,
        output_filename=output_filename,
        blueprint_hash=blueprint_hash,
        verification_report={
            "schemaVersion": BLUEPRINT_REPLAY_RESULT_SCHEMA,
            "catalogHash": blueprint_catalog_hash(),
            "boundary": "mcp-capability-and-locator",
        },
        error=_agent_error(exc, target="replay"),
    ).to_dict()


def tool_help() -> dict[str, str]:
    """Generate MCP descriptions from the same catalog as ``hwpx help``."""

    selector_examples = ", ".join(_CATALOG["query"]["examples"])
    return {
        "get": (
            "Get one bounded HWPX semantic node by canonical path. "
            f"Shared catalog {catalog_hash()}.\n\n{human_help()}"
        ),
        "query": (
            "Query bounded semantic nodes with selector v1 and return canonical paths. "
            f"Examples: {selector_examples}. Shared catalog {catalog_hash()}."
        ),
        "apply": (
            "Apply one heterogeneous atomic HWPX command batch using only the shared "
            "set/add/remove/move/copy union; all commands commit once or roll back. "
            f"Shared catalog {catalog_hash()}."
        ),
        "dumpBlueprint": (
            "Dump one revision-bound HWPX document/subtree into a validated typed .hwpxbp; "
            "returns bounded manifest/fidelity evidence and never exposes raw XML. "
            f"Shared blueprint catalog {blueprint_catalog_hash()}.\n\n{blueprint_human_help()}"
        ),
        "replayBlueprint": (
            "Atomically replay one validated typed blueprint request with strict dependency mapping, "
            "caller-owned idempotency, one save, rollback, lossless/openSafety evidence, and no session state. "
            f"Shared blueprint catalog {blueprint_catalog_hash()}."
        ),
    }


__all__ = [
    "AgentChildLimit",
    "AgentCommandList",
    "AgentQueryLimit",
    "AgentRevision",
    "AgentSelector",
    "AgentViewDepth",
    "BlueprintMode",
    "BlueprintPath",
    "BlueprintReplayRequest",
    "ScopedIdempotencyStore",
    "apply_document_command_batch",
    "batch_error_payload",
    "blueprint_replay_error_payload",
    "dump_blueprint_document",
    "error_payload",
    "query_document_node_records",
    "read_document_node",
    "replay_blueprint_document",
    "tool_help",
]
