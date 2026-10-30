# SPDX-License-Identifier: Apache-2.0
"""Canonical official-reference policy; core only reads generic sources."""

from __future__ import annotations

import re
from typing import Any, Sequence

from ..document_ops.sources import source_paragraphs

REFERENCE_CONSISTENCY_REPORT_VERSION = "reference-consistency-v1"

_ATTACHMENT_LINE_RE = re.compile(
    r"^\s*(?:붙임|첨부)\s*(\d+)?[.)]?\s+.+\s+\d+\s*부\.?\s*$"
)

_ATTACHMENT_REFERENCE_RE = re.compile(r"(?:붙임|첨부)\s*(\d+)\s*(?:참조|관련|확인|의)?")

_TABLE_NUMBER_RE = re.compile(r"(?:표|Table)\s*(\d+)", re.IGNORECASE)

_FIGURE_NUMBER_RE = re.compile(r"(?:그림|Figure|Fig\.)\s*(\d+)", re.IGNORECASE)


def inspect_reference_consistency(source: Any) -> dict[str, Any]:
    """Inspect attachment/table/figure semantic references in document text."""

    paragraphs = source_paragraphs(source)
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
    violations.extend(
        _numbering_violations(
            paragraphs, kind="table", pattern=_TABLE_NUMBER_RE, label="표"
        )
    )
    violations.extend(
        _numbering_violations(
            paragraphs, kind="figure", pattern=_FIGURE_NUMBER_RE, label="그림"
        )
    )
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


__all__ = ["REFERENCE_CONSISTENCY_REPORT_VERSION", "inspect_reference_consistency"]
