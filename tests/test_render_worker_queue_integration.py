from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path


from hwpx_automation.office.rendering.worker import (
    DeterministicFakeSession,
    SerializedHancomWorker,
)
from hwpx_automation.workflow.render_queue import DurableRenderQueue, sign_submission
from hwpx_automation.workflow.render_security import RenderSecurityPolicy
from hwpx_automation.workflow.rendering import RenderJobV2, RenderStatus


def _resolve_worker_script() -> Path:
    explicit_script = os.environ.get("HWPX_HANCOM_RENDER_WORKER_SCRIPT")
    if explicit_script:
        return Path(explicit_script).expanduser().resolve()

    return Path(__file__).resolve().parents[1] / "scripts" / "hancom_render_worker.py"


SCRIPT = _resolve_worker_script()
assert SCRIPT.is_file(), f"canonical automation render worker script is missing: {SCRIPT}"
spec = importlib.util.spec_from_file_location("s068_hancom_render_worker", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
run_queue_once = module.run_queue_once


def _minimal_hwpx() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/section0.xml", "<section/>")
    return stream.getvalue()


def setup_queue(tmp_path):
    secret = b"worker-integration-secret"
    root = tmp_path / "queue"
    queue = DurableRenderQueue(
        root,
        secret=secret,
        policy=RenderSecurityPolicy(sandbox_root=root / "sandboxes"),
        max_attempts=1,
    )
    data = _minimal_hwpx()
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    job = RenderJobV2(
        job_id="worker-integration-0001", workflow_id="workflow-integration-0001",
        idempotency_key="worker-integration-key", source_content_hash=digest,
        source_size_bytes=len(data), submitted_at=datetime.now(timezone.utc),
    )
    queue.submit(job, data, signature=sign_submission(secret, job), principal_id="integration")
    return queue, job


def fake_raster(pdf, destination, dpi):
    page = destination / "page-0001.png"
    page.write_bytes(b"png")
    return [page]


def test_fake_worker_queue_loop_ends_unverified_never_success(tmp_path, monkeypatch):
    queue, job = setup_queue(tmp_path)
    worker = SerializedHancomWorker(tmp_path / "worker", session_factory=DeterministicFakeSession, worker_version="fake/1")
    monkeypatch.setattr(worker, "_rasterize", fake_raster)
    assert run_queue_once(queue, worker, "worker-1") is True
    receipt = queue.get(job.job_id)
    assert receipt.status == RenderStatus.FAILED
    assert receipt.render_checked is False and receipt.terminal_reason == "FAKE_RENDER_ONLY"


class RealFixtureSession(DeterministicFakeSession):
    real_hancom = True
    hancom_build = "Hancom fixture build"


def test_real_contract_worker_stores_hash_bound_downloadable_artifacts(tmp_path, monkeypatch):
    queue, job = setup_queue(tmp_path)
    worker = SerializedHancomWorker(tmp_path / "worker", session_factory=RealFixtureSession, worker_version="worker/1")
    monkeypatch.setattr(worker, "_rasterize", fake_raster)
    assert run_queue_once(queue, worker, "worker-1") is True
    receipt = queue.get(job.job_id)
    assert receipt.status == RenderStatus.SUCCEEDED and receipt.render_checked is True
    assert receipt.binds(job)
    for artifact in receipt.artifacts:
        assert queue.content.path_for(artifact.content_hash).stat().st_size == artifact.size_bytes


def test_cancel_during_render_is_acknowledged_and_next_job_can_run(tmp_path, monkeypatch):
    queue, job = setup_queue(tmp_path)
    class CancellingSession(RealFixtureSession):
        def render_pdf(self, source, target):
            queue.cancel(job.job_id)
            return super().render_pdf(source, target)
    worker = SerializedHancomWorker(tmp_path / "worker", session_factory=CancellingSession, worker_version="worker/1")
    monkeypatch.setattr(worker, "_rasterize", fake_raster)
    assert run_queue_once(queue, worker, "worker-1")
    receipt = queue.get(job.job_id)
    assert receipt.status == RenderStatus.CANCELLED and not receipt.render_checked
    assert not receipt.artifacts
    assert not run_queue_once(queue, worker, "worker-1")


def test_receipt_backend_comes_from_session(tmp_path, monkeypatch):
    queue, job = setup_queue(tmp_path)
    class MacContractSession(RealFixtureSession):
        backend = "mac-gui-worker"
    worker = SerializedHancomWorker(tmp_path / "worker", session_factory=MacContractSession, worker_version="worker/1")
    monkeypatch.setattr(worker, "_rasterize", fake_raster)
    assert run_queue_once(queue, worker, "worker-1")
    assert queue.get(job.job_id).backend == "mac-gui-worker"


def test_cancel_at_completion_boundary_does_not_crash_worker(tmp_path, monkeypatch):
    queue, job = setup_queue(tmp_path)
    original = queue.complete
    def racing_complete(lease, receipt, **kwargs):
        queue.cancel(job.job_id)
        return original(lease, receipt, **kwargs)
    monkeypatch.setattr(queue, "complete", racing_complete)
    worker = SerializedHancomWorker(tmp_path / "worker", session_factory=RealFixtureSession, worker_version="worker/1")
    monkeypatch.setattr(worker, "_rasterize", fake_raster)
    assert run_queue_once(queue, worker, "worker-1")
    assert queue.get(job.job_id).status == RenderStatus.CANCELLED


def test_keepalive_extends_only_owned_unexpired_lease(tmp_path):
    from datetime import timedelta
    import pytest
    from hwpx_automation.workflow.render_queue import RenderQueueError
    queue, job = setup_queue(tmp_path)
    now = datetime.now(timezone.utc)
    lease = queue.claim("worker-1", lease_seconds=1, now=now)
    assert queue.keepalive(lease, now=now + timedelta(milliseconds=500))
    assert queue.claim("worker-2", now=now + timedelta(seconds=2)) is None
    with pytest.raises(RenderQueueError, match="expired"):
        queue.keepalive(lease, now=now + timedelta(seconds=302))
