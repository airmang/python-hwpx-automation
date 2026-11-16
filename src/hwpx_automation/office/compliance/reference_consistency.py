# SPDX-License-Identifier: Apache-2.0
"""Attachment, table and figure reference consistency lint.

Moved from the reference-consistency half of ``hwpx.tools.doc_diff``
(python-hwpx 6.x) unchanged. The paragraph diff half stays in python-hwpx for
now. Its paragraph reader (``paragraph_texts``) is not part of python-hwpx's
contract, so the reader is carried here as :func:`_paragraph_texts` (same
code, reading through :class:`hwpx.document.HwpxDocument` only).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from hwpx.document import HwpxDocument

REFERENCE_CONSISTENCY_REPORT_VERSION = "reference-consistency-v1"

_ATTACHMENT_LINE_RE = re.compile(r"^\s*(?:붙임|첨부)\s*(\d+)?[.)]?\s+.+\s+\d+\s*부\.?\s*$")
_ATTACHMENT_REFERENCE_RE = re.compile(r"(?:붙임|첨부)\s*(\d+)\s*(?:참조|관련|확인|의)?")
_TABLE_NUMBER_RE = re.compile(r"(?:표|Table)\s*(\d+)", re.IGNORECASE)
_FIGURE_NUMBER_RE = re.compile(r"(?:그림|Figure|Fig\.)\s*(\d+)", re.IGNORECASE)


def inspect_reference_consistency(source: Any) -> dict[str, Any]:
    """Inspect attachment/table/figure semantic references in document text."""

    paragraphs = _paragraphs_from_source(source)
    violations: list[dict[str, Any]] = []
    attachment_numbers = _attachment_numbers(paragraphs)
    for index, text in enumerate(paragraphs):
        for match in _ATTACHMENT_REFERENCE_RE.finditer(text):
            number = int(match.group(1))
            if number not in attachment_numbers:
                violations.append(
                    _violation(
                        "attachment-reference",
                        index,
                        text,
                        f"attachment reference {number} has no matching attachment line",
                        f'Add "붙임 {number}. ..." or update the reference.',
                    )
                )
    violations.extend(_numbering_violations(paragraphs, kind="table", pattern=_TABLE_NUMBER_RE, label="표"))
    violations.extend(_numbering_violations(paragraphs, kind="figure", pattern=_FIGURE_NUMBER_RE, label="그림"))
    return {
        "report_version": REFERENCE_CONSISTENCY_REPORT_VERSION,
        "pass": not violations,
        "summary": {
            "paragraph_count": len(paragraphs),
            "violation_count": len(violations),
            "attachment_numbers": sorted(attachment_numbers),
        },
        "violations": violations,
        "repair_hints": [
            {
                "rule": violation["rule"],
                "paragraph_index": violation["paragraph_index"],
                "suggestion": violation["suggestion"],
            }
            for violation in violations
        ],
    }


def _paragraphs_from_source(source: Any) -> list[str]:
    # Released reference APIs retain their document-plan compatibility.
    if isinstance(source, Mapping) and "sections" in source and "paragraphs" not in source and "text" not in source:
        return _paragraphs_from_document_plan(source)
    return _paragraph_texts(source)


def _paragraph_texts(source: Any) -> list[str]:
    """Read paragraph texts from a document, path, text, sequence or mapping.

    Mappings support ``paragraphs`` (first priority) or ``text``. Same code as
    python-hwpx's ``hwpx.tools.doc_diff.paragraph_texts``.
    """
    if isinstance(source, HwpxDocument):
        return [paragraph.text for paragraph in source.paragraphs if paragraph.text.strip()]
    if isinstance(source, Path):
        return _paragraphs_from_path(source)
    if isinstance(source, str):
        candidate = Path(source)
        if candidate.exists():
            return _paragraphs_from_path(candidate)
        return [line for line in source.splitlines() if line.strip()]
    if isinstance(source, Mapping):
        if "paragraphs" in source:
            return _paragraphs_from_sequence(source.get("paragraphs"))
        if "text" in source:
            return [line for line in str(source.get("text") or "").splitlines() if line.strip()]
    if isinstance(source, Sequence) and not isinstance(source, (bytes, bytearray)):
        return _paragraphs_from_sequence(source)
    raise TypeError("source must be a HWPX path, HwpxDocument, mapping, text, or paragraph sequence")


def _paragraphs_from_path(path: Path) -> list[str]:
    document = HwpxDocument.open(path)
    try:
        return [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    finally:
        document.close()


def _paragraphs_from_sequence(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError("paragraphs must be a sequence")
    paragraphs: list[str] = []
    for item in value:
        text = str(item.get("text") if isinstance(item, Mapping) else item).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def _paragraphs_from_document_plan(plan: Mapping[str, Any]) -> list[str]:
    paragraphs: list[str] = []
    for section in plan.get("sections") or ():
        if not isinstance(section, Mapping):
            continue
        for block in section.get("blocks", section.get("children")) or ():
            if not isinstance(block, Mapping):
                continue
            block_type = str(block.get("type") or "").strip()
            if block_type in {"heading", "paragraph"} and str(block.get("text") or "").strip():
                paragraphs.append(str(block.get("text") or "").strip())
            elif block_type == "table":
                for row in block.get("rows") or ():
                    if isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)):
                        text = " ".join(str(cell).strip() for cell in row if str(cell).strip())
                        if text:
                            paragraphs.append(text)
    return paragraphs


def _attachment_numbers(paragraphs: Sequence[str]) -> set[int]:
    numbers: set[int] = set()
    implicit = 1
    for text in paragraphs:
        match = _ATTACHMENT_LINE_RE.search(text)
        if not match:
            continue
        if match.group(1):
            numbers.add(int(match.group(1)))
        else:
            numbers.add(implicit)
        implicit += 1
    return numbers


def _numbering_violations(
    paragraphs: Sequence[str],
    *,
    kind: str,
    pattern: re.Pattern[str],
    label: str,
) -> list[dict[str, Any]]:
    occurrences: list[tuple[int, int, str]] = []
    for index, text in enumerate(paragraphs):
        for match in pattern.finditer(text):
            occurrences.append((int(match.group(1)), index, text))
    if not occurrences:
        return []
    numbers = {number for number, _, _ in occurrences}
    missing = [number for number in range(1, max(numbers) + 1) if number not in numbers]
    if not missing:
        return []
    first_index = occurrences[0][1]
    first_text = occurrences[0][2]
    return [
        _violation(
            f"{kind}-numbering",
            first_index,
            first_text,
            f"{label} numbering is not continuous; missing {missing}",
            f"Renumber {label} references/captions so numbers are continuous from 1.",
        )
    ]


def _violation(
    rule: str,
    paragraph_index: int,
    text: str,
    message: str,
    suggestion: str,
) -> dict[str, Any]:
    return {
        "rule": rule,
        "severity": "warning",
        "paragraph_index": paragraph_index,
        "text": text,
        "message": message,
        "suggestion": suggestion,
    }


__all__ = [
    "REFERENCE_CONSISTENCY_REPORT_VERSION",
    "inspect_reference_consistency",
]
