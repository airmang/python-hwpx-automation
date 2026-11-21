# SPDX-License-Identifier: Apache-2.0
"""Search and context utilities for hardened tools."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable, List, Sequence


@dataclass(frozen=True)
class SearchHit:
    node_id: str
    paragraph_index: int
    start: int
    end: int
    match: str
    context: str


def _iter_substring_matches(text: str, pattern: str) -> Iterable[tuple[int, int, str]]:
    start = 0
    length = len(pattern)
    if length == 0:
        return
    while True:
        index = text.find(pattern, start)
        if index == -1:
            break
        yield index, index + length, pattern
        start = index + length


def search_paragraphs(
    paragraphs: Sequence[str],
    *,
    pattern: str,
    limit: int,
    use_regex: bool,
    node_resolver: Callable[[int], str],
    context_radius: int = 20,
) -> List[SearchHit]:
    hits: List[SearchHit] = []
    if not pattern:
        return hits

    matcher = None
    if use_regex:
        matcher = re.compile(pattern)

    for index, paragraph in enumerate(paragraphs):
        matches: Iterable[tuple[int, int, str]]
        if matcher is not None:
            matches = ((m.start(), m.end(), m.group(0)) for m in matcher.finditer(paragraph))
        else:
            matches = _iter_substring_matches(paragraph, pattern)
        for start, end, match_text in matches:
            context = paragraph[max(0, start - context_radius) : min(len(paragraph), end + context_radius)]
            hits.append(
                SearchHit(
                    node_id=node_resolver(index),
                    paragraph_index=index,
                    start=start,
                    end=end,
                    match=match_text,
                    context=context,
                )
            )
            if len(hits) >= limit:
                return hits
    return hits


def window_for_paragraph(
    paragraphs: Sequence[str],
    index: int,
    *,
    radius: int,
) -> dict:
    radius = max(1, min(radius, 3))
    focus = paragraphs[index] if 0 <= index < len(paragraphs) else ""
    before = list(paragraphs[max(0, index - radius) : index])
    after = list(paragraphs[index + 1 : index + 1 + radius])
    return {
        "before": before,
        "focus": focus,
        "after": after,
    }


@dataclass(frozen=True)
class SessionLifecyclePolicy:
    """문서 handle 레지스트리 수명 정책."""

    registry_scope: str = "process"
    request_scope: str = "request"
    eviction: tuple[str, ...] = (
        "close_document_handle 호출 시",
        "프로세스 종료 시",
    )

    def as_dict(self) -> dict:
        return {
            "registryScope": self.registry_scope,
            "requestScope": self.request_scope,
            "eviction": list(self.eviction),
        }


def default_session_lifecycle_policy() -> SessionLifecyclePolicy:
    return SessionLifecyclePolicy()
