# SPDX-License-Identifier: Apache-2.0
"""Tracked-change automation handlers for the optional MCP adapter."""

from __future__ import annotations

import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

from .. import quality as quality_contract
from ..core.document import open_doc
from ..office.document_ops import verify_redline as verify_hwpx_redline
from ..storage import (
    build_hwpx_verification_report,
)
from ..utils.helpers import resolve_path
from ..workspace import backup_replaced_output

_REDLINE_RECEIPT_FIELDS = (
    "changeCount",
    "marksLinked",
    "displayEnabled",
    "opensClean",
    "render_checked",
)


class _RedlineVerificationError(RuntimeError):
    """Carry typed redline verification failures and their receipt."""

    def __init__(self, failures: list[dict[str, Any]], receipt: dict[str, Any]) -> None:
        self.failures = failures
        self.receipt = receipt
        messages = "; ".join(
            str(item.get("message", ""))
            for item in failures
            if item.get("message")
        )
        super().__init__(messages or "redline verification failed")


def _tracked_edit_format_error(
    filename: str,
    *,
    field: str,
    role: str,
    dry_run: bool,
) -> dict[str, Any] | None:
    suffix = Path(str(filename or "")).suffix.lower()
    if suffix == ".hwpx":
        return None
    return {
        "ok": False,
        "applied": False,
        "dryRun": dry_run,
        field: filename,
        "error": f"unsupported {role} format {suffix!r}; only .hwpx is supported",
        "handoff_status": "unsupported_format",
        "next_action": "use a .hwpx filename (ODT 기안문 등 비-HWPX 포맷은 별도 트랙)",
    }


def _tracked_paragraph_text(paragraph: Any) -> str:
    value = getattr(paragraph, "text", "")
    return value if isinstance(value, str) else str(value or "")


def _tracked_edit_error(
    index: int,
    code: str,
    message: str,
    *,
    edit: Any,
    **extra: Any,
) -> dict[str, Any]:
    payload = {
        "editIndex": index,
        "code": code,
        "message": message,
        "edit": edit,
    }
    payload.update(extra)
    return payload


def _tracked_edit_paragraph_index(edit: dict[str, Any]) -> int:
    raw = edit.get("paragraph_index", edit.get("paragraphIndex"))
    if isinstance(raw, bool):
        raise ValueError("paragraph_index must be an integer")
    return int(cast(Any, raw))


def _validate_tracked_edits(edits: Any, paragraphs: list[Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    previews: list[dict[str, Any]] = []
    paragraph_count = len(paragraphs)

    if not isinstance(edits, list):
        return {
            "ok": False,
            "errors": [
                {
                    "code": "invalid_edits",
                    "message": "edits must be a list",
                    "edit": edits,
                }
            ],
            "previews": [],
            "wouldChangeCount": 0,
        }
    if not edits:
        return {
            "ok": False,
            "errors": [
                {
                    "code": "empty_edits",
                    "message": "edits must contain at least one tracked edit",
                    "edit": edits,
                }
            ],
            "previews": [],
            "wouldChangeCount": 0,
        }

    for index, edit in enumerate(edits):
        edit_error_count = len(errors)
        if not isinstance(edit, dict):
            errors.append(
                _tracked_edit_error(
                    index,
                    "invalid_edit",
                    "each edit must be an object",
                    edit=edit,
                )
            )
            continue

        edit_type = str(edit.get("type", edit.get("op", ""))).strip().lower()
        try:
            paragraph_index = _tracked_edit_paragraph_index(edit)
        except (TypeError, ValueError):
            errors.append(
                _tracked_edit_error(
                    index,
                    "invalid_paragraph_index",
                    "paragraph_index must be an integer",
                    edit=edit,
                )
            )
            continue

        paragraph_text = ""
        if paragraph_index < 0 or paragraph_index >= paragraph_count:
            errors.append(
                _tracked_edit_error(
                    index,
                    "paragraph_index_out_of_range",
                    f"paragraph_index {paragraph_index} is outside 0..{max(paragraph_count - 1, 0)}",
                    edit=edit,
                    paragraphIndex=paragraph_index,
                    paragraphCount=paragraph_count,
                )
            )
        else:
            paragraph_text = _tracked_paragraph_text(paragraphs[paragraph_index])

        change_count = 0
        if edit_type == "insert":
            text = edit.get("text")
            if not isinstance(text, str) or text == "":
                errors.append(
                    _tracked_edit_error(
                        index,
                        "insert_text_required",
                        "insert edits require non-empty text",
                        edit=edit,
                    )
                )
            change_count = 1
        elif edit_type == "delete":
            match = edit.get("match")
            if match is not None and (not isinstance(match, str) or match == ""):
                errors.append(
                    _tracked_edit_error(
                        index,
                        "delete_match_invalid",
                        "delete match must be a non-empty string when provided",
                        edit=edit,
                    )
                )
            elif paragraph_index >= 0 and paragraph_index < paragraph_count:
                if match is None and not paragraph_text:
                    errors.append(
                        _tracked_edit_error(
                            index,
                            "delete_target_empty",
                            "delete edits without match require a paragraph with text",
                            edit=edit,
                            paragraphIndex=paragraph_index,
                        )
                    )
                elif match is not None and match not in paragraph_text:
                    errors.append(
                        _tracked_edit_error(
                            index,
                            "delete_match_not_found",
                            "delete match text was not found in the paragraph; no output was written",
                            edit=edit,
                            paragraphIndex=paragraph_index,
                            match=match,
                            warning=True,
                        )
                    )
            change_count = 1
        elif edit_type == "replace":
            old = edit.get("old")
            new = edit.get("new")
            if not isinstance(old, str) or old == "":
                errors.append(
                    _tracked_edit_error(
                        index,
                        "replace_old_required",
                        "replace edits require non-empty old text",
                        edit=edit,
                    )
                )
            elif (
                paragraph_index >= 0
                and paragraph_index < paragraph_count
                and old not in paragraph_text
            ):
                errors.append(
                    _tracked_edit_error(
                        index,
                        "replace_old_not_found",
                        "replace old text was not found in the paragraph; no output was written",
                        edit=edit,
                        paragraphIndex=paragraph_index,
                        old=old,
                    )
                )
            if not isinstance(new, str) or new == "":
                errors.append(
                    _tracked_edit_error(
                        index,
                        "replace_new_required",
                        "replace edits require non-empty new text",
                        edit=edit,
                    )
                )
            change_count = 2
        else:
            errors.append(
                _tracked_edit_error(
                    index,
                    "unknown_edit_type",
                    "edit type must be one of: insert, delete, replace",
                    edit=edit,
                    type=edit_type,
                )
            )

        if len(errors) == edit_error_count:
            previews.append(
                {
                    "editIndex": index,
                    "type": edit_type,
                    "paragraphIndex": paragraph_index,
                    "targetParagraphText": paragraph_text,
                    "changeCount": change_count,
                }
            )

    return {
        "ok": not errors,
        "errors": errors,
        "previews": previews,
        "wouldChangeCount": sum(item["changeCount"] for item in previews),
    }


def _normalize_tracked_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _redline_receipt(report: dict[str, Any]) -> dict[str, Any]:
    return {key: report.get(key) for key in _REDLINE_RECEIPT_FIELDS}


def _redline_receipt_failures(
    report: dict[str, Any],
    *,
    expected_change_count: int,
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    actual_change_count = int(report.get("changeCount") or 0)
    if actual_change_count < expected_change_count:
        failures.append(
            {
                "code": "redline_change_count_mismatch",
                "message": (
                    f"verify_redline reported {actual_change_count} changes; "
                    f"expected at least {expected_change_count}"
                ),
                "expectedChangeCount": expected_change_count,
                "actualChangeCount": actual_change_count,
            }
        )
    if report.get("marksLinked") is not True:
        failures.append(
            {
                "code": "redline_marks_unlinked",
                "message": "verify_redline reported unlinked body/header track-change marks",
            }
        )
    if report.get("displayEnabled") is not True:
        failures.append(
            {
                "code": "redline_display_disabled",
                "message": "verify_redline reported track-change display is not enabled",
            }
        )
    if report.get("opensClean") is False:
        failures.append(
            {
                "code": "redline_does_not_open_clean",
                "message": "verify_redline reported the destination does not open cleanly",
            }
        )
    return failures


def _save_verified_redline_document(
    doc: Any,
    *,
    source_path: str,
    destination_path: str,
    expected_change_count: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if verify_hwpx_redline is None:
        raise RuntimeError(
            "installed python-hwpx does not provide hwpx.tools.redline.verify_redline"
        )

    destination = Path(destination_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{destination.stem}.",
        suffix=".hwpx",
        dir=str(destination.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        os.close(fd)
        save_report = quality_contract.save_through_pipeline(doc, tmp_path)
        verification = build_hwpx_verification_report(tmp_path)
        if not verification["openSafety"]["ok"]:
            raise RuntimeError(
                "tracked-edit HWPX failed open-safety verification: "
                + verification["openSafety"]["summary"]
            )
        redline_report = verify_hwpx_redline(source_path, tmp_path)
        failures = _redline_receipt_failures(
            redline_report,
            expected_change_count=expected_change_count,
        )
        if failures:
            raise _RedlineVerificationError(failures, redline_report)
        # A document already at the destination stays as .bak: a wrong name does not erase it.
        backup = backup_replaced_output(destination)
        os.replace(tmp_path, destination)
        verification["backup"] = backup.to_dict()
        verification["filePath"] = str(destination)
        verification["visualComplete"] = quality_contract.visual_complete_block(
            save_report
        )
        return verification, redline_report
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def add_tracked_edit(
    source_filename: str,
    destination_filename: str,
    edits: list[dict[str, Any]],
    author: str = "AI Agent",
    date: Any = None,
    dry_run: bool = False,
) -> dict:
    """원본 HWPX를 보존하고 destination에 추적 삽입/삭제/치환(redline)을 작성합니다."""
    source_path = resolve_path(source_filename)
    guard = _tracked_edit_format_error(
        source_filename,
        field="source_filename",
        role="source",
        dry_run=dry_run,
    )
    if guard is not None:
        return guard

    destination_path = resolve_path(destination_filename)
    guard = _tracked_edit_format_error(
        destination_filename,
        field="destination_filename",
        role="output",
        dry_run=dry_run,
    )
    if guard is not None:
        return guard

    if Path(source_path).resolve(strict=False) == Path(destination_path).resolve(
        strict=False
    ):
        return {
            "ok": False,
            "applied": False,
            "dryRun": dry_run,
            "error": "add_tracked_edit refuses source-in-place edits; destination_filename must differ from source",
            "reason": "source equals destination",
            "source": {"filename": source_filename, "path": source_path},
            "destination": {"filename": destination_filename, "path": destination_path},
            "errors": [
                {
                    "code": "source_destination_same",
                    "message": "destination_filename must differ from source_filename",
                }
            ],
        }

    validation_doc = open_doc(source_path)
    try:
        validation = _validate_tracked_edits(
            edits, list(getattr(validation_doc, "paragraphs", []))
        )
    finally:
        validation_doc.close()

    if not validation["ok"]:
        return {
            "ok": False,
            "applied": False,
            "dryRun": dry_run,
            "error": "tracked edit validation failed",
            "handoff_status": "blocked",
            "source": {"filename": source_filename, "path": source_path},
            "destination": {"filename": destination_filename, "path": destination_path},
            "errors": validation["errors"],
            "editPreviews": validation["previews"],
            "written": False,
        }

    if dry_run:
        return {
            "ok": True,
            "applied": False,
            "dryRun": True,
            "handoff_status": "dry_run",
            "source": {"filename": source_filename, "path": source_path},
            "destination": {
                "filename": destination_filename,
                "path": destination_path,
                "exists": Path(destination_path).exists(),
            },
            "editsValidated": len(validation["previews"]),
            "wouldChangeCount": validation["wouldChangeCount"],
            "wouldWrite": True,
            "written": False,
            "editPreviews": validation["previews"],
        }

    normalized_date = _normalize_tracked_date(date)
    doc = open_doc(source_path)
    edit_results: list[dict[str, Any]] = []
    try:
        for index, edit in enumerate(edits):
            edit_type = str(edit.get("type", edit.get("op", ""))).strip().lower()
            paragraph_index = _tracked_edit_paragraph_index(edit)
            paragraph = doc.paragraphs[paragraph_index]
            before_text = _tracked_paragraph_text(paragraph)
            if edit_type == "insert":
                # tracking.insert/delete/replace now return TrackedChange /
                # TrackedReplacement objects rather than bare int/tuple
                # (design §2.6) — .change_id (and .delete/.insert for the
                # replace case, in the same delete-then-insert order 5.x
                # returned) keeps this handler's own int-list response shape
                # unchanged.
                change = doc.tracking.insert(
                    paragraph,
                    edit["text"],
                    author=author,
                    date=normalized_date,
                )
                change_ids = [change.change_id]
            elif edit_type == "delete":
                change = doc.tracking.delete(
                    paragraph,
                    match=edit.get("match"),
                    author=author,
                    date=normalized_date,
                )
                change_ids = [change.change_id]
            elif edit_type == "replace":
                replacement = doc.tracking.replace(
                    paragraph,
                    edit["old"],
                    edit["new"],
                    author=author,
                    date=normalized_date,
                )
                change_ids = [replacement.delete.change_id, replacement.insert.change_id]
            else:  # pragma: no cover - validation prevents this branch
                raise ValueError(f"unsupported tracked edit type: {edit_type}")
            edit_results.append(
                {
                    "editIndex": index,
                    "type": edit_type,
                    "paragraphIndex": paragraph_index,
                    "beforeText": before_text,
                    "changeIds": change_ids,
                    "changeCount": len(change_ids),
                }
            )
    except Exception as exc:
        return {
            "ok": False,
            "applied": False,
            "dryRun": False,
            "error": "tracked edit application failed before save",
            "handoff_status": "blocked",
            "source": {"filename": source_filename, "path": source_path},
            "destination": {"filename": destination_filename, "path": destination_path},
            "errors": [
                {
                    "code": "tracked_edit_apply_failed",
                    "message": str(exc),
                    "failedOperationIndex": len(edit_results),
                }
            ],
            "editResults": edit_results,
            "written": False,
        }

    expected_change_count = sum(item["changeCount"] for item in edit_results)
    try:
        verification, redline_report = _save_verified_redline_document(
            doc,
            source_path=source_path,
            destination_path=destination_path,
            expected_change_count=expected_change_count,
        )
    except _RedlineVerificationError as exc:
        return {
            "ok": False,
            "applied": False,
            "dryRun": False,
            "error": "redline verification failed; destination was not written",
            "handoff_status": "blocked",
            "source": {"filename": source_filename, "path": source_path},
            "destination": {"filename": destination_filename, "path": destination_path},
            "errors": exc.failures,
            "editResults": edit_results,
            "redlineReceipt": _redline_receipt(exc.receipt),
            "redlineVerification": exc.receipt,
            "written": False,
        }
    finally:
        doc.close()

    return {
        "ok": True,
        "applied": True,
        "dryRun": False,
        "handoff_status": "ready",
        "source": {"filename": source_filename, "path": source_path},
        "destination": {"filename": destination_filename, "path": destination_path},
        "author": author,
        "date": normalized_date,
        "editsApplied": len(edit_results),
        "changeCount": expected_change_count,
        "editResults": edit_results,
        "redlineReceipt": _redline_receipt(redline_report),
        "redlineVerification": redline_report,
        "verification": verification,
        "openSafety": verification.get("openSafety"),
        "visualComplete": verification.get("visualComplete"),
        "backup": verification.get("backup"),
        "written": True,
    }


__all__ = ["add_tracked_edit"]
