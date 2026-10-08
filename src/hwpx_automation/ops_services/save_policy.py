# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import dataclasses
import hashlib
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, cast
from uuid import uuid4

from .. import quality as quality_contract
from ..storage import LocalDocumentStorage, build_hwpx_verification_report
from ..workspace import (
    WorkspaceMissingParentGuard,
    WorkspaceOutputGuard,
    WorkspacePathError,
)
from ..core.transactions import (
    BackupReport,
    backup_path_for,
    rotate_and_backup,
    rotated_backup_path,
    semantic_diff,
)
from ..upstream import (
    HwpxDocument,
    new_document,
)

from .context import DocumentContext

logger = logging.getLogger("hwpx_automation.hwpx_ops")


@dataclasses.dataclass(frozen=True, slots=True)
class _ExactSidecarMutation:
    """One identity-bound sidecar publication and its exact prestate."""

    before_guard: WorkspaceOutputGuard
    before_bytes: bytes | None
    publication: WorkspaceOutputGuard


@dataclasses.dataclass(frozen=True, slots=True)
class _ExactRecoveryPublication:
    """One randomly named exact recovery publication and its immutable bytes."""

    base_path: Path
    data: bytes
    mode: int | None
    marker: str
    publication: WorkspaceOutputGuard


@dataclasses.dataclass(frozen=True, slots=True)
class _ExactBackupResult:
    """Backup receipt plus reversible identity-bound sidecar publications."""

    report: BackupReport
    mutations: tuple[_ExactSidecarMutation, ...] = ()
    recoveries: tuple[_ExactRecoveryPublication, ...] = ()


class SavePolicy:
    def __init__(self, context: DocumentContext) -> None:
        self._context = context

    def _ensure_backup(self, path: Path) -> Optional[Path]:
        return self._context.storage.ensure_backup(path)

    def _maybe_backup(self, path: Path) -> None:
        self._context.storage.maybe_backup(path)

    def _save_document(
        self, document: HwpxDocument, target: Path, *, quality: Any = None
    ) -> Dict[str, Any]:
        try:
            return self._context.storage.save_document(
                document, target, quality=quality
            )
        except quality_contract.CapabilitySkewError as exc:
            # Fail closed on core/automation/plugin skew (plan §2 Phase F).
            raise self._context._new_error(
                "CAPABILITY_SKEW",
                f"capability handshake skew; writes are blocked: {exc}",
                details={"capability": exc.state, "path": str(target)},
            ) from exc
        except quality_contract.QualityGateError as exc:
            # visual_complete gate failed under an elevated policy → ok=false with
            # a structured, retry-able error the model can act on.
            raise self._context._new_error(
                exc.code,
                f"visual_complete gate failed: {exc}",
                details={
                    "path": str(target),
                    "visualComplete": exc.block,
                    "suggestedRetry": exc.block.get("suggestedRetry"),
                },
            ) from exc
        except PermissionError as exc:
            raise self._context._new_error(
                "PERMISSION_DENIED",
                f"문서 저장 권한이 없습니다: {target}",
                details={"path": str(target)},
            ) from exc
        except Exception as exc:  # pragma: no cover - delegated to backend
            hwp_error = self._context._hwp_error(exc)
            if hwp_error is not None:
                raise hwp_error from exc
            raise self._context._new_error(
                "DOCUMENT_SAVE_FAILED",
                f"failed to save '{target}': {exc}",
                details={"path": str(target)},
            ) from exc

    def _save_transaction_document(
        self, document: HwpxDocument, target: Path, *, quality: Any = None
    ) -> Dict[str, Any]:
        backup = rotate_and_backup(target)
        verification = self._save_document(document, target, quality=quality)
        if not isinstance(verification, dict):
            verification = build_hwpx_verification_report(target)
        verification["filePath"] = str(target)
        verification["backup"] = backup.to_dict()
        if backup.backup_path is not None:
            try:
                verification["semanticDiff"] = semantic_diff(
                    backup.backup_path,
                    target,
                )
            except Exception as exc:  # pragma: no cover - diagnostic fallback
                verification["semanticDiff"] = {
                    "schemaVersion": "hwpx.semantic-diff.v1",
                    "changed": True,
                    "summary": f"Semantic diff unavailable: {exc}",
                    "items": [],
                    "error": str(exc),
                }
        return verification

    @staticmethod
    def _report_for_bytes(data: bytes, *, file_path: Path) -> Dict[str, Any]:
        return build_hwpx_verification_report(data, file_path=file_path)

    @staticmethod
    def _semantic_diff_bytes(before: bytes, after: bytes) -> Dict[str, Any]:
        return semantic_diff(before, after)

    def _capture_exact_sidecar_guard(self, path: Path) -> WorkspaceOutputGuard:
        """Authorize one derived sidecar name without following a final alias."""

        if not isinstance(
            self._context.storage, LocalDocumentStorage
        ):  # pragma: no cover
            raise TypeError("exact sidecar guards require local storage")
        lexical_path = path.parent.resolve(strict=True) / path.name
        guard = self._context.storage.capture_output_guard(path)
        if guard.path != lexical_path:
            raise WorkspacePathError(
                "derived backup path must not be a symlink or alias",
                code="WORKSPACE_PATH_INVALID",
                reason="output_target_alias",
            )
        return guard

    @staticmethod
    def _absent_publication_guard(
        guard: WorkspaceOutputGuard,
    ) -> WorkspaceOutputGuard:
        """Represent the exact absent state produced by a guarded deletion."""

        return dataclasses.replace(
            guard,
            target_existed=False,
            target_device=None,
            target_inode=None,
            target_digest=None,
            target_mode=None,
        )

    def _assert_exact_sidecar_publication(
        self,
        guard: WorkspaceOutputGuard,
    ) -> None:
        """Revalidate either an exact file publication or guarded absence."""

        if guard.target_existed:
            self._context._local_storage().read_guarded_bytes(guard)
            return
        observed = self._capture_exact_sidecar_guard(guard.path)
        if (
            observed.target_existed
            or observed.path != guard.path
            or observed.root != guard.root
            or observed.root_device != guard.root_device
            or observed.root_inode != guard.root_inode
            or observed.parent_device != guard.parent_device
            or observed.parent_inode != guard.parent_inode
        ):
            raise WorkspacePathError(
                "deleted sidecar changed before completion",
                code="WORKSPACE_PATH_CHANGED",
                reason="output_target_changed",
            )

    def _publish_exact_recovery(
        self,
        base_path: Path,
        data: bytes,
        *,
        mode: int | None,
        marker: str,
        max_candidates: int = 32,
    ) -> _ExactRecoveryPublication:
        """Publish recovery bytes without overwriting an existing sidecar."""

        storage = self._context._local_storage()
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", base_path.name)[:48]
        name_digest = hashlib.sha256(os.fsencode(base_path.name)).hexdigest()[:12]
        for _ in range(max_candidates):
            candidate = base_path.with_name(
                f".{safe_name}.{marker}.{name_digest}.{uuid4().hex}.recovery"
            )
            try:
                guard = self._capture_exact_sidecar_guard(candidate)
            except WorkspacePathError:
                continue
            if guard.target_existed:
                continue
            try:
                publication = storage.atomic_publish_bytes(
                    guard,
                    data,
                    mode=mode,
                )
                storage.read_guarded_bytes(publication)
                return _ExactRecoveryPublication(
                    base_path=base_path,
                    data=data,
                    mode=mode,
                    marker=marker,
                    publication=publication,
                )
            except (OSError, RuntimeError):
                # A publish-then-claim race may have installed and then
                # replaced this candidate before the returned token could be
                # verified. Preserve that external winner and retry the same
                # immutable preimage at a fresh unpredictable name.
                continue
        raise RuntimeError(f"no available exact recovery sidecar for {base_path.name}")

    def _preserve_exact_preimages(
        self,
        preimages: Sequence[tuple[Path, bytes, int | None]],
        *,
        marker: str,
    ) -> tuple[_ExactRecoveryPublication, ...] | None:
        """Preserve every preimage before any destructive mutation begins."""

        publications: list[_ExactRecoveryPublication] = []
        for path, data, mode in preimages:
            try:
                publications.append(
                    self._publish_exact_recovery(
                        path,
                        data,
                        mode=mode,
                        marker=marker,
                    )
                )
            except (OSError, RuntimeError):
                return None
        return tuple(publications)

    def _cleanup_exact_recoveries(
        self,
        recoveries: Sequence[_ExactRecoveryPublication],
    ) -> tuple[bool, bool]:
        """Remove proven recoveries, republishing all if any cleanup loses CAS."""

        storage = self._context._local_storage()
        for recovery in recoveries:
            try:
                storage.read_guarded_bytes(recovery.publication)
                storage.remove_guarded_output(recovery.publication)
            except (FileNotFoundError, OSError, RuntimeError):
                return False, self._republish_exact_recoveries(recoveries)
        return True, True

    def _republish_exact_recoveries(
        self,
        recoveries: Sequence[_ExactRecoveryPublication],
    ) -> bool:
        """Recreate immutable recovery copies after cleanup or claim loss."""

        for item in recoveries:
            try:
                self._publish_exact_recovery(
                    item.base_path,
                    item.data,
                    mode=item.mode,
                    marker=item.marker,
                )
            except (OSError, RuntimeError):
                return False
        return True

    def _rotate_and_backup_exact(
        self,
        target: Path,
        *,
        target_guard: WorkspaceOutputGuard | None = None,
        target_bytes: bytes | None = None,
        max_backups: int = 5,
    ) -> _ExactBackupResult:
        """Rotate local sidecars from no-follow guards and an exact preimage."""

        if not isinstance(self._context.storage, LocalDocumentStorage):
            return _ExactBackupResult(
                rotate_and_backup(target, max_backups=max_backups)
            )
        guard = target_guard or self._context.storage.capture_output_guard(target)
        if not guard.target_existed:
            return _ExactBackupResult(BackupReport(None))
        preimage = (
            target_bytes
            if target_bytes is not None
            else self._context.storage.read_guarded_bytes(guard)
        )
        # Revalidate ownership immediately before mutating any sidecar.
        if self._context.storage.read_guarded_bytes(guard) != preimage:
            raise WorkspacePathError(
                "backup source changed before snapshot",
                code="WORKSPACE_PATH_CHANGED",
                reason="output_target_changed",
            )
        source_report = self._report_for_bytes(preimage, file_path=target)
        if not source_report["openSafety"]["ok"]:
            raise self._context._new_error(
                "BACKUP_SOURCE_OPEN_SAFETY_FAILED",
                "backup source failed open-safety verification",
            )

        backup = backup_path_for(target)
        paths = [backup] + [
            rotated_backup_path(target, index) for index in range(1, max_backups + 1)
        ]
        guards = [self._capture_exact_sidecar_guard(path) for path in paths]
        states: list[tuple[bytes, int | None] | None] = []
        for slot_guard in guards:
            states.append(
                (
                    self._context.storage.read_guarded_bytes(slot_guard),
                    slot_guard.target_mode,
                )
                if slot_guard.target_existed
                else None
            )

        recoveries = self._preserve_exact_preimages(
            [
                (path, state[0], state[1])
                for path, state in zip(paths, states)
                if state is not None
            ],
            marker="rollback-recovery",
        )
        if recoveries is None:
            raise RuntimeError("backup rotation preimages could not be preserved")
        rotated: list[Path] = []
        mutations: list[_ExactSidecarMutation] = []
        try:
            for index in range(max_backups, 0, -1):
                destination_guard = guards[index]
                desired = states[index - 1]
                if desired is None:
                    if not destination_guard.target_existed:
                        continue
                    publication = self._absent_publication_guard(destination_guard)
                    mutations.append(
                        _ExactSidecarMutation(
                            before_guard=destination_guard,
                            before_bytes=cast(tuple[bytes, int | None], states[index])[0],
                            publication=publication,
                        )
                    )
                    self._context.storage.remove_guarded_output(destination_guard)
                    self._assert_exact_sidecar_publication(publication)
                    continue
                publication = self._context.storage.atomic_publish_bytes(
                    destination_guard,
                    desired[0],
                    mode=desired[1],
                )
                mutations.append(
                    _ExactSidecarMutation(
                        before_guard=destination_guard,
                        before_bytes=(
                            cast(tuple[bytes, int | None], states[index])[0] if states[index] is not None else None
                        ),
                        publication=publication,
                    )
                )
                self._context.storage.read_guarded_bytes(publication)
                rotated.append(paths[index])

            backup_publication = self._context.storage.atomic_publish_bytes(
                guards[0],
                preimage,
                mode=guard.target_mode,
            )
            mutations.append(
                _ExactSidecarMutation(
                    before_guard=guards[0],
                    before_bytes=states[0][0] if states[0] is not None else None,
                    publication=backup_publication,
                )
            )
            self._context.storage.read_guarded_bytes(backup_publication)
            for mutation in mutations:
                self._assert_exact_sidecar_publication(mutation.publication)
        except BaseException:
            self._rollback_exact_backup_mutations(
                mutations,
                preimages_preserved=True,
            )
            raise
        return _ExactBackupResult(
            BackupReport(backup, tuple(rotated)),
            tuple(mutations),
            recoveries,
        )

    def _rollback_exact_backup_mutations(
        self,
        mutations: Sequence[_ExactSidecarMutation],
        *,
        preimages_preserved: bool = False,
    ) -> None:
        """Restore every sidecar candidate that is still exactly ours."""

        if not preimages_preserved:
            recoveries = self._preserve_exact_preimages(
                [
                    (
                        mutation.publication.path,
                        mutation.before_bytes,
                        mutation.before_guard.target_mode,
                    )
                    for mutation in mutations
                    if mutation.before_bytes is not None
                ],
                marker="rollback-recovery",
            )
            if recoveries is None:
                return

        storage = self._context._local_storage()
        for mutation in reversed(mutations):
            try:
                self._assert_exact_sidecar_publication(mutation.publication)
            except (FileNotFoundError, OSError, RuntimeError):
                continue
            try:
                if mutation.before_bytes is None:
                    storage.remove_guarded_output(mutation.publication)
                else:
                    storage.atomic_publish_bytes(
                        mutation.publication,
                        mutation.before_bytes,
                        mode=mutation.before_guard.target_mode,
                    )
            except (FileNotFoundError, OSError, RuntimeError):
                # An external replacement that wins the CAS belongs to the
                # external writer. Every original preimage was preserved
                # before rollback began, so no later destructive step can
                # erase the last recoverable generation.
                continue

    def _write_patched(
        self,
        target_path,
        data: bytes,
        payload: Dict[str, Any],
        *,
        output_guard: (
            WorkspaceOutputGuard | WorkspaceMissingParentGuard | None
        ) = None,
        output_precondition: (
            WorkspaceOutputGuard | WorkspaceMissingParentGuard | None
        ) = None,
        publication_sink: Callable[[WorkspaceOutputGuard], None] | None = None,
    ) -> Dict[str, Any]:
        """Atomic temp-write + open-safety gate for a byte-preserving result
        (shared by byte_preserving_patch / apply_table_ops)."""
        candidate_bytes = bytes(data)
        report = build_hwpx_verification_report(
            candidate_bytes,
            file_path=target_path,
        )
        if not report["openSafety"]["ok"]:
            raise self._context._new_error(
                "FORM_FILL_OPEN_SAFETY_FAILED",
                "form-fill output failed open-safety verification: "
                + report["openSafety"]["summary"],
            )
        report["filePath"] = str(target_path)
        # These three are copied from the domain payload, so an incoherent
        # payload would print a preservation receipt onto a document that was
        # in fact rewritten. Refuse the incoherent combination instead of
        # forwarding it: "identical" and "these parts changed" cannot both hold.
        byte_identical = payload["byteIdentical"]
        changed_parts = payload["changedParts"]
        if byte_identical and changed_parts:
            raise self._context._new_error(
                "MUTATION_REPORT_INCOHERENT",
                "refusing to write a receipt claiming byteIdentical while "
                f"naming changed parts {list(changed_parts)!r}",
            )
        report["byteIdentical"] = byte_identical
        report["changedParts"] = changed_parts
        report["skipped"] = payload["skipped"]
        payload["verificationReport"] = report
        payload["openSafety"] = report["openSafety"]

        if isinstance(self._context.storage, LocalDocumentStorage):
            precondition = (
                output_precondition
                or output_guard
                or self._context.storage.capture_output_precondition(target_path)
            )
            materialized_guard: WorkspaceOutputGuard | None = None
            try:
                materialized_guard = self._context.storage.materialize_output_guard(
                    precondition
                )
                publication = self._context.storage.atomic_publish_bytes(
                    materialized_guard,
                    candidate_bytes,
                )
                if publication_sink is not None:
                    publication_sink(publication)
                payload["_workspacePublication"] = publication
            except BaseException:
                if materialized_guard is not None:
                    self._context.storage.cleanup_owned_parent_directories(
                        materialized_guard
                    )
                raise
        else:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{target_path.stem}.",
                suffix=target_path.suffix or ".hwpx",
                dir=str(target_path.parent),
            )
            tmp_path = Path(tmp_name)
            try:
                os.close(fd)
                tmp_path.write_bytes(candidate_bytes)
                os.replace(tmp_path, target_path)
            finally:
                tmp_path.unlink(missing_ok=True)
        return payload

    def save(self, path: str) -> Dict[str, Any]:
        document, resolved = self._context._open_document(path)
        verification_report = self._save_document(document, resolved)
        return {"ok": True, "verificationReport": verification_report}

    def save_as(self, path: str, out: str) -> Dict[str, Any]:
        document, resolved = self._context._open_document(path)
        out_path = self._context._resolve_output_path(out)
        verification_report = self._save_document(document, out_path)
        return {"outPath": str(out_path), "verificationReport": verification_report}

    def fill_template(
        self,
        source: str,
        output: str,
        replacements: Dict[str, str],
        *,
        preserve_style: bool = True,
        split_newlines: bool = True,
    ) -> Dict[str, Any]:
        document, _ = self._context._open_document(source)
        out_path = self._context._resolve_output_path(output)

        replaced_count = 0
        for needle, replacement in replacements.items():
            if not needle:
                continue
            content = replacement
            if not split_newlines:
                content = content.replace("\r\n", " ").replace("\n", " ")

            replaced_count += document.text.replace(needle, content)

        if not preserve_style:
            logger.debug(
                "fill_template called with preserve_style=False, but current backend always preserves run style"
            )

        verification_report = self._save_document(document, out_path)
        return {
            "outPath": str(out_path),
            "replacedCount": replaced_count,
            "verificationReport": verification_report,
        }

    def make_blank(self, out: str) -> Dict[str, Any]:
        document = new_document()
        out_path = self._context._resolve_output_path(out)
        verification_report = self._save_document(document, out_path)
        return {"outPath": str(out_path), "verificationReport": verification_report}
