# SPDX-License-Identifier: Apache-2.0
"""Compact document operations for small (local) models.

A 27B-class local model loses its way among a hundred tools, overflows its
context when it reads a document's structure, and breaks a tool call whose
argument carries a long body. These operations are shaped for it:

* reads return a short id-tagged list, never the document body;
* edits take ``{id: new text}`` and return counts and ids, never the result;
* a long body is staged in short chunks (:class:`DraftStore`) and passed on
  by its ``draft_id``, so no single tool argument is long.

Every operation takes and returns plain JSON values and resolves paths inside
the configured workspace. The document work itself is python-hwpx's
(``doc.text.outline`` / ``apply_changes`` / ``replace``,
``hwpx.tools.markdown_import``); this module only adds the workspace, the
drafts and the compact result shape.
"""

from __future__ import annotations

import inspect
import secrets
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

__all__ = [
    "DRAFTS",
    "DraftStore",
    "apply_text_changes",
    "create_from_markdown",
    "read_outline",
    "replace_text",
    "stage_text",
    "validate_document",
]

#: One staged draft may not grow past this many characters.
MAX_DRAFT_CHARS = 200_000
#: At most this many drafts are kept; the oldest is dropped first.
MAX_DRAFTS = 64
#: A draft not touched for this long is dropped.
DRAFT_TTL_SECONDS = 6 * 60 * 60
#: How many open-safety issues a result lists.
MAX_LISTED_ISSUES = 10


def _failure(code: str, message: str, **details: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "error": {"code": code, "message": message}}
    if details:
        payload["error"].update(details)
    return payload


class DraftStore:
    """Process-local text drafts addressed by an opaque id.

    A draft is built by one or more :meth:`stage` calls, each appending a
    chunk, and read back whole by :meth:`text`. Drafts live in memory: they
    survive between tool calls of one server process (stdio or HTTP), not a
    restart.
    """

    def __init__(
        self,
        *,
        max_chars: int = MAX_DRAFT_CHARS,
        max_drafts: int = MAX_DRAFTS,
        ttl_seconds: float = DRAFT_TTL_SECONDS,
        clock: Any = time.monotonic,
    ) -> None:
        self._max_chars = max_chars
        self._max_drafts = max_drafts
        self._ttl = ttl_seconds
        self._clock = clock
        self._drafts: dict[str, tuple[float, list[str], int]] = {}
        self._lock = threading.Lock()

    def _expire(self, now: float) -> None:
        for key in [key for key, (seen, _parts, _size) in self._drafts.items() if now - seen > self._ttl]:
            del self._drafts[key]

    def stage(self, text: str, draft_id: str | None = None) -> dict[str, Any]:
        """Append *text* to *draft_id* (a new draft when ``None``)."""

        if not isinstance(text, str):
            return _failure("DRAFT_TEXT_INVALID", "text must be a string")
        with self._lock:
            now = self._clock()
            self._expire(now)
            if draft_id is None:
                if len(text) > self._max_chars:
                    return _failure("DRAFT_TOO_LONG", f"a draft holds at most {self._max_chars} characters")
                while len(self._drafts) >= self._max_drafts:
                    oldest = min(self._drafts, key=lambda key: self._drafts[key][0])
                    del self._drafts[oldest]
                draft_id = "d" + secrets.token_hex(6)
                self._drafts[draft_id] = (now, [text], len(text))
            else:
                entry = self._drafts.get(draft_id)
                if entry is None:
                    return _failure("DRAFT_UNKNOWN", f"no draft {draft_id!r}; stage the text again without draft_id")
                _seen, parts, size = entry
                if size + len(text) > self._max_chars:
                    return _failure("DRAFT_TOO_LONG", f"a draft holds at most {self._max_chars} characters")
                parts.append(text)
                self._drafts[draft_id] = (now, parts, size + len(text))
            _seen, parts, size = self._drafts[draft_id]
            return {"ok": True, "draftId": draft_id, "chars": size, "chunks": len(parts)}

    def text(self, draft_id: str) -> str | None:
        with self._lock:
            self._expire(self._clock())
            entry = self._drafts.get(draft_id)
            return None if entry is None else "".join(entry[1])

    def discard(self, draft_id: str) -> None:
        with self._lock:
            self._drafts.pop(draft_id, None)


#: The drafts of this server process.
DRAFTS = DraftStore()


def _missing_text_blocks(doc: Any) -> dict[str, Any] | None:
    if hasattr(doc.text, "outline") and hasattr(doc.text, "apply_changes"):
        return None
    return _failure(
        "DEPENDENCY_MISSING",
        "this python-hwpx has no doc.text.outline/apply_changes; upgrade python-hwpx",
    )


def _resolve(path: str) -> Path:
    from ...utils.helpers import resolve_path

    return Path(resolve_path(path))


def _open(path: Path) -> Any:
    from ...core.document import open_doc

    return open_doc(str(path))


def _save(doc: Any, path: Path) -> bool:
    """Save through the workspace storage; ``True`` when the output is open-safe."""

    from ...core.document import save_doc

    verification = save_doc(doc, str(path))
    open_safety = verification.get("openSafety") if isinstance(verification, Mapping) else None
    if isinstance(open_safety, Mapping) and "ok" in open_safety:
        return bool(open_safety["ok"])
    return bool(verification.get("ok", True)) if isinstance(verification, Mapping) else True


def _default_output(source: Path) -> Path:
    """``name.hwpx`` → ``name.edited.hwpx`` beside it: the original stays."""

    return source.with_name(f"{source.stem}.edited{source.suffix or '.hwpx'}")


def _output_for(path: Path, output: str | None) -> Path:
    return _resolve(output) if output else _default_output(path)


def read_outline(path: str, *, max_chars: int = 6000, after: str | None = None) -> dict[str, Any]:
    """The document's non-empty paragraphs as ``[id] where: text`` lines within *max_chars*."""

    source = _resolve(path)
    if not source.exists():
        return _failure("FILE_NOT_FOUND", f"no file {path!r}")
    doc = _open(source)
    try:
        missing = _missing_text_blocks(doc)
        if missing is not None:
            return missing
        page = doc.text.outline(max_chars=max_chars, after=after)
    except KeyError:
        return _failure("OUTLINE_CURSOR_UNKNOWN", f"no paragraph id {after!r}; read again without after")
    finally:
        doc.close()
    return {
        "ok": True,
        "outline": page.to_text(),
        "complete": page.complete,
        "nextAfter": page.next_after,
        "listed": len(page),
        "total": page.total,
    }


def apply_text_changes(path: str, changes: Mapping[str, str], *, output: str | None = None) -> dict[str, Any]:
    """Replace each ``{id: text}`` and save to *output* (default ``<name>.edited.hwpx``)."""

    if not isinstance(changes, Mapping) or not all(isinstance(key, str) for key in changes):
        return _failure("CHANGES_INVALID", "changes must be an object of {id: new text}")
    source = _resolve(path)
    if not source.exists():
        return _failure("FILE_NOT_FOUND", f"no file {path!r}")
    doc = _open(source)
    try:
        missing = _missing_text_blocks(doc)
        if missing is not None:
            return missing
        report = doc.text.apply_changes({key: "" if value is None else str(value) for key, value in changes.items()})
        target = _output_for(source, output)
        open_safe = _save(doc, target) if report.changed else None
    finally:
        doc.close()
    return {
        "ok": not report.unknown_ids and open_safe is not False,
        "output": str(target) if report.changed else None,
        "changed": len(report.changed),
        "unchanged": len(report.unchanged),
        "unknownIds": list(report.unknown_ids),
        "overflow": [
            {"id": entry["id"], "where": entry["where"], "lines": entry["lines"], "lineBudget": entry["lineBudget"]}
            for entry in report.overflow
        ],
        "openSafe": open_safe,
    }


def replace_text(path: str, old: str, new: str, *, output: str | None = None) -> dict[str, Any]:
    """Replace every *old* with *new* — body, table cells, headers and footers — and save."""

    if not old:
        return _failure("TEXT_EMPTY", "old must not be empty")
    source = _resolve(path)
    if not source.exists():
        return _failure("FILE_NOT_FOUND", f"no file {path!r}")
    doc = _open(source)
    try:
        count = doc.text.replace(old, new, everywhere=True)
        target = _output_for(source, output)
        open_safe = _save(doc, target) if count else None
    finally:
        doc.close()
    return {"ok": open_safe is not False, "replaced": count, "output": str(target) if count else None, "openSafe": open_safe}


def stage_text(text: str, draft_id: str | None = None) -> dict[str, Any]:
    """Stage *text* (or append it to *draft_id*) and return the draft id."""

    return DRAFTS.stage(text, draft_id)


def create_from_markdown(
    output: str,
    *,
    draft_id: str | None = None,
    markdown_path: str | None = None,
    markdown: str | None = None,
    byline: str | None = None,
) -> dict[str, Any]:
    """Make a new document from Markdown given by draft id, workspace file or short inline text.

    *byline* is the department/date line python-hwpx writes right-aligned under
    the title. A python-hwpx whose ``from_markdown`` has no ``byline`` gets
    ``DEPENDENCY_MISSING`` and no document, rather than a document without it.
    """

    sources = [value for value in (draft_id, markdown_path, markdown) if value]
    if len(sources) != 1:
        return _failure("MARKDOWN_SOURCE", "give exactly one of draft_id, markdown_path or markdown")
    if draft_id:
        text = DRAFTS.text(draft_id)
        if text is None:
            return _failure("DRAFT_UNKNOWN", f"no draft {draft_id!r}; stage the text again")
    elif markdown_path:
        source = _resolve(markdown_path)
        if not source.is_file():
            return _failure("FILE_NOT_FOUND", f"no file {markdown_path!r}")
        text = source.read_text(encoding="utf-8")
    else:
        text = str(markdown)
    try:
        from hwpx.tools.markdown_import import from_markdown
    except ImportError:
        return _failure(
            "DEPENDENCY_MISSING",
            "this python-hwpx has no Markdown import (hwpx.tools.markdown_import); upgrade python-hwpx",
        )
    extra: dict[str, Any] = {}
    if byline and byline.strip():
        if "byline" not in inspect.signature(from_markdown).parameters:
            return _failure(
                "DEPENDENCY_MISSING",
                "this python-hwpx cannot write a byline (from_markdown has no byline); upgrade python-hwpx",
            )
        extra["byline"] = byline
    target = _resolve(output)
    doc = from_markdown(text, **extra)
    try:
        open_safe = _save(doc, target)
    finally:
        doc.close()
    if draft_id and open_safe:
        DRAFTS.discard(draft_id)
    return {"ok": open_safe, "output": str(target), "chars": len(text), "openSafe": open_safe}


def validate_document(path: str) -> dict[str, Any]:
    """Whether the file passes the package checks, reopens, and is safe to open in the editor."""

    from hwpx.tools.package_validator import validate_editor_open_safety

    source = _resolve(path)
    if not source.exists():
        return _failure("FILE_NOT_FOUND", f"no file {path!r}")
    report = validate_editor_open_safety(source)
    issues = [str(issue) for issue in report.blocking_package_errors]
    if report.reopen_error:
        issues.append(f"reopen: {report.reopen_error}")
    if report.document_validation_error:
        issues.append(f"document: {report.document_validation_error}")
    document_issues = [str(issue) for issue in getattr(report.validate_document, "issues", ()) or ()]
    if getattr(report.validate_document, "ok", True) is False:
        issues.extend(document_issues)
        warnings: list[str] = []
    else:
        # Schema notes on a document that still validates do not block opening it.
        warnings = document_issues
    return {
        "ok": bool(report.ok),
        "reopens": bool(report.reopen_ok),
        "issues": issues[:MAX_LISTED_ISSUES],
        "moreIssues": max(0, len(issues) - MAX_LISTED_ISSUES),
        "warnings": len(warnings),
    }
