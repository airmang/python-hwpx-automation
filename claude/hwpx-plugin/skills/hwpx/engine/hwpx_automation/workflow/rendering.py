# SPDX-License-Identifier: Apache-2.0
"""Transport-neutral render boundary consumed by the workflow engine.

The base workflow never claims that this interface rendered a document. A later
real-Hancom backend and provenance receipts behind this frozen contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Shared v2 contracts live in the leaf module that removed the import cycle; they are
# re-exported here so existing importers keep working unchanged.
from .render_contracts import (  # noqa: F401 - compatibility re-exports
    RENDER_SCHEMA_VERSION_V2,
    SHA256_PATTERN,
    RenderArtifactKind,
    RenderArtifactV2,
    RenderJobV2,
    RenderReceiptV2,
    RenderStatus,
    sign_submission,
)


RENDER_SCHEMA_VERSION = "hwpx.render.v1"


class RenderJob(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = RENDER_SCHEMA_VERSION
    job_id: str = Field(min_length=8, max_length=200)
    workflow_id: str = Field(min_length=8, max_length=200)
    source_path: str
    source_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    requested_backend: str = "real_hancom"
    dpi: int = Field(default=144, ge=72, le=600)


class RenderReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = RENDER_SCHEMA_VERSION
    job_id: str
    status: RenderStatus
    backend: str | None = None
    hancom_build: str | None = None
    page_artifacts: tuple[str, ...] = ()
    output_content_hash: str | None = None
    render_checked: bool = False
    error_code: str | None = None

    @model_validator(mode="after")
    def truthful_render_claim(self) -> "RenderReceipt":
        if self.render_checked and (
            self.status != RenderStatus.SUCCEEDED
            or not self.backend
            or not self.hancom_build
            or not self.page_artifacts
        ):
            raise ValueError(
                "render_checked requires succeeded status, backend, Hancom build, and page artifacts"
            )
        if self.status == RenderStatus.SUCCEEDED and not self.output_content_hash:
            raise ValueError("successful render receipt requires output_content_hash")
        return self


@runtime_checkable
class RenderBackend(Protocol):
    """Stable provider boundary; implementations may be local or remote."""

    def capabilities(self) -> dict[str, object]: ...

    def submit(self, job: RenderJob) -> RenderReceipt: ...

    def get(self, job_id: str) -> RenderReceipt: ...

    def cancel(self, job_id: str) -> RenderReceipt: ...


@runtime_checkable
class RenderClientV2(Protocol):
    def capabilities(self) -> dict[str, object]: ...
    def submit(self, job: RenderJobV2, source_path: Path) -> RenderReceiptV2: ...
    def get(self, job_id: str) -> RenderReceiptV2: ...
    def cancel(self, job_id: str) -> RenderReceiptV2: ...
    def fetch_artifact(self, job_id: str, content_hash: str) -> bytes: ...


class NullRenderClientV2:
    def capabilities(self) -> dict[str, object]:
        return {
            "schemaVersion": "hwpx.render-health.v1", "available": False,
            "degraded": True, "degradedReason": "NOT_CONFIGURED", "queueDepth": 0,
            "runningJobs": 0, "oldestQueuedAgeSeconds": 0.0,
            "lastSuccessfulRealRender": None, "workerVersion": None, "hancomBuild": None,
        }

    def submit(self, job: RenderJobV2, source_path: Path) -> RenderReceiptV2:
        del source_path
        return RenderReceiptV2(
            job_id=job.job_id, workflow_id=job.workflow_id,
            input_content_hash=job.source_content_hash, status=RenderStatus.UNAVAILABLE,
            queued_at=job.submitted_at, completed_at=job.submitted_at,
            terminal_reason="REAL_HANCOM_BACKEND_UNAVAILABLE",
        )

    def get(self, job_id: str) -> RenderReceiptV2:
        raise KeyError(job_id)

    def cancel(self, job_id: str) -> RenderReceiptV2:
        raise KeyError(job_id)

    def fetch_artifact(self, job_id: str, content_hash: str) -> bytes:
        raise KeyError(job_id)


class QueueRenderClientV2:
    """Trusted local client for the authenticated private durable queue."""

    def __init__(
        self,
        queue: object,
        *,
        secret: bytes,
        # Compatibility-preserved through 6.x: this value participates in
        # signed queue authorization, so renaming it would strand queued jobs.
        principal_id: str = "hwpx-mcp-server",
    ) -> None:
        self.queue = queue
        self.secret = secret
        self.principal_id = principal_id

    def capabilities(self) -> dict[str, object]:
        return self.queue.health()

    def submit(self, job: RenderJobV2, source_path: Path) -> RenderReceiptV2:
        return self.queue.submit(
            job, source_path.read_bytes(), signature=sign_submission(self.secret, job),
            principal_id=self.principal_id, filename=source_path.name,
        )

    def get(self, job_id: str) -> RenderReceiptV2:
        return self.queue.get(job_id)

    def cancel(self, job_id: str) -> RenderReceiptV2:
        return self.queue.cancel(job_id)

    def fetch_artifact(self, job_id: str, content_hash: str) -> bytes:
        receipt = self.queue.get(job_id)
        if content_hash not in {item.content_hash for item in receipt.artifacts}:
            raise KeyError(content_hash)
        return self.queue.content.path_for(content_hash).read_bytes()


class NullRenderBackend:
    """Honest default: render evidence is unavailable, never silently true."""

    def capabilities(self) -> dict[str, object]:
        return {
            "schemaVersion": RENDER_SCHEMA_VERSION,
            "available": False,
            "backend": "none",
            "renderChecked": False,
        }

    def submit(self, job: RenderJob) -> RenderReceipt:
        return self._unavailable(job.job_id)

    def get(self, job_id: str) -> RenderReceipt:
        return self._unavailable(job_id)

    def cancel(self, job_id: str) -> RenderReceipt:
        return RenderReceipt(job_id=job_id, status=RenderStatus.CANCELLED, error_code="NO_RENDER_BACKEND")

    @staticmethod
    def _unavailable(job_id: str) -> RenderReceipt:
        return RenderReceipt(
            job_id=job_id,
            status=RenderStatus.UNAVAILABLE,
            render_checked=False,
            error_code="REAL_HANCOM_BACKEND_UNAVAILABLE",
        )


__all__ = [
    "RENDER_SCHEMA_VERSION",
    "RENDER_SCHEMA_VERSION_V2",
    "NullRenderBackend",
    "NullRenderClientV2",
    "QueueRenderClientV2",
    "RenderArtifactKind",
    "RenderArtifactV2",
    "RenderBackend",
    "RenderClientV2",
    "RenderJob",
    "RenderJobV2",
    "RenderReceipt",
    "RenderReceiptV2",
    "RenderStatus",
]
