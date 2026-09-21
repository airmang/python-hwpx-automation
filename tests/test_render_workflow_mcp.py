from __future__ import annotations

import inspect
import io
import zipfile
from datetime import timedelta
from pathlib import Path

from hwpx_automation import server
from hwpx_automation.workflow.models import WorkFamily
from hwpx_automation.workflow.rendering import (
    RenderArtifactKind,
    RenderArtifactV2,
    RenderJobV2,
    RenderReceiptV2,
    RenderStatus,
)
from hwpx_automation.workflow.service import WorkflowService
from hwpx_automation.workflow.store import WorkflowStore


def hwpx_bytes() -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/section0.xml", "<section/>")
    return out.getvalue()


def tools():
    def create(**arguments):
        Path(arguments["filename"]).write_bytes(hwpx_bytes())
        return {"created": True, "verification": {"ok": True, "openSafety": {"ok": True}}}

    return {
        "validate_document_plan": lambda **arguments: {"ok": True},
        "create_document_from_plan": create,
        "inspect_document_authoring_quality": lambda **arguments: {"pass": True},
    }


class FakeRenderClient:
    def __init__(self) -> None:
        self.job: RenderJobV2 | None = None
        self.receipt: RenderReceiptV2 | None = None
        self.cancelled = False

    def capabilities(self):
        return {"available": True}

    def submit(self, job: RenderJobV2, source_path: Path):
        assert source_path.is_file()
        self.job = job
        self.receipt = RenderReceiptV2(
            job_id=job.job_id, workflow_id=job.workflow_id,
            input_content_hash=job.source_content_hash, status=RenderStatus.QUEUED,
            queued_at=job.submitted_at,
        )
        return self.receipt

    def get(self, job_id: str):
        if not self.receipt or self.receipt.job_id != job_id:
            raise KeyError(job_id)
        return self.receipt

    def cancel(self, job_id: str):
        self.cancelled = True
        assert self.job
        self.receipt = RenderReceiptV2(
            job_id=job_id, workflow_id=self.job.workflow_id,
            input_content_hash=self.job.source_content_hash, status=RenderStatus.CANCELLED,
            queued_at=self.job.submitted_at, completed_at=self.job.submitted_at,
            terminal_reason="CLIENT_CANCELLED",
        )
        return self.receipt

    def succeed(self, *, wrong_hash: bool = False):
        assert self.job
        self.receipt = RenderReceiptV2(
            job_id=self.job.job_id, workflow_id=self.job.workflow_id,
            input_content_hash=("sha256:" + "f" * 64) if wrong_hash else self.job.source_content_hash,
            status=RenderStatus.SUCCEEDED, backend="windows-com-worker",
            hancom_build="Hancom 2024", worker_version="worker/1",
            queued_at=self.job.submitted_at, started_at=self.job.submitted_at,
            completed_at=self.job.submitted_at + timedelta(seconds=1),
            artifacts=(
                RenderArtifactV2(kind=RenderArtifactKind.PDF, content_hash="sha256:" + "a" * 64, size_bytes=10),
                RenderArtifactV2(kind=RenderArtifactKind.PAGE_PNG, content_hash="sha256:" + "b" * 64, size_bytes=10, page_number=1),
            ), page_count=1, terminal_reason="SUCCEEDED", render_checked=True,
        )


def drive_to_verify(service: WorkflowService, receipt: dict) -> dict:
    for _ in range(12):
        if receipt["state"] == "decision":
            receipt = service.approve_decision(receipt["workflowId"], approved=True)
        elif receipt["state"] == "verify":
            return receipt
        else:
            receipt = service.continue_workflow(receipt["workflowId"])
    raise AssertionError(receipt)


def start_render_workflow(tmp_path: Path, client: FakeRenderClient):
    output = tmp_path / "output.hwpx"
    service = WorkflowService(tools(), store=WorkflowStore(tmp_path / "workflow.sqlite3"), render_client=client)
    receipt = service.start(
        family=WorkFamily.TYPED_AUTHORING.value, idempotency_key="render-workflow-0001",
        output_path=str(output),
        parameters={"documentPlan": {"schemaVersion": "hwpx.document_plan.v2", "sections": []}},
        policy={"require_real_hancom_render": True},
    )
    return service, drive_to_verify(service, receipt)


def test_workflow_defers_then_resumes_only_on_hash_bound_real_receipt(tmp_path):
    client = FakeRenderClient()
    service, verify = start_render_workflow(tmp_path, client)
    pending = service.continue_workflow(verify["workflowId"])
    assert pending["state"] == "verify" and pending["terminal"] is False
    assert pending["render"]["status"] == "queued"
    assert pending["openSafety"]["renderChecked"] is False
    client.succeed()
    completed = service.continue_workflow(verify["workflowId"])
    assert completed["state"] == "completed"
    assert completed["verificationStatus"] == "real_hancom_rendered_review_unverified"
    assert completed["renderEvidence"]["sourceHash"] == client.job.source_content_hash
    assert completed["renderEvidence"]["pdfHash"] == "sha256:" + "a" * 64
    assert completed["renderEvidence"]["pages"] == [
        {"pageNumber": 1, "pagePngHash": "sha256:" + "b" * 64}
    ]
    assert completed["renderEvidence"]["observationStatus"] == "rendered_unreviewed"
    assert completed["openSafety"]["renderChecked"] is True


def test_mismatched_receipt_never_marks_render_checked(tmp_path):
    client = FakeRenderClient()
    service, verify = start_render_workflow(tmp_path, client)
    service.continue_workflow(verify["workflowId"])
    client.succeed(wrong_hash=True)
    rejected = service.continue_workflow(verify["workflowId"])
    assert rejected["state"] == "needs_review"
    assert rejected["openSafety"]["renderChecked"] is False


def test_cancel_workflow_propagates_to_pending_render(tmp_path):
    client = FakeRenderClient()
    service, verify = start_render_workflow(tmp_path, client)
    service.continue_workflow(verify["workflowId"])
    cancelled = service.cancel(verify["workflowId"])
    assert cancelled["state"] == "cancelled" and client.cancelled is True


def test_direct_mcp_surface_is_async_idempotent_and_health_is_honest(tmp_path, monkeypatch):
    root = tmp_path / "queue"
    monkeypatch.setenv("HWPX_RENDER_QUEUE_ROOT", str(root))
    monkeypatch.setenv("HWPX_RENDER_QUEUE_SECRET", "test-render-secret")
    source = tmp_path / "input.hwpx"
    source.write_bytes(hwpx_bytes())
    first = server.render_submit(str(source), "direct-render-key")
    second = server.render_submit(str(source), "direct-render-key")
    assert first == second and first["receipt"]["status"] == "queued"
    job_id = first["receipt"]["job_id"]
    assert server.render_status(job_id)["receipt"]["status"] == "queued"
    health = server.render_health()
    assert health["available"] is False and health["degradedReason"] == "NO_WORKER_HEARTBEAT"
    assert server.render_cancel(job_id)["receipt"]["status"] == "cancelled"
    for function in (server.render_submit, server.render_status, server.render_cancel, server.render_health):
        assert "wait" not in inspect.signature(function).parameters


def test_unconfigured_surface_is_explicitly_unverified(tmp_path, monkeypatch):
    monkeypatch.delenv("HWPX_RENDER_QUEUE_ROOT", raising=False)
    monkeypatch.delenv("HWPX_RENDER_QUEUE_SECRET", raising=False)
    source = tmp_path / "input.hwpx"
    source.write_bytes(hwpx_bytes())
    response = server.render_submit(str(source), "unconfigured-render-key")
    assert response["ok"] is False
    assert response["receipt"]["status"] == "unavailable"
    assert server.render_health()["degradedReason"] == "NOT_CONFIGURED"
