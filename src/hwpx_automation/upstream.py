# SPDX-License-Identifier: Apache-2.0
# ruff: noqa: E402
"""Thin integration helpers for the upstream ``python-hwpx`` library.

Keep version-sensitive imports and non-obvious upstream calls here so the rest
of the codebase has fewer direct dependencies on internal upstream details.
"""

from __future__ import annotations

from copy import deepcopy
from os import PathLike
from typing import Any, Iterable, Literal
from xml.etree import ElementTree as ET

from .compat import patch_python_hwpx

# Compatibility patching must precede version-sensitive python-hwpx imports.
patch_python_hwpx()

from hwpx import ObjectFinder
from hwpx.document import (
    HwpxDocument,
)
from hwpx.oxml.memo import HwpxOxmlMemo
from hwpx.oxml.paragraph import HwpxOxmlParagraph
from hwpx.oxml.run import HwpxOxmlRun
from hwpx.oxml.table import HwpxOxmlTable
from hwpx.opc.package import HwpxPackage
from hwpx.templates import blank_document_bytes
from hwpx.tools.text_extractor import AnnotationOptions, TextExtractor
from hwpx.tools.validator import ValidationReport, validate_document
from hwpx.oxml.namespaces import HH as HH_NS, HP as HP_NS

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
_PATHOLOGICAL_CHAR_SPACING_LIMIT = -40


def open_document(source: str | PathLike[str] | Any) -> HwpxDocument:
    return HwpxDocument.open(source)


def new_document() -> HwpxDocument:
    return HwpxDocument.new()


def blank_document_template_bytes() -> bytes:
    return blank_document_bytes()


def open_package(path: str | PathLike[str]) -> HwpxPackage:
    return HwpxPackage.open(path)


def create_text_extractor(path: str | PathLike[str]) -> TextExtractor:
    return TextExtractor(path)


def create_object_finder(path: str | PathLike[str]) -> ObjectFinder:
    return ObjectFinder(path)


def validate_document_path(path: str | PathLike[str]) -> ValidationReport:
    return validate_document(path)


def export_document(document: HwpxDocument, output_format: Literal["text", "html", "markdown"]) -> str:
    if output_format == "text":
        return document.text.plain()
    if output_format == "html":
        return document.text.html()
    if output_format == "markdown":
        return document.text.markdown()
    raise ValueError(f"unsupported export format: {output_format}")


def default_cell_width() -> int:
    """Return the upstream default table-cell width.

    ``python-hwpx`` currently stores this as the private module constant
    ``hwpx.oxml.document._DEFAULT_CELL_WIDTH``. Centralize that lookup here so a
    future upstream change only touches one place downstream.
    """

    try:  # pragma: no branch - single lookup with defensive fallback
        from hwpx.oxml import document as hwpx_document_module

        return int(getattr(hwpx_document_module, "_DEFAULT_CELL_WIDTH", 7200))
    except Exception:  # pragma: no cover - fallback only used if upstream internals move
        return 7200


def append_xml_child(parent: ET.Element, tag: str, attrs: dict[str, str] | None = None) -> ET.Element:
    payload = dict(attrs or {})
    try:
        return ET.SubElement(parent, tag, payload)
    except TypeError:
        maker = getattr(parent, "makeelement", None)
        if not callable(maker):
            raise
        child = maker(tag, payload)
        parent.append(child)
        return child


def primary_header(document: HwpxDocument) -> Any:
    if not document.parts.headers:
        raise RuntimeError("document does not contain any headers to host styles")
    return document.parts.headers[0]


def style_identifier(style: Any) -> str | None:
    raw_id = getattr(style, "raw_id", None)
    if raw_id:
        return raw_id
    identifier = getattr(style, "id", None)
    if identifier is not None:
        return str(identifier)
    return None


def iter_unique_styles(document: HwpxDocument):
    seen: set[str] = set()
    for style in document.styles.values():
        style_id = style_identifier(style)
        if style_id is None or style_id in seen:
            continue
        seen.add(style_id)
        yield style


def resolve_style_id(document: HwpxDocument, style: str | None) -> str | None:
    if style is None:
        return None
    value = style.strip()
    if not value:
        return None

    resolved = document.styles.get(value)
    if resolved is not None:
        style_id = style_identifier(resolved)
        if style_id is not None:
            return style_id

    for candidate in iter_unique_styles(document):
        if value not in {candidate.name, candidate.eng_name}:
            continue
        style_id = style_identifier(candidate)
        if style_id is not None:
            return style_id

    raise ValueError(f"unknown style reference: {value}")


def normalize_hex_color(color: str | None, *, field_name: str = "color") -> str | None:
    if color is None:
        return None
    value = color.strip()
    if not value:
        return None
    if not value.startswith("#"):
        value = "#" + value
    if len(value) != 7 or any(ch not in "0123456789abcdefABCDEF#" for ch in value):
        raise ValueError(f"{field_name} must be a 6-digit hexadecimal value")
    return value.upper()


def normalize_font_size(font_size: float | None) -> str | None:
    if font_size is None:
        return None
    if font_size <= 0:
        raise ValueError("font_size must be greater than 0")
    return str(int(round(font_size * 100)))


def run_style_flags(run_style: Any) -> tuple[bool, bool, bool]:
    if run_style is None:
        return False, False, False
    children = getattr(run_style, "child_attributes", {})
    underline_attrs = children.get("underline")
    underline = False
    if underline_attrs is not None:
        underline = underline_attrs.get("type", "").upper() != "NONE"
    return "bold" in children, "italic" in children, underline


def run_style_height(run_style: Any) -> str | None:
    if run_style is None:
        return None
    return getattr(run_style, "attributes", {}).get("height")


def run_style_font_refs(run_style: Any) -> dict[str, str]:
    if run_style is None:
        return {}
    refs = dict(getattr(run_style, "child_attributes", {}).get("fontRef", {}))
    return {key: str(value) for key, value in refs.items() if key in _FONT_REF_KEYS}


def element_style_flags(element: ET.Element) -> tuple[bool, bool, bool]:
    underline_node = element.find(f"{HH_NS}underline")
    underline = False
    if underline_node is not None:
        underline = underline_node.get("type", "").upper() != "NONE"
    return (
        element.find(f"{HH_NS}bold") is not None,
        element.find(f"{HH_NS}italic") is not None,
        underline,
    )


def element_font_refs(element: ET.Element) -> dict[str, str]:
    font_ref = element.find(f"{HH_NS}fontRef")
    if font_ref is None:
        return {}
    return {key: str(value) for key, value in font_ref.attrib.items() if key in _FONT_REF_KEYS}


def char_style_matches(
    run_style: Any,
    *,
    flags: tuple[bool, bool, bool],
    color: str,
    height: str,
    font_refs: dict[str, str],
) -> bool:
    if run_style_flags(run_style) != flags:
        return False
    if ((run_style.text_color() if run_style is not None else None) or _DEFAULT_TEXT_COLOR).upper() != color:
        return False
    if (run_style_height(run_style) or _DEFAULT_CHAR_HEIGHT) != height:
        return False
    current_font_refs = run_style_font_refs(run_style)
    for key in _FONT_REF_KEYS:
        if current_font_refs.get(key) != font_refs.get(key):
            return False
    return True


def _ref_list_element(header: Any) -> ET.Element:
    element = header.element.find(f"{HH_NS}refList")
    if element is None:
        raise RuntimeError("document header does not expose a refList element")
    return element


def _fontfaces_element(header: Any) -> ET.Element:
    ref_list = _ref_list_element(header)
    fontfaces = ref_list.find(f"{HH_NS}fontfaces")
    if fontfaces is None:
        raise RuntimeError("document header does not expose fontfaces")
    return fontfaces


def _find_fontface_bucket(fontfaces: ET.Element, lang: str) -> ET.Element | None:
    for bucket in fontfaces.findall(f"{HH_NS}fontface"):
        if (bucket.get("lang") or "").upper() == lang:
            return bucket
    return None


def _next_font_id(bucket: ET.Element) -> str:
    numeric_ids: list[int] = []
    for child in bucket.findall(f"{HH_NS}font"):
        raw_id = child.get("id")
        if raw_id is None:
            continue
        try:
            numeric_ids.append(int(raw_id))
        except ValueError:
            continue
    return "0" if not numeric_ids else str(max(numeric_ids) + 1)


def ensure_font_face_refs(header: Any, font_name: str) -> dict[str, str]:
    name = (font_name or "").strip()
    if not name:
        raise ValueError("font_name cannot be empty")

    fontfaces = _fontfaces_element(header)
    refs: dict[str, str] = {}
    changed = False

    for lang, ref_key in _FONT_FACE_LANGS.items():
        bucket = _find_fontface_bucket(fontfaces, lang)
        if bucket is None:
            bucket = append_xml_child(fontfaces, f"{HH_NS}fontface", {"lang": lang, "fontCnt": "0"})
            changed = True

        font_element = None
        for candidate in bucket.findall(f"{HH_NS}font"):
            if (candidate.get("face") or "").strip() == name:
                font_element = candidate
                break

        if font_element is None:
            font_element = append_xml_child(
                bucket,
                f"{HH_NS}font",
                {
                    "id": _next_font_id(bucket),
                    "face": name,
                    "type": "TTF",
                    "isEmbedded": "0",
                },
            )
            bucket.set("fontCnt", str(len(bucket.findall(f"{HH_NS}font"))))
            changed = True

        font_id = font_element.get("id")
        if not font_id:
            raise RuntimeError("fontface entry is missing an id")
        refs[ref_key] = font_id

    if changed:
        header.mark_dirty()
    return refs


def ensure_char_style(
    document: HwpxDocument,
    *,
    base_char_pr_id: str | int | None,
    bold: bool | None = None,
    italic: bool | None = None,
    underline: bool | None = None,
    font_size: float | None = None,
    font_name: str | None = None,
    color: str | None = None,
) -> str:
    """Return a ``charPr`` id matching the requested formatting.

    This prefers the public-ish upstream helper ``document.styles.ensure_run()``
    when only bold/italic/underline flags are involved. When color, font size,
    or font family overrides are requested, we fall back to the header-level
    ``ensure_char_property()`` hook so downstream behavior stays aligned with the
    current upstream document engine.
    """

    base_style = document.styles.char_property(base_char_pr_id)
    base_flags = run_style_flags(base_style)
    target_flags = (
        base_flags[0] if bold is None else bool(bold),
        base_flags[1] if italic is None else bool(italic),
        base_flags[2] if underline is None else bool(underline),
    )

    if font_size is None and font_name is None and color is None:
        return document.styles.ensure_run(
            bold=target_flags[0],
            italic=target_flags[1],
            underline=target_flags[2],
            base_char_pr_id=base_char_pr_id,
        )

    header = primary_header(document)
    target_color = normalize_hex_color(color) or (
        (base_style.text_color() if base_style is not None else None) or _DEFAULT_TEXT_COLOR
    ).upper()
    target_height = normalize_font_size(font_size) or run_style_height(base_style) or _DEFAULT_CHAR_HEIGHT
    target_font_refs = {
        key: value for key, value in run_style_font_refs(base_style).items() if key in _FONT_REF_KEYS
    }
    if not target_font_refs:
        target_font_refs = {key: "0" for key in _FONT_REF_KEYS}
    if font_name is not None:
        target_font_refs.update(ensure_font_face_refs(header, font_name))

    if base_char_pr_id is not None and char_style_matches(
        base_style,
        flags=target_flags,
        color=target_color,
        height=target_height,
        font_refs=target_font_refs,
    ) and (
        not target_flags[2]
        or base_style is not None
        and base_style.child_attributes.get("underline", {}).get("type", "").upper()
        in {"BOTTOM", "CENTER", "TOP"}
    ):
        return str(base_char_pr_id)

    def predicate(element: ET.Element) -> bool:
        if element_style_flags(element) != target_flags:
            return False
        if target_flags[2]:
            underline_element = element.find(f"{HH_NS}underline")
            if underline_element is None or underline_element.get("type", "").upper() not in {"BOTTOM", "CENTER", "TOP"}:
                return False
        if (element.get("textColor", _DEFAULT_TEXT_COLOR) or _DEFAULT_TEXT_COLOR).upper() != target_color:
            return False
        if element.get("height", _DEFAULT_CHAR_HEIGHT) != target_height:
            return False
        existing_font_refs = element_font_refs(element)
        for key in _FONT_REF_KEYS:
            if existing_font_refs.get(key) != target_font_refs.get(key):
                return False
        return True

    def modifier(element: ET.Element) -> None:
        underline_nodes = list(element.findall(f"{HH_NS}underline"))
        existing_underline = dict(underline_nodes[0].attrib) if underline_nodes else {}

        for child in list(element.findall(f"{HH_NS}bold")):
            element.remove(child)
        for child in list(element.findall(f"{HH_NS}italic")):
            element.remove(child)
        for child in underline_nodes:
            element.remove(child)

        if target_flags[0]:
            append_xml_child(element, f"{HH_NS}bold")
        if target_flags[1]:
            append_xml_child(element, f"{HH_NS}italic")

        underline_attrs = dict(existing_underline)
        underline_attrs.setdefault("shape", existing_underline.get("shape", "SOLID"))
        underline_attrs["color"] = underline_attrs.get("color", target_color) or target_color
        if target_flags[2]:
            # OWPML uses type for underline position and shape for line style.
            # SOLID in type can round-trip through our reader but is invisible
            # in Hancom. Preserve a valid existing position when present.
            if underline_attrs.get("type", "").upper() not in {"BOTTOM", "CENTER", "TOP"}:
                underline_attrs["type"] = "BOTTOM"
            underline_attrs["color"] = target_color
        else:
            underline_attrs["type"] = "NONE"
        append_xml_child(element, f"{HH_NS}underline", underline_attrs)

        element.set("textColor", target_color)
        element.set("height", target_height)

        font_ref = element.find(f"{HH_NS}fontRef")
        if font_ref is None:
            font_ref = append_xml_child(element, f"{HH_NS}fontRef")
        for key in _FONT_REF_KEYS:
            value = target_font_refs.get(key)
            if value is not None:
                font_ref.set(key, str(value))

    char_element = header.ensure_char_property(
        predicate=predicate,
        modifier=modifier,
        base_char_pr_id=base_char_pr_id,
    )
    char_id = char_element.get("id")
    if not char_id:
        raise RuntimeError("char property does not expose an identifier")
    return char_id


def _char_property_element(
    document: HwpxDocument,
    char_pr_id_ref: str | int | None,
) -> tuple[Any, ET.Element] | None:
    if char_pr_id_ref is None:
        return None
    target = str(char_pr_id_ref).strip()
    if not target:
        return None

    for header in document.parts.headers:
        ref_list = header.element.find(f"{HH_NS}refList")
        if ref_list is None:
            continue
        char_properties = ref_list.find(f"{HH_NS}charProperties")
        if char_properties is None:
            continue
        for element in char_properties.findall(f"{HH_NS}charPr"):
            if (element.get("id") or "").strip() == target:
                return header, element
    return None


def _spacing_values(element: ET.Element | None) -> dict[str, int]:
    if element is None:
        return {}
    spacing = element.find(f"{HH_NS}spacing")
    if spacing is None:
        return {}

    values: dict[str, int] = {}
    for key in _FONT_REF_KEYS:
        raw = spacing.get(key)
        if raw is None:
            continue
        try:
            values[key] = int(raw)
        except ValueError:
            continue
    return values


def _safe_spacing_fallback_refs(
    document: HwpxDocument,
    paragraph: Any | None,
    explicit_ref: str | int | None,
) -> list[str]:
    refs: list[str] = []

    def append(value: str | int | None) -> None:
        if value is None:
            return
        normalized = str(value).strip()
        if normalized and normalized not in refs:
            refs.append(normalized)

    append(explicit_ref)
    if paragraph is not None:
        style = document.styles.get(getattr(paragraph, "style_id_ref", None))
        append(getattr(style, "char_pr_id_ref", None))
        append(getattr(paragraph, "char_pr_id_ref", None))

    style_zero_ref: str | int | None = None
    for style in iter_unique_styles(document):
        style_id = style_identifier(style)
        name = str(getattr(style, "name", None) or "").strip()
        eng_name = str(getattr(style, "eng_name", None) or "").strip().lower()
        char_ref = getattr(style, "char_pr_id_ref", None)
        if name in {"바탕글", "본문"} or eng_name in {"normal", "body"}:
            append(char_ref)
        if style_id == "0":
            style_zero_ref = char_ref
    append(style_zero_ref)
    append("0")
    return refs


def _element_signature(element: ET.Element) -> bytes:
    clone = deepcopy(element)
    clone.attrib.pop("id", None)
    return ET.tostring(clone, encoding="utf-8")


def _run_element(run: Any) -> ET.Element | None:
    element = getattr(run, "element", None)
    if element is not None:
        return element
    if hasattr(run, "get") and hasattr(run, "set"):
        return run
    return None


def repair_pathological_text_spacing(
    document: HwpxDocument,
    *,
    paragraph: Any | None = None,
    runs: Iterable[Any] | None = None,
    fallback_char_pr_id: str | int | None = None,
) -> int:
    """Remap touched text runs whose character spacing would over-print glyphs.

    Some form templates use ``hh:spacing=-50`` on short placeholder runs.  If a
    replacement or newly-added paragraph blindly keeps that ``charPr``, Hancom
    renders normal text with roughly half-width glyph advance and the letters
    overlap.  Only the touched runs are remapped: the source ``charPr`` remains
    byte-for-byte intact, while a deduplicated clone changes only pathological
    spacing values (``<= -40``) to a safe paragraph/body-style fallback.
    """

    selected_runs = list(runs if runs is not None else (getattr(paragraph, "runs", None) or []))
    if not selected_runs:
        return 0

    fallback_values: list[dict[str, int]] = []
    for fallback_ref in _safe_spacing_fallback_refs(document, paragraph, fallback_char_pr_id):
        found = _char_property_element(document, fallback_ref)
        if found is not None:
            fallback_values.append(_spacing_values(found[1]))

    remapped = 0
    replacements_by_ref: dict[str, str] = {}
    for run in selected_runs:
        element = _run_element(run)
        if element is None:
            continue
        base_ref = (element.get("charPrIDRef") or "").strip()
        if not base_ref:
            continue

        found = _char_property_element(document, base_ref)
        if found is None:
            continue
        header, base_element = found
        base_spacing = _spacing_values(base_element)
        unsafe_keys = [
            key
            for key, value in base_spacing.items()
            if value <= _PATHOLOGICAL_CHAR_SPACING_LIMIT
        ]
        if not unsafe_keys:
            continue

        target_ref = replacements_by_ref.get(base_ref)
        if target_ref is None:
            target_values: dict[str, int] = {}
            for key in unsafe_keys:
                safe_value = 0
                for candidate in fallback_values:
                    value = candidate.get(key, 0)
                    if value > _PATHOLOGICAL_CHAR_SPACING_LIMIT:
                        safe_value = value
                        break
                target_values[key] = safe_value

            target_element = deepcopy(base_element)
            target_element.attrib.pop("id", None)
            target_spacing = target_element.find(f"{HH_NS}spacing")
            if target_spacing is None:  # pragma: no cover - unsafe keys imply spacing exists
                target_spacing = append_xml_child(target_element, f"{HH_NS}spacing")
            for key, value in target_values.items():
                target_spacing.set(key, str(value))
            target_signature = _element_signature(target_element)

            def predicate(candidate: ET.Element) -> bool:
                return _element_signature(candidate) == target_signature

            def modifier(candidate: ET.Element) -> None:
                spacing = candidate.find(f"{HH_NS}spacing")
                if spacing is None:  # pragma: no cover - cloned unsafe style has spacing
                    spacing = append_xml_child(candidate, f"{HH_NS}spacing")
                for key, value in target_values.items():
                    spacing.set(key, str(value))

            safe_element = header.ensure_char_property(
                predicate=predicate,
                modifier=modifier,
                base_char_pr_id=base_ref,
            )
            target_ref = safe_element.get("id")
            if not target_ref:  # pragma: no cover - upstream guarantees an id
                raise RuntimeError("safe character property does not expose an identifier")
            replacements_by_ref[base_ref] = target_ref

        if hasattr(run, "char_pr_id_ref"):
            run.char_pr_id_ref = target_ref
        else:
            element.set("charPrIDRef", target_ref)
            section = getattr(paragraph, "section", None)
            if section is not None and hasattr(section, "mark_dirty"):
                section.mark_dirty()
        remapped += 1

    return remapped


def document_styles_element(document: HwpxDocument) -> ET.Element:
    """Return the raw ``<hh:styles>`` element for the primary header.

    This currently relies on the private upstream helper ``_styles_element()``
    because ``python-hwpx`` does not expose a public style-creation API yet.
    """

    header = primary_header(document)
    styles_element = header._styles_element()
    if styles_element is None:
        raise RuntimeError("document header does not expose styles")
    return styles_element


def style_element_by_id(styles_element: ET.Element, style_id: str) -> ET.Element | None:
    for style_element in styles_element.findall(f"{HH_NS}style"):
        raw_id = style_element.get("id")
        if raw_id == style_id:
            return style_element
        try:
            if raw_id is not None and str(int(raw_id)) == style_id:
                return style_element
        except ValueError:
            continue
    return None


def next_numeric_style_id(styles_element: ET.Element) -> str:
    numeric_ids: list[int] = []
    for style_element in styles_element.findall(f"{HH_NS}style"):
        raw_id = style_element.get("id")
        if raw_id is None:
            continue
        try:
            numeric_ids.append(int(raw_id))
        except ValueError:
            continue
    return "0" if not numeric_ids else str(max(numeric_ids) + 1)


def update_styles_item_count(styles_element: ET.Element) -> None:
    styles_element.set("itemCnt", str(len(styles_element.findall(f"{HH_NS}style"))))


def default_base_style_id(document: HwpxDocument) -> str:
    for candidate in ("1", "본문", "Body", "0", "바탕글", "Normal"):
        try:
            resolved = resolve_style_id(document, candidate)
        except ValueError:
            continue
        if resolved is not None:
            return resolved

    for style in iter_unique_styles(document):
        style_id = style_identifier(style)
        if style_id is not None:
            return style_id

    raise RuntimeError("document does not contain any styles")


__all__ = [
    "AnnotationOptions",
    "HH_NS",
    "HP_NS",
    "HwpxDocument",
    "HwpxOxmlMemo",
    "HwpxOxmlParagraph",
    "HwpxOxmlRun",
    "HwpxOxmlTable",
    "ValidationReport",
    "append_xml_child",
    "blank_document_template_bytes",
    "char_style_matches",
    "create_object_finder",
    "create_text_extractor",
    "default_base_style_id",
    "default_cell_width",
    "document_styles_element",
    "element_font_refs",
    "element_style_flags",
    "ensure_char_style",
    "ensure_font_face_refs",
    "export_document",
    "iter_unique_styles",
    "new_document",
    "normalize_font_size",
    "normalize_hex_color",
    "open_document",
    "open_package",
    "primary_header",
    "resolve_style_id",
    "run_style_flags",
    "run_style_font_refs",
    "run_style_height",
    "style_element_by_id",
    "style_identifier",
    "update_styles_item_count",
    "validate_document_path",
    "next_numeric_style_id",
]
