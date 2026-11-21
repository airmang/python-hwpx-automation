# SPDX-License-Identifier: Apache-2.0
"""Fail-closed security and log-minimization contract for render workers."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


HWPX_MEDIA_TYPE = "application/hwp+zip"


class RenderSecurityViolation(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class RenderSecurityPolicy(BaseModel):
    """Non-optional controls frozen before queue/worker implementation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    authenticated_transport_required: Literal[True] = True
    private_network_required: Literal[True] = True
    transport_auth: Literal["mtls", "signed_https"] = "mtls"
    per_job_sandbox_required: Literal[True] = True
    delete_on_terminal: Literal[True] = True
    sandbox_root: Path
    max_input_bytes: int = Field(default=100 * 1024 * 1024, gt=0)
    max_zip_entries: int = Field(default=10_000, ge=1)
    max_uncompressed_bytes: int = Field(default=500 * 1024 * 1024, gt=0)
    max_compression_ratio: float = Field(default=100.0, ge=1.0)
    input_retention_seconds: int = Field(default=3_600, ge=0, le=86_400)
    output_retention_seconds: int = Field(default=86_400, ge=0, le=604_800)
    log_retention_seconds: int = Field(default=604_800, ge=0, le=2_592_000)

    @model_validator(mode="after")
    def sandbox_root_is_absolute(self) -> "RenderSecurityPolicy":
        if not self.sandbox_root.expanduser().is_absolute():
            raise ValueError("sandbox_root must be absolute")
        return self

    def sandbox_for(self, job_id: str) -> Path:
        if not job_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in job_id):
            raise RenderSecurityViolation("INVALID_JOB_ID", "job id is unsafe for sandbox allocation")
        root = self.sandbox_root.expanduser().resolve()
        candidate = (root / job_id).resolve()
        if candidate.parent != root:
            raise RenderSecurityViolation("SANDBOX_ESCAPE", "job sandbox escaped configured root")
        return candidate

    def retention_deadlines(self, terminal_at: AwareDatetime) -> dict[str, AwareDatetime]:
        return {
            "inputDeleteBy": terminal_at + timedelta(seconds=self.input_retention_seconds),
            "outputDeleteBy": terminal_at + timedelta(seconds=self.output_retention_seconds),
            "logDeleteBy": terminal_at + timedelta(seconds=self.log_retention_seconds),
        }


class RenderInputInspection(BaseModel):
    """Result of authentication and ZIP inspection before sandbox ingestion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    authenticated: bool
    principal_id: str | None = None
    filename: str
    media_type: str
    compressed_bytes: int = Field(ge=0)
    uncompressed_bytes: int = Field(ge=0)
    zip_entries: int = Field(ge=0)
    has_encrypted_entry: bool = False
    has_symlink_entry: bool = False
    has_path_traversal: bool = False

    @property
    def compression_ratio(self) -> float:
        return self.uncompressed_bytes / max(self.compressed_bytes, 1)


def validate_render_input(
    inspection: RenderInputInspection,
    policy: RenderSecurityPolicy,
) -> RenderInputInspection:
    checks = (
        (not inspection.authenticated or not inspection.principal_id, "AUTH_REQUIRED"),
        (inspection.media_type != HWPX_MEDIA_TYPE, "MEDIA_TYPE_REJECTED"),
        (Path(inspection.filename).name != inspection.filename or not inspection.filename.lower().endswith(".hwpx"), "FILENAME_REJECTED"),
        (inspection.compressed_bytes > policy.max_input_bytes, "INPUT_TOO_LARGE"),
        (inspection.zip_entries > policy.max_zip_entries, "ZIP_ENTRY_LIMIT"),
        (inspection.uncompressed_bytes > policy.max_uncompressed_bytes, "ZIP_EXPANDED_SIZE_LIMIT"),
        (inspection.compression_ratio > policy.max_compression_ratio, "ZIP_COMPRESSION_RATIO"),
        (inspection.has_encrypted_entry, "ENCRYPTED_ZIP_REJECTED"),
        (inspection.has_symlink_entry, "ZIP_SYMLINK_REJECTED"),
        (inspection.has_path_traversal, "ZIP_TRAVERSAL_REJECTED"),
    )
    for failed, code in checks:
        if failed:
            raise RenderSecurityViolation(code, f"render input rejected: {code}")
    return inspection


_SAFE_LOG_KEYS = frozenset(
    {
        "event",
        "jobId",
        "workflowId",
        "status",
        "errorCode",
        "terminalReason",
        "inputHash",
        "outputHash",
        "workerVersion",
        "hancomBuild",
        "durationMs",
        "attempt",
        "retryCount",
        "queueDepth",
        "pageCount",
        "timestamp",
    }
)

_CODE_LOG_KEYS = frozenset({"event", "status", "errorCode", "terminalReason"})
_CODE_PATTERN_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")


def _redacted(value: Any) -> dict[str, Any]:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    except Exception:
        encoded = repr(type(value)).encode("utf-8")
    return {"redacted": True, "sha256": hashlib.sha256(encoded).hexdigest()}


def redact_render_log(event: Mapping[str, Any]) -> dict[str, Any]:
    """Return an allow-listed structured event with no text, path, or secret values."""

    safe: dict[str, Any] = {}
    for key, value in event.items():
        if key not in _SAFE_LOG_KEYS or isinstance(value, (Mapping, list, tuple, bytes, bytearray)):
            safe[str(key)] = _redacted(value)
            continue
        if key in _CODE_LOG_KEYS and (
            not isinstance(value, str)
            or not value
            or len(value) > 96
            or any(character not in _CODE_PATTERN_CHARS for character in value)
        ):
            safe[key] = _redacted(value)
            continue
        if isinstance(value, str) and (len(value) > 200 or "\n" in value or "\r" in value):
            safe[key] = _redacted(value)
            continue
        safe[key] = value
    return safe


__all__ = [
    "HWPX_MEDIA_TYPE",
    "RenderInputInspection",
    "RenderSecurityPolicy",
    "RenderSecurityViolation",
    "redact_render_log",
    "validate_render_input",
]
