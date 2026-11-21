"""Document revision and best-effort lock detection helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def document_revision(path: str | Path) -> str:
    """Return a stable content revision for optimistic concurrency checks."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _candidate_lock_paths(path: Path) -> list[Path]:
    name = path.name
    stem = path.stem
    parent = path.parent
    candidates = [
        parent / f"~${name}",
        parent / f".~{name}",
        parent / f".{name}.lock",
        parent / f".{name}.lck",
        parent / f"{name}.lock",
        parent / f"{name}.lck",
        parent / f"{stem}.lock",
        parent / f"{stem}.lck",
    ]
    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique.append(candidate)
    return unique


def document_lock_warnings(path: str | Path) -> list[dict[str, Any]]:
    """Return warnings for lock/temp files near *path*.

    Hancom Office lock behavior varies by host and version. This deliberately
    uses conservative adjacent-file markers so normal backups are not reported
    as active locks.
    """

    target = Path(path)
    warnings: list[dict[str, Any]] = []
    for candidate in _candidate_lock_paths(target):
        if not candidate.exists():
            continue
        warnings.append(
            {
                "code": "possible_document_lock",
                "severity": "warning",
                "message": "A lock or temporary file next to the HWPX suggests the document may be open elsewhere.",
                "path": str(candidate),
                "documentPath": str(target),
                "source": "adjacent-temp-file",
            }
        )
    return warnings


def document_state_payload(path: str | Path) -> dict[str, Any]:
    return {
        "document_revision": document_revision(path),
        "documentWarnings": document_lock_warnings(path),
    }


def revision_mismatch_response(
    path: str | Path,
    expected_revision: str | None,
) -> dict[str, Any] | None:
    if expected_revision is None:
        return None
    actual_revision = document_revision(path)
    if expected_revision == actual_revision:
        return None
    return {
        "ok": False,
        "handoff_status": "blocked",
        "reason": "document revision mismatch",
        "expected_revision": expected_revision,
        "document_revision": actual_revision,
        "documentWarnings": document_lock_warnings(path),
        "suggestion": "Re-read the document, review the external changes, then retry with the new document_revision as expected_revision.",
        "next_tool": "get_document_info",
    }
