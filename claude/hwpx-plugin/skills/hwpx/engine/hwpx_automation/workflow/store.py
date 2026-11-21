# SPDX-License-Identifier: Apache-2.0
"""Crash-safe SQLite state and tamper-evident append-only workflow ledger."""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

from .models import (
    ActionResult,
    TERMINAL_STATES,
    WorkOrder,
    WorkflowEvent,
    WorkflowRecord,
    WorkflowState,
    canonical_json,
    content_hash,
    sanitize_ledger_payload,
    utc_now,
)
from .state_machine import assert_transition

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_CRYPTOGRAPHY_INSTALL_HINT = (
    "The durable workflow store encrypts work orders and results with AES-GCM "
    "and needs the 'cryptography' package. Install it with: "
    "pip install 'python-hwpx-automation[workflow]' "
    "(the [mcp] extra includes it too)."
)


def _aesgcm_class() -> type[AESGCM]:
    """Import AES-GCM on first use; ``cryptography`` is an optional extra."""

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise WorkflowStoreDependencyError(_CRYPTOGRAPHY_INSTALL_HINT) from exc
    return AESGCM


class WorkflowStoreDependencyError(ImportError):
    """The optional dependency the encrypted workflow store needs is missing."""


class WorkflowConflict(RuntimeError):
    pass


class WorkflowNotFound(KeyError):
    pass


class WorkflowStore:
    """Durable local workflow store.

    Each mutation uses ``BEGIN IMMEDIATE`` and ``synchronous=FULL``.  The event
    chain makes accidental history edits detectable while SQLite WAL provides
    process-crash recovery.
    """

    _ENCRYPTED_PREFIX = "enc:v1:"
    _MAX_RESULT_RETENTION_SECONDS = 30 * 24 * 60 * 60

    def __init__(
        self,
        path: str | Path,
        *,
        encryption_key: bytes | str | None = None,
        result_retention_seconds: int = 24 * 60 * 60,
    ) -> None:
        # Fail before touching the disk: without the cipher no key file or
        # database should be created, and existing encrypted rows stay intact.
        aesgcm = _aesgcm_class()
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not 1 <= result_retention_seconds <= self._MAX_RESULT_RETENTION_SECONDS:
            raise ValueError("result retention must be between 1 second and 30 days")
        self.result_retention_seconds = result_retention_seconds
        self._key = self._load_or_create_key(encryption_key)
        self._aead = aesgcm(self._key)
        migrated = self._initialize()
        if migrated:
            # Ensure legacy plaintext does not survive in free pages or the WAL.
            self._compact_sensitive_storage()
        self.purge_expired_results()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA secure_delete=ON")
        return connection

    def _load_or_create_key(self, supplied: bytes | str | None) -> bytes:
        if supplied is not None:
            key = supplied if isinstance(supplied, bytes) else base64.urlsafe_b64decode(supplied)
            if len(key) != 32:
                raise ValueError("workflow encryption key must be exactly 32 bytes")
            return key
        configured = os.environ.get("HWPX_WORKFLOW_ENCRYPTION_KEY")
        if configured:
            try:
                key = base64.urlsafe_b64decode(configured)
            except Exception as exc:
                raise ValueError("HWPX_WORKFLOW_ENCRYPTION_KEY must be URL-safe base64") from exc
            if len(key) != 32:
                raise ValueError("HWPX_WORKFLOW_ENCRYPTION_KEY must decode to exactly 32 bytes")
            return key
        key_path = self.path.with_name(f"{self.path.name}.key")
        try:
            key = key_path.read_bytes()
        except FileNotFoundError:
            key = _aesgcm_class().generate_key(bit_length=256)
            temporary = key_path.with_name(f".{key_path.name}.{uuid.uuid4().hex}.tmp")
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(key)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(temporary, key_path)
                except FileExistsError:
                    key = key_path.read_bytes()
            finally:
                temporary.unlink(missing_ok=True)
        if len(key) != 32:
            raise WorkflowConflict(f"invalid workflow encryption key file: {key_path}")
        return key

    def _compact_sensitive_storage(self) -> None:
        """Remove replaced encrypted payloads from the WAL and free pages."""

        with self._connect() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("VACUUM")

    def _encrypt_json(self, value: Any, *, associated_data: str) -> str:
        nonce = os.urandom(12)
        plaintext = canonical_json(value).encode("utf-8")
        ciphertext = self._aead.encrypt(nonce, plaintext, associated_data.encode("utf-8"))
        return self._ENCRYPTED_PREFIX + base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")

    def _decrypt_json(self, envelope: str, *, associated_data: str) -> Any:
        if not envelope.startswith(self._ENCRYPTED_PREFIX):
            return json.loads(envelope)
        try:
            packed = base64.urlsafe_b64decode(envelope[len(self._ENCRYPTED_PREFIX) :])
            plaintext = self._aead.decrypt(
                packed[:12], packed[12:], associated_data.encode("utf-8")
            )
            return json.loads(plaintext)
        except Exception as exc:
            raise WorkflowConflict("encrypted workflow data failed authentication") from exc

    @staticmethod
    def _action_result_aad(
        workflow_id: str,
        action_hash: str,
        result_hash: str,
        size_bytes: int,
        created_at: str,
        expires_at: str,
    ) -> str:
        return canonical_json(
            {
                "kind": "action-result",
                "workflowId": workflow_id,
                "actionHash": action_hash,
                "contentHash": result_hash,
                "sizeBytes": size_bytes,
                "createdAt": created_at,
                "expiresAt": expires_at,
            }
        )

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> bool:
        migrated = False
        with self._transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS workflows (
                    workflow_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    work_order_json TEXT NOT NULL,
                    work_order_hash TEXT NOT NULL,
                    state TEXT NOT NULL,
                    state_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    original_content_hash TEXT,
                    output_content_hash TEXT,
                    stop_reason TEXT
                );
                CREATE TABLE IF NOT EXISTS workflow_events (
                    workflow_id TEXT NOT NULL REFERENCES workflows(workflow_id),
                    event_index INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    from_state TEXT,
                    to_state TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT,
                    event_hash TEXT NOT NULL,
                    event_key TEXT,
                    PRIMARY KEY (workflow_id, event_index),
                    UNIQUE (workflow_id, event_hash),
                    UNIQUE (workflow_id, event_key)
                );
                CREATE INDEX IF NOT EXISTS workflow_events_lookup
                    ON workflow_events(workflow_id, event_index);
                CREATE TABLE IF NOT EXISTS workflow_action_results (
                    workflow_id TEXT NOT NULL REFERENCES workflows(workflow_id) ON DELETE CASCADE,
                    action_hash TEXT NOT NULL,
                    result_ciphertext TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    PRIMARY KEY (workflow_id, action_hash)
                );
                CREATE INDEX IF NOT EXISTS workflow_action_results_expiry
                    ON workflow_action_results(expires_at);
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(workflow_events)").fetchall()
            }
            if "event_key" not in columns:
                connection.execute("ALTER TABLE workflow_events ADD COLUMN event_key TEXT")
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS workflow_events_event_key "
                    "ON workflow_events(workflow_id, event_key) WHERE event_key IS NOT NULL"
                )
            rows = connection.execute(
                "SELECT workflow_id, idempotency_key, work_order_json FROM workflows"
            ).fetchall()
            for row in rows:
                idempotency_key = str(row["idempotency_key"])
                if not idempotency_key.startswith("sha256:"):
                    connection.execute(
                        "UPDATE workflows SET idempotency_key = ? WHERE workflow_id = ?",
                        (content_hash(idempotency_key), row["workflow_id"]),
                    )
                    migrated = True
                serialized = str(row["work_order_json"])
                if serialized.startswith(self._ENCRYPTED_PREFIX):
                    continue
                parsed = json.loads(serialized)
                connection.execute(
                    "UPDATE workflows SET work_order_json = ? WHERE workflow_id = ?",
                    (
                        self._encrypt_json(
                            parsed,
                            associated_data=f"work-order:{row['workflow_id']}",
                        ),
                        row["workflow_id"],
                    ),
                )
                migrated = True
        return migrated

    def create(
        self,
        work_order: WorkOrder,
        *,
        original_content_hash: str | None = None,
        workflow_id: str | None = None,
    ) -> tuple[WorkflowRecord, bool]:
        """Create or idempotently recover a workflow.

        Returns ``(record, created)``. Reusing a key for different content fails
        closed instead of silently returning the unrelated workflow.
        """

        workflow_id = workflow_id or f"wf_{uuid.uuid4().hex}"
        now = utc_now()
        idempotency_key_hash = content_hash(work_order.idempotency_key)
        order_json = self._encrypt_json(
            work_order.model_dump(mode="json"),
            associated_data=f"work-order:{workflow_id}",
        )
        order_hash = work_order.fingerprint()
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM workflows WHERE idempotency_key = ?", (idempotency_key_hash,)
            ).fetchone()
            if existing is not None:
                if existing["work_order_hash"] != order_hash:
                    raise WorkflowConflict("idempotency key was already used for a different work order")
                return self._record_from_row(existing), False

            connection.execute(
                """INSERT INTO workflows(
                    workflow_id, idempotency_key, work_order_json, work_order_hash,
                    state, state_version, created_at, updated_at, original_content_hash
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                (
                    workflow_id,
                    idempotency_key_hash,
                    order_json,
                    order_hash,
                    WorkflowState.INTAKE.value,
                    now.isoformat(),
                    now.isoformat(),
                    original_content_hash,
                ),
            )
            self._append_event(
                connection,
                workflow_id=workflow_id,
                event_type="workflow.created",
                from_state=None,
                to_state=WorkflowState.INTAKE,
                payload=work_order.ledger_summary(),
                occurred_at=now,
            )
            row = connection.execute("SELECT * FROM workflows WHERE workflow_id = ?", (workflow_id,)).fetchone()
            assert row is not None
            return self._record_from_row(row), True

    def get(self, workflow_id: str) -> WorkflowRecord:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM workflows WHERE workflow_id = ?", (workflow_id,)).fetchone()
        if row is None:
            raise WorkflowNotFound(workflow_id)
        return self._record_from_row(row)

    def transition(
        self,
        workflow_id: str,
        target: WorkflowState,
        *,
        expected_state: WorkflowState,
        expected_version: int,
        event_type: str = "workflow.transitioned",
        payload: dict[str, Any] | None = None,
        output_content_hash: str | None = None,
        stop_reason: str | None = None,
    ) -> WorkflowRecord:
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM workflows WHERE workflow_id = ?", (workflow_id,)).fetchone()
            if row is None:
                raise WorkflowNotFound(workflow_id)
            current = WorkflowState(row["state"])
            version = int(row["state_version"])
            if event_type in {"decision.approved", "decision.rejected"}:
                raise WorkflowConflict("decision receipts must use the same-state append_event policy path")
            if current != expected_state or version != expected_version:
                raise WorkflowConflict(
                    f"stale workflow state: expected {expected_state.value}@{expected_version}, "
                    f"actual {current.value}@{version}"
                )
            assert_transition(current, target)
            now = utc_now()
            work_order_json = row["work_order_json"]
            if target in TERMINAL_STATES:
                raw_order = self._decrypt_json(
                    str(work_order_json), associated_data=f"work-order:{workflow_id}"
                )
                raw_order["parameters"] = {}
                work_order_json = self._encrypt_json(
                    raw_order, associated_data=f"work-order:{workflow_id}"
                )
            updated = connection.execute(
                """UPDATE workflows
                   SET state = ?, state_version = state_version + 1, updated_at = ?,
                       output_content_hash = COALESCE(?, output_content_hash),
                       stop_reason = COALESCE(?, stop_reason), work_order_json = ?
                   WHERE workflow_id = ? AND state = ? AND state_version = ?""",
                (
                    target.value,
                    now.isoformat(),
                    output_content_hash,
                    stop_reason,
                    work_order_json,
                    workflow_id,
                    current.value,
                    version,
                ),
            )
            if updated.rowcount != 1:
                raise WorkflowConflict("workflow changed concurrently")
            self._append_event(
                connection,
                workflow_id=workflow_id,
                event_type=event_type,
                from_state=current,
                to_state=target,
                payload=payload or {},
                occurred_at=now,
            )
            result = connection.execute("SELECT * FROM workflows WHERE workflow_id = ?", (workflow_id,)).fetchone()
            assert result is not None
            transitioned = self._record_from_row(result)
        if target in TERMINAL_STATES:
            self._compact_sensitive_storage()
        return transitioned

    def put_action_result(
        self,
        workflow_id: str,
        action_hash: str,
        result: Any,
        *,
        retention_seconds: int | None = None,
    ) -> ActionResult:
        """Persist a JSON result using authenticated encryption.

        Repeating the same workflow/action/result is idempotent. Reusing an
        action hash for different content fails closed.
        """

        retention = self.result_retention_seconds if retention_seconds is None else retention_seconds
        if not 1 <= retention <= self._MAX_RESULT_RETENTION_SECONDS:
            raise ValueError("result retention must be between 1 second and 30 days")
        raw = canonical_json(result).encode("utf-8")
        result_hash = content_hash(raw)
        now = utc_now()
        expires_at = now + timedelta(seconds=retention)
        created_at_text = now.isoformat()
        expires_at_text = expires_at.isoformat()
        with self._transaction() as connection:
            if connection.execute(
                "SELECT 1 FROM workflows WHERE workflow_id = ?", (workflow_id,)
            ).fetchone() is None:
                raise WorkflowNotFound(workflow_id)
            existing = connection.execute(
                "SELECT * FROM workflow_action_results WHERE workflow_id = ? AND action_hash = ?",
                (workflow_id, action_hash),
            ).fetchone()
            if existing is not None:
                if existing["content_hash"] != result_hash:
                    raise WorkflowConflict("action hash was already used for a different result")
                return self._action_result_from_row(existing, include_result=True)
            ciphertext = self._encrypt_json(
                result,
                associated_data=self._action_result_aad(
                    workflow_id,
                    action_hash,
                    result_hash,
                    len(raw),
                    created_at_text,
                    expires_at_text,
                ),
            )
            connection.execute(
                """INSERT INTO workflow_action_results(
                    workflow_id, action_hash, result_ciphertext, content_hash,
                    size_bytes, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    workflow_id,
                    action_hash,
                    ciphertext,
                    result_hash,
                    len(raw),
                    created_at_text,
                    expires_at_text,
                ),
            )
            row = connection.execute(
                "SELECT * FROM workflow_action_results WHERE workflow_id = ? AND action_hash = ?",
                (workflow_id, action_hash),
            ).fetchone()
            assert row is not None
            return self._action_result_from_row(row, include_result=True)

    def get_action_result(self, workflow_id: str, action_hash: str) -> Any:
        """Return the decrypted result body, or raise ``KeyError`` if unavailable."""

        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM workflow_action_results
                   WHERE workflow_id = ? AND action_hash = ? AND expires_at > ?""",
                (workflow_id, action_hash, utc_now().isoformat()),
            ).fetchone()
        if row is None:
            raise KeyError((workflow_id, action_hash))
        return self._action_result_from_row(row, include_result=True).result

    def action_result_metadata(self, workflow_id: str, action_hash: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM workflow_action_results
                   WHERE workflow_id = ? AND action_hash = ? AND expires_at > ?""",
                (workflow_id, action_hash, utc_now().isoformat()),
            ).fetchone()
        if row is None:
            return None
        value = self._action_result_from_row(row, include_result=False)
        return value.model_dump(mode="json", by_alias=True, exclude={"result"})

    def list_action_results(self, workflow_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM workflow_action_results
                   WHERE workflow_id = ? AND expires_at > ? ORDER BY created_at, action_hash""",
                (workflow_id, utc_now().isoformat()),
            ).fetchall()
        if not rows and not self._exists(workflow_id):
            raise WorkflowNotFound(workflow_id)
        return [
            self._action_result_from_row(row, include_result=False).model_dump(
                mode="json", by_alias=True, exclude={"result"}
            )
            for row in rows
        ]

    def purge_expired_results(self, *, now: datetime | None = None) -> int:
        cutoff = now or utc_now()
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        cutoff = cutoff.astimezone(timezone.utc)
        with self._transaction() as connection:
            deleted = connection.execute(
                "DELETE FROM workflow_action_results WHERE expires_at <= ?", (cutoff.isoformat(),)
            )
            deleted_count = int(deleted.rowcount)
        if deleted_count:
            self._compact_sensitive_storage()
        return deleted_count

    def append_event(
        self,
        workflow_id: str,
        event_type: str,
        *,
        expected_state: WorkflowState,
        expected_version: int,
        payload: dict[str, Any] | None = None,
        event_key: str | None = None,
    ) -> tuple[WorkflowRecord, WorkflowEvent, bool]:
        """Append an idempotent same-state receipt under optimistic CAS.

        Same-state actions are mutations too, so they advance ``state_version``.
        An ``event_key`` makes retries return the original receipt without
        creating a second event, while reuse for different content fails closed.
        """

        raw_payload = payload or {}
        safe_payload = sanitize_ledger_payload(raw_payload, key="event")
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM workflows WHERE workflow_id = ?", (workflow_id,)).fetchone()
            if row is None:
                raise WorkflowNotFound(workflow_id)
            current = WorkflowState(row["state"])
            version = int(row["state_version"])
            if event_type in {"decision.approved", "decision.rejected"}:
                if current != WorkflowState.DECISION:
                    raise WorkflowConflict("decision receipts are only valid in decision state")
                if not isinstance(raw_payload.get("actionHash"), str):
                    raise WorkflowConflict("decision receipt requires an action hash")
                expected_approval = event_type == "decision.approved"
                if raw_payload.get("approved") is not expected_approval:
                    raise WorkflowConflict("decision receipt type and approved value disagree")
            if event_key is not None:
                existing = connection.execute(
                    "SELECT * FROM workflow_events WHERE workflow_id = ? AND event_key = ?",
                    (workflow_id, event_key),
                ).fetchone()
                if existing is not None:
                    event = self._event_from_row(existing)
                    if event.event_type != event_type or event.payload != safe_payload:
                        raise WorkflowConflict("event key was already used for a different receipt")
                    return self._record_from_row(row), event, False
            if current != expected_state or version != expected_version:
                raise WorkflowConflict(
                    f"stale workflow state: expected {expected_state.value}@{expected_version}, "
                    f"actual {current.value}@{version}"
                )
            now = utc_now()
            updated = connection.execute(
                """UPDATE workflows SET state_version = state_version + 1, updated_at = ?
                   WHERE workflow_id = ? AND state = ? AND state_version = ?""",
                (now.isoformat(), workflow_id, current.value, version),
            )
            if updated.rowcount != 1:
                raise WorkflowConflict("workflow changed concurrently")
            self._append_event(
                connection,
                workflow_id=workflow_id,
                event_type=event_type,
                from_state=current,
                to_state=current,
                payload=raw_payload,
                occurred_at=now,
                event_key=event_key,
            )
            result = connection.execute("SELECT * FROM workflows WHERE workflow_id = ?", (workflow_id,)).fetchone()
            event_row = connection.execute(
                "SELECT * FROM workflow_events WHERE workflow_id = ? ORDER BY event_index DESC LIMIT 1",
                (workflow_id,),
            ).fetchone()
            assert result is not None and event_row is not None
            return self._record_from_row(result), self._event_from_row(event_row), True

    def events(self, workflow_id: str, *, verify_chain: bool = True) -> list[WorkflowEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM workflow_events WHERE workflow_id = ? ORDER BY event_index", (workflow_id,)
            ).fetchall()
        if not rows and not self._exists(workflow_id):
            raise WorkflowNotFound(workflow_id)
        events = [self._event_from_row(row) for row in rows]
        if verify_chain:
            previous: str | None = None
            for event in events:
                if event.previous_hash != previous or self._calculate_event_hash(event) != event.event_hash:
                    raise WorkflowConflict(f"workflow event chain is invalid at index {event.index}")
                previous = event.event_hash
        return events

    def _exists(self, workflow_id: str) -> bool:
        with self._connect() as connection:
            return connection.execute(
                "SELECT 1 FROM workflows WHERE workflow_id = ?", (workflow_id,)
            ).fetchone() is not None

    def _append_event(
        self,
        connection: sqlite3.Connection,
        *,
        workflow_id: str,
        event_type: str,
        from_state: WorkflowState | None,
        to_state: WorkflowState,
        payload: dict[str, Any],
        occurred_at: datetime,
        event_key: str | None = None,
    ) -> None:
        last = connection.execute(
            "SELECT event_index, event_hash FROM workflow_events WHERE workflow_id = ? ORDER BY event_index DESC LIMIT 1",
            (workflow_id,),
        ).fetchone()
        index = int(last["event_index"]) + 1 if last else 0
        previous_hash = str(last["event_hash"]) if last else None
        safe_payload = sanitize_ledger_payload(payload, key="event")
        event = WorkflowEvent(
            workflow_id=workflow_id,
            index=index,
            event_type=event_type,
            from_state=from_state,
            to_state=to_state,
            occurred_at=occurred_at,
            payload=safe_payload,
            previous_hash=previous_hash,
            event_hash="pending",
            event_key=event_key,
        )
        event_hash = self._calculate_event_hash(event)
        connection.execute(
            """INSERT INTO workflow_events(
                workflow_id, event_index, event_type, from_state, to_state,
                occurred_at, payload_json, previous_hash, event_hash
                , event_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                workflow_id,
                index,
                event_type,
                from_state.value if from_state else None,
                to_state.value,
                occurred_at.isoformat(),
                canonical_json(safe_payload),
                previous_hash,
                event_hash,
                event_key,
            ),
        )

    @staticmethod
    def _calculate_event_hash(event: WorkflowEvent) -> str:
        hashed = {
            "workflowId": event.workflow_id,
            "index": event.index,
            "eventType": event.event_type,
            "fromState": event.from_state.value if event.from_state else None,
            "toState": event.to_state.value,
            "occurredAt": event.occurred_at.isoformat(),
            "payload": event.payload,
            "previousHash": event.previous_hash,
        }
        if event.event_key is not None:
            hashed["eventKey"] = event.event_key
        return content_hash(hashed)

    def _record_from_row(self, row: sqlite3.Row) -> WorkflowRecord:
        work_order = self._decrypt_json(
            str(row["work_order_json"]), associated_data=f"work-order:{row['workflow_id']}"
        )
        return WorkflowRecord(
            workflow_id=row["workflow_id"],
            work_order=WorkOrder.model_validate(work_order),
            state=WorkflowState(row["state"]),
            state_version=int(row["state_version"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            original_content_hash=row["original_content_hash"],
            output_content_hash=row["output_content_hash"],
            stop_reason=row["stop_reason"],
        )

    def _action_result_from_row(
        self, row: sqlite3.Row, *, include_result: bool
    ) -> ActionResult:
        result = None
        if include_result:
            result = self._decrypt_json(
                str(row["result_ciphertext"]),
                associated_data=self._action_result_aad(
                    str(row["workflow_id"]),
                    str(row["action_hash"]),
                    str(row["content_hash"]),
                    int(row["size_bytes"]),
                    str(row["created_at"]),
                    str(row["expires_at"]),
                ),
            )
        return ActionResult(
            workflow_id=row["workflow_id"],
            action_hash=row["action_hash"],
            result=result,
            content_hash=row["content_hash"],
            size_bytes=int(row["size_bytes"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> WorkflowEvent:
        return WorkflowEvent(
            workflow_id=row["workflow_id"],
            index=int(row["event_index"]),
            event_type=row["event_type"],
            from_state=WorkflowState(row["from_state"]) if row["from_state"] else None,
            to_state=WorkflowState(row["to_state"]),
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
            payload=json.loads(row["payload_json"]),
            previous_hash=row["previous_hash"],
            event_hash=row["event_hash"],
            event_key=row["event_key"],
        )


__all__ = [
    "WorkflowConflict",
    "WorkflowNotFound",
    "WorkflowStore",
    "WorkflowStoreDependencyError",
]
