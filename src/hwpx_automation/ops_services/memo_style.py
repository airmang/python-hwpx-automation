# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import copy
import dataclasses
import logging
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple, cast
from xml.etree import ElementTree as ET

from ..upstream import (
    HP_NS,
    HwpxDocument,
    HwpxOxmlMemo,
    HwpxOxmlParagraph,
    HwpxOxmlRun,
    ensure_char_style,
    normalize_hex_color,
)

from .context import DocumentContext
from .save_policy import SavePolicy

logger = logging.getLogger("hwpx_automation.hwpx_ops")


class _Segment:
    __slots__ = ("element", "attr", "text")

    def __init__(self, element: ET.Element, attr: str, text: str) -> None:
        self.element = element
        self.attr = attr
        self.text = text

    def set(self, value: str) -> None:
        self.text = value
        if value:
            setattr(self.element, self.attr, value)
        else:
            setattr(self.element, self.attr, "")


def _gather_segments(element: ET.Element) -> List[_Segment]:
    segments: List[_Segment] = []

    def visit(node: ET.Element) -> None:
        text_value = node.text or ""
        segments.append(_Segment(node, "text", text_value))
        for child in list(node):
            visit(child)
            tail_value = child.tail or ""
            segments.append(_Segment(child, "tail", tail_value))

    for text_node in element.findall(f"{HP_NS}t"):
        visit(text_node)
    return segments


def _slice_run(run_obj: HwpxOxmlRun, start: int, end: int) -> None:
    segments = _gather_segments(run_obj.element)
    if not segments:
        return
    total_length = sum(len(segment.text) for segment in segments)
    start = max(0, min(start, total_length))
    end = max(0, min(end, total_length))
    if start >= end:
        for segment in segments:
            if segment.text:
                segment.set("")
        run_obj.paragraph.section.mark_dirty()
        return
    changed = False
    offset = 0
    for segment in segments:
        seg_start = offset
        seg_end = seg_start + len(segment.text)
        offset = seg_end
        if end <= seg_start or start >= seg_end:
            if segment.text:
                segment.set("")
                changed = True
            continue
        local_start = max(start, seg_start) - seg_start
        local_end = min(end, seg_end) - seg_start
        new_value = segment.text[local_start:local_end]
        if segment.text != new_value:
            segment.set(new_value)
            changed = True
    if changed:
        run_obj.paragraph.section.mark_dirty()


def _split_run(
    run_obj: HwpxOxmlRun, local_start: int, local_end: int, char_pr_id_ref: str
) -> None:
    text_value = run_obj.text or ""
    length = len(text_value)
    if length == 0:
        return
    local_start = max(0, min(local_start, length))
    local_end = max(0, min(local_end, length))
    if local_start >= local_end:
        return
    if local_start == 0 and local_end == length:
        run_obj.char_pr_id_ref = char_pr_id_ref
        return

    segments: List[Tuple[int, int, Optional[str]]] = []
    original_char = run_obj.char_pr_id_ref
    if local_start > 0:
        segments.append((0, local_start, original_char))
    segments.append((local_start, local_end, char_pr_id_ref))
    if local_end < length:
        segments.append((local_end, length, original_char))

    parent = run_obj.paragraph.element
    run_children = list(parent)
    try:
        index = run_children.index(run_obj.element)
    except ValueError:  # pragma: no cover - defensive branch
        return

    new_elements: List[ET.Element] = []
    for seg_start, seg_end, char_id in segments:
        if seg_start >= seg_end:
            continue
        element_copy = copy.deepcopy(run_obj.element)
        segment_run = HwpxOxmlRun(element_copy, run_obj.paragraph)
        _slice_run(segment_run, seg_start, seg_end)
        if char_id is None:
            segment_run.char_pr_id_ref = None
        else:
            segment_run.char_pr_id_ref = char_id
        new_elements.append(element_copy)

    if not new_elements:
        parent.remove(run_obj.element)
        run_obj.paragraph.section.mark_dirty()
        return

    for offset, element in enumerate(new_elements):
        parent.insert(index + offset, element)
    parent.remove(run_obj.element)
    run_obj.paragraph.section.mark_dirty()


def _paragraph_length(paragraph: HwpxOxmlParagraph) -> int:
    return sum(len(run.text or "") for run in paragraph.runs)


def _apply_span(
    paragraph: HwpxOxmlParagraph,
    span_start: int,
    span_end: int,
    char_pr_id_ref: str,
) -> bool:
    if span_start >= span_end:
        return False
    applied = False
    cursor = span_start
    while cursor < span_end:
        runs = list(paragraph.runs)
        offset = 0
        target: Tuple[HwpxOxmlRun, int, int, int] | None = None
        for candidate in runs:
            text = candidate.text or ""
            length = len(text)
            run_start = offset
            run_end = run_start + length
            if run_end <= cursor:
                offset = run_end
                continue
            if run_start >= span_end:
                target = None
                break
            if length == 0:
                offset = run_end
                continue
            target = (candidate, run_start, run_end, length)
            break

        if target is None:
            break

        run_obj, run_start, run_end, length = target
        local_start = max(0, cursor - run_start)
        local_end = min(length, span_end - run_start)
        if local_start >= local_end:
            cursor = max(cursor + 1, run_end)
            continue

        _split_run(run_obj, local_start, local_end, char_pr_id_ref)
        applied = True
        cursor = min(span_end, run_end)

    return applied


def _span_bounds(span: Any) -> Tuple[int, int, int]:
    if isinstance(span, dict):
        paragraph_index = int(span.get("paragraph_index", -1))
        start = int(span.get("start", 0))
        end = int(span.get("end", 0))
    else:
        paragraph_index = int(
            getattr(span, "paragraph_index", getattr(span, "paragraphIndex", -1))
        )
        start = int(getattr(span, "start", 0))
        end = int(getattr(span, "end", 0))
    return paragraph_index, start, end


class MemoStyleService:
    def __init__(self, context: DocumentContext, save: SavePolicy) -> None:
        self._context = context
        self._save = save

    def _normalize_color(self, color: str | None) -> Optional[str]:
        return normalize_hex_color(color, field_name="colorHex")

    def _ensure_char_style(
        self,
        document: HwpxDocument,
        run_style: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        if not run_style:
            return None
        bold = bool(run_style.get("bold", False))
        italic = bool(run_style.get("italic", False))
        underline = bool(run_style.get("underline", False))
        color = self._normalize_color(run_style.get("colorHex"))
        try:
            return ensure_char_style(
                document,
                base_char_pr_id=None,
                bold=bold,
                italic=italic,
                underline=underline,
                color=color,
            )
        except (ValueError, RuntimeError) as exc:
            message = str(exc)
            if "document does not contain any headers" in message:
                raise self._context._new_error("STYLE_HEADER_MISSING", message) from exc
            if "char property does not expose an identifier" in message:
                raise self._context._new_error(
                    "STYLE_CHAR_PROPERTY_ID_MISSING", message
                ) from exc
            raise

    def find_runs_by_style(
        self,
        path: str,
        *,
        filters: Optional[Dict[str, Any]] = None,
        max_results: int = 200,
    ) -> Dict[str, Any]:
        document, _ = self._context._open_document(path)
        filter_args: Dict[str, Any] = {}
        if filters:
            if "colorHex" in filters and filters["colorHex"]:
                filter_args["text_color"] = self._normalize_color(filters["colorHex"])
            if "underline" in filters:
                filter_args["underline_type"] = (
                    "BOTTOM" if filters["underline"] else "NONE"
                )
            if "charPrIDRef" in filters and filters["charPrIDRef"]:
                filter_args["char_pr_id_ref"] = filters["charPrIDRef"]
        runs = document.text.find_runs(**filter_args)
        paragraph_index_map: Dict[int, int] = {}
        paragraphs = self._context._iter_paragraphs(document)
        for index, paragraph in enumerate(paragraphs):
            paragraph_index_map[id(paragraph.element)] = index
        results: List[Dict[str, Any]] = []
        for run in runs[:max_results]:
            paragraph = run.paragraph
            para_index = paragraph_index_map.get(id(paragraph.element), -1)
            style = {}
            if run.style is not None:
                style_data = run.style
                if dataclasses.is_dataclass(style_data):
                    style = asdict(cast(Any, style_data))
            results.append(
                {
                    "text": run.text,
                    "paragraphIndex": para_index,
                    "charPrIDRef": run.char_pr_id_ref,
                    "style": style,
                }
            )
        return {"runs": results}

    def add_memo(
        self,
        path: str,
        text: str,
        *,
        section_index: Optional[int] = None,
        author: str | None = None,
        timestamp: str | None = None,
    ) -> Dict[str, Any]:
        document, resolved = self._context._open_document(path)
        memo = document.notes.add_memo(
            text,
            section_index=section_index,
            attributes={
                "author": author or "",
                "createDateTime": timestamp
                or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        self._save._save_document(document, resolved)
        return {"memoId": memo.id}

    def attach_memo_field(
        self,
        path: str,
        paragraph_index: int,
        memo_id: str,
    ) -> Dict[str, Any]:
        document, resolved = self._context._open_document(path)
        paragraphs = self._context._iter_paragraphs(document)
        try:
            paragraph = paragraphs[paragraph_index]
        except IndexError as exc:
            raise self._context._new_error(
                "PARAGRAPH_INDEX_OUT_OF_RANGE",
                "paragraphIndex out of range",
                details={"paragraphIndex": paragraph_index},
            ) from exc
        memo = self._find_memo(document, memo_id)
        if memo is None:
            raise self._context._new_error(
                "MEMO_NOT_FOUND",
                f"memo '{memo_id}' not found",
                details={"memoId": memo_id},
            )
        # notes.attach now returns the anchored Memo itself rather than a
        # bare field-id str (design §2.6) — .field_id (oxml/memo.py) resolves
        # it live by searching the section for the anchor field.
        attached_memo = document.notes.attach(paragraph, memo)
        self._save._save_document(document, resolved)
        return {"fieldId": attached_memo.field_id}

    def add_memo_with_anchor(
        self,
        path: str,
        *,
        text: str,
        section_index: Optional[int] = None,
        memo_shape_id_ref: str | None = None,
    ) -> Dict[str, Any]:
        document, resolved = self._context._open_document(path)
        # notes.add_memo(anchor=...) replaces add_memo_with_anchor (design
        # §2.6) but anchor= must resolve to an *existing* paragraph — unlike
        # 5.x, it has no "create one for me" mode (anchor=None routes to the
        # no-anchor path instead). Create the host paragraph explicitly
        # through the public add_paragraph, exactly mirroring what 5.x did
        # internally when its own paragraph= argument was omitted.
        paragraph = document.add_paragraph("", section_index=section_index)
        memo = document.notes.add_memo(
            text,
            anchor=paragraph,
            section_index=section_index,
            memo_shape_id_ref=memo_shape_id_ref,
        )
        field_id = memo.field_id
        paragraphs = self._context._iter_paragraphs(document)
        paragraph_index = len(paragraphs) - 1
        paragraph_element_id = id(paragraph.element)
        for idx, candidate in enumerate(paragraphs):
            if id(candidate.element) == paragraph_element_id:
                paragraph_index = idx
                break
        self._save._save_document(document, resolved)
        return {
            "memoId": memo.id,
            "paragraphIndex": paragraph_index,
            "fieldId": field_id,
        }

    def remove_memo(
        self,
        path: str,
        memo_id: str,
        *,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        document, resolved = self._context._open_document(path)
        memo = self._find_memo(document, memo_id)
        if memo is None:
            return {"removed": False}
        memo.remove()
        if not dry_run:
            self._save._save_document(document, resolved)
        return {"removed": True}

    def _find_memo(
        self, document: HwpxDocument, memo_id: str
    ) -> Optional[HwpxOxmlMemo]:
        for section in document.sections:
            for memo in section.memos:
                if memo.id == memo_id:
                    return memo
        return None

    def ensure_run_style(self, path: str, **run_style: Any) -> Dict[str, Any]:
        document, _ = self._context._open_document(path)
        char_id = self._ensure_char_style(document, run_style)
        return {"charPrIDRef": char_id}

    def list_styles_and_bullets(self, path: str) -> Dict[str, Any]:
        document, _ = self._context._open_document(path)
        styles = [
            asdict(cast(Any, style))
            for style in document.styles.values()
            if dataclasses.is_dataclass(style)
        ]
        bullets = [
            asdict(cast(Any, bullet))
            for bullet in document.styles.bullets.values()
            if dataclasses.is_dataclass(bullet)
        ]
        return {"styles": styles, "bullets": bullets}

    def apply_style_to_text_ranges(
        self,
        path: str,
        spans: Sequence[Dict[str, int]],
        char_pr_id_ref: str,
        *,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        if not char_pr_id_ref:
            raise ValueError("char_pr_id_ref must be provided")

        document, resolved = self._context._open_document(path)
        paragraphs = self._context._iter_paragraphs(document)

        styled = 0
        for span in spans:
            paragraph_index, start, end = _span_bounds(span)

            if paragraph_index < 0 or paragraph_index >= len(paragraphs):
                continue

            start = max(0, start)
            end = max(start, end)
            if start >= end:
                continue

            paragraph = paragraphs[paragraph_index]
            total_length = _paragraph_length(paragraph)
            if total_length == 0 or start >= total_length:
                continue
            clamped_end = min(end, total_length)

            if _apply_span(paragraph, start, clamped_end, char_pr_id_ref):
                styled += 1

        if not dry_run and styled:
            self._save._save_document(document, resolved)

        return {"styledSpans": styled}

    def apply_style_to_paragraphs(
        self,
        path: str,
        paragraph_indexes: Sequence[int],
        char_pr_id_ref: str,
        *,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        document, resolved = self._context._open_document(path)
        paragraphs = self._context._iter_paragraphs(document)
        updated = 0
        for index in paragraph_indexes:
            if index < 0 or index >= len(paragraphs):
                continue
            paragraph = paragraphs[index]
            paragraph.char_pr_id_ref = char_pr_id_ref
            for run in paragraph.runs:
                run.char_pr_id_ref = char_pr_id_ref
            updated += 1
        if not dry_run and updated:
            self._save._save_document(document, resolved)
        return {"updated": updated}
