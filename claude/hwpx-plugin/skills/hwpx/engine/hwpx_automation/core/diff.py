# SPDX-License-Identifier: Apache-2.0
"""Lightweight helpers for representing logical diffs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence


@dataclass(frozen=True)
class ParagraphMatch:
    """Capture a single pattern match inside a paragraph."""

    paragraph_index: int
    start: int
    end: int
    text: str

    def context(self, paragraph: str, radius: int = 20) -> str:
        left = max(self.start - radius, 0)
        right = min(self.end + radius, len(paragraph))
        snippet = paragraph[left:right]
        return snippet


@dataclass(frozen=True)
class ParagraphDiff:
    """A replace operation scoped to a paragraph."""

    paragraph_index: int
    start: int
    end: int
    before: str
    after: str

    def apply(self, paragraphs: Sequence[str]) -> List[str]:
        updated = list(paragraphs)
        if self.paragraph_index >= len(updated):
            raise ValueError("paragraph index out of range")
        original = updated[self.paragraph_index]
        if original[self.start : self.end] != self.before:
            raise ValueError("paragraph content changed before apply")
        updated[self.paragraph_index] = (
            original[: self.start] + self.after + original[self.end :]
        )
        return updated

    def as_preview(self) -> Dict[str, object]:
        return {
            "paragraphIndex": self.paragraph_index,
            "before": self.before,
            "after": self.after,
        }
