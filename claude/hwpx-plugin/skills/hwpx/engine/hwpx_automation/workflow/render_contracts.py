# SPDX-License-Identifier: Apache-2.0
"""Shared render contracts — the leaf both queue and transport sides import.

These contracts were extracted from :mod:`rendering`/:mod:`render_queue` to remove the
last package import cycle: the v2 job/receipt/status models and the submission
signature live here, and both former owners re-export them for compatibility.
This module may import only the standard library and pydantic.
"""

from __future__ import annotations

import hashlib
import hmac
from enum import Enum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


RENDER_SCHEMA_VERSION_V2 = "hwpx.render.v2"
SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"


class RenderStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    CANCELLED = "cancelled"


class RenderArtifactKind(str, Enum):
    PDF = "pdf"
    PAGE_PNG = "page_png"


class RenderArtifactV2(BaseModel):
    """Content-addressed output; worker-local paths never cross the boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: RenderArtifactKind
    content_hash: str = Field(pattern=SHA256_PATTERN)
    size_bytes: int = Field(ge=1)
    page_number: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def page_number_matches_kind(self) -> "RenderArtifactV2":
        if self.kind == RenderArtifactKind.PAGE_PNG and self.page_number is None:
            raise ValueError("page_png artifact requires page_number")
        if self.kind == RenderArtifactKind.PDF and self.page_number is not None:
            raise ValueError("pdf artifact cannot have page_number")
        return self


class RenderJobV2(BaseModel):
    """Measure-first, content-addressed real-Hancom queue request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[RENDER_SCHEMA_VERSION_V2] = RENDER_SCHEMA_VERSION_V2
    # Colon is deliberately excluded: it is not safe in Windows directory names.
    job_id: str = Field(min_length=8, max_length=200, pattern=r"^[A-Za-z0-9._-]+$")
    workflow_id: str = Field(min_length=8, max_length=200, pattern=r"^[A-Za-z0-9._-]+$")
    idempotency_key: str = Field(min_length=8, max_length=200)
    source_content_hash: str = Field(pattern=SHA256_PATTERN)
    source_size_bytes: int = Field(gt=0)
    source_media_type: Literal["application/hwp+zip"] = "application/hwp+zip"
    submitted_at: AwareDatetime
    requested_backend: Literal["real_hancom"] = "real_hancom"
    requested_outputs: tuple[RenderArtifactKind, ...] = (
        RenderArtifactKind.PDF,
        RenderArtifactKind.PAGE_PNG,
    )
    dpi: int = Field(default=144, ge=72, le=600)

    @field_validator("requested_outputs")
    @classmethod
    def outputs_are_unique_and_nonempty(
        cls, value: tuple[RenderArtifactKind, ...]
    ) -> tuple[RenderArtifactKind, ...]:
        if set(value) != {RenderArtifactKind.PDF, RenderArtifactKind.PAGE_PNG} or len(value) != 2:
            raise ValueError("v2 requires exactly PDF and page_png outputs")
        return value


class RenderReceiptV2(BaseModel):
    """Terminal/non-terminal receipt bound to input and real worker provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[RENDER_SCHEMA_VERSION_V2] = RENDER_SCHEMA_VERSION_V2
    job_id: str = Field(min_length=8, max_length=200)
    workflow_id: str = Field(min_length=8, max_length=200)
    input_content_hash: str = Field(pattern=SHA256_PATTERN)
    status: RenderStatus
    backend: str | None = None
    hancom_build: str | None = None
    worker_version: str | None = None
    queued_at: AwareDatetime
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    artifacts: tuple[RenderArtifactV2, ...] = ()
    page_count: int | None = Field(default=None, ge=0)
    retry_count: int = Field(default=0, ge=0)
    terminal_reason: str | None = None
    render_checked: bool = False

    @model_validator(mode="after")
    def validate_provenance_and_timeline(self) -> "RenderReceiptV2":
        terminal = self.status in {
            RenderStatus.SUCCEEDED,
            RenderStatus.FAILED,
            RenderStatus.UNAVAILABLE,
            RenderStatus.CANCELLED,
        }
        if self.started_at is not None and self.started_at < self.queued_at:
            raise ValueError("started_at cannot precede queued_at")
        if self.completed_at is not None and self.completed_at < (self.started_at or self.queued_at):
            raise ValueError("completed_at must preserve monotonic timestamps")
        if terminal and (self.completed_at is None or not self.terminal_reason):
            raise ValueError("terminal receipt requires completed_at and terminal_reason")
        if not terminal and (self.completed_at is not None or self.terminal_reason is not None):
            raise ValueError("non-terminal receipt cannot carry terminal completion fields")

        page_artifacts = [item for item in self.artifacts if item.kind == RenderArtifactKind.PAGE_PNG]
        page_numbers = [item.page_number for item in page_artifacts]
        if len(page_numbers) != len(set(page_numbers)):
            raise ValueError("page artifact numbers must be unique")
        if self.status == RenderStatus.SUCCEEDED:
            if self.started_at is None:
                raise ValueError("successful receipt requires started_at")
            if not page_artifacts or self.page_count != len(page_artifacts):
                raise ValueError("successful receipt requires artifacts and exact page_count")
            if page_numbers != list(range(1, len(page_numbers) + 1)):
                raise ValueError("successful receipt requires contiguous page numbers starting at one")
            pdf_count = sum(item.kind == RenderArtifactKind.PDF for item in self.artifacts)
            if pdf_count != 1:
                raise ValueError("successful receipt requires exactly one PDF artifact")
            if not self.render_checked or not self.backend or not self.hancom_build or not self.worker_version:
                raise ValueError(
                    "successful receipt requires render_checked and backend/Hancom/worker provenance"
                )
        elif self.artifacts or self.page_count not in (None, 0):
            raise ValueError("non-success receipt cannot claim output artifacts")

        if self.render_checked and (
            self.status != RenderStatus.SUCCEEDED
            or not self.backend
            or not self.hancom_build
            or not self.worker_version
        ):
            raise ValueError(
                "render_checked requires succeeded status and backend/Hancom/worker provenance"
            )
        return self

    def binds(self, job: RenderJobV2) -> bool:
        """Return true only when identity, workflow, and content address match."""

        return (
            self.job_id == job.job_id
            and self.workflow_id == job.workflow_id
            and self.input_content_hash == job.source_content_hash
        )


def sign_submission(secret: bytes, job: RenderJobV2) -> str:
    """Sign only immutable request metadata; document bytes are bound by SHA-256."""

    message = job.model_dump_json(exclude_none=False).encode("utf-8")
    return "sha256=" + hmac.new(secret, message, hashlib.sha256).hexdigest()
