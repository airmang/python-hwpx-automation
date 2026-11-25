# SPDX-License-Identifier: Apache-2.0
# ruff: noqa: E402
"""Thin integration helpers for the upstream ``python-hwpx`` library.

Keep version-sensitive imports and non-obvious upstream calls here so the rest
of the codebase has fewer direct dependencies on internal upstream details.
"""

from __future__ import annotations

import hashlib
import json
from os import PathLike
from pathlib import Path
from typing import Any, Iterable, Literal
from xml.etree import ElementTree as ET
from zipfile import ZipFile

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


def content_seed(data: bytes) -> int:
    """The id seed of a document made from *data*: the first 8 hex digits of its sha256.

    Every path that rewrites a given file opens it with this seed (python-hwpx ``open(seed=)``), so
    the same file and the same request write the same bytes: the paragraphs, objects and copies
    made on the way get the same ids. Only ids follow it; the clock (``now=``) is left alone.
    """

    return int(hashlib.sha256(data).hexdigest()[:8], 16)


def source_seed(source: object) -> int | None:
    """:func:`content_seed` of what *source* holds (bytes, a file path, a stream's value); None
    for anything else (an opened package), which then opens as before."""

    if isinstance(source, (bytes, bytearray)):
        return content_seed(bytes(source))
    if isinstance(source, (str, PathLike)):
        path = Path(source)
        return content_seed(path.read_bytes()) if path.is_file() else None
    getvalue = getattr(source, "getvalue", None)
    if callable(getvalue):
        value = getvalue()
        if isinstance(value, (bytes, bytearray)):
            return content_seed(bytes(value))
    return None


def request_seed(request: object) -> int:
    """:func:`content_seed` of a request with no input file (a plan, a Markdown text, a spec):
    its canonical JSON (sorted keys; a value JSON cannot hold is written as its ``repr``)."""

    if isinstance(request, str):
        data = request.encode("utf-8")
    else:
        data = json.dumps(
            request, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=repr
        ).encode("utf-8")
    return content_seed(data)


def open_seeded_input(source: str | PathLike[str] | Any) -> HwpxDocument:
    """``HwpxDocument.open`` of an input to rewrite, seeded from its bytes (:func:`source_seed`)."""

    seed = source_seed(source)
    if seed is None:
        return HwpxDocument.open(source)
    return HwpxDocument.open(source, seed=seed)


def open_document(source: str | PathLike[str] | Any) -> HwpxDocument:
    return open_seeded_input(source)


# HWP 5.0 (.hwp) files are OLE2 compound files; HWPX files are ZIP packages.
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def native_hwp5_supported() -> bool:
    """Whether the installed python-hwpx opens and writes ``.hwp`` itself (6.6.0+)."""

    return hasattr(HwpxDocument, "conversion_report")


def is_hwp5_source(source: str | PathLike[str] | bytes) -> bool:
    """Whether *source* holds an HWP 5.0 file, judged by its leading bytes."""

    if isinstance(source, bytes):
        return source[:8] == _OLE2_MAGIC
    try:
        with open(source, "rb") as stream:
            return stream.read(8) == _OLE2_MAGIC
    except OSError:
        return False


def is_hwp5_target(path: str | PathLike[str]) -> bool:
    """Whether saving to *path* writes HWP 5.0; the extension picks the format."""

    return str(path).lower().endswith(".hwp")


def hwp5_conversion_report(document: HwpxDocument) -> dict[str, dict[str, int]] | None:
    """What opening an ``.hwp`` left out of the model; None for an HWPX source."""

    report = getattr(document, "conversion_report", None)
    if report is None:
        return None
    return {"unconverted": dict(report.unconverted), "dropped": dict(report.dropped)}


def hwp5_document_bytes(document: HwpxDocument) -> bytes:
    """Serialize *document* as HWP 5.0; core raises ``Hwp5Error`` before writing anything."""

    return document.to_bytes(format="hwp")


def hwpx_view_bytes(source: str | PathLike[str] | bytes) -> bytes:
    """The HWPX package of the document model an ``.hwp`` source opens to."""

    document = HwpxDocument.open(source)
    try:
        return document.to_bytes()
    finally:
        document.close()


from .save_dates import (  # noqa: E402 - re-exported: the save-date helpers live apart (light layer)
    date_new_document,
    fixed_save_time,
    same_but_save_dates,
    save_time,
    stamp_save_dates,
)


def new_document(*, seed: int | None = None) -> HwpxDocument:
    """A new document (6.x layout: core 7.0 changed the default first line). With *seed*
    (:func:`request_seed` of the request) the ids it gets are the same each time. Made now
    (:func:`date_new_document`)."""

    if seed is None:
        document = HwpxDocument.new(empty_first_line=True)
    else:
        document = HwpxDocument.new(empty_first_line=True, seed=seed)
    date_new_document(document)
    return document


def blank_document_template_bytes() -> bytes:
    return blank_document_bytes()


def open_package(path: str | PathLike[str]) -> HwpxPackage:
    return HwpxPackage.open(path)


def create_text_extractor(path: str | PathLike[str] | ZipFile) -> TextExtractor:
    return TextExtractor(path)


def create_object_finder(path: str | PathLike[str] | ZipFile) -> ObjectFinder:
    return ObjectFinder(path)


def validate_document_path(path: str | PathLike[str]) -> ValidationReport:
    return validate_document(path)


def export_document(document: HwpxDocument, output_format: Literal["text", "html", "markdown"]) -> str:
    if output_format == "text":
        return document.text.plain()
    if output_format == "html":
        from .markdown import to_html

        return to_html(document)
    if output_format == "markdown":
        from .markdown import to_markdown

        return to_markdown(document)
    raise ValueError(f"unsupported export format: {output_format}")


def border_width_mm(width: Any) -> Any:
    """A 6.x border width (``"0.12 mm"``, ``"1mm"``, a number) as the millimetres python-hwpx
    7.0 takes (``border_width_mm=``).

    6.x wrote a width that is not one of Hancom's as the nearest of them (the thicker when
    halfway: ``"0.45 mm"`` drew 0.5 mm); 7.0 refuses such a width, so the nearest is taken
    here and the tools keep drawing what they drew. ``None`` or ``""`` is the 0.12 mm 6.x
    fell back to; a value that is not a positive width in mm is passed on as it is, so core
    refuses it with ``style-line-width-invalid`` as before.
    """

    from decimal import Decimal, InvalidOperation

    # Hancom's line widths in mm; python-hwpx refuses any other. Snapping to the
    # nearest is this package's 6.x compatibility, not the engine's.
    from hwpx.oxml.utils import LINE_WIDTHS_MM

    if width is None or width == "":
        return 0.12
    if isinstance(width, bool):
        return width
    text = str(width).strip().lower()
    number = (text[:-2] if text.endswith("mm") else text).strip()
    try:
        millimetres = Decimal(number)
    except InvalidOperation:
        return width
    if not millimetres.is_finite() or millimetres <= 0:
        return width
    nearest = min(
        (Decimal(str(listed)) for listed in LINE_WIDTHS_MM),
        key=lambda listed: (abs(listed - millimetres), -listed),
    )
    return float(nearest)


def section_index_of(document: HwpxDocument, item: Any) -> int | None:
    """The place in ``document.sections`` of the section holding *item* (a picture,
    equation, shape or table), or ``None`` when no section holds it (a master page)."""

    section = item.section
    return None if section is None else document.sections.index(section)


def sections_with_settings_not_first(document: Any) -> list[int]:
    """Indexes of the sections whose ``hp:secPr`` sits in a later paragraph than the first.

    Hancom reads a section's settings only from its first paragraph. python-hwpx
    reports this shape (``section-properties-not-first``; 6.x's
    ``section.insert_paragraphs(0, ...)`` left files that way) and, from 7.0.2, moves
    the settings to the first paragraph when the document is saved.
    """

    settings = f"{HP_NS}run/{HP_NS}secPr"
    found: list[int] = []
    sections = getattr(getattr(document, "oxml", None), "sections", None) or ()
    for index, section in enumerate(sections):
        paragraphs = section.element.findall(f"{HP_NS}p")
        if not paragraphs or paragraphs[0].find(settings) is not None:
            continue
        if any(paragraph.find(settings) is not None for paragraph in paragraphs[1:]):
            found.append(index)
    return found


def _hwpunit_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def picture_reference_payloads(document: HwpxDocument) -> list[dict[str, Any]]:
    """Every body picture as the dict python-hwpx 6.x ``doc.media.picture_references()``
    gave (``pictureIndex``, ``sectionIndex``, ``binaryItemIDRef``, ``width``, ``height``),
    in document order.

    7.0 replaced that read with ``doc.media.pictures`` (``Picture`` objects, the same
    pictures in the same order, which is also ``replace_picture``'s ``index``). The size
    is read from the picture's ``hp:sz`` as 6.x did, so a picture without one still
    reports ``None`` rather than the 0 ``Picture.width`` gives.
    """

    payloads: list[dict[str, Any]] = []
    for index, picture in enumerate(document.media.pictures):
        size = picture.element.find(f"{HP_NS}sz")
        payloads.append(
            {
                "pictureIndex": index,
                "sectionIndex": section_index_of(document, picture),
                "binaryItemIDRef": picture.item_id,
                "width": _hwpunit_or_none(size.get("width") if size is not None else None),
                "height": _hwpunit_or_none(size.get("height") if size is not None else None),
            }
        )
    return payloads


#: The unit of this package's table auto-fit (HWPUNIT, about 25.4 mm). python-hwpx
#: keeps no public default cell width (a table without ``width=`` takes the room of
#: its paragraph), so the value 6.x's private fallback had is held here.
DEFAULT_CELL_WIDTH = 7200


def default_cell_width() -> int:
    """The default table-cell width this package's auto-fit works in (HWPUNIT)."""

    return DEFAULT_CELL_WIDTH


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
    if ((run_style.color if run_style is not None else None) or _DEFAULT_TEXT_COLOR).upper() != color:
        return False
    if (run_style_height(run_style) or _DEFAULT_CHAR_HEIGHT) != height:
        return False
    current_font_refs = run_style_font_refs(run_style)
    for key in _FONT_REF_KEYS:
        if current_font_refs.get(key) != font_refs.get(key):
            return False
    return True


def ensure_font_face_refs(header: Any, font_name: str) -> dict[str, str]:
    """Declare *font_name* in every language block of *header* and return its ``hh:fontRef`` ids.

    python-hwpx's ``header.ensure_font`` declares the face in each of the seven blocks (an existing
    declaration is reused) and ``header.font_ref_for_face`` reads the id each block gives it.
    """

    name = (font_name or "").strip()
    if not name:
        raise ValueError("font_name cannot be empty")
    header.ensure_font(name)
    found = header.font_ref_for_face(name) or {}
    refs: dict[str, str] = {}
    for ref_key in _FONT_FACE_LANGS.values():
        font_id = found.get(ref_key)
        if not font_id:
            raise RuntimeError("fontface entry is missing an id")
        refs[ref_key] = font_id
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
    """Return a ``charPr`` id with the requested formatting, by python-hwpx's
    ``document.styles.ensure_run``.

    The character shape is *base_char_pr_id*'s with only the requested values changed (a flag left
    as ``None`` keeps the base's); python-hwpx reuses a character shape with the same content or
    adds one, and registers *font_name* in every language block.
    """

    base_flags = run_style_flags(document.styles.char_property(base_char_pr_id))
    changes: dict[str, Any] = {
        "bold": base_flags[0] if bold is None else bool(bold),
        "italic": base_flags[1] if italic is None else bool(italic),
        "underline": base_flags[2] if underline is None else bool(underline),
    }
    if color is not None:
        changes["color"] = normalize_hex_color(color)
        if changes["underline"]:
            # the underline takes the text colour asked for, as this tool has always drawn it
            changes["underline_color"] = changes["color"]
    if font_size is not None:
        normalize_font_size(font_size)  # refuses a size that is not above 0, as before
        changes["size"] = font_size
    if font_name is not None:
        changes["font"] = font_name  # python-hwpx gives it every language (#798)
    return document.styles.ensure_run(base_char_pr_id_ref=base_char_pr_id, **changes)


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
    byte-for-byte intact, while python-hwpx's ``document.styles.ensure_run``
    (``letter_spacing_by_lang=``) gives a character shape that differs from it only in the
    pathological spacing values (``<= -40``), set to a safe paragraph/body-style fallback.
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
        if not hasattr(run, "char_pr_id_ref"):
            continue
        base_ref = str(run.char_pr_id_ref or "").strip()
        if not base_ref:
            continue

        found = _char_property_element(document, base_ref)
        if found is None:
            continue
        base_spacing = _spacing_values(found[1])
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
                        safe_value = min(value, 100)  # 자간 is -50..100 (python-hwpx #801)
                        break
                target_values[key] = safe_value
            target_ref = document.styles.ensure_run(
                base_char_pr_id_ref=base_ref,
                letter_spacing_by_lang={key.upper(): value for key, value in target_values.items()},
            )
            replacements_by_ref[base_ref] = target_ref

        run.char_pr_id_ref = target_ref
        remapped += 1

    return remapped


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
    "date_new_document",
    "default_base_style_id",
    "default_cell_width",
    "element_font_refs",
    "element_style_flags",
    "ensure_char_style",
    "ensure_font_face_refs",
    "export_document",
    "fixed_save_time",
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
    "same_but_save_dates",
    "save_time",
    "sections_with_settings_not_first",
    "stamp_save_dates",
    "style_identifier",
    "validate_document_path",
]
