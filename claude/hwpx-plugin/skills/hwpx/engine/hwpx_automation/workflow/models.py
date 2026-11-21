# SPDX-License-Identifier: Apache-2.0
"""Versioned contracts for durable server-side HWPX workflows.

These models deliberately accept typed work rather than a free-form prompt.  Prompt
bodies belong to the MCP request boundary, not the durable event ledger.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator


WORKFLOW_SCHEMA_VERSION = "hwpx.workflow.v1"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value: Any) -> str:
    raw = value if isinstance(value, bytes) else canonical_json(value).encode("utf-8")
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


_SENSITIVE_LEDGER_KEY_PARTS = ("prompt", "instruction", "body", "text", "content", "bytes", "binary")


def sanitize_ledger_payload(value: Any, *, key: str = "value") -> Any:
    """Remove prompt/document content before an event reaches durable storage."""

    normalized_key = "".join(character for character in key.lower() if character.isalnum())
    already_a_hash = normalized_key.endswith("hash") or normalized_key.endswith("revision")
    if not already_a_hash and any(part in normalized_key for part in _SENSITIVE_LEDGER_KEY_PARTS):
        return {"redacted": True, "hash": content_hash(value)}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"redacted": True, "hash": content_hash(bytes(value))}
    if isinstance(value, Mapping):
        return {str(nested_key): sanitize_ledger_payload(nested, key=str(nested_key)) for nested_key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_ledger_payload(nested, key=key) for nested in value]
    return value


class WorkFamily(str, Enum):
    READ_EXTRACT = "read_extract"
    TRANSACTIONAL_EDIT = "transactional_edit"
    KNOWN_TEMPLATE_FILL = "known_template_fill"
    UNKNOWN_FORM_FILL = "unknown_form_fill"
    STRUCTURAL_TABLE_EDIT = "structural_table_edit"
    TYPED_AUTHORING = "typed_authoring"
    MUST_ABSTAIN = "must_abstain"


class WorkflowState(str, Enum):
    INTAKE = "intake"
    RECON = "recon"
    PLAN = "plan"
    DECISION = "decision"
    EXECUTE = "execute"
    VERIFY = "verify"
    REPAIR = "repair"
    COMPLETED = "completed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATES = frozenset(
    {
        WorkflowState.COMPLETED,
        WorkflowState.NEEDS_REVIEW,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    }
)


class WorkflowBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_attempts: int = Field(default=3, ge=1, le=20)
    max_tool_calls: int = Field(default=50, ge=1, le=1000)
    max_elapsed_seconds: int = Field(default=900, ge=1, le=86_400)
    max_repair_rounds: int = Field(default=3, ge=0, le=10)


class WorkflowPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    preserve_original: bool = True
    require_expected_revision: bool = True
    require_decision_for_destructive: bool = True
    require_open_safety: bool = True
    require_verified_completion: bool = True
    require_real_hancom_render: bool = False

    @field_validator("preserve_original")
    @classmethod
    def original_preservation_cannot_be_disabled(cls, value: bool) -> bool:
        if not value:
            raise ValueError("server workflows always preserve the original document")
        return value


def confined_workflow_path(value: str | None) -> str | None:
    """Normalize a workflow path and require it to be inside the workspace."""

    if not value:
        return None
    from ..workspace import WorkspaceResolver

    resolver = WorkspaceResolver.from_environment()
    return str(resolver.resolve(value, must_exist=False))


class WorkOrder(BaseModel):
    """Typed, restartable request accepted by the workflow engine.

    ``parameters`` may contain structured adapter input but never raw bytes.  Event
    records persist only its hash and key list, not its values.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = WORKFLOW_SCHEMA_VERSION
    family: WorkFamily
    source_path: str | None = None
    output_path: str | None = None
    expected_revision: str | None = None
    idempotency_key: str = Field(min_length=8, max_length=200)
    parameters: dict[str, Any] = Field(default_factory=dict)
    budget: WorkflowBudget = Field(default_factory=WorkflowBudget)
    policy: WorkflowPolicy = Field(default_factory=WorkflowPolicy)

    @field_validator("schema_version")
    @classmethod
    def supported_schema(cls, value: str) -> str:
        if value != WORKFLOW_SCHEMA_VERSION:
            raise ValueError(f"unsupported workflow schema: {value}")
        return value

    @field_validator("source_path", "output_path")
    @classmethod
    def normalize_path(cls, value: str | None) -> str | None:
        return str(Path(value).expanduser().resolve()) if value else None

    @field_validator("parameters")
    @classmethod
    def reject_binary_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        def walk(item: Any) -> None:
            if isinstance(item, (bytes, bytearray, memoryview)):
                raise ValueError("document bytes are not accepted in workflow parameters")
            if isinstance(item, Mapping):
                for nested in item.values():
                    walk(nested)
            elif isinstance(item, (list, tuple)):
                for nested in item:
                    walk(nested)

        walk(value)
        return value

    def fingerprint(self) -> str:
        return content_hash(self.model_dump(mode="json"))

    def ledger_summary(self) -> dict[str, Any]:
        """Return the non-content request summary safe for append-only events."""

        return {
            "schemaVersion": self.schema_version,
            "family": self.family.value,
            "sourcePathHash": content_hash(self.source_path) if self.source_path else None,
            "outputPathHash": content_hash(self.output_path) if self.output_path else None,
            "expectedRevision": self.expected_revision,
            "parameterKeys": sorted(self.parameters),
            "parametersHash": content_hash(self.parameters),
            "workOrderHash": self.fingerprint(),
        }


class WorkflowEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_id: str
    index: int = Field(ge=0)
    event_type: str
    from_state: WorkflowState | None
    to_state: WorkflowState
    occurred_at: datetime
    payload: dict[str, Any]
    previous_hash: str | None
    event_hash: str
    event_key: str | None = None


class WorkflowRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_id: str
    work_order: WorkOrder
    state: WorkflowState
    state_version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    original_content_hash: str | None = None
    output_content_hash: str | None = None
    stop_reason: str | None = None

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES


class ActionResult(BaseModel):
    """Decrypted durable result plus non-sensitive retention metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    workflow_id: str = Field(serialization_alias="workflowId")
    action_hash: str = Field(serialization_alias="actionHash")
    result: Any
    content_hash: str = Field(serialization_alias="contentHash")
    size_bytes: int = Field(ge=0, serialization_alias="sizeBytes")
    created_at: datetime = Field(serialization_alias="createdAt")
    expires_at: datetime = Field(serialization_alias="expiresAt")


__all__ = [
    "TERMINAL_STATES",
    "WORKFLOW_SCHEMA_VERSION",
    "ActionResult",
    "WorkFamily",
    "WorkOrder",
    "WorkflowBudget",
    "WorkflowEvent",
    "WorkflowPolicy",
    "WorkflowRecord",
    "WorkflowState",
    "canonical_json",
    "content_hash",
    "sanitize_ledger_payload",
    "utc_now",
]
