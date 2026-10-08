# SPDX-License-Identifier: Apache-2.0
"""Transactional edit helpers for stateless HWPX tools."""

from __future__ import annotations

import difflib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .. import quality as quality_contract
from ..storage import (
    build_hwpx_verification_report,
    require_hwpx_editor_open_safe,
    require_native_hwp5,
)
from ..upstream import HwpxDocument, hwp5_document_bytes, is_hwp5_target, open_document

_MAX_SUMMARY_ITEMS = 20
_MAX_SNIPPET = 80
HwpxSnapshotSource = str | Path | bytes


@dataclass(frozen=True)
class BackupReport:
    backup_path: Path | None
    rotated_paths: tuple[Path, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "created": self.backup_path is not None,
            "path": str(self.backup_path) if self.backup_path else None,
            "rotatedPaths": [str(path) for path in self.rotated_paths],
        }


def backup_path_for(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".bak")


def rotated_backup_path(path: Path, index: int) -> Path:
    if index < 1:
        raise ValueError("backup rotation index must be >= 1")
    return path.with_suffix(path.suffix + f".bak.{index}")


def rotate_and_backup(path: Path, *, max_backups: int = 5) -> BackupReport:
    """Rotate existing ``.bak`` files and copy *path* to the current backup."""

    if not path.exists():
        return BackupReport(None)

    if path.suffix.lower() == ".hwpx":
        require_hwpx_editor_open_safe(path, role="transaction backup source")

    backup = backup_path_for(path)
    rotated: list[Path] = []
    if max_backups > 0:
        oldest = rotated_backup_path(path, max_backups)
        if oldest.exists():
            oldest.unlink()
        for index in range(max_backups - 1, 0, -1):
            src = rotated_backup_path(path, index)
            if src.exists():
                dst = rotated_backup_path(path, index + 1)
                os.replace(src, dst)
                rotated.append(dst)
        if backup.exists():
            dst = rotated_backup_path(path, 1)
            os.replace(backup, dst)
            rotated.append(dst)

    shutil.copy2(path, backup)
    return BackupReport(backup, tuple(rotated))


def _snippet(text: str) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= _MAX_SNIPPET:
        return compact
    return compact[: _MAX_SNIPPET - 1] + "..."


def _iter_tables(document: HwpxDocument) -> Iterable[Any]:
    for paragraph in document.paragraphs:
        for table in getattr(paragraph, "tables", []) or []:
            yield table
            yield from _iter_nested_tables(table)


def _iter_nested_tables(table: Any) -> Iterable[Any]:
    for row in getattr(table, "rows", []) or []:
        for cell in getattr(row, "cells", []) or []:
            for paragraph in getattr(cell, "paragraphs", []) or []:
                for nested in getattr(paragraph, "tables", []) or []:
                    yield nested
                    yield from _iter_nested_tables(nested)


def _paragraph_signature(paragraph: Any) -> dict[str, Any]:
    element = getattr(paragraph, "element", None)
    attrs = dict(getattr(element, "attrib", {}) or {}) if element is not None else {}
    runs: list[dict[str, Any]] = []
    for run in getattr(paragraph, "runs", []) or []:
        run_element = getattr(run, "element", None)
        runs.append(
            {
                "text": getattr(run, "text", "") or "",
                "attrs": dict(getattr(run_element, "attrib", {}) or {})
                if run_element is not None
                else {},
            }
        )
    return {"attrs": attrs, "runs": runs}


def _source_bytes(source: HwpxSnapshotSource) -> bytes:
    return source if isinstance(source, bytes) else Path(source).read_bytes()


def snapshot_document(source: HwpxSnapshotSource) -> dict[str, Any]:
    source_bytes = _source_bytes(source)
    display_path = "<memory>" if isinstance(source, bytes) else str(Path(source))
    document = open_document(source_bytes)
    try:
        paragraphs = [
            {
                "index": index,
                "text": paragraph.text or "",
                "signature": _paragraph_signature(paragraph),
            }
            for index, paragraph in enumerate(document.paragraphs)
        ]
        tables: list[dict[str, Any]] = []
        for table_index, table in enumerate(_iter_tables(document)):
            data = [
                [cell.text or "" for cell in getattr(row, "cells", []) or []]
                for row in getattr(table, "rows", []) or []
            ]
            rows = len(data)
            cols = max((len(row) for row in data), default=0)
            tables.append(
                {
                    "index": table_index,
                    "rows": rows,
                    "cols": cols,
                    "data": data,
                }
            )
        return {
            "path": display_path,
            "paragraphs": paragraphs,
            "tables": tables,
            "paragraphCount": len(paragraphs),
            "tableCount": len(tables),
        }
    finally:
        close = getattr(document, "close", None)
        if callable(close):
            close()


def _paragraph_diff_items(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    before_text = [entry["text"] for entry in before]
    after_text = [entry["text"] for entry in after]
    matcher = difflib.SequenceMatcher(a=before_text, b=after_text, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if len(items) >= _MAX_SUMMARY_ITEMS:
            break
        if tag == "equal":
            for offset, before_index in enumerate(range(i1, i2)):
                if len(items) >= _MAX_SUMMARY_ITEMS:
                    break
                after_index = j1 + offset
                if before[before_index]["signature"] != after[after_index]["signature"]:
                    index = after[after_index]["index"]
                    items.append(
                        {
                            "type": "paragraph_format_changed",
                            "paragraphIndex": index,
                            "summary": f"Paragraph {index} formatting changed",
                        }
                    )
            continue
        if tag == "replace" and (i2 - i1) == (j2 - j1):
            for before_index, after_index in zip(range(i1, i2), range(j1, j2)):
                if len(items) >= _MAX_SUMMARY_ITEMS:
                    break
                index = after[after_index]["index"]
                items.append(
                    {
                        "type": "paragraph_changed",
                        "paragraphIndex": index,
                        "before": before[before_index]["text"],
                        "after": after[after_index]["text"],
                        "summary": (
                            f"Paragraph {index} text changed: "
                            f"'{_snippet(before[before_index]['text'])}' -> "
                            f"'{_snippet(after[after_index]['text'])}'"
                        ),
                    }
                )
            continue
        for before_index in range(i1, i2):
            if len(items) >= _MAX_SUMMARY_ITEMS:
                break
            index = before[before_index]["index"]
            items.append(
                {
                    "type": "paragraph_removed",
                    "paragraphIndex": index,
                    "before": before[before_index]["text"],
                    "summary": f"Paragraph {index} removed: '{_snippet(before[before_index]['text'])}'",
                }
            )
        for after_index in range(j1, j2):
            if len(items) >= _MAX_SUMMARY_ITEMS:
                break
            index = after[after_index]["index"]
            items.append(
                {
                    "type": "paragraph_added",
                    "paragraphIndex": index,
                    "after": after[after_index]["text"],
                    "summary": f"Paragraph {index} added: '{_snippet(after[after_index]['text'])}'",
                }
            )
    return items


def _table_diff_items(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for table_index in range(min(len(before), len(after))):
        if len(items) >= _MAX_SUMMARY_ITEMS:
            break
        before_table = before[table_index]
        after_table = after[table_index]
        if before_table["rows"] != after_table["rows"] or before_table["cols"] != after_table["cols"]:
            items.append(
                {
                    "type": "table_shape_changed",
                    "tableIndex": table_index,
                    "summary": (
                        f"Table {table_index} shape changed: "
                        f"{before_table['rows']}x{before_table['cols']} -> "
                        f"{after_table['rows']}x{after_table['cols']}"
                    ),
                }
            )
        max_rows = max(before_table["rows"], after_table["rows"])
        for row in range(max_rows):
            if len(items) >= _MAX_SUMMARY_ITEMS:
                break
            before_row = before_table["data"][row] if row < before_table["rows"] else []
            after_row = after_table["data"][row] if row < after_table["rows"] else []
            max_cols = max(len(before_row), len(after_row))
            for col in range(max_cols):
                if len(items) >= _MAX_SUMMARY_ITEMS:
                    break
                before_text = before_row[col] if col < len(before_row) else ""
                after_text = after_row[col] if col < len(after_row) else ""
                if before_text != after_text:
                    items.append(
                        {
                            "type": "table_cell_changed",
                            "tableIndex": table_index,
                            "row": row,
                            "col": col,
                            "before": before_text,
                            "after": after_text,
                            "summary": (
                                f"Table {table_index} cell ({row}, {col}) changed: "
                                f"'{_snippet(before_text)}' -> '{_snippet(after_text)}'"
                            ),
                        }
                    )
    for table_index in range(len(before), len(after)):
        if len(items) >= _MAX_SUMMARY_ITEMS:
            break
        table = after[table_index]
        items.append(
            {
                "type": "table_added",
                "tableIndex": table_index,
                "summary": f"Table {table_index} added: {table['rows']}x{table['cols']}",
            }
        )
    for table_index in range(len(after), len(before)):
        if len(items) >= _MAX_SUMMARY_ITEMS:
            break
        table = before[table_index]
        items.append(
            {
                "type": "table_removed",
                "tableIndex": table_index,
                "summary": f"Table {table_index} removed: {table['rows']}x{table['cols']}",
            }
        )
    return items


def semantic_diff(
    before_source: HwpxSnapshotSource,
    after_source: HwpxSnapshotSource,
) -> dict[str, Any]:
    before_bytes = _source_bytes(before_source)
    after_bytes = _source_bytes(after_source)
    before = snapshot_document(before_bytes)
    after = snapshot_document(after_bytes)
    items = _paragraph_diff_items(before["paragraphs"], after["paragraphs"])
    remaining = max(0, _MAX_SUMMARY_ITEMS - len(items))
    if remaining:
        items.extend(_table_diff_items(before["tables"], after["tables"])[:remaining])

    changed = before_bytes != after_bytes
    if changed and not items:
        items.append(
            {
                "type": "package_changed",
                "summary": "Package XML changed without paragraph/table text changes",
            }
        )

    summaries = [item["summary"] for item in items]
    return {
        "schemaVersion": "hwpx.semantic-diff.v1",
        "changed": changed,
        "summary": "; ".join(summaries) if summaries else "No semantic changes",
        "items": items,
        "truncated": len(items) >= _MAX_SUMMARY_ITEMS,
        "counts": {
            "paragraphsBefore": before["paragraphCount"],
            "paragraphsAfter": after["paragraphCount"],
            "tablesBefore": before["tableCount"],
            "tablesAfter": after["tableCount"],
        },
    }


def save_dry_run(
    document: HwpxDocument, target: str | Path, *, quality: Any = None
) -> dict[str, Any]:
    target_path = Path(target)
    hwp_target = is_hwp5_target(target_path)
    if hwp_target:
        require_native_hwp5()
    # The gate checks HWPX parts, so an .hwp target is staged as HWPX.
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target_path.stem}.dry-run.",
        suffix=".hwpx" if hwp_target else (target_path.suffix or ".hwpx"),
        dir=str(target_path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        os.close(fd)
        try:
            report = quality_contract.save_through_pipeline(document, tmp_path, quality=quality)
        except quality_contract.QualityGateError as gate:
            # A dry run reports the gate verdict instead of committing.
            return {
                "dryRun": True,
                "wouldSave": False,
                "visualComplete": gate.block,
                "openSafety": None,
                "semanticDiff": None,
            }
        verification = build_hwpx_verification_report(tmp_path)
        if not verification["openSafety"]["ok"]:
            raise RuntimeError(
                "dry-run HWPX failed open-safety verification: "
                + verification["openSafety"]["summary"]
            )
        if hwp_target:
            # Raises Hwp5Error (hwp5-write-unsupported) as the real save would.
            hwp5_document_bytes(document)
            verification["format"] = "hwp"
        diff = semantic_diff(target_path, tmp_path) if target_path.exists() else None
        verification["filePath"] = str(target_path)
        verification["dryRunTempDeleted"] = True
        verification["visualComplete"] = quality_contract.visual_complete_block(report)
        return {
            "dryRun": True,
            "wouldSave": True,
            "verificationReport": verification,
            "openSafety": verification.get("openSafety"),
            "semanticDiff": diff,
            "visualComplete": verification["visualComplete"],
        }
    finally:
        tmp_path.unlink(missing_ok=True)


def undo_last_backup(target: str | Path) -> dict[str, Any]:
    target_path = Path(target)
    backup_path = backup_path_for(target_path)
    if not target_path.exists():
        raise FileNotFoundError(f"target document does not exist: {target_path}")
    if not backup_path.exists():
        raise FileNotFoundError(f"backup document does not exist: {backup_path}")

    require_hwpx_editor_open_safe(backup_path, role="undo backup source")
    require_hwpx_editor_open_safe(target_path, role="undo current source")

    current_fd, current_name = tempfile.mkstemp(
        prefix=f".{target_path.stem}.current.",
        suffix=target_path.suffix or ".hwpx",
        dir=str(target_path.parent),
    )
    backup_fd, backup_name = tempfile.mkstemp(
        prefix=f".{target_path.stem}.backup.",
        suffix=target_path.suffix or ".hwpx",
        dir=str(target_path.parent),
    )
    current_tmp = Path(current_name)
    backup_tmp = Path(backup_name)
    try:
        os.close(current_fd)
        os.close(backup_fd)
        shutil.copy2(target_path, current_tmp)
        shutil.copy2(backup_path, backup_tmp)
        os.replace(backup_tmp, target_path)
        os.replace(current_tmp, backup_path)
        verification = build_hwpx_verification_report(target_path)
        if not verification["openSafety"]["ok"]:
            raise RuntimeError(
                "undo HWPX failed open-safety verification: "
                + verification["openSafety"]["summary"]
            )
        verification["filePath"] = str(target_path)
        diff = semantic_diff(backup_path, target_path)
        return {
            "restored": True,
            "filename": str(target_path),
            "backupPath": str(backup_path),
            "verificationReport": verification,
            "openSafety": verification.get("openSafety"),
            "semanticDiff": diff,
        }
    except BaseException:
        current_tmp.unlink(missing_ok=True)
        backup_tmp.unlink(missing_ok=True)
        raise
