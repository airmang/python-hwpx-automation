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

The plan carries ``"look": "report"``: ``create_document_from_plan`` then writes it in the report
look ``from_markdown`` writes by default (the look the owner chose for a Markdown document), from
the plan's blocks as they are when it is called (:func:`plan_to_markdown`), so an agent's changes
to the plan count. ``"look": "plain"`` asks for the plain look; a ``metadata.document_type`` with
a design profile of its own (공문, 가정통신문) is composed from that profile instead.
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


#: The named Markdown looks a plan may ask for (``plan["look"]``); see :func:`plan_to_markdown`.
LOOKS = ("report", "plain")
DEFAULT_LOOK = "report"
_ESCAPED = set("\\`*_[]<>|~")


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
        columns: list[dict[str, Any]] = [
            {"key": key, "label": (cell(header[index]) if index < len(header) else "") or key}
            for index, key in enumerate(keys)
        ]
        for column, align in zip(columns, block.aligns):
            if align:  # ":---:" / "---:" in the separator: kept for the named look (plan_to_markdown)
                column["align"] = align
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
            "look": DEFAULT_LOOK,
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


def plan_to_markdown(plan: Mapping[str, Any]) -> str | None:
    """The Markdown ``from_markdown`` writes *plan* from, or ``None`` when the plan holds what the
    Markdown subset cannot say (a page break, a memo, a coloured run, a cell style)."""

    lines: list[str] = []
    title = str(plan.get("title") or "").strip()
    if title:
        lines += [f"# {_escape(title)}", ""]
    for block in plan.get("blocks") or []:
        if not isinstance(block, Mapping):
            return None
        written = _block_markdown(block)
        if written is None:
            return None
        lines += written
    return "\n".join(lines).rstrip() + "\n"


def _block_markdown(block: Mapping[str, Any]) -> list[str] | None:
    kind = block.get("type")
    if kind == "heading":
        level = min(max(int(block.get("level") or 1), 1), 6)
        return ["#" * level + " " + _escape(str(block.get("text") or ""), line_start=False), ""]
    if kind == "paragraph":
        runs = block.get("runs")
        if runs:
            if any(not isinstance(run, Mapping) or run.get("color") for run in runs):
                return None
            text = "".join(
                f"**{_escape(str(run.get('text') or ''), line_start=False)}**"
                if run.get("bold")
                else _escape(str(run.get("text") or ""), line_start=False)
                for run in runs
            )
            text = _escape_line_start(text)
        else:
            text = _escape(str(block.get("text") or ""))
        # A line break inside the paragraph: a trailing backslash.
        return [text.replace("\n", "\\\n"), ""] if text.strip() else []
    if kind == "bullets":
        items = block.get("items") or []
        if isinstance(items, list) and all(isinstance(item, (str, int, float)) for item in items):
            return [f"- {_escape(str(item), line_start=False)}" for item in items] + [""]
        nested = _nested_bullet_lines(items, 0) if isinstance(items, list) else None
        return None if nested is None else nested + [""]
    if kind == "table":
        columns = [column for column in block.get("columns") or [] if isinstance(column, Mapping)]
        if block.get("cellStyles") or not columns:
            return None

        def cell(value: Any) -> str:
            return _escape(str(value or ""), line_start=False).replace("\n", "<br>")

        lines: list[str] = []
        if block.get("showHeader") is not False:
            lines.append("| " + " | ".join(cell(c.get("label") or c.get("key")) for c in columns) + " |")
            marks = {"left": ":---", "center": ":---:", "right": "---:"}
            lines.append("|" + "".join(marks.get(str(c.get("align")), "---") + "|" for c in columns))
        for row in block.get("rows") or []:
            values = row if isinstance(row, Mapping) else {}
            lines.append("| " + " | ".join(cell(values.get(c.get("key"))) for c in columns) + " |")
        return lines + [""]
    return None


#: How deep a plan's bullet items may nest: the depth the plan validator allows.
_MAX_BULLET_DEPTH = 10


def _nested_bullet_lines(items: list[Any], depth: int) -> list[str] | None:
    """Bullet items that nest (``{"text": ..., "children": [...]}``) as a Markdown list inside the
    list, two spaces in a depth; ``None`` for an item the plan validator refuses (it names what is
    wrong when the plan goes the general way)."""

    if depth >= _MAX_BULLET_DEPTH and items:
        return None
    lines: list[str] = []
    for item in items:
        if isinstance(item, (str, int, float)) and not isinstance(item, bool):
            text, children = str(item).strip(), None
        elif isinstance(item, Mapping) and type(item.get("text")) in (str, int, float):
            text, children = str(item["text"]).strip(), item.get("children")
            if not text or not isinstance(children, (list, type(None))):
                return None
        else:
            return None
        if text:
            lines.append(f"{'  ' * depth}- {_escape(text, line_start=False)}")
        if children:
            below = _nested_bullet_lines(children, depth + 1)
            if below is None:
                return None
            lines += below
    return lines


def _escape(text: str, *, line_start: bool = True) -> str:
    """*text* as Markdown that reads back as the same text (*line_start*: it begins a line)."""

    escaped = "".join("\\" + char if char in _ESCAPED else char for char in text)
    return _escape_line_start(escaped) if line_start else escaped


def _escape_line_start(escaped: str) -> str:
    """A paragraph line the parser would take for a heading, list item or quote, kept a paragraph.
    (A heading's own number, "1. 개요", is left as it is: from_markdown reads it as the writer's.)"""

    if escaped[:1] in ("#", "-", "+", ">"):
        return "\\" + escaped
    digits = len(escaped) - len(escaped.lstrip("0123456789"))
    if digits and escaped[digits : digits + 2] in (". ", ") "):
        return escaped[:digits] + "\\" + escaped[digits:]
    return escaped
