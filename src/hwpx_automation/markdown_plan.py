# SPDX-License-Identifier: Apache-2.0
"""Markdown-to-document-plan bridge.

The Markdown is read by the same parser :func:`hwpx_automation.markdown.from_markdown` uses
(:mod:`hwpx_automation.markdown._import`): one grammar for blocks and for inline marks, so
``**굵게**`` means the same on both ways in. The two ways differ only in what they write:
``from_markdown`` writes a document in one of its looks, this writes a ``hwpx.document_plan.v1``
the agent can read, change and hand to ``create_document_from_plan`` (which can then compose
it from a design profile). A plan paragraph's ``runs`` carry bold (and colour) only, so bold
becomes a bold run, and italic, strike, code, links, pictures and footnotes are written as
their text; each such loss is named once in ``warnings``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .markdown._import import (
    _Code,
    _Heading,
    _List,
    _Paragraph,
    _parse,
    _Quote,
    _Refs,
    _Span,
    _spans,
    _Table,
)


@dataclass(frozen=True, slots=True)
class MarkdownPlanResult:
    plan: dict[str, Any]
    warnings: list[str]


class _Converter:
    def __init__(self, refs: _Refs) -> None:
        self.refs = refs
        self.blocks: list[dict[str, Any]] = []
        self.warnings: list[str] = []
        self.title = ""

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    # inline ---------------------------------------------------------------------------------
    def pieces(self, text: str, where: str) -> list[tuple[str, bool]]:
        """*text* as ``(text, bold)`` pieces; marks a plan cannot carry are written as text."""

        pieces: list[tuple[str, bool]] = []
        for span in _spans(text, self.refs):
            piece = self.span_text(span, where)
            if not piece:
                continue
            if pieces and pieces[-1][1] == span.bold:
                pieces[-1] = (pieces[-1][0] + piece, span.bold)
            else:
                pieces.append((piece, span.bold))
        return pieces

    def span_text(self, span: _Span, where: str) -> str:
        if span.note is not None:
            definition = self.refs.notes.get(span.note, "")
            self.warn("Markdown footnotes were written in parentheses after their reference.")
            return f"({definition})" if definition else ""
        if span.image is not None:
            self.warn("Markdown pictures were written as their description; a document plan holds no pictures.")
            return span.text
        lost = [
            name
            for name, present in (
                ("italic", span.italic),
                ("strikethrough", span.strike),
                ("inline code", span.code),
            )
            if present
        ]
        if span.link is not None:
            lost.append("links")
        for name in lost:
            self.warn(f"Markdown {name}: written as plain text; document_plan runs carry bold and color only.")
        if span.bold and where != "paragraph":
            self.warn(f"Markdown bold in a {where} was kept as plain text; only paragraph runs carry bold.")
        if span.link is not None and span.text and span.link.removeprefix("mailto:") != span.text:
            return f"{span.text}({span.link.removeprefix('mailto:')})"
        return span.text

    def plain(self, text: str, where: str) -> str:
        return "".join(piece for piece, _bold in self.pieces(text, where)).strip()

    # blocks ---------------------------------------------------------------------------------
    def block(self, block: object, *, quoted: bool = False) -> None:
        if isinstance(block, _Heading):
            text = self.plain(block.text, "heading")
            if not text:
                return
            if not self.title and block.level == 1 and not self.blocks and not quoted:
                self.title = text
                return
            self.blocks.append({"type": "heading", "level": min(block.level, 3), "text": text})
            if block.level > 3:
                self.warn(f"Heading level {block.level} was clamped to document_plan level 3.")
        elif isinstance(block, _Paragraph):
            self.paragraph(block.text)
        elif isinstance(block, _List):
            items = [self.plain(item.text, "list item") for item in block.items]
            items = [item for item in items if item]
            if items:
                self.blocks.append({"type": "bullets", "items": items})
            if any(item.kind == "number" for item in block.items):
                self.warn("Ordered Markdown lists were converted to bullet blocks.")
            if any(item.level > 1 for item in block.items):
                self.warn("Nested Markdown list items were written at one level.")
        elif isinstance(block, _Table):
            self.table(block)
        elif isinstance(block, _Code):
            if block.text.strip():
                self.blocks.append({"type": "paragraph", "text": block.text})
            self.warn("Markdown code blocks were written as plain paragraphs.")
        elif isinstance(block, _Quote):
            self.warn("Markdown block quotes were written as ordinary blocks.")
            for inner in block.blocks:
                self.block(inner, quoted=True)

    def paragraph(self, text: str) -> None:
        pieces = self.pieces(text, "paragraph")
        plain = "".join(piece for piece, _bold in pieces).strip()
        if not plain:
            return
        if any(bold for _piece, bold in pieces):
            runs = [{"text": piece, "bold": True} if bold else {"text": piece} for piece, bold in pieces]
            self.blocks.append({"type": "paragraph", "text": plain, "runs": runs})
        else:
            self.blocks.append({"type": "paragraph", "text": plain})

    def table(self, block: _Table) -> None:
        if not block.rows:
            return
        width = max(len(row) for row in block.rows)
        keys = [f"col{index + 1}" for index in range(width)]
        header = block.rows[0] if block.header else []
        body = block.rows[1:] if block.header else block.rows
        cell = lambda value: self.plain(value.replace("<br>", "\n"), "table cell")  # noqa: E731
        columns = [
            {"key": key, "label": (cell(header[index]) if index < len(header) else "") or key}
            for index, key in enumerate(keys)
        ]
        rows = [
            {key: cell(row[index]) if index < len(row) else "" for index, key in enumerate(keys)}
            for row in body
        ]
        table: dict[str, Any] = {"type": "table", "columns": columns, "rows": rows}
        if not block.header:
            table["showHeader"] = False
        if not rows:  # a header row alone: write it as the only row
            table = {
                "type": "table",
                "columns": [{"key": column["key"], "label": column["key"]} for column in columns],
                "rows": [{column["key"]: column["label"] for column in columns}],
                "showHeader": False,
            }
        self.blocks.append(table)


def markdown_to_document_plan(
    markdown: str,
    *,
    title: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    style_preset: str = "standard_korean_business",
) -> MarkdownPlanResult:
    """Convert Markdown into ``hwpx.document_plan.v1`` with the ``from_markdown`` parser."""

    parsed, refs = _parse(markdown or "")
    converter = _Converter(refs)
    converter.title = (title or "").strip()
    for block in parsed:
        converter.block(block)
    blocks = converter.blocks
    warnings = converter.warnings
    resolved_title = converter.title

    if not resolved_title:
        resolved_title = _title_from_blocks(blocks) or "Markdown Import"

    if not blocks:
        blocks.append({"type": "paragraph", "text": "작성 필요"})
        warnings.append("Markdown had no content blocks; inserted an empty paragraph placeholder.")

    quality_gates = {
        "validatePackage": True,
        "validateDocument": True,
        "reopen": True,
        "minNonEmptyParagraphs": max(1, _non_empty_block_count(blocks)),
        "visualReviewRequired": True,
    }
    return MarkdownPlanResult(
        plan={
            "schemaVersion": "hwpx.document_plan.v1",
            "title": resolved_title,
            "metadata": _string_metadata(metadata or {}),
            "stylePreset": style_preset,
            "blocks": blocks,
            "qualityGates": quality_gates,
        },
        warnings=warnings,
    )


def _title_from_blocks(blocks: list[dict[str, Any]]) -> str:
    for block in blocks:
        text = str(block.get("text") or "").strip()
        if block.get("type") == "heading" and text:
            return text
    for block in blocks:
        text = str(block.get("text") or "").strip()
        if text:
            return text[:80]
    return ""


def _string_metadata(metadata: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(key): str(value)
        for key, value in metadata.items()
        if value is not None and str(value).strip()
    }


def _non_empty_block_count(blocks: list[dict[str, Any]]) -> int:
    count = 0
    for block in blocks:
        kind = block.get("type")
        if kind in {"heading", "paragraph"} and str(block.get("text") or "").strip():
            count += 1
        elif kind == "bullets":
            count += len(block.get("items") or [])
    return count
