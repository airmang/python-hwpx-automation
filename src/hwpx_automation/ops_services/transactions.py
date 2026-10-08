# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, cast

from ..core.content import (
    add_heading_to_doc,
    add_page_break_to_doc,
    add_paragraph_to_doc,
    add_table_to_doc,
    delete_paragraph_from_doc,
    insert_paragraph_to_doc,
    set_cell_text,
)
from ..storage import LocalDocumentStorage, build_hwpx_verification_report
from ..workspace import (
    WorkspaceOutputGuard,
)
from ..core.search import batch_replace_in_doc, replace_in_doc
from ..core.transactions import (
    backup_path_for,
    rotate_and_backup,
    save_dry_run,
    semantic_diff,
    undo_last_backup,
)
from ..upstream import (
    HwpxDocument,
)

from .context import DocumentContext
from .save_policy import SavePolicy
from .save_policy import _ExactBackupResult, _ExactRecoveryPublication

logger = logging.getLogger("hwpx_automation.hwpx_ops")


class TransactionService:
    def __init__(self, context: DocumentContext, save: SavePolicy) -> None:
        self._context = context
        self._save = save

    def _with_transaction_verification(
        self,
        result: Dict[str, Any],
        document: HwpxDocument,
        target: Path,
        *,
        dry_run: bool,
        quality: Any = None,
    ) -> Dict[str, Any]:
        payload = dict(result)
        payload.setdefault("dryRun", dry_run)
        if dry_run:
            payload.update(save_dry_run(document, target, quality=quality))
            return payload

        verification = self._save._save_transaction_document(
            document, target, quality=quality
        )
        payload["verificationReport"] = verification
        payload["openSafety"] = verification.get("openSafety")
        if "visualComplete" in verification:
            payload["visualComplete"] = verification["visualComplete"]
        if "backup" in verification:
            payload["backup"] = verification["backup"]
        if "semanticDiff" in verification:
            payload["semanticDiff"] = verification["semanticDiff"]
        return payload

    def _operation_value(
        self, operation: Dict[str, Any], *names: str, default: Any = None
    ) -> Any:
        for name in names:
            if name in operation:
                return operation[name]
        return default

    def _apply_transaction_operation(
        self,
        document: HwpxDocument,
        operation: Dict[str, Any],
        index: int,
    ) -> Dict[str, Any]:
        if not isinstance(operation, dict):
            raise TypeError(f"operation {index} must be an object")
        raw_type = self._operation_value(operation, "type", "op", "operation")
        if not isinstance(raw_type, str) or not raw_type.strip():
            raise ValueError(f"operation {index} must include a type")
        op_type = raw_type.strip().replace("-", "_")

        if op_type == "replace_text":
            find = self._operation_value(operation, "findText", "find_text", "find")
            replace = self._operation_value(
                operation, "replaceText", "replace_text", "replace", default=""
            )
            if find is None:
                raise ValueError("replace_text requires findText")
            count = replace_in_doc(
                document, find_text=str(find), replace_text=str(replace)
            )
            return {"type": op_type, "replaced_count": count}

        if op_type == "batch_replace":
            replacements = self._operation_value(operation, "replacements")
            if not isinstance(replacements, list):
                raise ValueError("batch_replace requires a replacements list")
            result = batch_replace_in_doc(document, replacements)
            return {"type": op_type, **result}

        if op_type == "add_heading":
            text = self._operation_value(operation, "text", default="")
            level = int(self._operation_value(operation, "level", default=1))
            paragraph_index = add_heading_to_doc(document, str(text), level)
            return {"type": op_type, "paragraph_index": paragraph_index}

        if op_type == "add_paragraph":
            text = self._operation_value(operation, "text", default="")
            style = self._operation_value(operation, "style")
            paragraph_index = add_paragraph_to_doc(document, str(text), style)
            return {"type": op_type, "paragraph_index": paragraph_index}

        if op_type == "insert_paragraph":
            paragraph_index = self._operation_value(
                operation, "paragraphIndex", "paragraph_index"
            )
            if paragraph_index is None:
                raise ValueError("insert_paragraph requires paragraphIndex")
            text = self._operation_value(operation, "text", default="")
            style = self._operation_value(operation, "style")
            inserted = insert_paragraph_to_doc(
                document, int(paragraph_index), str(text), style
            )
            return {"type": op_type, "inserted_index": inserted}

        if op_type == "delete_paragraph":
            paragraph_index = self._operation_value(
                operation, "paragraphIndex", "paragraph_index"
            )
            if paragraph_index is None:
                raise ValueError("delete_paragraph requires paragraphIndex")
            remaining = delete_paragraph_from_doc(document, int(paragraph_index))
            return {
                "type": op_type,
                "deleted_index": int(paragraph_index),
                "remaining_paragraphs": remaining,
            }

        if op_type == "add_table":
            rows = self._operation_value(operation, "rows")
            cols = self._operation_value(operation, "cols", "columns")
            if rows is None or cols is None:
                raise ValueError("add_table requires rows and cols")
            data = self._operation_value(operation, "data")
            table_index = add_table_to_doc(document, int(rows), int(cols), data)
            return {"type": op_type, "table_index": table_index}

        if op_type == "set_table_cell_text":
            table_index = self._operation_value(
                operation, "tableIndex", "table_index", default=0
            )
            row = self._operation_value(operation, "row")
            col = self._operation_value(operation, "col", "column")
            text = self._operation_value(operation, "text", default="")
            if row is None or col is None:
                raise ValueError("set_table_cell_text requires row and col")
            preserve_format = bool(
                self._operation_value(
                    operation, "preserveFormat", "preserve_format", default=True
                )
            )
            split_paragraphs = bool(
                self._operation_value(
                    operation, "splitParagraphs", "split_paragraphs", default=False
                )
            )
            set_cell_text(
                document,
                int(table_index),
                int(row),
                int(col),
                str(text),
                preserve_format=preserve_format,
                split_paragraphs=split_paragraphs,
            )
            return {
                "type": op_type,
                "table_index": int(table_index),
                "row": int(row),
                "col": int(col),
            }

        if op_type == "fill_by_path":
            mappings = self._operation_value(operation, "mappings")
            if not isinstance(mappings, dict):
                raise ValueError("fill_by_path requires mappings")
            result = document.tables.fill_by_path(mappings)
            return {"type": op_type, **result}

        if op_type == "add_page_break":
            add_page_break_to_doc(document)
            return {"type": op_type, "success": True}

        raise ValueError(f"unsupported operation type: {raw_type}")

    def apply_edits(
        self,
        path: str,
        operations: Sequence[Dict[str, Any]],
        *,
        dry_run: bool = False,
        quality: Any = None,
    ) -> Dict[str, Any]:
        document, resolved = self._context._open_document(path)
        operation_results: List[Dict[str, Any]] = []
        try:
            for index, operation in enumerate(operations):
                operation_result = self._apply_transaction_operation(document, operation, index)
                operation_result["operationIndex"] = index
                operation_results.append(operation_result)
        except Exception as exc:
            return {
                "ok": False,
                "rolledBack": True,
                "dryRun": dry_run,
                "filename": path,
                "failedOperationIndex": len(operation_results),
                "error": str(exc),
                "operationsApplied": 0,
            }

        result: Dict[str, Any] = {
            "ok": True,
            "rolledBack": False,
            "dryRun": dry_run,
            "filename": path,
            "operationsApplied": len(operation_results),
            "operationResults": operation_results,
        }
        if dry_run:
            result.update(save_dry_run(document, resolved, quality=quality))
            return result
        verification = self._save._save_transaction_document(
            document, resolved, quality=quality
        )
        result["verificationReport"] = verification
        result["openSafety"] = verification.get("openSafety")
        if "visualComplete" in verification:
            result["visualComplete"] = verification["visualComplete"]
        if "backup" in verification:
            result["backup"] = verification["backup"]
        if "semanticDiff" in verification:
            result["semanticDiff"] = verification["semanticDiff"]
        return result

    def undo_last_edit(self, path: str) -> Dict[str, Any]:
        resolved = self._context._resolve_path(path)
        if not isinstance(self._context.storage, LocalDocumentStorage):
            return undo_last_backup(resolved)

        backup_path = backup_path_for(resolved)
        target_guard = self._context.storage.capture_output_guard(resolved)
        if not target_guard.target_existed:
            raise FileNotFoundError(f"target document does not exist: {resolved}")
        backup_guard = self._save._capture_exact_sidecar_guard(backup_path)
        if not backup_guard.target_existed:
            raise FileNotFoundError(f"backup document does not exist: {backup_path}")
        target_before = self._context.storage.read_guarded_bytes(target_guard)
        backup_before = self._context.storage.read_guarded_bytes(backup_guard)
        target_report = self._save._report_for_bytes(target_before, file_path=resolved)
        backup_report = self._save._report_for_bytes(
            backup_before,
            file_path=backup_path,
        )
        if not target_report["openSafety"]["ok"]:
            raise self._context._new_error(
                "UNDO_TARGET_OPEN_SAFETY_FAILED",
                "current document failed open-safety verification",
            )
        if not backup_report["openSafety"]["ok"]:
            raise self._context._new_error(
                "UNDO_BACKUP_OPEN_SAFETY_FAILED",
                "backup document failed open-safety verification",
            )

        recoveries = self._save._preserve_exact_preimages(
            [
                (
                    resolved,
                    target_before,
                    target_guard.target_mode,
                ),
                (
                    backup_path,
                    backup_before,
                    backup_guard.target_mode,
                ),
            ],
            marker="undo-recovery",
        )
        if recoveries is None:
            raise RuntimeError("undo preimages could not be preserved")
        target_publication: WorkspaceOutputGuard | None = None
        backup_publication: WorkspaceOutputGuard | None = None
        rollback_recoveries_ready = True
        try:
            target_publication = self._context.storage.atomic_publish_bytes(
                target_guard,
                backup_before,
                mode=backup_guard.target_mode,
            )
            backup_publication = self._context.storage.atomic_publish_bytes(
                backup_guard,
                target_before,
                mode=target_guard.target_mode,
            )
            self._context.storage.read_guarded_bytes(target_publication)
            self._context.storage.read_guarded_bytes(backup_publication)
            verification = self._save._report_for_bytes(
                backup_before,
                file_path=resolved,
            )
            if not verification["openSafety"]["ok"]:
                raise RuntimeError("undo HWPX failed open-safety verification")
            diff = self._save._semantic_diff_bytes(target_before, backup_before)
            # Evidence was computed from immutable bytes; bind the success
            # response to the exact two publications immediately before return.
            self._context.storage.read_guarded_bytes(target_publication)
            self._context.storage.read_guarded_bytes(backup_publication)
            payload = {
                "restored": True,
                "filename": str(resolved),
                "backupPath": str(backup_path),
                "verificationReport": verification,
                "openSafety": verification.get("openSafety"),
                "semanticDiff": diff,
            }
            cleaned, rollback_recoveries_ready = self._save._cleanup_exact_recoveries(
                recoveries
            )
            if not cleaned:
                raise RuntimeError("undo recovery cleanup lost its exact claim")
            try:
                self._context.storage.read_guarded_bytes(target_publication)
                self._context.storage.read_guarded_bytes(backup_publication)
            except (FileNotFoundError, OSError, RuntimeError):
                rollback_recoveries_ready = self._save._republish_exact_recoveries(
                    recoveries
                )
                raise
            return payload
        except BaseException:
            if not rollback_recoveries_ready:
                raise
            if target_publication is not None and backup_publication is None:
                try:
                    self._context.storage.read_guarded_bytes(target_publication)
                    self._context.storage.atomic_publish_bytes(
                        target_publication,
                        target_before,
                        mode=target_guard.target_mode,
                    )
                except (FileNotFoundError, OSError, RuntimeError):
                    pass
                raise
            target_owned = False
            backup_owned = False
            if target_publication is not None:
                try:
                    self._context.storage.read_guarded_bytes(target_publication)
                    target_owned = True
                except (FileNotFoundError, OSError, RuntimeError):
                    pass
            if backup_publication is not None:
                try:
                    self._context.storage.read_guarded_bytes(backup_publication)
                    backup_owned = True
                except (FileNotFoundError, OSError, RuntimeError):
                    pass
            # Roll back only while both swap candidates are still ours. The
            # A/B recovery sidecars above remain available regardless of how
            # either publication changes during the following writes.
            # target_owned/backup_owned are only ever set once the matching
            # publication is non-None, so the explicit checks below never alter
            # the branch — they re-express that invariant for the type checker.
            if (
                target_owned
                and backup_owned
                and target_publication is not None
                and backup_publication is not None
            ):
                try:
                    self._context.storage.atomic_publish_bytes(
                        target_publication,
                        target_before,
                        mode=target_guard.target_mode,
                    )
                    self._context.storage.atomic_publish_bytes(
                        backup_publication,
                        backup_before,
                        mode=backup_guard.target_mode,
                    )
                except (FileNotFoundError, OSError, RuntimeError):
                    # The exact A/B recovery sidecars are intentionally retained
                    # on every failure path, including cross-step CAS loss.
                    pass
            raise

    def byte_preserving_patch(
        self,
        path: str,
        patches: Sequence[Dict[str, Any]],
        *,
        output: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            from hwpx.patch import paragraph_patch
        except Exception as exc:  # pragma: no cover - dependency compatibility
            raise self._context._new_error(
                "BYTE_PATCH_UNAVAILABLE",
                "installed python-hwpx does not provide hwpx.patch.paragraph_patch",
            ) from exc

        source_path = self._context._resolve_path(path)
        self._context._require_hwpx_package(source_path, output)
        output_precondition = None
        if isinstance(self._context.storage, LocalDocumentStorage):
            output_precondition = self._context.storage.capture_output_precondition(
                output if output else source_path
            )
            target_path = output_precondition.path
            local_guard = (
                output_precondition
                if isinstance(output_precondition, WorkspaceOutputGuard)
                else None
            )
        else:
            target_path = (
                self._context._resolve_output_path(output) if output else source_path
            )
            local_guard = None
        target_before = (
            self._context._local_storage().read_guarded_bytes(local_guard)
            if local_guard is not None and local_guard.target_existed
            else None
        )
        result = paragraph_patch(source_path, patches)
        payload = result.to_dict()
        payload["outputPath"] = str(target_path)
        verification_report = {
            "ok": bool(payload["openSafety"]["ok"]) and not payload["skipped"],
            "filePath": str(target_path),
            "openSafety": payload["openSafety"],
            "byteIdentical": payload["byteIdentical"],
            "changedParts": payload["changedParts"],
            "skipped": payload["skipped"],
        }
        if payload["skipped"]:
            payload["verificationReport"] = verification_report
            return payload

        candidate_bytes = bytes(result.data)
        verification_report = build_hwpx_verification_report(
            candidate_bytes,
            file_path=target_path,
        )
        if not verification_report["openSafety"]["ok"]:
            raise self._context._new_error(
                "BYTE_PATCH_OPEN_SAFETY_FAILED",
                "patched HWPX failed open-safety verification: "
                + verification_report["openSafety"]["summary"],
            )

        target_recoveries: tuple[_ExactRecoveryPublication, ...] = ()
        if target_before is not None:
            preserved_target = self._save._preserve_exact_preimages(
                [
                    (
                        target_path,
                        target_before,
                        (local_guard.target_mode if local_guard is not None else None),
                    )
                ],
                marker="rollback-recovery",
            )
            if preserved_target is None:
                raise RuntimeError("byte patch target preimage could not be preserved")
            target_recoveries = preserved_target
        publication: WorkspaceOutputGuard | None = None
        exact_backup: _ExactBackupResult | None = None
        materialized_guard: WorkspaceOutputGuard | None = None
        rollback_recoveries_ready = True
        try:
            if output_precondition is not None:
                local_storage = self._context._local_storage()
                local_guard = local_storage.materialize_output_guard(
                    output_precondition
                )
                materialized_guard = local_guard
                # Preserve the retained public backup contract, but bind the
                # sidecar to the exact preimage captured with the output guard.
                exact_backup = self._save._rotate_and_backup_exact(
                    target_path,
                    target_guard=local_guard,
                    target_bytes=target_before,
                )
                backup = exact_backup.report
                publication = local_storage.atomic_publish_bytes(
                    local_guard,
                    candidate_bytes,
                )
            else:
                backup = rotate_and_backup(target_path)
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
            verification_report["backup"] = backup.to_dict()
            if backup.backup_path is not None:
                try:
                    verification_report["semanticDiff"] = (
                        self._save._semantic_diff_bytes(
                            target_before or b"",
                            candidate_bytes,
                        )
                        if local_guard is not None
                        else semantic_diff(backup.backup_path, target_path)
                    )
                except Exception as exc:  # pragma: no cover - diagnostic fallback
                    verification_report["semanticDiff"] = {
                        "schemaVersion": "hwpx.semantic-diff.v1",
                        "changed": True,
                        "summary": f"Semantic diff unavailable: {exc}",
                        "items": [],
                        "error": str(exc),
                    }
            if publication is not None:
                # Receipt evidence is valid only while the exact published
                # candidate and reported backup sidecars still occupy their
                # authorized names with the exact published identities.
                for mutation in cast(_ExactBackupResult, exact_backup).mutations:
                    self._save._assert_exact_sidecar_publication(mutation.publication)
                self._context._local_storage().read_guarded_bytes(publication)
            all_recoveries = target_recoveries + (
                exact_backup.recoveries if exact_backup is not None else ()
            )
            cleaned, rollback_recoveries_ready = self._save._cleanup_exact_recoveries(
                all_recoveries
            )
            if not cleaned:
                raise RuntimeError("byte patch recovery cleanup lost its exact claim")
            try:
                if publication is not None:
                    for mutation in cast(_ExactBackupResult, exact_backup).mutations:
                        self._save._assert_exact_sidecar_publication(
                            mutation.publication
                        )
                    self._context._local_storage().read_guarded_bytes(publication)
            except (FileNotFoundError, OSError, RuntimeError):
                rollback_recoveries_ready = self._save._republish_exact_recoveries(
                    all_recoveries
                )
                raise
        except BaseException:
            target_preimage_preserved = (
                target_before is None or rollback_recoveries_ready
            )
            if target_preimage_preserved and publication is not None:
                local_storage = self._context._local_storage()
                try:
                    if local_guard is not None and local_guard.target_existed:
                        if target_before is not None:
                            restored_publication = (
                                local_storage.atomic_publish_bytes(
                                    publication,
                                    target_before,
                                    mode=local_guard.target_mode,
                                )
                            )
                            local_storage.read_guarded_bytes(
                                restored_publication
                            )
                    else:
                        local_storage.remove_guarded_output(publication)
                except (OSError, RuntimeError):
                    pass
            if exact_backup is not None and target_preimage_preserved:
                self._save._rollback_exact_backup_mutations(
                    exact_backup.mutations,
                    preimages_preserved=rollback_recoveries_ready,
                )
            if materialized_guard is not None:
                self._context._local_storage().cleanup_owned_parent_directories(
                    materialized_guard
                )
            raise
        verification_report["filePath"] = str(target_path)
        verification_report["byteIdentical"] = payload["byteIdentical"]
        verification_report["changedParts"] = payload["changedParts"]
        verification_report["skipped"] = payload["skipped"]
        payload["verificationReport"] = verification_report
        payload["openSafety"] = verification_report["openSafety"]
        return payload
