#!/usr/bin/env python3
"""Run one supervised render job. Queue/network credentials stay outside CLI/logs.

Production service wiring must inject authenticated queue jobs and requires owner
approval. This command is deliberately a local worker diagnostic, not a public
document upload endpoint.

Windows operator runbook:
1. Use a dedicated licensed Windows account/desktop with no interactive documents.
2. Keep the queue private; inject its secret through the service manager, never CLI.
3. Set HWPX_HANCOM_BUILD from the installed About/build value and pin worker code.
4. Give the service account write access only to ``--root`` and deny public ingress.
5. Treat COM watchdog failures as a poisoned session; investigate repeated failures
   before restarting the dedicated host. Host/firewall/service changes need owner approval.
"""

from __future__ import annotations

import argparse
import hashlib
from functools import partial
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from hwpx_automation.office.rendering.worker import (
    DeterministicFakeSession, PowerShellHancomSession, SerializedHancomWorker, WorkerJob,
)


def run_queue_once(queue, worker: SerializedHancomWorker, worker_id: str) -> bool:
    """Claim and finish at most one job; return false when the queue is empty."""

    from hwpx_automation.workflow.rendering import (
        RenderArtifactKind, RenderArtifactV2, RenderReceiptV2, RenderStatus,
    )

    from hwpx_automation.workflow.render_queue import RenderQueueError

    lease = queue.claim(worker_id)
    if lease is None:
        return False
    lease_lost = False
    def cancelled():
        nonlocal lease_lost
        try:
            return not queue.keepalive(lease)
        except RenderQueueError as exc:
            if exc.code != "LEASE_NOT_OWNED":
                raise
            lease_lost = True
            return True

    started = datetime.now(timezone.utc)
    result = worker.render(WorkerJob(
        lease.job.job_id, lease.source_path, lease.job.source_content_hash, lease.job.dpi,
    ), cancelled=cancelled)
    completed = datetime.now(timezone.utc)
    if lease_lost:
        return True
    if not result.render_checked:
        queue.fail(lease, reason=result.terminal_reason, retryable=result.retryable, now=completed)
        return True
    artifacts = []
    for item in result.artifacts:
        path = worker.artifacts / item.relative_path
        queue.content.put(path.read_bytes(), item.content_hash)
        artifacts.append(RenderArtifactV2(
            kind=RenderArtifactKind(item.kind), content_hash=item.content_hash,
            size_bytes=item.size_bytes, page_number=item.page_number,
        ))
    receipt = RenderReceiptV2(
        job_id=lease.job.job_id, workflow_id=lease.job.workflow_id,
        input_content_hash=lease.job.source_content_hash, status=RenderStatus.SUCCEEDED,
        backend=result.backend or "unknown-worker", hancom_build=result.hancom_build,
        worker_version=result.worker_version, queued_at=lease.job.submitted_at,
        started_at=started, completed_at=completed, artifacts=tuple(artifacts),
        page_count=result.page_count, retry_count=lease.attempt - 1,
        terminal_reason="SUCCEEDED", render_checked=True,
    )
    try:
        if not queue.keepalive(lease):
            queue.fail(lease, reason="CLIENT_CANCELLED", retryable=False)
        else:
            queue.complete(lease, receipt, now=completed)
    except RenderQueueError as exc:
        if exc.code == "LEASE_NOT_OWNED":
            return True
        if exc.code != "CANCEL_REQUESTED":
            raise
        queue.fail(lease, reason="CLIENT_CANCELLED", retryable=False)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, nargs="?")
    parser.add_argument("--job-id")
    parser.add_argument("--root", type=Path, required=True, help="worker sandbox/artifact root")
    parser.add_argument("--queue-root", type=Path)
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--worker-id", default="hancom-worker-1")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--max-jobs", type=int)
    parser.add_argument("--backend", choices=("auto", "windows", "mac"), default="auto")
    parser.add_argument("--fake", action="store_true", help="test only; never renderChecked")
    parser.add_argument("--hancom-build", default=os.environ.get("HWPX_HANCOM_BUILD"))
    parser.add_argument("--worker-version", default="hancom-worker/1")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    backend = ("mac" if sys.platform == "darwin" else "windows") if args.backend == "auto" else args.backend
    if not args.fake and backend == "windows" and not args.hancom_build:
        parser.error("--hancom-build or HWPX_HANCOM_BUILD is required")
    if args.fake:
        factory = DeterministicFakeSession
    elif backend == "mac":
        from hwpx_automation.office.rendering.mac_session import MacHancomSession
        factory = partial(MacHancomSession, timeout_seconds=args.timeout)
    else:
        factory = partial(PowerShellHancomSession, hancom_build=args.hancom_build)
    if args.daemon:
        if not args.queue_root:
            parser.error("--queue-root is required with --daemon")
        secret = os.environ.get("HWPX_RENDER_QUEUE_SECRET")
        if not secret:
            parser.error("HWPX_RENDER_QUEUE_SECRET is required with --daemon")
        from hwpx_automation.workflow.render_queue import DurableRenderQueue
        from hwpx_automation.workflow.render_security import RenderSecurityPolicy
        policy = RenderSecurityPolicy(sandbox_root=args.queue_root.resolve() / "sandboxes")
        queue = DurableRenderQueue(args.queue_root, secret=secret.encode(), policy=policy)
        worker = SerializedHancomWorker(
            args.root, session_factory=factory, worker_version=args.worker_version,
            timeout_seconds=args.timeout,
        )
        processed = 0
        try:
            while args.max_jobs is None or processed < args.max_jobs:
                if args.fake:
                    available = False
                    degraded_reason = "FAKE_RENDERER"
                else:
                    from hwpx_automation.office.rendering.oracle import MacHancomOracle, WindowsComOracle
                    oracle = MacHancomOracle() if backend == "mac" else WindowsComOracle()
                    available = oracle.available()
                    degraded_reason = None if available else "HANCOM_UNAVAILABLE"
                queue.heartbeat(
                    worker_version=args.worker_version,
                    hancom_build=(factory().hancom_build if available and backend == "mac" else args.hancom_build) or "UNVERIFIED",
                    available=available,
                    degraded_reason=degraded_reason,
                )
                if not available:
                    if args.max_jobs is not None:
                        return 2
                    time.sleep(args.poll_seconds)
                    continue
                if run_queue_once(queue, worker, args.worker_id):
                    processed += 1
                else:
                    time.sleep(args.poll_seconds)
            return 0
        finally:
            worker.close()
    if not args.input or not args.job_id:
        parser.error("input and --job-id are required outside --daemon")
    digest = "sha256:" + hashlib.sha256(args.input.read_bytes()).hexdigest()
    worker = SerializedHancomWorker(
        args.root,
        session_factory=factory,
        worker_version=args.worker_version,
        timeout_seconds=args.timeout,
    )
    try:
        result = worker.render(WorkerJob(args.job_id, args.input, digest))
        print(result.to_json())
        return 0 if result.render_checked else 2
    finally:
        worker.close()


if __name__ == "__main__":
    raise SystemExit(main())
