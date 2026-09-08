from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

from hwpx_automation.office.rendering.worker import (
    DeterministicFakeSession,
    SerializedHancomWorker,
    WorkerJob,
)


def job(tmp_path: Path, suffix: str = "0001") -> WorkerJob:
    source = tmp_path / f"{suffix}.hwpx"
    source.write_bytes(b"hwpx-fixture-" + suffix.encode())
    digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    return WorkerJob(f"job-{suffix}", source, digest, 72)


def fake_pdf_rasterizer(pdf: Path, destination: Path, dpi: int):
    page = destination / "page-0001.png"
    page.write_bytes(b"png:" + pdf.read_bytes())
    return [page]


def test_fake_worker_is_content_addressed_serialized_and_never_real(tmp_path, monkeypatch):
    worker = SerializedHancomWorker(tmp_path / "worker", session_factory=DeterministicFakeSession, worker_version="test/1")
    monkeypatch.setattr(worker, "_rasterize", fake_pdf_rasterizer)
    result = worker.render(job(tmp_path))
    assert result.status == "succeeded"
    assert result.real_hancom is False and result.render_checked is False
    assert result.terminal_reason == "FAKE_RENDER_ONLY"
    assert [item.kind for item in result.artifacts] == ["pdf", "page_png"]
    assert result.page_count == 1
    assert not any(worker.sandboxes.iterdir())
    assert "hwpx-fixture" not in result.to_json()


def test_hash_mismatch_fails_without_starting_session(tmp_path):
    created = []
    worker = SerializedHancomWorker(tmp_path / "worker", session_factory=lambda: created.append(1), worker_version="test/1")
    bad = job(tmp_path)
    result = worker.render(WorkerJob(bad.job_id, bad.input_path, "sha256:" + "0" * 64))
    assert result.terminal_reason == "INPUT_HASH_MISMATCH"
    assert result.retryable is False and created == []


def test_page_raster_failure_is_honest_and_leaves_no_artifacts(tmp_path, monkeypatch):
    worker = SerializedHancomWorker(tmp_path / "worker", session_factory=DeterministicFakeSession, worker_version="test/1")
    monkeypatch.setattr(worker, "_rasterize", lambda *args: (_ for _ in ()).throw(RuntimeError("bad pdf")))
    result = worker.render(job(tmp_path))
    assert result.terminal_reason == "PAGE_RASTERIZE_FAILED"
    assert result.render_checked is False and result.retryable is True
    assert not (worker.artifacts / "job-0001").exists()


class BlockingSession:
    real_hancom = True
    hancom_build = "Hancom test build"

    def __init__(self):
        self.stop = threading.Event()
        self.aborted = False

    def render_pdf(self, source, target):
        self.stop.wait(2)
        return None

    def abort(self):
        self.aborted = True
        self.stop.set()

    def close(self):
        self.abort()


def test_watchdog_aborts_poisoned_session_and_restarts_generation(tmp_path):
    sessions = []
    def factory():
        session = BlockingSession(); sessions.append(session); return session
    worker = SerializedHancomWorker(
        tmp_path / "worker", session_factory=factory, worker_version="test/1",
        timeout_seconds=0.02, abort_grace_seconds=0.2,
    )
    first = worker.render(job(tmp_path, "0001"))
    second = worker.render(job(tmp_path, "0002"))
    assert first.terminal_reason == second.terminal_reason == "COM_WATCHDOG_TIMEOUT"
    assert first.retryable and sessions[0].aborted
    assert len(sessions) == 2 and second.session_generation == 2


class NonCooperativeSession(BlockingSession):
    def abort(self):
        self.aborted = True


def test_noncooperative_timed_out_session_blocks_all_new_com_work(tmp_path):
    sessions = []
    def factory():
        session = NonCooperativeSession(); sessions.append(session); return session
    worker = SerializedHancomWorker(
        tmp_path / "worker", session_factory=factory, worker_version="test/1",
        timeout_seconds=0.01, abort_grace_seconds=0.01,
    )
    first = worker.render(job(tmp_path, "0001"))
    second = worker.render(job(tmp_path, "0002"))
    assert first.terminal_reason == "COM_WATCHDOG_TIMEOUT"
    assert second.terminal_reason == "POISONED_SESSION_STILL_RUNNING"
    assert len(sessions) == 1
    sessions[0].stop.set()


class SerialProbeSession(DeterministicFakeSession):
    def __init__(self, probe):
        super().__init__(); self.probe = probe
    def render_pdf(self, source, target):
        with self.probe["lock"]:
            self.probe["active"] += 1
            self.probe["max"] = max(self.probe["max"], self.probe["active"])
        time.sleep(0.05)
        try:
            return super().render_pdf(source, target)
        finally:
            with self.probe["lock"]:
                self.probe["active"] -= 1


def test_concurrent_second_job_is_deferred_not_parallel(tmp_path, monkeypatch):
    probe = {"lock": threading.Lock(), "active": 0, "max": 0}
    worker = SerializedHancomWorker(tmp_path / "worker", session_factory=lambda: SerialProbeSession(probe), worker_version="test/1")
    monkeypatch.setattr(worker, "_rasterize", fake_pdf_rasterizer)
    results = []
    first = threading.Thread(target=lambda: results.append(worker.render(job(tmp_path, "0001"))))
    first.start(); time.sleep(0.01)
    results.append(worker.render(job(tmp_path, "0002")))
    first.join()
    assert probe["max"] == 1
    assert sorted(item.terminal_reason for item in results) == ["FAKE_RENDER_ONLY", "WORKER_BUSY"]


def test_copied_input_is_rechecked_before_starting_renderer(tmp_path, monkeypatch):
    import hwpx_automation.office.rendering.worker as module
    created = []
    worker = SerializedHancomWorker(tmp_path / "worker", session_factory=lambda: created.append(1), worker_version="test/1")
    original = module.shutil.copyfile
    def racing_copy(source, target):
        result = original(source, target)
        Path(target).write_bytes(b"changed-after-source-check")
        return result
    monkeypatch.setattr(module.shutil, "copyfile", racing_copy)
    result = worker.render(job(tmp_path))
    assert result.terminal_reason == "INPUT_HASH_MISMATCH"
    assert not result.render_checked and not created


def test_empty_page_set_cannot_claim_render_checked(tmp_path, monkeypatch):
    worker = SerializedHancomWorker(tmp_path / "worker", session_factory=DeterministicFakeSession, worker_version="test/1")
    monkeypatch.setattr(worker, "_rasterize", lambda *args: [])
    result = worker.render(job(tmp_path))
    assert result.terminal_reason == "PAGE_RASTERIZE_FAILED"
    assert not result.render_checked and not any(worker.artifacts.iterdir())


def test_poisoned_thread_keeps_input_until_it_stops(tmp_path):
    session = NonCooperativeSession()
    worker = SerializedHancomWorker(tmp_path / "worker", session_factory=lambda: session, worker_version="test/1", timeout_seconds=.01, abort_grace_seconds=.01)
    worker.render(job(tmp_path))
    assert len(list(worker.sandboxes.glob("*/input.hwpx"))) == 1
    session.stop.set()
    worker._poisoned_thread.join(1)
    bad = job(tmp_path, "next")
    worker.render(WorkerJob(bad.job_id, bad.input_path, "bad-hash"))
    assert not any(worker.sandboxes.iterdir())


def test_cancel_stops_owned_renderer_without_claiming_artifacts(tmp_path):
    session = BlockingSession()
    worker = SerializedHancomWorker(tmp_path / "worker", session_factory=lambda: session, worker_version="test/1")
    calls = []
    def cancelled():
        calls.append(1)
        return len(calls) > 1
    result = worker.render(job(tmp_path), cancelled=cancelled)
    assert result.terminal_reason == "CLIENT_CANCELLED" and not result.retryable
    assert session.aborted and not result.artifacts


def test_invalid_job_path_does_not_remove_existing_artifacts(tmp_path):
    worker = SerializedHancomWorker(tmp_path / "worker", session_factory=DeterministicFakeSession, worker_version="test/1")
    source = job(tmp_path)
    result = worker.render(WorkerJob("../victim", source.input_path, source.input_content_hash))
    assert result.terminal_reason == "INVALID_JOB"


def test_incomplete_pdf_is_not_repaired_into_success(tmp_path):
    import pymupdf
    document = pymupdf.open()
    document.new_page()
    path = tmp_path / "incomplete.pdf"
    path.write_bytes(document.tobytes().rsplit(b"%%EOF", 1)[0])
    document.close()
    import pytest
    with pytest.raises(ValueError, match="Incomplete PDF"):
        SerializedHancomWorker._rasterize(path, tmp_path, 72)


def test_retry_failure_preserves_previous_receipt_files(tmp_path, monkeypatch):
    worker = SerializedHancomWorker(tmp_path / "worker", session_factory=DeterministicFakeSession, worker_version="test/1")
    monkeypatch.setattr(worker, "_rasterize", fake_pdf_rasterizer)
    request = job(tmp_path)
    first = worker.render(request)
    saved = {a.relative_path: (worker.artifacts / a.relative_path).read_bytes() for a in first.artifacts}
    monkeypatch.setattr(worker, "_rasterize", lambda *args: [])
    second = worker.render(request)
    assert not second.artifacts and second.terminal_reason == "PAGE_RASTERIZE_FAILED"
    assert saved == {name: (worker.artifacts / name).read_bytes() for name in saved}
