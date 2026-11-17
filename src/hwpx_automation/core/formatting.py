# SPDX-License-Identifier: Apache-2.0
"""Text formatting helpers backed by python-hwpx character/style definitions."""

from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET

from ..upstream import (
    HwpxDocument,
    HwpxOxmlParagraph,
    HwpxOxmlRun,
    append_xml_child,
    char_style_matches,
    default_base_style_id,
    element_font_refs,
    element_style_flags,
    ensure_char_style,
    ensure_font_face_refs,
    iter_unique_styles,
    normalize_font_size,
    normalize_hex_color,
    primary_header,
    resolve_style_id as upstream_resolve_style_id,
    run_style_flags,
    run_style_font_refs,
    run_style_height,
)

_FONT_REF_KEYS = (
    "hangul",
    "latin",
    "hanja",
    "japanese",
    "other",
    "symbol",
    "user",
)
_FONT_FACE_LANGS = {
    "HANGUL": "hangul",
    "LATIN": "latin",
    "HANJA": "hanja",
    "JAPANESE": "japanese",
    "OTHER": "other",
    "SYMBOL": "symbol",
    "USER": "user",
}
_DEFAULT_TEXT_COLOR = "#000000"
_DEFAULT_CHAR_HEIGHT = "1000"


def _append_child(parent: ET.Element, tag: str, attrs: dict[str, str] | None = None) -> ET.Element:
    return append_xml_child(parent, tag, attrs)


def _iter_unique_styles(doc: HwpxDocument):
    yield from iter_unique_styles(doc)


def _normalize_color(color: str | None) -> str | None:
    return normalize_hex_color(color)


def _normalize_font_size(font_size: float | None) -> str | None:
    return normalize_font_size(font_size)


def _run_style_flags(run_style: Any) -> tuple[bool, bool, bool]:
    return run_style_flags(run_style)


def _run_style_height(run_style: Any) -> str | None:
    return run_style_height(run_style)


def _run_style_font_refs(run_style: Any) -> dict[str, str]:
    return run_style_font_refs(run_style)


def _element_flags(element: ET.Element) -> tuple[bool, bool, bool]:
    return element_style_flags(element)


def _element_font_refs(element: ET.Element) -> dict[str, str]:
    return element_font_refs(element)


def _char_style_matches(
    run_style: Any,
    *,
    flags: tuple[bool, bool, bool],
    color: str,
    height: str,
    font_refs: dict[str, str],
) -> bool:
    return char_style_matches(run_style, flags=flags, color=color, height=height, font_refs=font_refs)


def _ensure_font_face_refs(header: Any, font_name: str) -> dict[str, str]:
    return ensure_font_face_refs(header, font_name)


def resolve_style_id(doc: HwpxDocument, style: str | None) -> str | None:
    return upstream_resolve_style_id(doc, style)


def _ensure_char_style(
    doc: HwpxDocument,
    *,
    base_char_pr_id: str | int | None,
    bold: bool | None = None,
    italic: bool | None = None,
    underline: bool | None = None,
    font_size: float | None = None,
    font_name: str | None = None,
    color: str | None = None,
) -> str:
    return ensure_char_style(
        doc,
        base_char_pr_id=base_char_pr_id,
        bold=bold,
        italic=italic,
        underline=underline,
        font_size=font_size,
        font_name=font_name,
        color=color,
    )


def split_run_for_format(
    run_obj: HwpxOxmlRun, local_start: int, local_end: int, char_pr_id_ref: str
) -> None:
    """Give ``run.text[local_start:local_end]`` the character style *char_pr_id_ref*.

    The run is divided into at most three runs (before / target / after). Text
    is moved, never copied: ``hp:secPr``, ``hp:ctrl`` and the ``hp:tab`` /
    ``hp:lineBreak`` inside ``hp:t`` each remain exactly once. The paragraph's
    line layout cache is dropped whenever the run is divided or restyled.
    """

    length = len(run_obj.text or "")
    if length == 0:
        return

    local_start = max(0, min(local_start, length))
    local_end = max(0, min(local_end, length))
    if local_start >= local_end:
        return

    if local_start == 0 and local_end == length:
        run_obj.char_pr_id_ref = char_pr_id_ref
        return

    paragraph = run_obj.paragraph
    runs = list(paragraph.runs)
    if run_obj not in runs:
        return
    # The run's first character in paragraph.text (a tab or a line break is one character there too).
    base = sum(len(run.text or "") for run in runs[: runs.index(run_obj)])

    # python-hwpx's paragraph.split_run cuts only text: hp:secPr, hp:ctrl and objects stay on one side.
    # Cut the far end first so the near offset still addresses the left piece.
    if local_end < length:
        paragraph.split_run(base + local_end)
    target = paragraph.split_run(base + local_start) if local_start > 0 else run_obj
    target.char_pr_id_ref = char_pr_id_ref
    paragraph.clear_layout_cache()


# Kept as the historical private name used inside this module.
_split_run = split_run_for_format


def _paragraph_length(paragraph: HwpxOxmlParagraph) -> int:
    return sum(len(run.text or "") for run in paragraph.runs)


def _default_base_style_id(doc: HwpxDocument) -> str:
    return default_base_style_id(doc)
    for candidate in ("1", "본문", "Body", "0", "바탕글", "Normal"):
        try:
            resolved = resolve_style_id(doc, candidate)
        except ValueError:
            continue
        if resolved is not None:
            return resolved

    for style in _iter_unique_styles(doc):
        raw_id = getattr(style, "raw_id", None)
        if raw_id:
            return raw_id
        if getattr(style, "id", None) is not None:
            return str(style.id)

    raise RuntimeError("document does not contain any styles")


def format_text_range(
    doc: HwpxDocument,
    paragraph_index: int,
    start_pos: int,
    end_pos: int,
    bold: bool = None,
    italic: bool = None,
    underline: bool = None,
    font_size: float = None,
    font_name: str = None,
    color: str = None,
) -> None:
    """Apply character formatting to a text span within a paragraph."""
    if all(value is None for value in (bold, italic, underline, font_size, font_name, color)):
        return
    if paragraph_index < 0 or paragraph_index >= len(doc.paragraphs):
        raise ValueError(f"invalid paragraph_index: {paragraph_index}")
    if start_pos < 0 or end_pos < 0 or end_pos < start_pos:
        raise ValueError("start_pos/end_pos are out of range")
    if start_pos == end_pos:
        return

    paragraph = doc.paragraphs[paragraph_index]
    total_length = _paragraph_length(paragraph)
    if total_length == 0 or start_pos >= total_length:
        return
    span_end = min(end_pos, total_length)

    cursor = start_pos
    while cursor < span_end:
        runs = list(paragraph.runs)
        offset = 0
        target: tuple[HwpxOxmlRun, int, int, int] | None = None
        for candidate in runs:
            text = candidate.text or ""
            length = len(text)
            run_start = offset
            run_end = run_start + length
            offset = run_end
            if length == 0 or run_end <= cursor:
                continue
            if run_start >= span_end:
                break
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

        char_id = _ensure_char_style(
            doc,
            base_char_pr_id=run_obj.char_pr_id_ref,
            bold=bold,
            italic=italic,
            underline=underline,
            font_size=font_size,
            font_name=font_name,
            color=color,
        )
        _split_run(run_obj, local_start, local_end, char_id)
        cursor = min(span_end, run_end)


def create_style_in_doc(
    doc: HwpxDocument,
    style_name: str,
    bold: bool = None,
    italic: bool = None,
    font_size: float = None,
    font_name: str = None,
    color: str = None,
) -> dict[str, Any]:
    """Create a paragraph style backed by a stable upstream charPr definition."""
    name = (style_name or "").strip()
    if not name:
        raise ValueError("style_name cannot be empty")
    if not doc.parts.headers:
        raise RuntimeError("document does not contain any headers to host styles")

    for style in _iter_unique_styles(doc):
        if name not in {style.name, style.eng_name}:
            continue
        style_id = getattr(style, "raw_id", None) or str(style.id)
        char_ref = style.char_pr_id_ref
        para_ref = style.para_pr_id_ref
        return {
            "style_id": style_id,
            "style_name": style.name or name,
            "created": False,
            "char_pr_id_ref": None if char_ref is None else str(char_ref),
            "para_pr_id_ref": None if para_ref is None else str(para_ref),
        }

    base_style_id = _default_base_style_id(doc)
    base_style = doc.styles.get(base_style_id)
    if base_style is None:
        raise RuntimeError(f"failed to resolve base style id: {base_style_id}")

    base_char_ref = getattr(base_style, "char_pr_id_ref", None)
    char_ref: str | None
    if any(value is not None for value in (bold, italic, font_size, font_name, color)):
        char_ref = _ensure_char_style(
            doc,
            base_char_pr_id=None if base_char_ref is None else str(base_char_ref),
            bold=bold,
            italic=italic,
            underline=None,
            font_size=font_size,
            font_name=font_name,
            color=color,
        )
    else:
        char_ref = None if base_char_ref is None else str(base_char_ref)

    para_ref = base_style.para_pr_id_ref
    style_id = doc.styles.ensure_style(
        name,
        style_type=base_style.type,
        eng_name=name,
        para_pr_id_ref=para_ref,
        char_pr_id_ref=char_ref,
        lang_id=base_style.lang_id,
        lock_form=base_style.lock_form,
    )
    doc.styles.ensure_style(name, next_style_id_ref=style_id)

    return {
        "style_id": style_id,
        "style_name": name,
        "created": True,
        "char_pr_id_ref": char_ref,
        "para_pr_id_ref": None if para_ref is None else str(para_ref),
    }


def list_styles_in_doc(doc: HwpxDocument) -> list[dict[str, str | None]]:
    """Return styles defined in the document."""
    styles: list[dict[str, str | None]] = []
    seen: set[int] = set()
    for style in primary_header(doc).styles.values():
        # The header maps both the raw and the normalized id to one style.
        if id(style) in seen:
            continue
        seen.add(id(style))
        para_ref, char_ref = style.para_pr_id_ref, style.char_pr_id_ref
        styles.append(
            {
                "id": style.raw_id,
                "name": style.name,
                "eng_name": style.eng_name,
                "type": style.type,
                "para_pr_id_ref": None if para_ref is None else str(para_ref),
                "char_pr_id_ref": None if char_ref is None else str(char_ref),
            }
        )
    return styles


def outline_style_levels(doc: HwpxDocument) -> dict[str, int]:
    """스타일 id → 개요 수준 매핑을 반환한다 ("개요 N"/"Outline N" 문단 스타일)."""
    levels: dict[str, int] = {}
    for style in list_styles_in_doc(doc):
        if (style.get("type") or "").upper() == "CHAR":
            continue
        for label in (style.get("name") or "", style.get("eng_name") or ""):
            for prefix in ("개요 ", "Outline "):
                if label.startswith(prefix):
                    try:
                        level = int(label[len(prefix):].strip())
                    except ValueError:
                        continue
                    style_id = style.get("id")
                    if style_id is not None:
                        levels[str(style_id)] = min(6, max(1, level))
                    break
            if str(style.get("id")) in levels:
                break
    return levels
