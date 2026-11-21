# SPDX-License-Identifier: Apache-2.0
"""Canonical, non-XPath semantic paths for the HWPX agent facade."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .model import AgentContractError, NODE_KINDS_V2

MAX_PATH_CHARS = 2048
MAX_PATH_SEGMENTS = 32
PATH_ATTRIBUTES = frozenset({"id", "name"})

_SEGMENT_RE = re.compile(
    r"^(?P<kind>[a-z][a-z-]*)\["
    r"(?:(?P<index>0*[1-9][0-9]*)|"
    r"@(?P<attribute>[a-z]+)=(?P<value>\"(?:[^\"\\]|\\.)*\"))\]$"
)
# agent-command v2: a character range of the paragraph above, ``text[<start>:<end>]``
# (offsets count as ``paragraph.text`` does; ``end`` is exclusive).
_TEXT_SEGMENT_RE = re.compile(r"^text\[(?P<start>0|[1-9][0-9]*):(?P<end>0|[1-9][0-9]*)\]$")


@dataclass(frozen=True, slots=True)
class PathSegment:
    kind: str
    index: int | None = None
    attribute: str | None = None
    value: str | None = None
    start: int | None = None
    end: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in NODE_KINDS_V2 or self.kind in {"document", "unsupported"}:
            raise AgentContractError("unknown_kind", f"unknown path kind: {self.kind}", target="path")
        if self.kind == "text":
            if (
                self.index is not None
                or self.attribute is not None
                or not isinstance(self.start, int)
                or not isinstance(self.end, int)
                or not 0 <= self.start <= self.end
            ):
                raise AgentContractError(
                    "invalid_syntax", "a text segment is text[<start>:<end>] with start <= end", target="path"
                )
            return
        if self.start is not None or self.end is not None:
            raise AgentContractError("invalid_syntax", "only a text segment takes a range", target="path")
        positional = self.index is not None
        attributed = self.attribute is not None or self.value is not None
        if positional == attributed:
            raise AgentContractError(
                "invalid_syntax", "path segment requires exactly one index or attribute", target="path"
            )
        if self.index is not None and (isinstance(self.index, bool) or self.index < 1):
            raise AgentContractError("invalid_syntax", "path indexes are one-based", target="path")
        if attributed and self.attribute not in PATH_ATTRIBUTES:
            raise AgentContractError(
                "invalid_syntax", f"unsupported path attribute: {self.attribute}", target="path"
            )
        if attributed and (not isinstance(self.value, str) or not self.value or len(self.value) > 256):
            raise AgentContractError("resource_limit", "path attribute value is invalid", target="path")

    def canonical(self) -> str:
        if self.kind == "text":
            return f"text[{self.start}:{self.end}]"
        if self.index is not None:
            return f"{self.kind}[{self.index}]"
        value = json.dumps(self.value, ensure_ascii=False, separators=(",", ":"))
        return f"{self.kind}[@{self.attribute}={value}]"


@dataclass(frozen=True, slots=True)
class SemanticPath:
    segments: tuple[PathSegment, ...] = ()

    @property
    def canonical(self) -> str:
        if not self.segments:
            return "/"
        return "/" + "/".join(segment.canonical() for segment in self.segments)

    @property
    def parent(self) -> "SemanticPath | None":
        if not self.segments:
            return None
        return SemanticPath(self.segments[:-1])

    def child(self, segment: PathSegment) -> "SemanticPath":
        if len(self.segments) >= MAX_PATH_SEGMENTS:
            raise AgentContractError("resource_limit", "path nesting exceeds limit", target="path")
        return SemanticPath((*self.segments, segment))


def parse_path(value: str) -> SemanticPath:
    """Parse and canonicalize a bounded semantic path without invoking XPath."""

    if not isinstance(value, str) or not value:
        raise AgentContractError("invalid_syntax", "path must be a non-empty string", target="path")
    if len(value) > MAX_PATH_CHARS:
        raise AgentContractError("resource_limit", "path is too long", target="path")
    if value == "/":
        return SemanticPath()
    if not value.startswith("/") or value.endswith("/"):
        raise AgentContractError("invalid_syntax", "path must be absolute and canonical", target="path")
    raw_segments: list[str] = []
    start = 1
    quoted = False
    escaped = False
    for index, char in enumerate(value[1:], start=1):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == "/":
            raw_segments.append(value[start:index])
            start = index + 1
    if quoted:
        raise AgentContractError("invalid_syntax", "unterminated path string", target="path")
    raw_segments.append(value[start:])
    if any(not segment for segment in raw_segments):
        raise AgentContractError("invalid_syntax", "path contains an empty segment", target="path")
    if len(raw_segments) > MAX_PATH_SEGMENTS:
        raise AgentContractError("resource_limit", "path nesting exceeds limit", target="path")
    segments = [_text_segment_of(raw) or _segment_of(raw) for raw in raw_segments]
    _check_text_place(segments)
    return SemanticPath(tuple(segments))


def _segment_of(raw: str) -> PathSegment:
    match = _SEGMENT_RE.fullmatch(raw)
    if match is None:
        raise AgentContractError("invalid_syntax", f"invalid path segment: {raw!r}", target="path")
    kind = match.group("kind")
    index_text = match.group("index")
    if index_text is not None:
        return PathSegment(kind=kind, index=int(index_text))
    try:
        decoded = json.loads(match.group("value"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AgentContractError("invalid_syntax", "invalid path string literal", target="path") from exc
    return PathSegment(kind=kind, attribute=match.group("attribute"), value=decoded)


def _text_segment_of(raw: str) -> PathSegment | None:
    match = _TEXT_SEGMENT_RE.fullmatch(raw)
    if match is None:
        return None
    return PathSegment(kind="text", start=int(match.group("start")), end=int(match.group("end")))


def _check_text_place(segments: list[PathSegment]) -> None:
    """A text range is the last segment, right under a paragraph."""

    kinds = [segment.kind for segment in segments]
    if "text" not in kinds:
        return
    if kinds.index("text") != len(kinds) - 1 or len(kinds) < 2 or kinds[-2] != "paragraph":
        raise AgentContractError(
            "invalid_syntax", "a text range is the last segment, under a paragraph", target="path"
        )


def text_segment(start: int, end: int) -> PathSegment:
    return PathSegment(kind="text", start=start, end=end)


def canonicalize_path(value: str) -> str:
    return parse_path(value).canonical


def indexed_segment(kind: str, index: int) -> PathSegment:
    return PathSegment(kind=kind, index=index)


def identified_segment(kind: str, value: str, *, attribute: str = "id") -> PathSegment:
    return PathSegment(kind=kind, attribute=attribute, value=value)


__all__ = [
    "MAX_PATH_CHARS",
    "MAX_PATH_SEGMENTS",
    "PATH_ATTRIBUTES",
    "PathSegment",
    "SemanticPath",
    "canonicalize_path",
    "identified_segment",
    "indexed_segment",
    "parse_path",
    "text_segment",
]
