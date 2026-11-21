# SPDX-License-Identifier: Apache-2.0
"""Crash-safe private queue and content store for real-Hancom render jobs."""

from __future__ import annotations

import hashlib
import hmac
import io
import os
import sqlite3
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .render_security import (
    HWPX_MEDIA_TYPE,
    RenderInputInspection,
    RenderSecurityPolicy,
    RenderSecurityViolation,
    validate_render_input,
)
# Shared contracts come from the leaf module that removed the import cycle;
# sign_submission is re-exported for existing importers of this module.
from .render_contracts import (  # noqa: F401 - compatibility re-export
    RenderJobV2,
    RenderReceiptV2,
    RenderStatus,
    sign_submission,
)


class RenderQueueError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def authenticate_submission(secret: bytes, job: RenderJobV2, signature: str) -> None:
    expected = sign_submission(secret, job)
    if not signature or not hmac.compare_digest(expected, signature):
        raise RenderSecurityViolation("AUTH_SIGNATURE_INVALID", "render submission signature rejected")


def inspect_hwpx(data: bytes, *, filename: str, principal_id: str) -> RenderInputInspection:
    """Inspect the actual archive; no caller-supplied ZIP facts are trusted."""

    encrypted = symlink = traversal = False
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            names = {info.filename.replace("\\", "/") for info in infos}
            for info in infos:
                normalized = info.filename.replace("\\", "/")
                parts = Path(normalized).parts
                traversal |= normalized.startswith("/") or ".." in parts
                encrypted |= bool(info.flag_bits & 0x1)
                mode = info.external_attr >> 16
                symlink |= stat.S_ISLNK(mode)
                total += info.file_size
            if "mimetype" not in names or not any(name.startswith("Contents/") for name in names):
                raise RenderSecurityViolation("INVALID_HWPX_PACKAGE", "required HWPX package members are missing")
            try:
                media = archive.read("mimetype", pwd=None).decode("ascii").strip()
            except (KeyError, UnicodeDecodeError, RuntimeError) as exc:
                raise RenderSecurityViolation("INVALID_HWPX_PACKAGE", "HWPX mimetype is unreadable") from exc
            if media != HWPX_MEDIA_TYPE:
                raise RenderSecurityViolation("INVALID_HWPX_PACKAGE", "HWPX mimetype is invalid")
    except (zipfile.BadZipFile, OSError) as exc:
        raise RenderSecurityViolation("INVALID_HWPX_ZIP", "render input is not a readable HWPX ZIP") from exc
    return RenderInputInspection(
        authenticated=True,
        principal_id=principal_id,
        filename=filename,
        media_type=HWPX_MEDIA_TYPE,
        compressed_bytes=len(data),
        uncompressed_bytes=total,
        zip_entries=len(infos),
        has_encrypted_entry=encrypted,
        has_symlink_entry=symlink,
        has_path_traversal=traversal,
    )


@dataclass(frozen=True)
class RenderLease:
    job: RenderJobV2
    worker_id: str
    attempt: int
    lease_expires_at: datetime
    source_path: Path


class ContentAddressedStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.blobs = self.root / "blobs"
        self.blobs.mkdir(parents=True, exist_ok=True)

    def path_for(self, content_hash: str) -> Path:
        digest = content_hash.removeprefix("sha256:")
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise RenderQueueError("INVALID_CONTENT_HASH", "invalid SHA-256 content address")
        return self.blobs / digest[:2] / digest

    def put(self, data: bytes, expected_hash: str) -> Path:
        actual = "sha256:" + hashlib.sha256(data).hexdigest()
        if actual != expected_hash:
            raise RenderQueueError("CONTENT_HASH_MISMATCH", "input bytes do not match source_content_hash")
        target = self.path_for(actual)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            return target
        fd, tmp_name = tempfile.mkstemp(prefix=".incoming-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        finally:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
        return target


class DurableRenderQueue:
    """SQLite WAL/FULL queue with leases, idempotency, and terminal receipts."""

    TERMINAL = {"succeeded", "failed", "unavailable", "cancelled"}

    def __init__(
        self,
        root: Path,
        *,
        secret: bytes,
        policy: RenderSecurityPolicy,
        max_attempts: int = 3,
    ) -> None:
        if not secret:
            raise ValueError("queue authentication secret must not be empty")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "render-queue.sqlite3"
        self.secret = secret
        self.policy = policy
        self.max_attempts = max_attempts
        self.content = ContentAddressedStore(self.root / "content")
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=FULL")
            con.execute(
                """CREATE TABLE IF NOT EXISTS render_jobs (
                    job_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE, input_hash TEXT NOT NULL,
                    job_json TEXT NOT NULL, source_path TEXT NOT NULL,
                    state TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
                    worker_id TEXT, lease_expires_at TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
                    receipt_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    terminal_at TEXT
                )"""
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS worker_heartbeat (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), observed_at TEXT NOT NULL,
                    worker_version TEXT NOT NULL, hancom_build TEXT NOT NULL,
                    available INTEGER NOT NULL, degraded_reason TEXT
                )"""
            )

    def pragmas(self) -> tuple[str, int]:
        with self._connect() as con:
            return str(con.execute("PRAGMA journal_mode").fetchone()[0]).lower(), int(
                con.execute("PRAGMA synchronous").fetchone()[0]
            )

    def submit(
        self,
        job: RenderJobV2,
        data: bytes,
        *,
        signature: str,
        principal_id: str,
        filename: str = "document.hwpx",
    ) -> RenderReceiptV2:
        authenticate_submission(self.secret, job, signature)
        if len(data) != job.source_size_bytes:
            raise RenderQueueError("CONTENT_SIZE_MISMATCH", "input bytes do not match source_size_bytes")
        inspection = inspect_hwpx(data, filename=filename, principal_id=principal_id)
        validate_render_input(inspection, self.policy)
        source_path = self.content.put(data, job.source_content_hash)
        now = utcnow()
        queued = RenderReceiptV2(
            job_id=job.job_id,
            workflow_id=job.workflow_id,
            input_content_hash=job.source_content_hash,
            status=RenderStatus.QUEUED,
            queued_at=job.submitted_at,
        )
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute(
                "SELECT * FROM render_jobs WHERE idempotency_key=? OR job_id=?",
                (job.idempotency_key, job.job_id),
            ).fetchone()
            if existing:
                same = (
                    existing["job_id"] == job.job_id
                    and existing["input_hash"] == job.source_content_hash
                    and existing["job_json"] == job.model_dump_json()
                )
                if not same:
                    con.rollback()
                    raise RenderQueueError("IDEMPOTENCY_CONFLICT", "idempotency key or job id reused")
                con.commit()
                return self._receipt_from_row(existing)
            con.execute(
                """INSERT INTO render_jobs
                (job_id,workflow_id,idempotency_key,input_hash,job_json,source_path,state,receipt_json,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    job.job_id, job.workflow_id, job.idempotency_key, job.source_content_hash,
                    job.model_dump_json(), str(source_path), "queued", queued.model_dump_json(),
                    _iso(now), _iso(now),
                ),
            )
            con.commit()
        return queued

    def _recover_expired(self, con: sqlite3.Connection, now: datetime) -> None:
        rows = con.execute(
            "SELECT * FROM render_jobs WHERE state='running' AND lease_expires_at < ?",
            (_iso(now),),
        ).fetchall()
        for row in rows:
            if row["attempt"] >= self.max_attempts:
                receipt = self._terminal_from_row(row, RenderStatus.UNAVAILABLE, now, "LEASE_EXHAUSTED")
                con.execute(
                    "UPDATE render_jobs SET state='unavailable',receipt_json=?,terminal_at=?,worker_id=NULL,lease_expires_at=NULL,updated_at=? WHERE job_id=?",
                    (receipt.model_dump_json(), _iso(now), _iso(now), row["job_id"]),
                )
            else:
                con.execute(
                    "UPDATE render_jobs SET state='queued',worker_id=NULL,lease_expires_at=NULL,updated_at=? WHERE job_id=?",
                    (_iso(now), row["job_id"]),
                )

    def claim(self, worker_id: str, *, lease_seconds: int = 300, now: datetime | None = None) -> RenderLease | None:
        if not worker_id or lease_seconds < 1:
            raise ValueError("worker_id and a positive lease are required")
        now = now or utcnow()
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            self._recover_expired(con, now)
            row = con.execute("SELECT * FROM render_jobs WHERE state='queued' ORDER BY created_at,job_id LIMIT 1").fetchone()
            if not row:
                con.commit()
                return None
            if row["cancel_requested"]:
                receipt = self._terminal_from_row(row, RenderStatus.CANCELLED, now, "CLIENT_CANCELLED")
                con.execute(
                    "UPDATE render_jobs SET state='cancelled',receipt_json=?,terminal_at=?,updated_at=? WHERE job_id=?",
                    (receipt.model_dump_json(), _iso(now), _iso(now), row["job_id"]),
                )
                con.commit()
                return None
            expires = now + timedelta(seconds=lease_seconds)
            attempt = int(row["attempt"]) + 1
            running = RenderReceiptV2(
                job_id=row["job_id"], workflow_id=row["workflow_id"],
                input_content_hash=row["input_hash"], status=RenderStatus.RUNNING,
                queued_at=RenderJobV2.model_validate_json(row["job_json"]).submitted_at,
                started_at=now, retry_count=attempt - 1,
            )
            con.execute(
                "UPDATE render_jobs SET state='running',attempt=?,worker_id=?,lease_expires_at=?,receipt_json=?,updated_at=? WHERE job_id=?",
                (attempt, worker_id, _iso(expires), running.model_dump_json(), _iso(now), row["job_id"]),
            )
            con.commit()
        return RenderLease(RenderJobV2.model_validate_json(row["job_json"]), worker_id, attempt, expires, Path(row["source_path"]))

    def keepalive(self, lease: RenderLease, *, lease_seconds: int = 300, now: datetime | None = None) -> bool:
        """Renew an owned lease; return False when cancellation was requested."""
        if lease_seconds < 1:
            raise ValueError("a positive lease is required")
        now = now or utcnow()
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = self._owned_running(con, lease)
            if datetime.fromisoformat(row["lease_expires_at"]) <= now:
                raise RenderQueueError("LEASE_NOT_OWNED", "render lease has expired")
            con.execute(
                "UPDATE render_jobs SET lease_expires_at=?,updated_at=? WHERE job_id=?",
                (_iso(now + timedelta(seconds=lease_seconds)), _iso(now), lease.job.job_id),
            )
            con.commit()
            return not bool(row["cancel_requested"])

    def complete(self, lease: RenderLease, receipt: RenderReceiptV2, *, now: datetime | None = None) -> RenderReceiptV2:
        now = now or utcnow()
        if receipt.status != RenderStatus.SUCCEEDED or not receipt.binds(lease.job):
            raise RenderQueueError("RECEIPT_BINDING_INVALID", "success receipt is not bound to leased job")
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = self._owned_running(con, lease)
            if row["cancel_requested"]:
                con.rollback()
                raise RenderQueueError("CANCEL_REQUESTED", "worker must stop and acknowledge cancellation")
            con.execute(
                "UPDATE render_jobs SET state='succeeded',receipt_json=?,terminal_at=?,worker_id=NULL,lease_expires_at=NULL,updated_at=? WHERE job_id=?",
                (receipt.model_dump_json(), _iso(now), _iso(now), lease.job.job_id),
            )
            con.commit()
        return receipt

    def fail(self, lease: RenderLease, *, reason: str, retryable: bool, now: datetime | None = None) -> RenderReceiptV2:
        now = now or utcnow()
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = self._owned_running(con, lease)
            cancelled = bool(row["cancel_requested"])
            if retryable and lease.attempt < self.max_attempts and not cancelled:
                queued = RenderReceiptV2(
                    job_id=lease.job.job_id, workflow_id=lease.job.workflow_id,
                    input_content_hash=lease.job.source_content_hash, status=RenderStatus.QUEUED,
                    queued_at=lease.job.submitted_at, retry_count=lease.attempt,
                )
                con.execute(
                    "UPDATE render_jobs SET state='queued',receipt_json=?,worker_id=NULL,lease_expires_at=NULL,updated_at=? WHERE job_id=?",
                    (queued.model_dump_json(), _iso(now), lease.job.job_id),
                )
                con.commit()
                return queued
            status = RenderStatus.CANCELLED if cancelled else RenderStatus.FAILED
            code = "CLIENT_CANCELLED" if cancelled else reason
            receipt = self._terminal_from_row(row, status, now, code)
            con.execute(
                "UPDATE render_jobs SET state=?,receipt_json=?,terminal_at=?,worker_id=NULL,lease_expires_at=NULL,updated_at=? WHERE job_id=?",
                (status.value, receipt.model_dump_json(), _iso(now), _iso(now), lease.job.job_id),
            )
            con.commit()
            return receipt

    def cancel(self, job_id: str, *, now: datetime | None = None) -> RenderReceiptV2:
        now = now or utcnow()
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT * FROM render_jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row:
                con.rollback()
                raise RenderQueueError("JOB_NOT_FOUND", "render job not found")
            if row["state"] in self.TERMINAL:
                con.commit()
                return self._receipt_from_row(row)
            if row["state"] == "running":
                con.execute("UPDATE render_jobs SET cancel_requested=1,updated_at=? WHERE job_id=?", (_iso(now), job_id))
                con.commit()
                return self._receipt_from_row(row)
            receipt = self._terminal_from_row(row, RenderStatus.CANCELLED, now, "CLIENT_CANCELLED")
            con.execute(
                "UPDATE render_jobs SET state='cancelled',cancel_requested=1,receipt_json=?,terminal_at=?,updated_at=? WHERE job_id=?",
                (receipt.model_dump_json(), _iso(now), _iso(now), job_id),
            )
            con.commit()
            return receipt

    def get(self, job_id: str) -> RenderReceiptV2:
        with self._connect() as con:
            row = con.execute("SELECT * FROM render_jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            raise RenderQueueError("JOB_NOT_FOUND", "render job not found")
        return self._receipt_from_row(row)

    def heartbeat(
        self, *, worker_version: str, hancom_build: str, available: bool,
        degraded_reason: str | None = None, now: datetime | None = None,
    ) -> None:
        if not worker_version or not hancom_build:
            raise ValueError("worker_version and hancom_build are required")
        if not available and not degraded_reason:
            raise ValueError("unavailable heartbeat requires degraded_reason")
        now = now or utcnow()
        with self._connect() as con:
            con.execute(
                """INSERT INTO worker_heartbeat
                (singleton,observed_at,worker_version,hancom_build,available,degraded_reason)
                VALUES (1,?,?,?,?,?) ON CONFLICT(singleton) DO UPDATE SET
                observed_at=excluded.observed_at,worker_version=excluded.worker_version,
                hancom_build=excluded.hancom_build,available=excluded.available,
                degraded_reason=excluded.degraded_reason""",
                (_iso(now), worker_version, hancom_build, int(available), degraded_reason),
            )

    def health(self, *, now: datetime | None = None, heartbeat_ttl_seconds: int = 120) -> dict[str, object]:
        now = now or utcnow()
        with self._connect() as con:
            counts = {row["state"]: int(row["count"]) for row in con.execute(
                "SELECT state, COUNT(*) AS count FROM render_jobs GROUP BY state"
            )}
            oldest = con.execute("SELECT MIN(created_at) FROM render_jobs WHERE state='queued'").fetchone()[0]
            success = con.execute(
                "SELECT receipt_json,terminal_at FROM render_jobs WHERE state='succeeded' ORDER BY terminal_at DESC LIMIT 1"
            ).fetchone()
            heartbeat = con.execute("SELECT * FROM worker_heartbeat WHERE singleton=1").fetchone()
        last_receipt = self._receipt_from_row(success) if success else None
        heartbeat_fresh = bool(
            heartbeat and (now - _dt(heartbeat["observed_at"])).total_seconds() <= heartbeat_ttl_seconds
        )
        available = bool(heartbeat_fresh and heartbeat["available"])
        degraded_reason = None if available else (
            heartbeat["degraded_reason"] if heartbeat_fresh else "NO_WORKER_HEARTBEAT"
        )
        return {
            "schemaVersion": "hwpx.render-health.v1",
            "available": available,
            "degraded": not available,
            "degradedReason": degraded_reason,
            "queueDepth": counts.get("queued", 0),
            "runningJobs": counts.get("running", 0),
            "oldestQueuedAgeSeconds": max(0.0, (now - _dt(oldest)).total_seconds()) if oldest else 0.0,
            "lastSuccessfulRealRender": success["terminal_at"] if success else None,
            "workerVersion": heartbeat["worker_version"] if heartbeat else (last_receipt.worker_version if last_receipt else None),
            "hancomBuild": heartbeat["hancom_build"] if heartbeat else (last_receipt.hancom_build if last_receipt else None),
        }

    def purge(self, *, now: datetime | None = None) -> int:
        now = now or utcnow()
        cutoff = now - timedelta(seconds=max(self.policy.input_retention_seconds, self.policy.output_retention_seconds))
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            rows = con.execute(
                "SELECT source_path FROM render_jobs WHERE terminal_at IS NOT NULL AND terminal_at <= ?",
                (_iso(cutoff),),
            ).fetchall()
            removed = con.execute(
                "DELETE FROM render_jobs WHERE terminal_at IS NOT NULL AND terminal_at <= ?",
                (_iso(cutoff),),
            ).rowcount
            con.commit()
        for row in rows:
            path = Path(row["source_path"])
            with self._connect() as con:
                referenced = con.execute("SELECT 1 FROM render_jobs WHERE source_path=? LIMIT 1", (str(path),)).fetchone()
            if not referenced:
                path.unlink(missing_ok=True)
        return int(removed)

    def _owned_running(self, con: sqlite3.Connection, lease: RenderLease) -> sqlite3.Row:
        row = con.execute("SELECT * FROM render_jobs WHERE job_id=?", (lease.job.job_id,)).fetchone()
        if not row or row["state"] != "running" or row["worker_id"] != lease.worker_id or row["attempt"] != lease.attempt:
            raise RenderQueueError("LEASE_NOT_OWNED", "render lease is stale or not owned")
        return row

    @staticmethod
    def _receipt_from_row(row: sqlite3.Row) -> RenderReceiptV2:
        return RenderReceiptV2.model_validate_json(row["receipt_json"])

    @staticmethod
    def _terminal_from_row(row: sqlite3.Row, status: RenderStatus, now: datetime, reason: str) -> RenderReceiptV2:
        job = RenderJobV2.model_validate_json(row["job_json"])
        return RenderReceiptV2(
            job_id=job.job_id, workflow_id=job.workflow_id, input_content_hash=job.source_content_hash,
            status=status, queued_at=job.submitted_at, completed_at=now,
            retry_count=int(row["attempt"]), terminal_reason=reason,
        )


__all__ = [
    "ContentAddressedStore", "DurableRenderQueue", "RenderLease", "RenderQueueError",
    "authenticate_submission", "inspect_hwpx", "sign_submission",
]
