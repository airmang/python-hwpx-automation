# SPDX-License-Identifier: Apache-2.0
"""Read and export automation handlers for the optional MCP adapter."""

from __future__ import annotations

import base64
import binascii
import html
import os
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

from hwpx.ingest import DocumentIngestError, DocumentIngestor
from hwpx.tools import read_fidelity as _read_fidelity

from ..configuration import env_float, env_int
from ..core.content import (
    collect_full_text,
    get_paragraph_text_from_doc,
    get_table_data,
    get_table_map_in_doc,
)
from ..core.document import open_doc
from ..core.formatting import (
    outline_style_levels,
)
from ..core.search import find_in_doc
from ..network_policy import NetworkPolicy, NetworkPolicyError, open_url
from ..office.compliance import DEFAULT_POLICY, mask_pii
from ..runtime_services import RUNTIME_SERVICES
from ..upstream import (
    HP_NS,
    open_document,
)
from ..utils.helpers import default_max_chars, resolve_path, truncate_response
from ..utils.read_budget import bound_document_summary
from ._shared import _with_document_state

_OUTPUT_MODES = {"full", "chunks"}


_CHUNK_STRATEGIES = {"section", "paragraph"}


_DEFAULT_MAX_CHARS_PER_CHUNK = 8000


_DEFAULT_MAX_INPUT_BYTES = 20 * 1024 * 1024


_DEFAULT_FETCH_TIMEOUT_SECONDS = 20.0


_FIGURE_CAPTION_RE = re.compile(r"^\s*(?:Figure|Fig\.|그림)\s*\d*", re.IGNORECASE)


def _mask_pii_text(value: str, mask: bool = True) -> str:
    """Mask machine-set PII (rrn/phone/email/card) in user-facing extract output.

    On by default (safe-by-default per 개인정보 보호법); contextual types stay
    label-gated low-confidence inside ``mask_pii`` so free text isn't over-masked.
    """
    if not mask or not value:
        return value
    return mask_pii(value, DEFAULT_POLICY)


def _deep_mask_pii(obj: Any, mask: bool = True) -> Any:
    """Recursively mask PII in string VALUES of a nested JSON-able structure.

    Dict keys are left untouched; only string values are masked (``mask_pii`` only
    rewrites machine-set PII + label-gated contextual, so normal text is unchanged).
    """
    if not mask:
        return obj
    if isinstance(obj, str):
        return mask_pii(obj, DEFAULT_POLICY)
    if isinstance(obj, list):
        return [_deep_mask_pii(item, True) for item in obj]
    if isinstance(obj, dict):
        return {key: _deep_mask_pii(val, True) for key, val in obj.items()}
    return obj


def _normalize_output_mode(output: str | None) -> str:
    value = (output or "full").strip().lower()
    if value not in _OUTPUT_MODES:
        expected = ", ".join(sorted(_OUTPUT_MODES))
        raise ValueError(f"output must be one of: {expected}")
    return value


def _normalize_chunk_strategy(chunk_strategy: str | None) -> str:
    value = (chunk_strategy or "section").strip().lower()
    if value not in _CHUNK_STRATEGIES:
        expected = ", ".join(sorted(_CHUNK_STRATEGIES))
        raise ValueError(f"chunk_strategy must be one of: {expected}")
    return value


def _resolve_chunk_size(max_chars_per_chunk: int | None) -> int:
    if max_chars_per_chunk is None:
        return max(1, env_int("MAX_CHARS_PER_CHUNK", _DEFAULT_MAX_CHARS_PER_CHUNK))
    if max_chars_per_chunk <= 0:
        raise ValueError("max_chars_per_chunk must be greater than 0")
    return max_chars_per_chunk


def _normalize_heading_text(text: str) -> str:
    stripped = (text or "").strip()
    if stripped.startswith("#"):
        return stripped.lstrip("#").strip()
    return stripped


def _looks_like_figure_caption(text: str) -> bool:
    return bool(_FIGURE_CAPTION_RE.match((text or "").strip()))


def _download_hwpx_from_url(url: str, *, max_input_bytes: int) -> bytes:
    request = Request(url, headers={"User-Agent": "python-hwpx-automation/6"})
    timeout = env_float("FETCH_TIMEOUT_SECONDS", _DEFAULT_FETCH_TIMEOUT_SECONDS)
    try:
        with open_url(
            request,
            policy=NetworkPolicy.from_environment(),
            timeout=timeout,
        ) as response:
            payload = response.read(max_input_bytes + 1)
    except NetworkPolicyError:
        raise
    except HTTPError as exc:
        raise ValueError(f"failed to download url: HTTP {exc.code}") from exc
    except URLError as exc:
        raise ValueError(f"failed to download url: {exc.reason}") from exc

    if len(payload) > max_input_bytes:
        raise ValueError(f"input is too large: limit is {max_input_bytes} bytes")
    if not payload:
        raise ValueError("downloaded payload is empty")
    return payload


def _load_hwpx_payload(
    hwpx_base64: str | None, url: str | None
) -> tuple[bytes, dict[str, Any]]:
    use_base64 = bool(hwpx_base64 and hwpx_base64.strip())
    use_url = bool(url and url.strip())
    if use_base64 == use_url:
        raise ValueError("provide exactly one of hwpx_base64 or url")

    max_input_bytes = max(1, env_int("MAX_INPUT_BYTES", _DEFAULT_MAX_INPUT_BYTES))
    if use_base64:
        try:
            payload = base64.b64decode((hwpx_base64 or "").strip(), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("invalid hwpx_base64 payload") from exc
        if len(payload) > max_input_bytes:
            raise ValueError(f"input is too large: limit is {max_input_bytes} bytes")
        if not payload:
            raise ValueError("hwpx_base64 decoded to empty payload")
        return payload, {"source_type": "base64", "size_bytes": len(payload)}

    source_url = (url or "").strip()
    payload = _download_hwpx_from_url(source_url, max_input_bytes=max_input_bytes)
    return payload, {
        "source_type": "url",
        "source_url": source_url,
        "size_bytes": len(payload),
    }


def _open_hwpx_from_payload(hwpx_base64: str | None, url: str | None):
    payload, source_meta = _load_hwpx_payload(hwpx_base64, url)
    try:
        doc = open_document(BytesIO(payload))
    except Exception as exc:  # pragma: no cover - delegated to parser
        raise ValueError(f"failed to parse hwpx payload: {exc}") from exc
    return doc, source_meta


def _table_rows(table: Any) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in getattr(table, "rows", []):
        rows.append([(cell.text or "") for cell in getattr(row, "cells", [])])
    return rows


def _table_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max((len(row) for row in rows), default=0)
    if width <= 0:
        return ""

    def _pad(row: list[str]) -> list[str]:
        return row + [""] * (width - len(row))

    normalized = [_pad([str(cell) for cell in row]) for row in rows]
    header = normalized[0]
    divider = ["---"] * width

    def _render(cells: list[str]) -> str:
        escaped = [cell.replace("|", r"\|").replace("\n", "<br>") for cell in cells]
        return f"| {' | '.join(escaped)} |"

    lines = [_render(header), _render(divider)]
    for row in normalized[1:]:
        lines.append(_render(row))
    return "\n".join(lines)


def _table_to_html(rows: list[list[str]]) -> str:
    if not rows:
        return "<table></table>"
    width = max((len(row) for row in rows), default=0)
    if width <= 0:
        return "<table></table>"

    def _pad(row: list[str]) -> list[str]:
        return row + [""] * (width - len(row))

    normalized = [_pad([str(cell) for cell in row]) for row in rows]
    header = normalized[0]
    body_rows = normalized[1:]

    head_html = "".join(f"<th>{html.escape(cell)}</th>" for cell in header)
    body_html = []
    for row in body_rows:
        cells = "".join(f"<td>{html.escape(cell)}</td>" for cell in row)
        body_html.append(f"<tr>{cells}</tr>")

    if body_html:
        body = "<tbody>" + "".join(body_html) + "</tbody>"
    else:
        body = ""
    return f"<table><thead><tr>{head_html}</tr></thead>{body}</table>"


def _run_format_detail(
    run: Any, fontfaces: dict[str, dict[str, str]] | None = None
) -> dict[str, Any]:
    """Resolved inline formatting for one run.

    Named fields (bold/italic/underline/strikeout/color/fontSize/fontName/
    super-subscript) come from the canonical :mod:`hwpx.tools.read_fidelity`
    resolver so this surface and the fidelity harness agree by construction.
    ``strikeout`` is shape-normalised (the always-present
    ``<hh:strikeout shape="NONE"/>`` previously read as always-on); ``underline``
    is the type or ``None`` when off. Legacy keys are preserved for compat.
    """
    style = getattr(run, "style", None)
    span = _read_fidelity.run_span(
        getattr(run, "text", "") or "", style, fontfaces or {}
    )
    return {
        "text": span.text,
        "charPrIDRef": getattr(run, "char_pr_id_ref", None),
        "bold": span.bold,
        "italic": span.italic,
        "underline": span.underline,
        "strikeout": span.strikeout,
        "color": span.color,
        "fontSize": span.size_pt,
        "fontName": span.font,
        "superscript": span.superscript,
        "subscript": span.subscript,
        # legacy back-compat keys
        "textColor": span.color,
        "underlineType": style.underline_type() if style is not None else None,
        "underlineColor": style.underline_color() if style is not None else None,
        "attributes": dict(getattr(style, "attributes", {}) or {}),
    }


def _paragraph_format_detail(
    paragraph: Any, fontfaces: dict[str, dict[str, str]] | None = None
) -> dict[str, Any]:
    return {
        "paraPrIDRef": getattr(paragraph, "para_pr_id_ref", None),
        "styleIDRef": getattr(paragraph, "style_id_ref", None),
        "charPrIDRef": getattr(paragraph, "char_pr_id_ref", None),
        "runs": [
            _run_format_detail(run, fontfaces) for run in getattr(paragraph, "runs", [])
        ],
    }


def _cell_format_detail(cell: Any) -> dict[str, Any]:
    return {
        "width": getattr(cell, "width", None),
        "height": getattr(cell, "height", None),
        "span": list(getattr(cell, "span", ()) or ()),
        "address": list(getattr(cell, "address", ()) or ()),
        "borderFillIDRef": getattr(
            getattr(cell, "element", None), "get", lambda _name, _default=None: _default
        )("borderFillIDRef"),
    }


def _table_format_detail(table: Any) -> dict[str, Any]:
    rows = []
    for row in getattr(table, "rows", []):
        cells = [_cell_format_detail(cell) for cell in getattr(row, "cells", [])]
        rows.append(cells)
    return {
        "columnCount": getattr(table, "column_count", None),
        "rowCount": getattr(table, "row_count", None),
        "cells": rows,
    }


def _build_read_model(doc: Any, *, format_detail: bool = False) -> dict[str, Any]:
    toc: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    figures: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []

    current_section: dict[str, Any] = {
        "index": 0,
        "title": None,
        "level": 0,
        "paragraphs": [],
        "tables": [],
        "figures": [],
    }

    def _flush_current_section() -> None:
        if (
            not current_section["paragraphs"]
            and not current_section["tables"]
            and not current_section["figures"]
        ):
            return
        sections.append(
            {
                "index": len(sections),
                "title": current_section["title"],
                "level": current_section["level"],
                "paragraphs": list(current_section["paragraphs"]),
                "tables": list(current_section["tables"]),
                "figures": list(current_section["figures"]),
            }
        )

    table_index = 0
    style_levels = outline_style_levels(doc)
    fontfaces = _read_fidelity.fontface_maps(doc) if format_detail else {}
    for paragraph_index, paragraph in enumerate(doc.paragraphs):
        text = (paragraph.text or "").strip()
        level = _paragraph_outline_level(paragraph, text, style_levels)
        paragraph_payload = {"index": paragraph_index, "text": text}
        if format_detail:
            paragraph_payload["format"] = _paragraph_format_detail(paragraph, fontfaces)

        if level > 0 and text:
            _flush_current_section()
            current_section = {
                "index": len(sections),
                "title": _normalize_heading_text(text),
                "level": level,
                "paragraphs": [],
                "tables": [],
                "figures": [],
            }
            heading_text = _normalize_heading_text(text)
            toc.append(
                {
                    "level": level,
                    "text": heading_text,
                    "paragraph_index": paragraph_index,
                }
            )
            item = {
                "type": "heading",
                "level": level,
                "text": heading_text,
                "paragraph_index": paragraph_index,
            }
            if format_detail:
                item["format"] = _paragraph_format_detail(paragraph, fontfaces)
            items.append(item)
        elif text:
            item = {
                "type": "paragraph",
                "text": text,
                "paragraph_index": paragraph_index,
            }
            if format_detail:
                item["format"] = _paragraph_format_detail(paragraph, fontfaces)
            items.append(item)

        if text:
            current_section["paragraphs"].append(paragraph_payload)
            if _looks_like_figure_caption(text):
                figure = {
                    "figure_index": len(figures),
                    "paragraph_index": paragraph_index,
                    "caption": text,
                }
                figures.append(figure)
                current_section["figures"].append(figure)

        for table in getattr(paragraph, "tables", []):
            rows = _table_rows(table)
            table_payload = {
                "table_index": table_index,
                "paragraph_index": paragraph_index,
                "rows": len(rows),
                "cols": max((len(row) for row in rows), default=0),
                "data": rows,
            }
            if format_detail:
                table_payload["format"] = _table_format_detail(table)
            tables.append(table_payload)
            current_section["tables"].append(table_payload)
            item = {
                "type": "table",
                "table_index": table_index,
                "paragraph_index": paragraph_index,
                "data": rows,
            }
            if format_detail:
                item["format"] = table_payload["format"]
            items.append(item)
            table_index += 1

    _flush_current_section()
    try:
        notes = [note.to_dict() for note in _read_fidelity.collect_notes(doc)]
    except Exception:  # pragma: no cover - defensive: never break a read
        notes = []
    return {
        "title": toc[0]["text"] if toc else None,
        "toc": toc,
        "sections": sections,
        "tables": tables,
        "figures": figures,
        "items": items,
        "notes": notes,
    }


def _append_notes_markdown(
    markdown: str, notes: list[dict[str, Any]], mask: bool
) -> str:
    """Append a footnote/endnote definition appendix (reference-style).

    The reading surfaces used to drop note bodies entirely; this preserves them
    at the installed surface as ``[^fn1]: body`` lines under a rule.
    """
    if not notes:
        return markdown
    fn_i = en_i = 0
    lines: list[str] = []
    for note in notes:
        if note.get("kind") == "footNote":
            fn_i += 1
            marker, label = f"[^fn{fn_i}]", "각주"
        else:
            en_i += 1
            marker, label = f"[^en{en_i}]", "미주"
        body = _mask_pii_text(note.get("bodyText", "") or "", mask)
        lines.append(f"{marker}: ({label}) {body}")
    appendix = "\n".join(lines)
    return f"{markdown}\n\n---\n\n{appendix}" if markdown else appendix


def _render_markdown(model: dict[str, Any]) -> str:
    blocks: list[str] = []
    for item in model["items"]:
        kind = item["type"]
        if kind == "heading":
            level = max(1, min(6, int(item["level"])))
            blocks.append(f"{'#' * level} {item['text']}")
        elif kind == "paragraph":
            blocks.append(item["text"])
        elif kind == "table":
            table_markdown = _table_to_markdown(item["data"])
            if table_markdown:
                blocks.append(table_markdown)
    return "\n\n".join(blocks).strip()


def _render_html(model: dict[str, Any]) -> str:
    body: list[str] = ['<article class="hwpx-document">']
    for item in model["items"]:
        kind = item["type"]
        if kind == "heading":
            level = max(1, min(6, int(item["level"])))
            body.append(f"<h{level}>{html.escape(item['text'])}</h{level}>")
        elif kind == "paragraph":
            body.append(f"<p>{html.escape(item['text'])}</p>")
        elif kind == "table":
            body.append(_table_to_html(item["data"]))
    body.append("</article>")
    return (
        "<!doctype html>"
        "<html><head><meta charset='utf-8'><title>HWPX Document</title></head>"
        f"<body>{''.join(body)}</body></html>"
    )


def _section_markdown(section: dict[str, Any]) -> str:
    blocks: list[str] = []
    title = section.get("title")
    level = max(1, min(6, int(section.get("level") or 1)))
    paragraphs = list(section.get("paragraphs") or [])
    if title:
        blocks.append(f"{'#' * level} {title}")
        if paragraphs and paragraphs[0].get("text") == title:
            paragraphs = paragraphs[1:]
    for paragraph in paragraphs:
        text = (paragraph.get("text") or "").strip()
        if text:
            blocks.append(text)
    for table in section.get("tables") or []:
        markdown_table = _table_to_markdown(table.get("data") or [])
        if markdown_table:
            blocks.append(markdown_table)
    return "\n\n".join(blocks).strip()


def _section_html(section: dict[str, Any]) -> str:
    parts: list[str] = ["<section>"]
    title = section.get("title")
    level = max(1, min(6, int(section.get("level") or 1)))
    paragraphs = list(section.get("paragraphs") or [])
    if title:
        parts.append(f"<h{level}>{html.escape(title)}</h{level}>")
        if paragraphs and paragraphs[0].get("text") == title:
            paragraphs = paragraphs[1:]
    for paragraph in paragraphs:
        text = (paragraph.get("text") or "").strip()
        if text:
            parts.append(f"<p>{html.escape(text)}</p>")
    for table in section.get("tables") or []:
        parts.append(_table_to_html(table.get("data") or []))
    parts.append("</section>")
    return "".join(parts)


def _chunk_paragraphs(paragraphs: list[str], max_chars_per_chunk: int) -> list[str]:
    chunks: list[str] = []
    buffer: list[str] = []
    used = 0
    for paragraph in paragraphs:
        text = (paragraph or "").strip()
        if not text:
            continue
        additional = len(text) + (2 if buffer else 0)
        if buffer and used + additional > max_chars_per_chunk:
            chunks.append("\n\n".join(buffer))
            buffer = []
            used = 0
        if len(text) > max_chars_per_chunk:
            if buffer:
                chunks.append("\n\n".join(buffer))
                buffer = []
                used = 0
            for start in range(0, len(text), max_chars_per_chunk):
                chunks.append(text[start : start + max_chars_per_chunk])
            continue
        buffer.append(text)
        used += additional
    if buffer:
        chunks.append("\n\n".join(buffer))
    return chunks


def _markdown_chunks(
    model: dict[str, Any], *, chunk_strategy: str, max_chars_per_chunk: int
) -> list[str]:
    if chunk_strategy == "section":
        return [
            chunk
            for section in model["sections"]
            if (chunk := _section_markdown(section))
        ]

    paragraphs = [
        item["text"]
        for item in model["items"]
        if item["type"] in {"heading", "paragraph"}
    ]
    return _chunk_paragraphs(paragraphs, max_chars_per_chunk)


def _ingest_markdown_chunks(markdown: str, *, max_chars_per_chunk: int) -> list[str]:
    paragraphs = [part for part in re.split(r"\n{2,}", markdown or "") if part.strip()]
    return _chunk_paragraphs(paragraphs, max_chars_per_chunk)


def _html_chunks(
    model: dict[str, Any], *, chunk_strategy: str, max_chars_per_chunk: int
) -> list[str]:
    if chunk_strategy == "section":
        chunks = [_section_html(section) for section in model["sections"]]
        return [chunk for chunk in chunks if chunk]

    paragraphs = [
        f"<p>{html.escape(item['text'])}</p>"
        for item in model["items"]
        if item["type"] in {"heading", "paragraph"}
    ]
    plain_chunks = _chunk_paragraphs(paragraphs, max_chars_per_chunk)
    return [
        f"<article class='hwpx-document'>{chunk}</article>" for chunk in plain_chunks
    ]


def _json_chunks(
    model: dict[str, Any], *, chunk_strategy: str, max_chars_per_chunk: int
) -> list[dict[str, Any]]:
    if chunk_strategy == "section":
        return [
            {"chunk_index": index, "strategy": "section", "section": section}
            for index, section in enumerate(model["sections"])
        ]

    paragraphs = []
    for section in model["sections"]:
        for paragraph in section.get("paragraphs") or []:
            paragraphs.append(
                {
                    "section_index": section.get("index"),
                    "paragraph_index": paragraph.get("index"),
                    "text": paragraph.get("text") or "",
                }
            )
    groups = _chunk_paragraphs(
        [item["text"] for item in paragraphs], max_chars_per_chunk
    )
    chunks: list[dict[str, Any]] = []
    offset = 0
    for chunk_index, chunk in enumerate(groups):
        consumed = len(chunk.split("\n\n")) if chunk else 0
        selected = paragraphs[offset : offset + consumed]
        offset += consumed
        chunks.append(
            {
                "chunk_index": chunk_index,
                "strategy": "paragraph",
                "paragraphs": selected,
            }
        )
    return chunks


def _build_conversion_meta(
    model: dict[str, Any], source_meta: dict[str, Any]
) -> dict[str, Any]:
    return {
        "source_type": source_meta.get("source_type"),
        "source_url": source_meta.get("source_url"),
        "size_bytes": source_meta.get("size_bytes"),
        "section_count": len(model["sections"]),
        "paragraph_count": sum(
            1 for item in model["items"] if item["type"] in {"heading", "paragraph"}
        ),
        "table_count": len(model["tables"]),
        "figure_caption_count": len(model["figures"]),
    }


def _ingest_local_document(filename: str):
    if DocumentIngestor is None:
        raise RuntimeError("installed python-hwpx does not provide document ingest")
    from ..ingest_adapters import MarkItDownAdapter, MissingMarkItDownDependency

    path = resolve_path(filename)
    ingestor = DocumentIngestor.default()
    ingestor.register_converter(MarkItDownAdapter(), priority=100.0)
    try:
        return path, ingestor.convert(path)
    except DocumentIngestError as exc:
        for attempt in getattr(exc, "attempts", []) or []:
            if getattr(attempt, "error_type", None) == "MissingMarkItDownDependency":
                raise MissingMarkItDownDependency(
                    str(attempt.message), attempts=exc.attempts
                ) from exc
        raise


def _document_ingest_error_payload(exc: Exception, filename: str) -> dict[str, Any]:
    if DocumentIngestError is not None and isinstance(exc, DocumentIngestError):
        payload = exc.as_dict()
    else:
        payload = {"error": type(exc).__name__, "message": str(exc), "attempts": []}
    payload.update({"ok": False, "filename": filename})
    return payload


def _document_ingest_meta(result: Any) -> dict[str, Any]:
    source_info = getattr(result, "source_info", None)
    meta = {
        "source_format": getattr(result, "source_format", None),
        "engine": getattr(result, "engine", None),
        "engine_version": getattr(result, "engine_version", None),
        "lossiness": getattr(result, "lossiness", None),
    }
    if source_info is not None:
        meta["source_info"] = {
            "mimetype": getattr(source_info, "mimetype", None),
            "extension": getattr(source_info, "extension", None),
            "charset": getattr(source_info, "charset", None),
            "filename": getattr(source_info, "filename", None),
            "local_path": getattr(source_info, "local_path", None),
            "url": getattr(source_info, "url", None),
        }
    metadata = getattr(result, "metadata", None)
    if isinstance(metadata, dict):
        meta.update(metadata)
    return {key: value for key, value in meta.items() if value is not None}


def _attempts_payload(result: Any) -> list[dict[str, Any]]:
    attempts = getattr(result, "attempts", []) or []
    return [
        attempt.as_dict() if hasattr(attempt, "as_dict") else dict(attempt)
        for attempt in attempts
    ]


def _paragraph_count(doc) -> int:
    return len(doc.paragraphs)


def _table_count(doc) -> int:
    table_tag = f"{HP_NS}tbl"
    count = 0
    for section in getattr(doc, "sections", []):
        section_element = getattr(section, "element", None)
        if section_element is None or not hasattr(section_element, "iter"):
            continue
        count += sum(1 for _ in section_element.iter(table_tag))
    return count


def _outline_level(text: str) -> int:
    stripped = (text or "").strip()
    if not stripped:
        return 0
    if stripped.startswith("#"):
        return min(6, len(stripped) - len(stripped.lstrip("#")))
    if stripped[:2].isdigit() and "." in stripped[:6]:
        return 2
    if stripped[:1].isdigit() and "." in stripped[:4]:
        return 1
    return 1 if len(stripped) < 60 else 0


def _paragraph_outline_level(
    paragraph: Any, text: str, style_levels: dict[str, int]
) -> int:
    """개요 문단 스타일을 우선하고, 구버전 '#' 헤딩만 fallback으로 인식한다."""
    if not (text or "").strip():
        return 0
    ref = getattr(paragraph, "style_id_ref", None)
    if ref is not None and str(ref) in style_levels:
        return style_levels[str(ref)]
    if text.strip().startswith("#"):
        return _outline_level(text)
    if style_levels:
        return 0
    return _outline_level(text)


def get_document_info(filename: str) -> dict:
    """문서 메타데이터와 구조 요약을 조회합니다."""
    path = resolve_path(filename)
    doc = open_doc(path)
    file_size = Path(path).stat().st_size
    return _with_document_state(
        {
            "filename": filename,
            "sections": len(doc.sections),
            "paragraphs": _paragraph_count(doc),
            "tables": _table_count(doc),
            "file_size": str(file_size),
        },
        path,
    )


def get_document_text(
    filename: str, max_chars: int | None = None, mask: bool = True
) -> dict:
    """문서 전체 텍스트를 조회합니다. (기본: 기계검증 PII 마스킹 ON — `mask=False`로 원본)"""
    path = resolve_path(filename)
    doc = open_doc(path)
    text = _mask_pii_text(collect_full_text(doc), mask)
    return _with_document_state(truncate_response(text, max_chars=max_chars), path)


def get_document_outline(filename: str) -> dict:
    """문단 기준 제목/개요 구조를 조회합니다."""
    path = resolve_path(filename)
    doc = open_doc(path)
    outline: list[dict] = []
    style_levels = outline_style_levels(doc)
    for index, para in enumerate(doc.paragraphs):
        text = (para.text or "").strip()
        level = _paragraph_outline_level(para, text, style_levels)
        if level > 0 and text:
            outline.append(
                {
                    "level": level,
                    "text": _normalize_heading_text(text),
                    "paragraph_index": index,
                }
            )
    return _with_document_state({"outline": outline}, path)


def _summary_table_map(path) -> dict:
    """Compact per-table map (FR-006) via python-hwpx table_summary — bounded."""
    try:
        from hwpx.table_patch import table_summary
    except Exception as exc:  # pragma: no cover - dependency compatibility
        return {"tables": [], "count": 0, "note": f"summary unavailable: {exc}"}
    tables = table_summary(path)
    return {"tables": tables, "count": len(tables), "detail": "summary"}


def get_document_map(
    filename: str,
    max_preview_chars: int = 80,
    detail: str = "full",
) -> dict:
    """문서 개요, 표, 양식 필드, 앵커를 한 번에 조회합니다.

    detail="summary" (FR-006): 표는 셀 덤프 없이 표당 {tableIndex, rows, cols,
    merges, heading, firstRow} 요약만 반환 — 37표 양식도 토큰한도 내 1콜. 헤딩은
    apply_table_ops/fill_cells의 tableAnchor로 그대로 쓸 수 있는 텍스트.
    detail="full"(기본)은 종전대로 셀 단위 표 지도를 반환한다."""
    path = resolve_path(filename)
    doc = open_doc(path)
    model = _build_read_model(doc)
    preview_limit = max(0, int(max_preview_chars))
    summary_mode = str(detail).lower() == "summary"

    paragraph_anchors = []
    for item in model["items"]:
        if item.get("type") not in {"heading", "paragraph"}:
            continue
        text = str(item.get("text") or "")
        paragraph_index = item.get("paragraph_index")
        paragraph_anchors.append(
            {
                "kind": item.get("type"),
                "paragraphIndex": paragraph_index,
                "textPreview": text[:preview_limit],
                "anchor": {
                    "kind": "body_paragraph",
                    "paragraphIndex": paragraph_index,
                },
            }
        )

    table_anchors = [
        {
            "kind": "table",
            "tableIndex": table.get("table_index"),
            "paragraphIndex": table.get("paragraph_index"),
            "rows": table.get("rows"),
            "cols": table.get("cols"),
            "anchor": {
                "kind": "table",
                "tableIndex": table.get("table_index"),
                "paragraphIndex": table.get("paragraph_index"),
            },
        }
        for table in model["tables"]
    ]

    try:
        form_fields = RUNTIME_SERVICES.ops.list_form_fields(path)
    except Exception as exc:  # pragma: no cover - diagnostic fallback
        form_fields = {"fields": [], "error": str(exc)}

    result = {
        "filename": filename,
        "info": {
            "sections": len(doc.sections),
            "paragraphs": _paragraph_count(doc),
            "tables": _table_count(doc),
        },
        "outline": model["toc"],
        "sections": [
            {
                "index": section.get("index"),
                "title": section.get("title"),
                "level": section.get("level"),
                "paragraphCount": len(section.get("paragraphs") or []),
                "tableCount": len(section.get("tables") or []),
                "figureCount": len(section.get("figures") or []),
            }
            for section in model["sections"]
        ],
        "tables": _summary_table_map(path)
        if summary_mode
        else get_table_map_in_doc(doc),
        "formFields": form_fields,
        "anchors": {
            "paragraphs": paragraph_anchors,
            "tables": table_anchors,
            "figures": model["figures"],
        },
        "sourceTools": [
            "get_document_info",
            "get_document_outline",
            "get_table_map",
            "list_form_fields",
            "hwpx_extract_json",
        ],
    }
    result = _with_document_state(result, path)
    return bound_document_summary(result) if summary_mode else result


def hwpx_to_markdown(
    hwpx_base64: str | None = None,
    url: str | None = None,
    output: str = "full",
    chunk_strategy: str = "section",
    max_chars_per_chunk: int | None = None,
    mask: bool = True,
) -> dict:
    """HWPX payload 또는 URL을 Markdown으로 변환합니다. (기본: 기계검증 PII 마스킹 ON)"""
    mode = _normalize_output_mode(output)
    strategy = _normalize_chunk_strategy(chunk_strategy)
    chunk_size = _resolve_chunk_size(max_chars_per_chunk)

    doc, source_meta = _open_hwpx_from_payload(hwpx_base64, url)
    model = _build_read_model(doc)
    markdown = _mask_pii_text(_render_markdown(model), mask)
    markdown = _append_notes_markdown(markdown, model.get("notes", []), mask)

    result: dict[str, Any] = {
        "markdown": markdown,
        "meta": _build_conversion_meta(model, source_meta),
    }
    if mode == "chunks":
        result["chunks"] = _deep_mask_pii(
            _markdown_chunks(
                model,
                chunk_strategy=strategy,
                max_chars_per_chunk=chunk_size,
            ),
            mask,
        )
        result["meta"]["chunk_strategy"] = strategy
        result["meta"]["max_chars_per_chunk"] = chunk_size
    return result


def document_to_markdown(
    filename: str,
    output: str = "full",
    chunk_strategy: str = "section",
    max_chars_per_chunk: int | None = None,
    mask: bool = True,
) -> dict:
    """로컬 문서를 Markdown으로 변환합니다. 현재 HWPX는 python-hwpx ingest 엔진으로 처리합니다."""
    mode = _normalize_output_mode(output)
    strategy = _normalize_chunk_strategy(chunk_strategy)
    chunk_size = _resolve_chunk_size(max_chars_per_chunk)

    try:
        path, ingest_result = _ingest_local_document(filename)
    except Exception as exc:
        return _document_ingest_error_payload(exc, filename)

    markdown = _mask_pii_text(ingest_result.markdown, mask)
    payload: dict[str, Any] = {
        "ok": True,
        "filename": str(path),
        "markdown": markdown,
        "meta": _document_ingest_meta(ingest_result),
        "warnings": list(getattr(ingest_result, "warnings", []) or []),
        "attempts": _attempts_payload(ingest_result),
    }
    if mode == "chunks":
        payload["chunks"] = _deep_mask_pii(
            _ingest_markdown_chunks(markdown, max_chars_per_chunk=chunk_size),
            mask,
        )
        payload["meta"]["chunk_strategy"] = strategy
        payload["meta"]["max_chars_per_chunk"] = chunk_size
    return payload


def hwpx_to_html(
    hwpx_base64: str | None = None,
    url: str | None = None,
    output: str = "full",
    chunk_strategy: str = "section",
    max_chars_per_chunk: int | None = None,
) -> dict:
    """HWPX payload 또는 URL을 HTML로 변환합니다."""
    mode = _normalize_output_mode(output)
    strategy = _normalize_chunk_strategy(chunk_strategy)
    chunk_size = _resolve_chunk_size(max_chars_per_chunk)

    doc, source_meta = _open_hwpx_from_payload(hwpx_base64, url)
    model = _build_read_model(doc)
    payload: dict[str, Any] = {
        "html": _render_html(model),
        "meta": _build_conversion_meta(model, source_meta),
    }
    payload["meta"]["image_policy"] = "omitted"

    if mode == "chunks":
        payload["chunks"] = _html_chunks(
            model,
            chunk_strategy=strategy,
            max_chars_per_chunk=chunk_size,
        )
        payload["meta"]["chunk_strategy"] = strategy
        payload["meta"]["max_chars_per_chunk"] = chunk_size
    return payload


def hwpx_extract_json(
    hwpx_base64: str | None = None,
    url: str | None = None,
    output: str = "full",
    chunk_strategy: str = "section",
    max_chars_per_chunk: int | None = None,
    format_detail: bool = False,
    mask: bool = True,
) -> dict:
    """HWPX payload 또는 URL에서 구조화된 JSON을 추출합니다. (기본: 기계검증 PII 마스킹 ON)"""
    mode = _normalize_output_mode(output)
    strategy = _normalize_chunk_strategy(chunk_strategy)
    chunk_size = _resolve_chunk_size(max_chars_per_chunk)

    doc, source_meta = _open_hwpx_from_payload(hwpx_base64, url)
    model = _build_read_model(doc, format_detail=bool(format_detail))
    doc_payload = _deep_mask_pii(
        {
            "title": model["title"],
            "toc": model["toc"],
            "sections": model["sections"],
            "tables": model["tables"],
            "figures": model["figures"],
            "notes": model.get("notes", []),
        },
        mask,
    )
    result: dict[str, Any] = {
        "doc": doc_payload,
        "meta": _build_conversion_meta(model, source_meta),
    }
    if format_detail:
        result["meta"]["format_detail"] = True
    if mode == "chunks":
        result["chunks"] = _deep_mask_pii(
            _json_chunks(
                model,
                chunk_strategy=strategy,
                max_chars_per_chunk=chunk_size,
            ),
            mask,
        )
        result["meta"]["chunk_strategy"] = strategy
        result["meta"]["max_chars_per_chunk"] = chunk_size
    return result


def document_extract_json(
    filename: str,
    output: str = "full",
    chunk_strategy: str = "section",
    max_chars_per_chunk: int | None = None,
    format_detail: bool = False,
    mask: bool = True,
) -> dict:
    """로컬 문서에서 Markdown과 구조화된 JSON을 함께 추출합니다. 현재 HWPX ingest를 우선 사용합니다."""
    del format_detail
    mode = _normalize_output_mode(output)
    strategy = _normalize_chunk_strategy(chunk_strategy)
    chunk_size = _resolve_chunk_size(max_chars_per_chunk)

    try:
        path, ingest_result = _ingest_local_document(filename)
    except Exception as exc:
        return _document_ingest_error_payload(exc, filename)

    markdown = _mask_pii_text(ingest_result.markdown, mask)
    doc_payload = _deep_mask_pii(
        {
            "title": getattr(ingest_result, "title", None),
            "markdown": markdown,
            "sections": getattr(ingest_result, "sections", []) or [],
            "tables": getattr(ingest_result, "tables", []) or [],
            "metadata": getattr(ingest_result, "metadata", {}) or {},
        },
        mask,
    )
    payload: dict[str, Any] = {
        "ok": True,
        "filename": str(path),
        "doc": doc_payload,
        "meta": _document_ingest_meta(ingest_result),
        "warnings": list(getattr(ingest_result, "warnings", []) or []),
        "attempts": _attempts_payload(ingest_result),
    }
    if mode == "chunks":
        payload["chunks"] = _deep_mask_pii(
            _ingest_markdown_chunks(markdown, max_chars_per_chunk=chunk_size),
            mask,
        )
        payload["meta"]["chunk_strategy"] = strategy
        payload["meta"]["max_chars_per_chunk"] = chunk_size
    return payload


def get_paragraph_text(
    filename: str,
    paragraph_index: int | None = None,
    location: dict[str, Any] | None = None,
) -> dict:
    """본문 문단 또는 표 셀 문단 텍스트를 조회합니다."""
    path = resolve_path(filename)
    doc = open_doc(path)
    result = get_paragraph_text_from_doc(
        doc, paragraph_index=paragraph_index, location=location
    )
    if result["location"].get("kind") == "body_paragraph":
        result["paragraph_index"] = result["location"]["paragraph_index"]
    return _with_document_state(result, path)


def get_location_text(filename: str, location: dict[str, Any]) -> dict:
    """get_table_map/find_text가 반환한 location으로 텍스트를 조회합니다."""
    return get_paragraph_text(filename, location=location)


def get_paragraphs_text(
    filename: str,
    start_index: int = 0,
    end_index: int = None,
    max_chars: int | None = None,
) -> dict:
    """문단 범위 텍스트를 조회합니다."""
    path = resolve_path(filename)
    doc = open_doc(path)
    if max_chars is None:
        max_chars = default_max_chars()

    total = len(doc.paragraphs)
    end = total if end_index is None else min(end_index, total)
    start = max(0, start_index)
    picked = []
    used = 0
    truncated = False
    for index in range(start, end):
        text = doc.paragraphs[index].text or ""
        next_size = used + len(text)
        if next_size > max_chars:
            remaining = max(0, max_chars - used)
            picked.append({"index": index, "text": text[:remaining]})
            truncated = True
            break
        picked.append({"index": index, "text": text})
        used = next_size
    return _with_document_state({"paragraphs": picked, "truncated": truncated}, path)


def find_text(
    filename: str, text_to_find: str, match_case: bool = True, max_results: int = 50
) -> dict:
    """문서에서 텍스트를 검색합니다. 원본은 수정하지 않습니다."""
    path = resolve_path(filename)
    doc = open_doc(path)
    return _with_document_state(
        find_in_doc(
            doc,
            text_to_find=text_to_find,
            match_case=match_case,
            max_results=max_results,
        ),
        path,
    )


def get_table_text(filename: str, table_index: int = 0) -> dict:
    """표 셀 텍스트를 2D 배열로 조회합니다."""
    path = resolve_path(filename)
    doc = open_doc(path)
    result = get_table_data(doc, table_index)
    return _with_document_state(
        {
            "table_index": table_index,
            "rows": result["rows"],
            "cols": result["cols"],
            "data": result["data"],
        },
        path,
    )


def get_table_map(filename: str) -> dict:
    """문서 내 표 위치, 크기, 문맥 요약을 조회합니다."""
    path = resolve_path(filename)
    doc = open_doc(path)
    return _with_document_state(get_table_map_in_doc(doc), path)


def list_available_documents(directory: str = ".") -> dict:
    """지정 디렉토리의 .hwpx 파일 목록을 조회합니다."""
    import glob

    path = resolve_path(directory)
    files = glob.glob(os.path.join(path, "*.hwpx"))
    docs = []
    for file_path in sorted(files):
        stat = os.stat(file_path)
        docs.append(
            {
                "filename": os.path.basename(file_path),
                "size": f"{stat.st_size / 1024:.1f}KB",
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        )
    return {"directory": directory, "documents": docs, "count": len(docs)}


def package_parts(filename: str) -> dict:
    """[고급] HWPX 패키지 파트 목록을 조회합니다."""
    path = resolve_path(filename)
    return RUNTIME_SERVICES.ops.package_parts(path)


def package_get_xml(filename: str, part_name: str, max_chars: int = 5000) -> dict:
    """[고급] 특정 패키지 파트의 XML을 조회합니다."""
    path = resolve_path(filename)
    result = RUNTIME_SERVICES.ops.package_get_xml(path, part_name)
    return truncate_response(result.get("xmlString", ""), max_chars=max_chars)


def package_get_text(filename: str, part_name: str, max_chars: int = 5000) -> dict:
    """[고급] 특정 패키지 파트의 텍스트를 조회합니다."""
    path = resolve_path(filename)
    result = RUNTIME_SERVICES.ops.package_get_text(path, part_name)
    return truncate_response(result.get("text", ""), max_chars=max_chars)


def object_find_by_tag(filename: str, tag_name: str, max_results: int = 20) -> dict:
    """[고급] 문서 XML에서 태그를 검색합니다."""
    path = resolve_path(filename)
    return RUNTIME_SERVICES.ops.object_find_by_tag(
        path, tag_name, max_results=max_results
    )


def object_find_by_attr(
    filename: str, attr_name: str, attr_value: str = None, max_results: int = 20
) -> dict:
    """[고급] 문서 XML에서 속성을 검색합니다."""
    path = resolve_path(filename)
    return RUNTIME_SERVICES.ops.object_find_by_attr(
        path, None, attr_name, attr_value, max_results=max_results
    )


__all__ = [
    "get_document_text",
    "get_document_info",
    "get_document_outline",
    "get_document_map",
    "get_paragraph_text",
    "get_paragraphs_text",
    "get_location_text",
    "get_table_text",
    "get_table_map",
    "find_text",
    "list_available_documents",
    "hwpx_to_markdown",
    "document_to_markdown",
    "hwpx_to_html",
    "hwpx_extract_json",
    "document_extract_json",
    "package_parts",
    "package_get_text",
    "package_get_xml",
    "object_find_by_attr",
    "object_find_by_tag",
]
