# SPDX-License-Identifier: Apache-2.0
"""Layout-oriented HTML preview rendering for HWPX packages.

This renderer is intentionally approximate: it exposes page boxes, margins,
paragraph alignment, table geometry, and table borders so agents can cheaply
inspect layout before the final Hancom viewer check.

Moved from ``hwpx.tools.layout_preview`` (python-hwpx 6.x) unchanged; it reads
the package through python-hwpx's public input guards.
"""

from __future__ import annotations

import base64
import html
import io
import re
from collections import Counter
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from hwpx import HwpxDocument, experimental
from hwpx.errors import HwpxError
from hwpx.opc.security import guard_zip_file, parse_xml_stdlib, read_member
from hwpx.oxml.section_format import PAGE_PORTRAIT
from hwpx.oxml.table_sizes import cell_margins_of
from hwpx.tools.exporter import ListLabels

from .equation_render import render_equation

_HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_HH_NS = "http://www.hancom.co.kr/hwpml/2011/head"
_HC_NS = "http://www.hancom.co.kr/hwpml/2011/core"
_HS_NS = "http://www.hancom.co.kr/hwpml/2011/section"
_HP = f"{{{_HP_NS}}}"
_HH = f"{{{_HH_NS}}}"
_HC = f"{{{_HC_NS}}}"
_HS = f"{{{_HS_NS}}}"

_HWP_UNITS_PER_MM = 7200 / 25.4

# Inline object tags (children of ``<hp:run>``) that are rendered as honest
# placeholder markers instead of being silently dropped (Constitution VI).
_PICTURE_TAG = f"{_HP}pic"
_OLE_TAG = f"{_HP}ole"
_EQUATION_TAG = f"{_HP}equation"
_SHAPE_TAGS = frozenset(
    f"{_HP}{name}"
    for name in (
        "container",
        "rect",
        "ellipse",
        "line",
        "arc",
        "polygon",
        "curve",
        "connectLine",
        "textart",
    )
)

_OTHER_OBJECT_LABELS = {
    f"{_HP}{kind}": label for kind, label in {
        "chart": "차트", "video": "동영상", "checkBtn": "체크 상자", "radioBtn": "선택 단추",
        "btn": "단추", "button": "단추", "comboBox": "콤보 상자", "edit": "편집 상자",
        "listBox": "목록 상자", "scrollBar": "스크롤 막대",
    }.items()
}
_OBJECT_KINDS = {_PICTURE_TAG: "picture", _OLE_TAG: "embedded-object", _EQUATION_TAG: "equation"}
_AREA_LABELS = {
    f"{_HP}{kind}": label
    for kind, label in (("header", "머리말"), ("footer", "꼬리말"), ("footNote", "각주"), ("endNote", "미주"))
}
_OBJECT_TAGS = frozenset(_OBJECT_KINDS) | _SHAPE_TAGS | frozenset(_OTHER_OBJECT_LABELS)


@dataclass(frozen=True)
class _AnchorMarkup:
    page: int
    html: str
    flow: bool = True
    #: Placed as a character (``hp:pos@treatAsChar``): it stands inside its paragraph's line.
    inline: bool = False
    #: Drawn over or under the text at engine coordinates: it takes no room in a flow page.
    overlay: bool = False
    #: What a flow page shows instead of *html* (area lines at the engine's pitch, a table's flowing rows).
    flow_html: str | None = None
    #: What drawing *html* counts in ``limitations``, and drawing *flow_html* (for anchors that keep
    #: them apart: what is counted depends on which of the two the page draws).
    issues: Counter[tuple[str, str]] | None = None
    flow_issues: Counter[tuple[str, str]] | None = None
    #: The table (by ``id``) an engine-placed table fragment belongs to.
    table: int | None = None
    #: The engine's box of an engine-placed table fragment on its page: (paper top, paper bottom, width), HWPUNIT.
    box: tuple[int, int, int] | None = None

    def markup(self, flow: bool) -> tuple[str, Counter[tuple[str, str]] | None]:
        """The markup a page draws (a *flow* page or one at coordinates) and what it counts."""
        if flow and self.flow_html is not None:
            return self.flow_html, self.flow_issues
        return self.html, self.issues


@dataclass
class _PlacedLine:
    """A body line waiting for its page: a flow page gives it the engine's advance to the next line."""

    line: Any
    paragraph: ET.Element
    #: Objects placed as characters this line holds. A flow page draws them inside the line;
    #: a page at coordinates draws each at its own place after the line.
    hosted: list[_AnchorMarkup] = field(default_factory=list)


@dataclass(frozen=True)
class _ParagraphSources:
    tables: Mapping[Any, Any]
    objects: Mapping[Any, Any]
    areas: Mapping[Any, list[Any]]
    images: Mapping[str, tuple[str, bytes]]
    #: Tables (by ``TablePlacement.table``) the engine sets on a line of some cell of this paragraph.
    hosted_tables: frozenset[int] = frozenset()
    #: The paragraph's visible engine lines (where an object without a place may stand).
    lines: tuple[Any, ...] = ()
    #: The section's header and footer margins (HWPUNIT): where a header or footer without a page stands.
    margins: Mapping[str, int] = field(default_factory=dict)
    #: The numbers of the pages, for the page numbers a header or footer holds.
    numbering: _Numbering | None = None


_DEFAULT_PAGE_WIDTH_MM = 210.0
_DEFAULT_PAGE_HEIGHT_MM = 297.0
_DEFAULT_MARGINS_MM = {
    "left": 30.0,
    "right": 30.0,
    "top": 20.0,
    "bottom": 15.0,
    "header": 15.0,
    "footer": 15.0,
    "gutter": 0.0,
}


@dataclass
class _ObjectCounter:
    """Document-wide running index for placeholder markers (pictures)."""

    pictures: int = 0

    def next_picture(self) -> int:
        self.pictures += 1
        return self.pictures


@dataclass(frozen=True)
class PreviewPage:
    """Metadata for one rendered preview page."""

    index: int
    section_index: int
    page_id: str
    width_mm: float
    height_mm: float
    margins_mm: Mapping[str, float]
    paragraph_count: int
    table_count: int

    @property
    def content_width_mm(self) -> float:
        return max(0.0, self.width_mm - self.margins_mm["left"] - self.margins_mm["right"])

    @property
    def content_height_mm(self) -> float:
        return max(0.0, self.height_mm - self.margins_mm["top"] - self.margins_mm["bottom"])

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "sectionIndex": self.section_index,
            "pageId": self.page_id,
            "widthMm": round(self.width_mm, 2),
            "heightMm": round(self.height_mm, 2),
            "marginsMm": {key: round(value, 2) for key, value in self.margins_mm.items()},
            "contentWidthMm": round(self.content_width_mm, 2),
            "contentHeightMm": round(self.content_height_mm, 2),
            "paragraphCount": self.paragraph_count,
            "tableCount": self.table_count,
        }


_APPROX = "text-approx-pagination"
_ENGINE = "engine-estimated-pagination"
_PARTIAL = "partial-engine-estimated-pagination"
_BADGES = {
    _APPROX: "텍스트 근사 프리뷰 · 쪽·줄 추정 · 수식 MathML 렌더",
    _ENGINE: "쪽·줄 나눔은 엔진 추정",
    _PARTIAL: "쪽·줄 나눔은 엔진 추정 · 일부 요소 근사",
}


@dataclass(frozen=True)
class _Limitation:
    kind: str
    reason: str
    count: int

    def as_dict(self) -> dict[str, str | int]:
        return {"kind": self.kind, "reason": self.reason, "count": self.count}


@dataclass(frozen=True)
class LayoutPreview:
    """Rendered layout preview HTML plus machine-readable page metadata."""

    html: str
    pages: tuple[PreviewPage, ...]
    warnings: tuple[str, ...]
    mode: str
    page_fragments: tuple[str, ...] = ()
    fidelity_tier: str = _APPROX
    limitations: tuple[_Limitation, ...] = ()

    @property
    def badge(self) -> str:
        return _BADGES[self.fidelity_tier]

    def as_dict(self) -> dict[str, Any]:
        return {
            "html": self.html,
            "mode": self.mode,
            "pages": [page.as_dict() for page in self.pages],
            "pageCount": len(self.pages),
            "warnings": list(self.warnings),
            "fidelityTier": self.fidelity_tier,
            "limitations": [item.as_dict() for item in self.limitations],
        }

    def page_html_documents(self, *, title: str = "HWPX Layout Preview") -> list[str]:
        """Return standalone HTML documents, one per rendered preview page."""

        return [
            _document_html(
                title=f"{title} - page {index + 1}",
                mode=self.mode,
                body=fragment,
                screenshot=True,
                fidelity_tier=self.fidelity_tier,
                has_flow='data-layout-mode="flow"' in fragment,
            )
            for index, fragment in enumerate(self.page_fragments)
        ]


def _hwp_to_mm(value: str | int | float | None, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value) / _HWP_UNITS_PER_MM
    except (TypeError, ValueError):
        return default


def _char_height_to_pt(value: str | int | float | None, default: float = 10.0) -> float:
    if value is None:
        return default
    try:
        return max(1.0, float(value) / 100)
    except (TypeError, ValueError):
        return default


def _fmt_mm(value: float) -> str:
    return f"{value:.2f}mm"


def _fmt_pt(value: float) -> str:
    return f"{value:.2f}pt"


_HEX_COLOR_RE = re.compile(r"#?([0-9A-Fa-f]{8}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\Z")
_BORDER_WIDTH_RE = re.compile(r"(\d{1,3}(?:\.\d{1,3})?) ?mm\Z")
_TEXT_ALIGN = {
    "left": "left",
    "right": "right",
    "center": "center",
    "both": "justify",
    "justify": "justify",
    "distribute": "justify",
    "distribute_space": "justify",
}


def _css_color(value: str | None, default: str = "#000000") -> str:
    """Return ``value`` as a CSS hex colour, or ``default`` for anything else.

    The value comes from the document and ends up inside a ``style``
    attribute, so only a bare hex colour is let through.
    """

    if not value or value.lower() == "none":
        return default
    match = _HEX_COLOR_RE.match(value.strip())
    if match is None:
        return default
    digits = match.group(1)
    if len(digits) == 8:  # HWPX writes alpha first (#AARRGGBB); CSS wants it last.
        digits = digits[2:] + digits[:2]
    return f"#{digits}"


def _css_border_width(value: str | None, default: str = "0.1mm") -> str:
    match = _BORDER_WIDTH_RE.match((value or "").strip())
    return f"{match.group(1)}mm" if match else default


def _safe_int(value: str | None, default: int = 0) -> int:
    try:
        return int(value or default)
    except ValueError:
        return default


def _read_package_parts(source: str | Path | bytes) -> tuple[dict[str, bytes], list[str]]:
    warnings: list[str] = []
    archive: io.BytesIO | Path
    try:
        if isinstance(source, bytes):
            archive = io.BytesIO(source)
        else:
            archive = Path(source)
        with ZipFile(archive) as zf:
            guard_zip_file(zf)
            return {name: read_member(zf, name) for name in zf.namelist()}, warnings
    except (BadZipFile, FileNotFoundError, OSError) as exc:
        raise ValueError(f"unable to read HWPX package: {exc}") from exc


def _parse_xml(parts: Mapping[str, bytes], name: str, warnings: list[str]) -> ET.Element | None:
    payload = parts.get(name)
    if payload is None:
        warnings.append(f"missing XML part: {name}")
        return None
    try:
        return parse_xml_stdlib(payload, part_name=name)
    except ValueError as exc:
        warnings.append(f"unable to parse XML part {name}: {exc}")
        return None


def _section_names(parts: Mapping[str, bytes]) -> list[str]:
    return sorted(
        name
        for name in parts
        if name.startswith("Contents/section") and name.endswith(".xml")
    )


_INLINE_TEXT = {
    f"{_HP}lineBreak": "\n",
    f"{_HP}tab": "\t",
    f"{_HP}fwSpace": "\u3000",
    f"{_HP}nbSpace": "\u00a0",
}


def _text_node_content(node: ET.Element) -> str:
    """Text of an ``hp:t`` node, read as mixed content.

    Line breaks, tabs and marks (highlighter, tracked changes) sit *inside*
    ``hp:t``; the text after each of them is that element's tail.
    """

    parts = [node.text or ""]
    for child in node.iter():
        if child is node:
            continue
        parts.append(_INLINE_TEXT.get(child.tag, ""))
        parts.append(child.tail or "")
    return "".join(parts)


def _find_text_in_run(run: ET.Element) -> str:
    parts: list[str] = []
    for child in list(run):
        if child.tag == f"{_HP}t":
            parts.append(_text_node_content(child))
        elif child.tag == f"{_HP}tab" or (
            child.tag == f"{_HP}ctrl" and (child.get("id") or "").lower() == "tab"
        ):
            parts.append("\t")
        elif child.tag == f"{_HP}lineBreak":
            parts.append("\n")
    return "".join(parts)


def _paragraph_text(paragraph: ET.Element) -> str:
    return "".join(_find_text_in_run(run) for run in paragraph.findall(f"{_HP}run"))


def _collect_style_maps(header: ET.Element | None) -> dict[str, dict[str, Any]]:
    para: dict[str, Any] = {}
    chars: dict[str, Any] = {}
    borders: dict[str, Any] = {}
    if header is None:
        return {"para": para, "char": chars, "border": borders}

    for node in header.findall(f".//{_HH}paraPr"):
        para[node.get("id", "")] = _parse_para_style(node)
    for node in header.findall(f".//{_HH}charPr"):
        underline = node.find(f"{_HH}underline")
        chars[node.get("id", "")] = {
            "font_size_pt": _char_height_to_pt(node.get("height")),
            "color": _css_color(node.get("textColor")),
            "bold": node.find(f"{_HH}bold") is not None,
            "italic": node.find(f"{_HH}italic") is not None,
            "underline": underline is not None and underline.get("type", "NONE") != "NONE",
            "underline_color": _css_color(underline.get("color")) if underline is not None else None,
        }
    for node in header.findall(f".//{_HH}borderFill"):
        borders[node.get("id", "")] = _parse_border_fill(node)
    return {"para": para, "char": chars, "border": borders}


def _parse_para_style(node: ET.Element) -> dict[str, Any]:
    align = node.find(f"{_HH}align")
    horizontal = (align.get("horizontal") if align is not None else "LEFT") or "LEFT"
    line_spacing = node.find(f".//{_HH}lineSpacing")
    margin = node.find(f".//{_HH}margin")
    margins = {"left": 0.0, "right": 0.0, "top": 0.0, "bottom": 0.0, "indent": 0.0}
    if margin is not None:
        for child in list(margin):
            key = {
                f"{_HC}left": "left",
                f"{_HC}right": "right",
                f"{_HC}prev": "top",
                f"{_HC}next": "bottom",
                f"{_HC}intent": "indent",
            }.get(child.tag)
            if key:
                margins[key] = _hwp_to_mm(child.get("value"))
    spacing_value = _safe_int(line_spacing.get("value") if line_spacing is not None else None, 160)
    spacing_kind = (line_spacing.get("type") if line_spacing is not None else None) or "PERCENT"
    if spacing_kind != "PERCENT" and line_spacing is not None and line_spacing.get("unit") == "CHAR":
        spacing_kind = "UNKNOWN"  # a length in character units: not read here
    return {
        "align": _TEXT_ALIGN.get(horizontal.lower(), "left"),
        "line_spacing_percent": spacing_value,
        # (type, value) as written: PERCENT of the line height, or a length in HWPUNIT.
        "line_spacing": (spacing_kind, spacing_value),
        "margins_mm": margins,
    }


def _parse_border_fill(node: ET.Element) -> dict[str, Any]:
    sides: dict[str, str] = {}
    for side, tag in {
        "left": "leftBorder",
        "right": "rightBorder",
        "top": "topBorder",
        "bottom": "bottomBorder",
    }.items():
        border = node.find(f"{_HH}{tag}")
        if border is None or (border.get("type") or "NONE").upper() == "NONE":
            sides[side] = "none"
            continue
        width = _css_border_width(border.get("width"))
        color = _css_color(border.get("color"))
        sides[side] = f"{width} solid {color}"

    fill = "transparent"
    win_brush = node.find(f".//{_HC}winBrush")
    if win_brush is not None:
        face = win_brush.get("faceColor")
        if face and face.lower() != "none":
            fill = _css_color(face, default="transparent")

    # What an engine page draws: the solid face colour as it is; one colour for a pattern
    # (its face, nothing when it has none) or a gradient (the mean of its colours); no
    # picture. *fill_notes* names what was reduced, so the page can say so.
    shown, notes = fill, []
    if win_brush is not None and (win_brush.get("hatchStyle") or "NONE").upper() != "NONE":
        notes.append("pattern" if fill != "transparent" else "bare-pattern")
    gradation = node.find(f".//{_HC}gradation")
    if gradation is not None:
        stops = [_css_color(stop.get("value"), default="") for stop in gradation.findall(f"{_HC}color")]
        shown = _mean_color([stop for stop in stops if stop]) or shown
        notes.append("gradient")
    image = node.find(f".//{_HC}imgBrush")
    if image is not None:
        notes.append("picture")

    return {
        "sides": sides, "fill": fill, "shown_fill": shown, "fill_notes": tuple(notes), "fill_picture": image,
        "diagonal": _parse_diagonal(node),
    }


# A diagonal's ends in the cell's box (x1, y1, x2, y2): a slash rises from the bottom left corner to the
# top right, a back slash falls from the top left to the bottom right; a centre line crosses the middle.
_SLASH_ENDS = {"slash": ("0", "100%", "100%", "0"), "backSlash": ("0", "0", "100%", "100%")}
_CENTRE_LINE_ENDS = {
    "VERTICAL": (("50%", "0", "50%", "100%"),),
    "HORIZONTAL": (("0", "50%", "100%", "50%"),),
    "CROSS": (("50%", "0", "50%", "100%"), ("0", "50%", "100%", "50%")),
}
_DIAGONAL_BESIDE = ("table-cell", "cell diagonal is drawn as its centre line: the slanted lines beside it are not drawn")
_DIAGONAL_BENT = ("table-cell", "cell diagonal is drawn straight: its bend or counter direction is not drawn")
_DIAGONAL_STYLE = ("table-cell", "cell diagonal line style is drawn solid")
_CENTRE_LINE = ("table-cell", "cell centre line is drawn with the diagonal's line")


def _parse_diagonal(node: ET.Element) -> dict[str, Any] | None:
    """The lines a border fill's ``hh:slash``, ``hh:backSlash`` and ``centerLine`` draw across a cell, with
    the ``hh:diagonal`` line they are drawn with; ``None`` when there is nothing to draw.

    With no ``hh:diagonal`` (or one of type ``NONE``) no line is drawn: the line has no kind (python-hwpx
    writes it as kind 0 to a .hwp). What is drawn otherwise than the file says is named in *notes*.
    """
    line = node.find(f"{_HH}diagonal")
    kind = (line.get("type") or "NONE").upper() if line is not None else "NONE"
    if line is None or kind == "NONE":
        return None
    ends: list[tuple[str, str, str, str]] = []
    notes: list[tuple[str, str]] = []
    for tag, corner_to_corner in _SLASH_ENDS.items():
        slash = node.find(f"{_HH}{tag}")
        shape = (slash.get("type") or "NONE").upper() if slash is not None else "NONE"
        if slash is None or shape == "NONE":
            continue
        ends.append(corner_to_corner)
        if shape != "CENTER":
            notes.append(_DIAGONAL_BESIDE)
        if any((slash.get(name) or "0").lower() not in ("0", "false") for name in ("Crooked", "isCounter")):
            notes.append(_DIAGONAL_BENT)
    centre = _CENTRE_LINE_ENDS.get((node.get("centerLine") or "NONE").upper(), ())
    if centre:
        ends.extend(centre)
        notes.append(_CENTRE_LINE)
    if not ends:
        return None
    if kind != "SOLID":
        notes.append(_DIAGONAL_STYLE)
    return {
        "ends": tuple(ends), "width": _css_border_width(line.get("width")), "color": _css_color(line.get("color")),
        "notes": tuple(dict.fromkeys(notes)),
    }


def _cell_diagonal(
    border_ref: str | None, styles: Mapping[str, Any], issues: Counter[tuple[str, str]] | None,
) -> str:
    """The diagonals of a cell's border fill as an SVG over the cell's box (``""`` for none), solid lines
    of the file's width (a pixel at least, as a browser draws a thin border) and colour; what is drawn
    otherwise than the file says is counted in *issues*."""
    diagonal = styles["border"].get(border_ref or "", {}).get("diagonal")
    if not diagonal:
        return ""
    if issues is not None:
        for note in diagonal["notes"]:
            issues[note] += 1
    stroke = _style_attr({"stroke": diagonal["color"], "stroke-width": f"max(1px, {diagonal['width']})"})
    lines = "".join(
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" style="{stroke}"/>' for x1, y1, x2, y2 in diagonal["ends"]
    )
    return f'<svg class="hwpx-cell-diagonal" aria-hidden="true">{lines}</svg>'


def _mean_color(colors: list[str]) -> str | None:
    """The channel-wise mean of CSS hex colours (alpha left out), or ``None`` for no colours."""
    channels = []
    for color in colors:
        digits = color.removeprefix("#")
        if len(digits) == 3:
            digits = "".join(digit * 2 for digit in digits)
        channels.append([int(digits[index:index + 2], 16) for index in (0, 2, 4)])
    if not channels:
        return None
    return "#" + "".join(f"{round(sum(values) / len(values)):02X}" for values in zip(*channels))


def _page_spec(section: ET.Element) -> tuple[float, float, dict[str, float]]:
    page_pr = section.find(f".//{_HP}pagePr")
    if page_pr is None:
        return _DEFAULT_PAGE_WIDTH_MM, _DEFAULT_PAGE_HEIGHT_MM, dict(_DEFAULT_MARGINS_MM)
    width = _hwp_to_mm(page_pr.get("width"), _DEFAULT_PAGE_WIDTH_MM)
    height = _hwp_to_mm(page_pr.get("height"), _DEFAULT_PAGE_HEIGHT_MM)
    if page_pr.get("landscape") != PAGE_PORTRAIT:  # NARROWLY turns the page
        width, height = height, width
    margin_node = page_pr.find(f"{_HP}margin")
    margins = dict(_DEFAULT_MARGINS_MM)
    if margin_node is not None:
        for key in margins:
            margins[key] = _hwp_to_mm(margin_node.get(key), margins[key])
    return width, height, margins


def _style_attr(items: Mapping[str, str | float | int | None]) -> str:
    pairs = [
        f"{key}: {value}"
        for key, value in items.items()
        if value is not None and str(value) != ""
    ]
    return html.escape("; ".join(pairs), quote=True)


def _render_equation_element(equation: ET.Element) -> str:
    script_node = equation.find(f"{_HP}script")
    script = (script_node.text or "") if script_node is not None else ""
    return render_equation(script).html


def _render_object_marker(label: str) -> str:
    return f'<span class="hwpx-object-marker">⟦{html.escape(label)}⟧</span>'


def _shape_text_lines(element: ET.Element, *, captions: bool = True) -> list[str]:
    """The text of a drawing object's text boxes (a group's too), one line per paragraph.

    Tables inside are rendered as tables after the paragraph and are not read here.
    Without *captions* the object's caption is left to whoever draws it as a caption.
    """
    lines: list[str] = []
    for child in element:
        if child.tag == f"{_HP}tbl" or (not captions and child.tag == f"{_HP}caption"):
            continue
        if child.tag == f"{_HP}p":
            text = _paragraph_text(child)
            labels = _LABELS.get()
            found = labels.label(child) if labels is not None else None
            if found is not None and labels is not None:
                labels.drawn.add(child)
                text = f"{found.text} {text}"
            if text.strip():
                lines.append(text)
        lines.extend(_shape_text_lines(child, captions=captions))
    return lines


def _cell_paragraphs(cell: ET.Element) -> list[ET.Element]:
    """The paragraphs a table cell shows, in order: a nested table's are flattened
    in; a text box's are left to the shape that holds them (:func:`_render_shape`)."""

    parents = {child: parent for parent in cell.iter() for child in parent}
    shown: list[ET.Element] = []
    for paragraph in cell.iter(f"{_HP}p"):
        node = parents.get(paragraph)
        while node is not None and node is not cell and node.tag != f"{_HP}tbl" and node.tag not in _SHAPE_TAGS:
            node = parents.get(node)
        if node is None or node.tag not in _SHAPE_TAGS:
            shown.append(paragraph)
    return shown


def _render_shape(shape: ET.Element, *, captions: bool = True) -> str:
    lines = _shape_text_lines(shape, captions=captions)
    text = "<br>".join(html.escape(line) for line in lines)
    return _render_object_marker("도형") + (f'<span class="hwpx-shape-text">{text}</span>' if lines else "")


def _render_inline_object(child: ET.Element, counter: _ObjectCounter) -> str:
    if child.tag == _EQUATION_TAG:
        return _render_equation_element(child)
    if child.tag == _PICTURE_TAG:
        return _render_object_marker(f"그림 {counter.next_picture()}")
    if child.tag == _OLE_TAG:
        return _render_object_marker("개체")
    if child.tag in _SHAPE_TAGS:
        return _render_shape(child)
    return ""


_PLACEHOLDER = "object is shown as a placeholder"


@dataclass(frozen=True)
class _CellObjects:
    """Draws what the cells of an engine page's tables anchor: nothing a cell holds may vanish.

    A picture is shown itself when the engine gives its size and the file holds bytes a browser
    reads, an equation as an equation, anything else as its marker (a shape with its text).
    They stand in the cell's flow; every marker is counted.
    """

    objects: Mapping[Any, Any]
    images: Mapping[str, tuple[str, bytes]]
    issues: Counter[tuple[str, str]]
    counter: _ObjectCounter
    styles: Mapping[str, Any]

    def markup(self, element: ET.Element) -> str:
        """The object, and after it the text of its caption."""
        caption = _caption_text(element, self.styles, self.counter)
        return self._object(element) + (f'<span class="hwpx-object-caption">{caption}</span>' if caption else "")

    def _object(self, element: ET.Element) -> str:
        if element.tag == _EQUATION_TAG:
            return _render_equation_element(element)
        kind = _OBJECT_KINDS.get(element.tag, "shape" if element.tag in _SHAPE_TAGS else element.tag.removeprefix(_HP))
        if element.tag == _PICTURE_TAG:
            label = f"그림 {self.counter.next_picture()}"
            placed = self.objects.get(element)
            image = element.find(f".//{_HC}img")
            asset = self.images.get(image.get("binaryItemIDRef", "")) if image is not None else None
            if asset is not None and placed is not None and placed.width and placed.height:
                css = _style_attr({
                    "width": _fmt_mm(_hwp_to_mm(placed.width)), "height": _fmt_mm(_hwp_to_mm(placed.height)),
                })
                encoded = base64.b64encode(asset[1]).decode("ascii")
                return f'<img class="hwpx-cell-picture" alt="{label}" style="{css}" src="data:{asset[0]};base64,{encoded}">'
            self.issues[(kind, _PLACEHOLDER)] += 1
            return _render_object_marker(label)
        self.issues[(kind, _PLACEHOLDER)] += 1
        if element.tag in _SHAPE_TAGS:
            return _render_shape(element, captions=False)
        return _render_object_marker(_OTHER_OBJECT_LABELS.get(element.tag, "개체"))


def _caption_text(element: ET.Element, styles: Mapping[str, Any], counter: _ObjectCounter) -> str:
    """The text of an object's caption (``hp:caption``), a line per paragraph; empty without one."""
    caption = element.find(f"{_HP}caption")
    if caption is None:
        return ""
    lines = [
        _label_markup(paragraph, styles)
        + _render_inline_runs(paragraph, styles, counter, include_objects=False, extended_styles=True)
        for paragraph in caption.iter(f"{_HP}p")
    ]
    return "<br>".join(line for line in lines if line)


def _run_objects(run: ET.Element) -> Iterator[ET.Element]:
    """The objects a run anchors, tables apart: its own, and of an ``hp:switch`` the first choice."""
    for child in run:
        if child.tag in _OBJECT_TAGS:
            yield child
        elif child.tag == f"{_HP}switch":
            found = next((node for node in child.iter() if node.tag in _OBJECT_TAGS), None)
            if found is not None:
                yield found


@dataclass(frozen=True)
class _PageNumbers:
    """The page an area is drawn on, for the page numbers it holds (``hp:autoNum``): the number the
    engine's page order gives that page, and the document's page count."""

    number: int
    total: int
    #: What drawing a number counts (a number style this module does not write, drawn in digits).
    issues: Counter[tuple[str, str]]
    #: The engine gives the page no number: *number* is the preview's own count.
    counted: bool = False


#: Set while a header or footer is drawn for one page: its page numbers are written as that page's.
_PAGE_NUMBERS: ContextVar[_PageNumbers | None] = ContextVar("_PAGE_NUMBERS", default=None)

_CIRCLED = "".join(chr(code) for code in range(0x2460, 0x2474))
_LETTER_STYLES = {
    "LATIN_CAPITAL": "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "LATIN_SMALL": "abcdefghijklmnopqrstuvwxyz",
    "HANGUL_SYLLABLE": "가나다라마바사아자차카타파하",
    "HANGUL_JAMO": "ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ",
    "IDEOGRAPH": "一二三四五六七八九十",
    "CIRCLED_DIGIT": _CIRCLED,
}
_NUMBER_STYLE_UNREAD = ("page-number", "number style is not written here: the number is drawn in digits")
_NUMBER_COUNTED = ("page-number", "the engine gives the page no number: the preview's own count is drawn")


def _roman(value: int) -> str:
    result = []
    for amount, letters in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
                            (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        count, value = divmod(value, amount)
        result.append(letters * count)
    return "".join(result)


def _number_text(value: int, style: str | None, issues: Counter[tuple[str, str]]) -> str:
    """*value* in the file's number style (``DIGIT`` and those named here); any other in digits, counted."""
    style = (style or "DIGIT").upper()
    if style == "DIGIT":
        return str(value)
    if style in ("ROMAN_CAPITAL", "ROMAN_SMALL") and 0 < value < 4000:
        roman = _roman(value)
        return roman if style == "ROMAN_CAPITAL" else roman.lower()
    letters = _LETTER_STYLES.get(style)
    if letters is not None and 0 < value <= len(letters):
        return letters[value - 1]
    issues[_NUMBER_STYLE_UNREAD] += 1
    return str(value)


def _auto_number(node: ET.Element) -> str | None:
    """The text a page number or page count (``hp:autoNum``) shows on the page being drawn, else ``None``."""
    numbers = _PAGE_NUMBERS.get()
    kind = node.get("numType")
    if numbers is None or kind not in ("PAGE", "TOTAL_PAGE"):
        return None
    form = node.find(f"{_HP}autoNumFormat")
    style = form.get("type") if form is not None else None
    if kind == "PAGE" and numbers.counted:
        numbers.issues[_NUMBER_COUNTED] += 1
    text = _number_text(numbers.number if kind == "PAGE" else numbers.total, style, numbers.issues)
    if form is not None:
        text = f"{form.get('prefixChar') or ''}{text}{form.get('suffixChar') or ''}"
    return text


def _number_span(number: str, style: str) -> str:
    """A page number in a header or footer. The style sheet draws it from the attribute: it is no text of
    the document (Hangul lists none for it among a page's text), so it stays out of the page's text."""
    shown = html.escape(number, quote=True)
    return f'<span class="hwpx-page-number-text" data-number-text="{shown}" style="{style}"></span>'


def _run_numbers(run: ET.Element) -> list[str]:
    """The page numbers a run holds, as the page being drawn shows them."""
    return [
        text for node in run.findall(f"{_HP}ctrl/{_HP}autoNum") if (text := _auto_number(node)) is not None
    ]


# The number or bullet Hangul draws before a paragraph, in the engine preview. Its text is python-hwpx's own
# count (:class:`hwpx.tools.exporter.ListLabels`, the count the engine measures a label's room with): every
# paragraph once, in reading order -- the body's paragraphs, each followed by those of the tables, text boxes
# and captions placed in it. What a header, footer or note holds is not counted there, nor labelled here.
# Where the engine's line carries a label of its own (``line.label``, with its ``text`` and character shape
# ``char_pr_id_ref``), that one is drawn instead.

_NO_SHAPE = "4294967295"
#: Each paragraph drawn with its label: the engine gives the label no place, so it stands at its line's start, its gap approximated.
_LABEL_ROOM = ("paragraph-label", "number or bullet is drawn at its paragraph's first line: its place and room are approximate")
#: A paragraph its shape numbers whose label python-hwpx does not write (a number format it does not write,
#: a level its numbering does not define, a picture bullet).
_LABEL_UNWRITTEN = ("paragraph-label", "number or bullet is not written here: the paragraph is drawn without it")


@dataclass(frozen=True)
class _Label:
    """A label to draw: its text, the character shape it is set in and the gap after it."""

    text: str
    char_pr_id_ref: str
    #: The gap to the paragraph's text: (value, unit), unit ``"em"`` (of the label's size) or ``"hwp"``.
    gap: tuple[float, str]


def _heading(para_pr: Any) -> Any | None:
    """A paragraph shape's ``hh:heading``: its own, else the one an ``hp:switch`` holds (case, then default)."""
    own = para_pr.find(f"{_HH}heading")
    if own is not None:
        return own
    for switch in para_pr.findall(f"{_HP}switch"):
        for branch in (*switch.findall(f"{_HP}case"), *switch.findall(f"{_HP}default")):
            found = branch.find(f"{_HH}heading")
            if found is not None:
                return found
    return None


def _label_heads(header: Any, outline: str | None) -> dict[str, dict[str, str]]:
    """The ``hh:paraHead`` attributes of each paragraph shape that numbers or bullets its paragraphs."""
    if header is None:
        return {}
    numberings = {node.get("id") or "": node for node in header.iter(f"{_HH}numbering")}
    bullets = {node.get("id") or "": node for node in header.iter(f"{_HH}bullet")}
    found: dict[str, dict[str, str]] = {}
    for para_pr in header.iter(f"{_HH}paraPr"):
        heading = _heading(para_pr)
        kind = (heading.get("type") or "NONE").upper() if heading is not None else "NONE"
        if heading is None or kind == "NONE":
            continue
        ref = heading.get("idRef") or ""
        if kind == "BULLET":
            head = bullets[ref].find(f"{_HH}paraHead") if ref in bullets else None
        else:
            numbering = numberings.get((outline or "") if kind == "OUTLINE" else ref)
            level = str(_safe_int(heading.get("level")) + 1)
            head = next((node for node in numbering.iter(f"{_HH}paraHead") if (node.get("level") or "1") == level),
                        None) if numbering is not None else None
        found[para_pr.get("id") or ""] = dict(head.attrib) if head is not None else {}
    return found


@dataclass
class _Labels:
    """The labels of a document's paragraphs (by their ``hp:p`` element) and what drawing them counts."""

    labels: dict[Any, str]
    heads: dict[str, dict[str, str]]
    shapes: frozenset[str]
    issues: Counter[tuple[str, str]] = field(default_factory=Counter)
    #: The paragraphs drawn with their label (a paragraph a page draws twice, or as two alternatives, once).
    drawn: set[Any] = field(default_factory=set)

    @classmethod
    def of(cls, document: HwpxDocument, char_shapes: Mapping[str, Any]) -> _Labels:
        counted = ListLabels(document)
        labels: dict[Any, str] = {}
        issues: Counter[tuple[str, str]] = Counter()
        sections = [section.element for section in document.sections]
        for section in sections:
            for paragraph in section.iter(f"{_HP}p"):
                label = counted.label(paragraph)
                if label:
                    labels[paragraph] = label
                elif counted.kind(paragraph) is not None:
                    issues[_LABEL_UNWRITTEN] += 1
        sec_pr = next(sections[0].iter(f"{_HP}secPr"), None) if sections else None
        headers = document.oxml.headers
        heads = _label_heads(headers[0].element if headers else None,
                             sec_pr.get("outlineShapeIDRef") if sec_pr is not None else None)
        return cls(labels, heads, frozenset(char_shapes), issues)

    def label(self, paragraph: Any, engine: Any = None) -> _Label | None:
        """The label drawn before *paragraph* (the engine's own *engine* label first), else None."""
        head = self.heads.get(paragraph.get("paraPrIDRef") or "", {})
        text = getattr(engine, "text", None) if engine is not None else None
        own = getattr(engine, "char_pr_id_ref", None) if text else None
        if not text:
            text = self.labels.get(paragraph)
            own = head.get("charPrIDRef")
        if not text:
            return None
        if not own or own == _NO_SHAPE or own not in self.shapes:
            # a label without a shape of its own takes the paragraph end's (its last run's), as the engine measures it
            runs = paragraph.findall(f"{_HP}run")
            own = (runs[-1].get("charPrIDRef") if runs else None) or "0"
        try:
            offset = float(head.get("textOffset") or 50)
        except ValueError:
            offset = 50.0
        gap = (offset, "hwp") if (head.get("textOffsetType") or "").upper() == "HWPUNIT" else (offset / 100, "em")
        return _Label(text, str(own), gap)


#: Set while the engine preview is drawn: the numbers and bullets of the document's paragraphs.
_LABELS: ContextVar[_Labels | None] = ContextVar("_LABELS", default=None)


def _opens_paragraph(line: Any) -> bool:
    """Whether *line* is its paragraph's first: a cell or text box line's index 0, a body line's text from 0."""
    index = getattr(line, "line", None)
    return index == 0 if isinstance(index, int) else line.text_start == 0


def _label_markup(paragraph: ET.Element, styles: Mapping[str, Any], line: Any = None) -> str:
    """The number or bullet drawn before *paragraph* (on *line*, when it is the paragraph's first), in its
    character shape and followed by its gap to the text; empty without one or outside the engine preview.
    Each one drawn is counted: the engine gives no place for it, so where it stands is approximate."""
    labels = _LABELS.get()
    if labels is None or (line is not None and not _opens_paragraph(line)):
        return ""
    found = labels.label(paragraph, getattr(line, "label", None))
    if found is None:
        return ""
    labels.drawn.add(paragraph)
    value, unit = found.gap
    css = _character_css(styles["char"].get(found.char_pr_id_ref, {}), extended=True)
    gap = f"{value:.2f}em" if unit == "em" else _fmt_mm(_hwp_to_mm(value))
    return (f'<span class="hwpx-paragraph-label" data-approx="label" '
            f'style="{css}; margin-right: {gap}">{html.escape(found.text)}</span>')


def _render_inline_runs(
    paragraph: ET.Element,
    styles: Mapping[str, Any],
    counter: _ObjectCounter,
    *,
    include_objects: bool = True,
    extended_styles: bool = False,
    cell_objects: _CellObjects | None = None,
) -> str:
    spans: list[str] = []
    char_styles = styles["char"]
    for run in paragraph.findall(f"{_HP}run"):
        text = _find_text_in_run(run)
        numbers = _run_numbers(run) if _PAGE_NUMBERS.get() is not None else []
        if text or numbers:
            char_style = char_styles.get(run.get("charPrIDRef") or "0", {})
            style = _character_css(char_style, extended=extended_styles)
            spans.append(f'<span style="{style}">{html.escape(text)}</span>' if text else "")
            spans.extend(_number_span(number, style) for number in numbers)
        # Inline objects that carry no text are rendered as real content or an
        # honest marker -- never dropped to a blank (Constitution VI).
        if include_objects and cell_objects is not None:
            spans.extend(cell_objects.markup(child) for child in _run_objects(run))
        elif include_objects:
            spans.extend(_render_inline_object(child, counter) for child in run)
    return "".join(spans)


def _character_css(char: Mapping[str, Any], *, extended: bool) -> str:
    return _style_attr({
        "font-size": _fmt_pt(char.get("font_size_pt", 10.0)),
        "color": char.get("color", "#000000"),
        "font-weight": "bold" if extended and char.get("bold") else None,
        "font-style": "italic" if extended and char.get("italic") else None,
        "text-decoration-line": "underline" if extended and char.get("underline") else None,
        "text-decoration-color": char.get("underline_color") if extended and char.get("underline") else None,
    })


def _paragraph_style(paragraph: ET.Element, styles: Mapping[str, Any]) -> str:
    para_styles = styles["para"]
    style = para_styles.get(paragraph.get("paraPrIDRef") or "0", {})
    margins = style.get("margins_mm", {})
    return _style_attr(
        {
            "text-align": style.get("align", "left"),
            "line-height": f"{style.get('line_spacing_percent', 160)}%",
            "margin-top": _fmt_mm(margins.get("top", 0.0)),
            "margin-right": _fmt_mm(margins.get("right", 0.0)),
            "margin-bottom": _fmt_mm(margins.get("bottom", 1.6)),
            "margin-left": _fmt_mm(margins.get("left", 0.0)),
            "text-indent": _fmt_mm(margins.get("indent", 0.0)),
        }
    )


_CELL_FILL_NOTES = {
    "pattern": ("table-cell", "cell fill pattern or gradient is drawn as one colour"),
    "gradient": ("table-cell", "cell fill pattern or gradient is drawn as one colour"),
    "bare-pattern": ("table-cell", "cell fill pattern is not drawn"),
    "picture": ("table-cell", "cell fill picture is not drawn"),
}


def _border_style(
    border_ref: str | None, styles: Mapping[str, Any], *, issues: Counter[tuple[str, str]] | None = None,
) -> dict[str, str | None]:
    """Borders and background of a cell. With *issues* (an engine page) a pattern or gradient
    is drawn as one colour and every reduced fill is counted."""
    border = styles["border"].get(border_ref or "", {})
    sides = border.get("sides") or {}
    fill = border.get("fill", "transparent")
    if issues is not None:
        fill = border.get("shown_fill", fill)
        for note in dict.fromkeys(_CELL_FILL_NOTES[note] for note in border.get("fill_notes", ())):
            issues[note] += 1
    return {
        "border-left": sides.get("left", "1px solid #b9c0c7"),
        "border-right": sides.get("right", "1px solid #b9c0c7"),
        "border-top": sides.get("top", "1px solid #b9c0c7"),
        "border-bottom": sides.get("bottom", "1px solid #b9c0c7"),
        "background": fill,
    }


_AUTHORED_ROW_HEIGHT = ("table-row", "row height is the authored cell height, not an engine value")


def _column_widths(table: ET.Element) -> list[int] | None:
    """The table's column widths (HWPUNIT) as its cells' addresses, spans and widths settle them.

    A fixed-layout HTML table takes its columns from its first row alone; a first row of merged
    cells would leave them even. ``None`` when the cells do not settle every column.
    """
    cells = []
    count = 0
    for cell in table.findall(f"{_HP}tr/{_HP}tc"):
        address, span, size = (cell.find(f"{_HP}{name}") for name in ("cellAddr", "cellSpan", "cellSz"))
        if address is None or size is None:
            return None
        start = _safe_int(address.get("colAddr"))
        columns = max(1, _safe_int(span.get("colSpan") if span is not None else None, 1))
        cells.append((start, columns, _safe_int(size.get("width"))))
        count = max(count, start + columns)
    known: dict[int, int] = {}
    settled = True
    while settled and len(known) < count:
        settled = False
        for start, columns, width in cells:
            missing = [column for column in range(start, start + columns) if column not in known]
            if len(missing) == 1:
                value = width - sum(known[column] for column in range(start, start + columns) if column in known)
                if value <= 0:
                    return None
                known[missing[0]] = value
                settled = True
    return [known[column] for column in range(count)] if count and len(known) == count else None


def _padding_less_border(margin_mm: float, border: str | None) -> str | None:
    """A cell margin less the half of *border* (a CSS border side) the cell's box takes; ``None`` for no border.

    A browser lays a border thinner than a pixel out as one whole pixel.
    """
    width = (border or "none").split(" ", 1)[0]
    pixels = 0.0
    if width.endswith("mm"):
        pixels = float(width[:-2]) * 96 / 25.4
    elif width.endswith("px"):
        pixels = float(width[:-2])
    if pixels <= 0:
        return None
    half = max(1.0, float(int(pixels))) / 2
    if margin_mm * 96 / 25.4 <= half:
        return "0mm"
    return f"calc({_fmt_mm(margin_mm)} - {half:g}px)"


def _authored_row_height(cells: list[ET.Element]) -> int:
    """The tallest ``hp:cellSz@height`` (HWPUNIT) among the row's cells that span one row."""
    heights = []
    for cell in cells:
        span = cell.find(f"{_HP}cellSpan")
        size = cell.find(f"{_HP}cellSz")
        if size is not None and _safe_int(span.get("rowSpan") if span is not None else None, 1) == 1:
            heights.append(_safe_int(size.get("height")))
    return max(heights, default=0)


def _render_table(
    table: ET.Element,
    styles: Mapping[str, Any],
    counter: _ObjectCounter,
    *,
    flow: bool = False,
    row_parts: tuple[Any, ...] = (),
    table_placements: Mapping[Any, Any] | None = None,
    table_index: int | None = None,
    continued_rows: frozenset[int] = frozenset(),
    captions: tuple[Any, ...] = (),
    show_approx_caption: bool = False,
    issues: Counter[tuple[str, str]] | None = None,
    sources: _ParagraphSources | None = None,
    plans: Mapping[int, _CellPlan] | None = None,
    closing: bool = False,
    diagonals: Counter[tuple[str, str]] | None = None,
) -> str:
    """One table, or the rows of it the engine set on one page (*row_parts*).

    *plans* say where each placed cell draws what the engine's lines do not show. The part
    that is *closing* (it holds the table's last placed row) also draws, from the file, the
    rows of cells the engine placed in no row at all. On an engine page (*issues* or *diagonals*
    given, the latter where a table there is otherwise drawn the approximate way) the cells' diagonals
    are drawn and what of them is approximate counted; a declined document's page draws none.
    """
    diagonal_notes = issues if issues is not None else diagonals
    draw_diagonals = issues is not None or diagonals is not None
    size = table.find(f"{_HP}sz")
    table_width = _hwp_to_mm(size.get("width") if size is not None else None)
    table_style = _style_attr(
        {
            "width": _fmt_mm(table_width) if table_width > 0 else "100%",
            "border-collapse": "collapse",
            "table-layout": "fixed",
            "margin": "1.5mm 0",
        }
    )
    rows: list[str] = []
    source_rows = table.findall(f"{_HP}tr")
    if row_parts:
        source_cells = table.findall(f"{_HP}tr/{_HP}tc")
        selected = [([source_cells[cell.source_index] for cell in part.cells if cell.source_index is not None], part)
                    for part in row_parts]
        if closing and plans is not None:
            numbers = {id(cell): number for number, cell in enumerate(source_cells)}
            for row in source_rows:
                unplaced = [cell for cell in row.findall(f"{_HP}tc")
                            if numbers[id(cell)] not in plans and _holds_content(cell)]
                if unplaced:
                    selected.append((unplaced, None))
                    if issues is not None:
                        issues[_UNPLACED_CELL] += len(unplaced)
    else:
        selected = [(row.findall(f"{_HP}tc"), None) for row in source_rows]
    for source_cells, part in selected:
        cells: list[str] = []
        measured = {cell.column: cell for cell in part.cells} if part is not None else {}
        for tc in source_cells:
            cell_address = tc.find(f"{_HP}cellAddr")
            column = _safe_int(cell_address.get("colAddr") if cell_address is not None else None, 0)
            placement = measured.get(column)
            cell_size = tc.find(f"{_HP}cellSz")
            # The cell's effective margins (``cell.margins``): the table's
            # hp:inMargin unless the cell's hasMargin is on.
            cell_margins = cell_margins_of(tc, table)
            width = _hwp_to_mm(cell_size.get("width") if cell_size is not None else None)
            height = _hwp_to_mm(cell_size.get("height") if cell_size is not None else None)
            if placement is not None and placement.width is not None:
                width = _hwp_to_mm(placement.width)
            if part is not None:
                height = _hwp_to_mm(placement.height if placement is not None else None)
            padding = {
                key: _hwp_to_mm(getattr(cell_margins, key)) if cell_margins is not None else 0.5
                for key in ("top", "right", "bottom", "left")
            }
            border_ref = tc.get("borderFillIDRef") or table.get("borderFillIDRef")
            css = _border_style(border_ref, styles, issues=issues)
            diagonal = _cell_diagonal(border_ref, styles, diagonal_notes) if draw_diagonals else ""
            above = below = None
            vertical = "middle"
            if flow:
                # The engine's row height has no border in it: the half of each border the cell's box
                # takes comes off the margin, so that a row of engine lines is as tall as the engine says.
                above = _padding_less_border(padding["top"], css["border-top"])
                below = _padding_less_border(padding["bottom"], css["border-bottom"])
                vertical = _cell_vertical_align(tc)
                if placement is not None and placement.line_start:
                    vertical = "top"  # the later part of a split cell goes on from its top
            css.update(
                {
                    "width": _fmt_mm(width) if width > 0 else None,
                    "min-height": _fmt_mm(height) if height > 0 else None,
                    "padding": (
                        f"{_fmt_mm(padding['top'])} {_fmt_mm(padding['right'])} "
                        f"{_fmt_mm(padding['bottom'])} {_fmt_mm(padding['left'])}"
                    ),
                    "padding-top": above,
                    "padding-bottom": below,
                    "vertical-align": vertical,
                    "position": "relative" if diagonal else None,  # the diagonals' box is the cell's
                }
            )
            plan = None
            if plans is not None and placement is not None and part is not None and not part.repeated:
                plan = plans.get(placement.source_index)
            body_parts = _table_cell_body(
                tc, styles, counter, flow=flow, placement=placement, table_placements=table_placements,
                continued=part is not None and part.row in continued_rows and not part.repeated,
                page=part.page if part is not None else None, issues=issues, sources=sources, plan=plan,
            )
            if not body_parts and part is None:
                body_parts.append("&nbsp;")
            span = tc.find(f"{_HP}cellSpan")
            colspan = _safe_int(span.get("colSpan") if span is not None else None, 1)
            rowspan = _safe_int(span.get("rowSpan") if span is not None else None, 1)
            if placement is not None:
                rowspan = placement.row_span
            if part is not None and rowspan > 1:
                rowspan = sum(part.row <= other.row < part.row + rowspan and other.repeated == part.repeated
                              for other in row_parts)
            attrs = [
                f'style="{_style_attr(css)}"',
                f'data-border-fill-id="{html.escape(tc.get("borderFillIDRef") or "")}"',
            ]
            if colspan > 1:
                attrs.append(f'colspan="{colspan}"')
            if rowspan > 1:
                attrs.append(f'rowspan="{rowspan}"')
            cells.append(f"<td {' '.join(attrs)}>{diagonal}{''.join(body_parts)}</td>")
        row_attrs = ""
        if part is not None:
            row_attrs = f' data-engine-row="{part.row}" data-engine-repeated="{int(part.repeated)}"'
            if part.top is not None:
                row_attrs += f' data-engine-top="{part.top}"'
            if part.height is not None:
                row_attrs += f' style="height:{_fmt_mm(_hwp_to_mm(part.height))}"'
        elif flow and (authored := _authored_row_height(source_cells)) > 0:
            # No engine row: the height written in the file is the least the row takes.
            row_attrs = f' data-row-height="authored" style="height:{_fmt_mm(_hwp_to_mm(authored))}"'
            if issues is not None:
                issues[_AUTHORED_ROW_HEIGHT] += 1
        rows.append(f"<tr{row_attrs}>{''.join(cells)}</tr>")
    table_attrs = f' data-engine-table="{table_index}"' if table_index is not None else ""
    caption_html = _table_caption_markup(table, captions, styles, counter, approximate=show_approx_caption)
    columns = ""
    if flow and (widths := _column_widths(table)) is not None:
        columns = "".join(f'<col style="width:{_fmt_mm(_hwp_to_mm(width))}">' for width in widths)
        columns = f"<colgroup>{columns}</colgroup>"
    return (
        f'<table class="hwpx-table"{table_attrs} style="{table_style}">{caption_html}{columns}'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


_CELL_VERTICAL = {"TOP": "top", "CENTER": "middle", "BOTTOM": "bottom"}
_STACKED_CELL = ("table-cell", "cell lines stand at the file's line spacing, not at engine tops")
_CONTINUED_PARAGRAPH = "이어지는 문단의 줄 위치 미확인"


def _cell_vertical_align(cell: ET.Element) -> str:
    """Where the cell sets its content (``hp:subList@vertAlign``); the middle when it does not say."""
    content = cell.find(f"{_HP}subList")
    return _CELL_VERTICAL.get((content.get("vertAlign") if content is not None else None) or "CENTER", "middle")


_WHOLE_PARAGRAPH = ("table-cell", "cell paragraph is drawn whole: the engine's lines do not give all its text")
_UNPLACED_CELL = ("table-cell", "cell the engine placed in no row is drawn after the table's placed rows")


@dataclass(frozen=True)
class _CellPlan:
    """Where a placed cell draws what the engine's lines do not show, over all the cell's parts.

    The engine gives a cell's lines part by part (a part per page the cell runs over). Whatever
    of the cell's own paragraphs those lines do not cover is still drawn, once, the approximate
    way: *whole* names such paragraphs, *home* the part (by ``id``) each paragraph begins in,
    *first* the cell's first part.
    """

    first: int
    home: Mapping[int, int]
    whole: frozenset[int]
    lines: bool
    #: Paragraphs in *whole* only for the objects they set as characters: the engine's lines give all
    #: their text, so a page at coordinates draws those lines and each object at its own place.
    for_objects: frozenset[int] = frozenset()


def _characters(text: str) -> Counter[str]:
    return Counter(character for character in text if not character.isspace())


def _fragment_lines(placement: Any) -> tuple[Any, ...]:
    """A cell part's lines. A cell holding tables gives them, the tables' among them, apart from ``lines``."""
    return getattr(placement, "lines_with_tables", ()) or placement.lines


def _holds_content(cell: ET.Element) -> bool:
    return any(
        _paragraph_text(paragraph).strip() or _has_objects(paragraph) or next(_anchored_tables(paragraph), None) is not None
        for paragraph in cell.findall(f"{_HP}subList/{_HP}p")
    )


def _has_objects(paragraph: ET.Element) -> bool:
    return any(True for run in paragraph.findall(f"{_HP}run") for _ in _run_objects(run))


def _cell_plans(table: ET.Element, placed: Any) -> dict[int, _CellPlan]:
    """A plan for every cell of *table* the engine placed (by the cell's index among ``hp:tr/hp:tc``)."""
    cells = table.findall(f"{_HP}tr/{_HP}tc")
    parts_of: dict[int, list[Any]] = {}
    for row in placed.rows:
        if not row.repeated:
            for part in row.cells:
                if part.source_index is not None and part.source_index < len(cells):
                    parts_of.setdefault(part.source_index, []).append(part)
    plans = {}
    for number, parts in parts_of.items():
        own = cells[number].findall(f"{_HP}subList/{_HP}p")
        shown: dict[int, Counter[str]] = {}
        home: dict[int, int] = {}
        ends: dict[int, int] = {}
        for part in parts:
            for line in _fragment_lines(part):
                if line.paragraph < len(own):
                    home.setdefault(line.paragraph, id(part))
                    ends[line.paragraph] = id(part)
                    shown.setdefault(line.paragraph, Counter()).update(_characters(line.text or ""))
        whole = set()
        for_objects = set()
        latest = id(parts[0])
        for index, paragraph in enumerate(own):
            if index in home:
                latest = ends[index]
            else:  # no line anywhere: it begins where the paragraph before it ends
                home[index] = latest
            uncovered = bool(_characters(_paragraph_text(paragraph)) - shown.get(index, Counter()))
            unseen = index not in shown and (
                _has_objects(paragraph) or next(_anchored_tables(paragraph, areas=False), None) is not None
            )
            if uncovered or unseen or _has_inline_objects(paragraph):
                whole.add(index)
                if not uncovered and not unseen:
                    for_objects.add(index)
        plans[number] = _CellPlan(id(parts[0]), home, frozenset(whole), bool(shown), frozenset(for_objects))
    return plans


def _table_cell_body(
    cell: ET.Element, styles: Mapping[str, Any], counter: _ObjectCounter, *, flow: bool,
    placement: Any, continued: bool, page: int | None, table_placements: Mapping[Any, Any] | None,
    issues: Counter[tuple[str, str]] | None = None, sources: _ParagraphSources | None = None,
    plan: _CellPlan | None = None,
) -> list[str]:
    cell_objects = None
    if sources is not None and issues is not None:
        cell_objects = _CellObjects(sources.objects, sources.images, issues, counter, styles)
    lines = () if placement is None else _fragment_lines(placement)
    empty = placement is not None and placement.line_start is not None and placement.line_start == placement.line_end
    if placement is not None and (lines or (plan is not None and plan.lines)):
        body = _placed_cell_lines(
            cell, placement, styles, counter, page=page, table_placements=table_placements, issues=issues,
            sources=sources, cell_objects=cell_objects, plan=plan,
        )
        if body or lines or empty:
            return body
        return [_render_object_marker("이어지는 칸의 줄 위치 미확인")]
    if plan is not None:
        later = id(placement) != plan.first  # the engine gives the cell no line: all of it is drawn in its first part
    else:
        later = continued or (placement is not None and bool(placement.line_start))
    if later:
        return [] if empty else [_render_object_marker("이어지는 칸의 줄 위치 미확인")]
    if not flow:
        return [
            _render_paragraph(paragraph, styles, counter, include_tables=False)
            for paragraph in _cell_paragraphs(cell)
        ]
    # No engine lines: the cell's own paragraphs in order, each table after the paragraph that anchors it.
    body = []
    for paragraph in cell.findall(f"{_HP}subList/{_HP}p"):
        body.append(_render_paragraph(
            paragraph, styles, counter, include_tables=False, extended_styles=True, cell_objects=cell_objects,
        ))
        body.extend(
            _nested_table(nested, styles, counter, page=page, table_placements=table_placements,
                          issues=issues, sources=sources, every_page=plan is not None)
            for nested in _anchored_tables(paragraph)
        )
    return body


def _nested_table(
    table: ET.Element, styles: Mapping[str, Any], counter: _ObjectCounter, *, page: int | None,
    table_placements: Mapping[Any, Any] | None, issues: Counter[tuple[str, str]] | None,
    sources: _ParagraphSources | None, every_page: bool = False,
) -> str:
    """A table inside a cell: its engine rows of *page* (of every page with *every_page*), or all of it
    when the engine placed no row."""
    found = table_placements.get(table) if table_placements is not None else None
    rows = tuple(row for row in found.rows if every_page or row.page == page) if found is not None else ()
    if found is not None and found.rows and not rows:
        return ""  # placed, on other pages only
    return _render_table(
        table, styles, counter, flow=True, row_parts=rows, table_placements=table_placements,
        table_index=found.table if found is not None and rows else None,
        captions=tuple(caption for caption in found.captions if every_page or caption.page == page) if found else (),
        show_approx_caption=found is None or not found.captions, issues=issues, sources=sources,
        plans=_cell_plans(table, found) if found is not None and rows else None,
        closing=found is not None and bool(rows) and rows[-1] is found.rows[-1],
    )


def _has_inline_objects(paragraph: ET.Element) -> bool:
    return any(_placed_as_character(node) for run in paragraph.findall(f"{_HP}run") for node in _run_objects(run))


def _cell_line_room(
    line: Any, following: Any, style: Mapping[str, Any], following_style: Mapping[str, Any],
    character_mm: float | None = None,
) -> tuple[float | None, int | None]:
    """Millimetres from this cell line's top to the next line's top, and the engine's value if it gave one.

    With both engine tops, their difference. Otherwise what the file states: the paragraph's line
    spacing over the line's height (over the character size for a line that is a table), plus the
    paragraph spacing between two paragraphs -- never less than the line's own height, so that
    two lines cannot overlap. The cell's last line here has no next line and keeps its height.
    """
    if following is None:
        return None, None
    if line.top is not None and following.top is not None and following.top > line.top:
        return _hwp_to_mm(following.top - line.top), following.top - line.top
    height = _hwp_to_mm(line.height)
    kind, value = style.get("line_spacing", ("PERCENT", 160))
    if kind == "FIXED":
        room = _hwp_to_mm(value)
    elif kind == "BETWEEN_LINES":
        room = height + _hwp_to_mm(value)
    elif kind == "AT_LEAST":
        room = max(height, _hwp_to_mm(value))
    elif kind == "PERCENT":
        room = height + (height if character_mm is None else character_mm) * (value - 100) / 100
    else:
        room = height
    if following.paragraph != line.paragraph:
        room += style.get("margins_mm", {}).get("bottom", 0.0) + following_style.get("margins_mm", {}).get("top", 0.0)
    return max(room, height), None


def _placed_cell_lines(
    cell: ET.Element, placement: Any, styles: Mapping[str, Any], counter: _ObjectCounter, *,
    page: int | None, table_placements: Mapping[Any, Any] | None, issues: Counter[tuple[str, str]] | None,
    sources: _ParagraphSources | None, cell_objects: _CellObjects | None, plan: _CellPlan | None,
) -> list[str]:
    """The part of a cell the engine placed on a page: its lines in order, a table on the line holding it.

    Nothing of the cell's own paragraphs is dropped. A paragraph whose text the engine's lines do not
    give in full (a line without text, a paragraph without a line, objects set as characters) is
    drawn whole, once, in the part where it begins (*plan*); its other parts show a marker. What else
    a paragraph anchors -- floating objects, tables the engine sets on no line -- follows it there.
    Without a plan (a repeated header row) the part stands for itself.
    """
    own = cell.findall(f"{_HP}subList/{_HP}p")
    held = {placed.table: element for element, placed in (table_placements or {}).items()}
    hosted = sources.hosted_tables if sources is not None else frozenset()
    para_styles = styles["para"]
    here = id(placement)

    def style_of(index: int) -> Mapping[str, Any]:
        return para_styles.get(own[index].get("paraPrIDRef") or "0", {})

    lines = tuple(line for line in _fragment_lines(placement) if line.paragraph < len(own))
    met = {line.paragraph for line in lines}
    if plan is not None:
        whole = plan.whole
        begins = {index for index, part in plan.home.items() if part == here}
    else:
        whole = frozenset(
            line.paragraph for line in lines
            if not getattr(line, "tables", ()) and (line.text is None or _has_inline_objects(own[line.paragraph]))
        )
        begins = met
    body: list[str] = []
    done: set[int] = set()
    stacked = False

    def anchored(index: int) -> None:
        """Tables of the paragraph the engine sets on no line."""
        for nested in _anchored_tables(own[index], areas=False):
            found = table_placements.get(nested) if table_placements is not None else None
            if found is None or found.table not in hosted:
                body.append(_nested_table(
                    nested, styles, counter, page=page, table_placements=table_placements, issues=issues,
                    sources=sources, every_page=True,
                ))

    def draw_whole(index: int) -> None:
        done.add(index)
        if index not in begins:
            if index in met:
                body.append(f'<p class="hwpx-paragraph">{_render_object_marker(_CONTINUED_PARAGRAPH)}</p>')
            return
        paragraph = own[index]
        if _paragraph_text(paragraph).strip() or _has_objects(paragraph):
            body.append(_render_paragraph(
                paragraph, styles, counter, include_tables=False, extended_styles=True, cell_objects=cell_objects,
            ))
            if issues is not None:
                issues[_WHOLE_PARAGRAPH] += 1
        anchored(index)

    def before(limit: int) -> None:
        """Whole paragraphs beginning here that come before paragraph *limit* and have no line here."""
        for index in sorted(whole & begins - met - done):
            if index < limit:
                draw_whole(index)

    for position, line in enumerate(lines):
        index = line.paragraph
        before(index)
        paragraph = own[index]
        following = lines[position + 1] if position + 1 < len(lines) else None
        style = style_of(index)
        following_style = style_of(following.paragraph) if following is not None else {}
        tables = getattr(line, "tables", ())
        if tables:
            run = next((run for run in paragraph.findall(f"{_HP}run") if _find_text_in_run(run)), None)
            if run is None:
                run = paragraph.find(f"{_HP}run")
            char = styles["char"].get(run.get("charPrIDRef") or "0", {}) if run is not None else {}
            room, engine = _cell_line_room(
                line, following, style, following_style, character_mm=char.get("font_size_pt", 10.0) * 25.4 / 72,
            )
            stacked = stacked or (room is not None and engine is None)
            inner = "".join(
                _nested_table(held[number], styles, counter, page=page, table_placements=table_placements,
                              issues=issues, sources=sources)
                for number in tables if number in held
            )
            css = _style_attr({
                "--hwpx-line-height": _fmt_mm(_hwp_to_mm(line.height)),
                "--hwpx-line-advance": _fmt_mm(room) if room is not None else None,
            })
            body.append(f'<div class="hwpx-engine-cell-line" data-engine-host="1" style="{css}">{inner}</div>')
        elif index in whole:
            if index not in done:
                draw_whole(index)
        else:
            room, engine = _cell_line_room(line, following, style, following_style)
            stacked = stacked or (room is not None and engine is None)
            body.append(_cell_line_markup(line, paragraph, styles, room=room, engine_advance=engine))
        if following is None or following.paragraph != index:
            if index in whole:
                if index not in done:  # only lines holding tables: the paragraph's own text follows them
                    draw_whole(index)
            elif index in begins:
                # What the paragraph anchors beside its lines stands after them, where it begins.
                if cell_objects is not None:
                    extras = "".join(
                        cell_objects.markup(node)
                        for run in paragraph.findall(f"{_HP}run") for node in _run_objects(run)
                    )
                    if extras:
                        body.append(f'<div class="hwpx-engine-cell-objects">{extras}</div>')
                anchored(index)
    before(len(own))
    if stacked and issues is not None:
        issues[_STACKED_CELL] += 1
    return body


def _cell_line_markup(
    line: Any, paragraph: ET.Element, styles: Mapping[str, Any], *,
    room: float | None = None, engine_advance: int | None = None,
) -> str:
    """One text line of a cell: as tall as the line, taking *room* down to the next line's top."""
    run = next((run for run in paragraph.findall(f"{_HP}run") if _find_text_in_run(run)), None)
    char = styles["char"].get(run.get("charPrIDRef", "0") if run is not None else "0", {})
    para_style = styles["para"].get(paragraph.get("paraPrIDRef") or "0", {})
    margins = para_style.get("margins_mm", {})
    indent = margins.get("indent", 0.0)
    # A first line is set in by a positive indent; the lines after it by a negative one.
    left = margins.get("left", 0.0) + (max(indent, 0.0) if line.line == 0 else max(-indent, 0.0))
    right = margins.get("right", 0.0)
    align = para_style.get("align", "left")
    css = _style_attr({
        "line-height": _fmt_mm(_hwp_to_mm(line.height)),
        "height": _fmt_mm(room) if room is not None else None,
        "font-size": _fmt_pt(char.get("font_size_pt", 10.0)),
        "color": char.get("color", "#000000"),
        "white-space": "pre",
        "text-align": align if align != "left" else None,
        "margin-left": _fmt_mm(left) if left > 0 else None,
        "margin-right": _fmt_mm(right) if right > 0 else None,
    })
    # A line without text here belongs to a paragraph that has none: it keeps its room.
    text = _label_markup(paragraph, styles, line) + (_styled_line_text(line, styles) if line.text is not None else "")
    pitch = ""
    if engine_advance is not None:
        pitch = f' data-engine-advance="{engine_advance}"'
    elif room is not None:
        pitch = ' data-line-pitch="file"'
    return (
        f'<div class="hwpx-engine-cell-line" data-text-start="{line.text_start}" '
        f'data-text-end="{line.text_end}"{pitch} style="{css}">{text}</div>'
    )


def _table_caption_markup(
    table: ET.Element, captions: tuple[Any, ...], styles: Mapping[str, Any], counter: _ObjectCounter,
    *, approximate: bool,
) -> str:
    if not captions and not approximate:
        return ""
    caption = table.find(f"{_HP}caption")
    if caption is None:
        return ""
    paragraphs = caption.findall(f"{_HP}subList/{_HP}p")
    text = "".join(_render_paragraph(para, styles, counter, include_tables=False) for para in paragraphs)
    side = captions[0].side if captions else "top" if caption.get("side") == "TOP" else "bottom"
    return f'<caption style="caption-side:{side}">{text}</caption>'


def _render_paragraph(
    paragraph: ET.Element,
    styles: Mapping[str, Any],
    counter: _ObjectCounter,
    *,
    include_tables: bool = True,
    include_objects: bool = True,
    extended_styles: bool = False,
    cell_objects: _CellObjects | None = None,
    diagonals: Counter[tuple[str, str]] | None = None,
) -> str:
    """A paragraph the approximate way, and after it the tables it holds (their cell diagonals drawn
    on an engine page, *diagonals* counting what of them is approximate)."""
    text_html = _label_markup(paragraph, styles) + _render_inline_runs(
        paragraph, styles, counter, include_objects=include_objects, extended_styles=extended_styles,
        cell_objects=cell_objects,
    )
    css = _paragraph_style(paragraph, styles)
    classes = ["hwpx-paragraph"]
    if not text_html:
        classes.append("hwpx-empty-paragraph")
        text_html = "&nbsp;"
    result = [f'<p class="{" ".join(classes)}" style="{css}">{text_html}</p>']
    if include_tables:
        for table in paragraph.findall(f".//{_HP}tbl"):
            result.append(_render_table(table, styles, counter, diagonals=diagonals))
    return "".join(result)


def _section_blocks(section: ET.Element) -> list[ET.Element]:
    """The paragraphs of a section in order, and a table set right in the section (not in a paragraph)."""
    return [child for child in section if child.tag in (f"{_HP}p", f"{_HP}tbl")]


def _split_section_pages(section: ET.Element) -> list[list[ET.Element]]:
    pages: list[list[ET.Element]] = [[]]
    for paragraph in _section_blocks(section):
        if paragraph.tag == f"{_HP}p" and paragraph.get("pageBreak") == "1" and pages[-1]:
            pages.append([])
        pages[-1].append(paragraph)
    return [page for page in pages if page]


def _render_page(
    page_index: int,
    section_index: int,
    paragraphs: list[ET.Element],
    section: ET.Element,
    styles: Mapping[str, Any],
    counter: _ObjectCounter,
) -> tuple[str, PreviewPage]:
    width_mm, height_mm, margins_mm = _page_spec(section)
    page_id = f"hwpx-preview-page-{page_index + 1}"
    page_style = _style_attr(
        {
            "width": _fmt_mm(width_mm),
            "min-height": _fmt_mm(height_mm),
            "padding": (
                f"{_fmt_mm(margins_mm['top'])} {_fmt_mm(margins_mm['right'])} "
                f"{_fmt_mm(margins_mm['bottom'])} {_fmt_mm(margins_mm['left'])}"
            ),
        }
    )
    # A table right in the section is drawn where it stands among the paragraphs.
    body = "".join(
        _render_table(p, styles, counter) if p.tag == f"{_HP}tbl" else _render_paragraph(p, styles, counter)
        for p in paragraphs
    )
    table_count = sum(len(p.findall(f".//{_HP}tbl")) + (p.tag == f"{_HP}tbl") for p in paragraphs)
    page = PreviewPage(
        index=page_index,
        section_index=section_index,
        page_id=page_id,
        width_mm=width_mm,
        height_mm=height_mm,
        margins_mm=margins_mm,
        paragraph_count=sum(p.tag == f"{_HP}p" for p in paragraphs),
        table_count=table_count,
    )
    html_page = (
        f'<section id="{page_id}" class="hwpx-preview-page" '
        f'data-page-index="{page_index}" data-section-index="{section_index}" '
        f'style="{page_style}">{body}</section>'
    )
    return html_page, page


def _base_css(mode: str) -> str:
    long_page_css = ""
    if mode == "long":
        long_page_css = ".hwpx-preview-page { min-height: auto !important; }\n"
    return (
        "html { background: #f2f3f5; }\n"
        "body { margin: 0; padding: 12mm; color: #111827; "
        "font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif; }\n"
        ".hwpx-preview-page { box-sizing: border-box; background: #fff; "
        "margin: 0 auto 10mm; box-shadow: 0 0 0 1px #cfd4dc, "
        "0 6px 18px rgba(15, 23, 42, 0.16); overflow: hidden; }\n"
        ".hwpx-engine-page { height: auto; overflow: visible; }\n"
        ".hwpx-engine-canvas { position: relative; isolation: isolate; }\n"
        ".hwpx-engine-canvas :is(.hwpx-engine-line, .hwpx-engine-area-line, .hwpx-placed-object) "
        "{ position: absolute; }\n"
        ".hwpx-engine-line, .hwpx-engine-area-line { margin: 0; white-space: pre; "
        "overflow: visible; overflow-wrap: normal; word-break: normal; }\n"
        # A table at the engine's coordinates: cells at their rectangles, borders over the fills, lines over both.
        ".hwpx-engine-table { position: absolute; isolation: isolate; margin: 0; font-size: 10pt; }\n"
        ".hwpx-engine-cell { position: absolute; box-sizing: border-box; margin: 0; }\n"
        ".hwpx-cell-frame { position: absolute; box-sizing: border-box; z-index: 1; pointer-events: none; }\n"
        ".hwpx-engine-cell > .hwpx-engine-cell-line { position: absolute; z-index: 2; margin: 0; "
        "white-space: pre; overflow: visible; }\n"
        # A cell's diagonals span its box (a positioned cell's rectangle, a flowing cell's td), under its lines.
        ".hwpx-cell-diagonal { position: absolute; inset: 0; width: 100%; height: 100%; z-index: 1; "
        "overflow: visible; pointer-events: none; }\n"
        ".hwpx-engine-flow { display: flow-root; }\n"
        ".hwpx-engine-flow :is(.hwpx-engine-line, .hwpx-engine-area-line) "
        "{ margin-left: var(--hwpx-line-offset, 0mm); "
        "min-height: var(--hwpx-line-height); }\n"
        # A flow line takes the engine's distance to the next line's top, not its glyph height.
        ".hwpx-engine-flow [data-engine-advance] "
        "{ height: var(--hwpx-line-advance); min-height: 0; }\n"
        # An empty line holding objects placed as characters grows with them; the line is their room.
        ".hwpx-engine-flow [data-engine-host] { height: auto; white-space: normal; "
        "min-height: var(--hwpx-line-advance, var(--hwpx-line-height)); }\n"
        ".hwpx-engine-flow [data-engine-host] > .hwpx-table { margin: 0 !important; }\n"
        ".hwpx-engine-cell-objects { white-space: normal; }\n"
        ".hwpx-object-caption { display: block; white-space: normal; }\n"
        ".hwpx-cell-picture { display: inline-block; vertical-align: bottom; }\n"
        ".hwpx-engine-flow-page { position: relative; isolation: isolate; }\n"
        # A flow page with columns: a row per column area, a box per column (not positioned: what stands
        # on the paper is still placed from the page box).
        ".hwpx-engine-column-area { display: flex; align-items: flex-start; }\n"
        ".hwpx-engine-column { flex: none; display: flow-root; min-width: 0; }\n"
        # The line between two columns, on the paper (a flow page's too), centred on the middle of their gap.
        ".hwpx-column-line { position: absolute; width: 0; margin: 0; pointer-events: none; }\n"
        # What the approximate flow stacks past the body's foot: under the page box, marked.
        ".hwpx-engine-spill { position: absolute; top: 100%; left: 0; right: 0; box-sizing: border-box; isolation: isolate; "
        "padding-top: 1mm !important; padding-bottom: 2mm !important; background: #fff8ef; "
        "border-top: 0.6mm dashed #d08a3a; box-shadow: 0 0 0 1px #e8c9a4; }\n"
        ".hwpx-engine-spill::before { display: table; margin: 0 0 1mm; padding: 0 1mm; color: #6b4a1a; "
        "background: #fff8ef; font-size: 8pt; "
        "content: '넘침 · 엔진은 이 쪽 본문에 넣었으나 근사 배치가 본문 높이를 넘은 부분'; }\n"
        ".hwpx-engine-spill .hwpx-engine-column-area { min-height: 0 !important; }\n"
        # A footer (and a page number at the foot) of a flow page stands on the page box's foot.
        ".hwpx-area-foot { position: absolute; left: 0; right: 0; bottom: 0; "
        "height: var(--hwpx-paper-height); margin: 0; pointer-events: none; }\n"
        ".hwpx-page-number { position: absolute; display: flex; align-items: center; box-sizing: border-box; "
        "margin: 0; font-size: 10pt; white-space: pre; }\n"
        ":is(.hwpx-page-number, .hwpx-page-number-text)::before { content: attr(data-number-text); }\n"
        ".hwpx-placed-object { display: block; box-sizing: border-box; margin: 0; }\n"
        ".hwpx-placed-object[data-overlay] { position: absolute; }\n"
        ".hwpx-placed-object[data-overlay=behind] { z-index: -1; }\n"
        ".hwpx-placed-object[data-overlay=front] { z-index: 2; }\n"
        ".hwpx-floating-table > .hwpx-table { margin: 0 !important; }\n"
        # A table over or under the text running past the paper's foot: the page keeps the room, marked.
        ".hwpx-engine-page[data-float-overflow=true] { outline: 1px dashed #c58a1b; outline-offset: 2px; }\n"
        ".hwpx-placed-object img { display: block; width: 100%; height: 100%; }\n"
        ".hwpx-placed-object.hwpx-shape-outline { border: 1px solid #646e79; }\n"
        # A group's members and a text box's lines stand at their places in the object's box.
        ".hwpx-group { position: relative; }\n"
        ".hwpx-group > .hwpx-placed-object { position: absolute; }\n"
        ".hwpx-placed-object > .hwpx-engine-cell-line { position: absolute; z-index: 2; margin: 0; "
        "white-space: pre; overflow: visible; }\n"
        # A flat line (no height or no width) keeps a box the browser draws.
        ".hwpx-shape-svg { position: absolute; inset: 0; width: 100%; height: 100%; min-width: 1px; "
        "min-height: 1px; overflow: visible; }\n"
        ".hwpx-box-text { white-space: pre-wrap; font-size: 10pt; }\n"
        # A chart, an embedded or form object (or a picture the browser cannot show): its box and a marker.
        ".hwpx-object-placeholder { border: 1px dashed #9aa2ad; background: #f7f8fa; }\n"
        # A header, footer or note stands at its place on the paper, beside the body (a flow page included).
        ".hwpx-area-layer { position: absolute; inset: 0; margin: 0; pointer-events: none; }\n"
        ".hwpx-area-layer > .hwpx-engine-area-line { position: absolute; margin-left: 0; }\n"
        ".hwpx-area-room { position: absolute; overflow: visible; }\n"
        # A table in a header or footer drawn whole takes its own height only: the room is the area's.
        ".hwpx-area-room > .hwpx-table, .hwpx-area-paragraph > .hwpx-table { margin: 0 !important; }\n"
        # A paragraph of a room drawn whole, at its first line's top where the engine gives it.
        ".hwpx-area-paragraph { position: absolute; left: 0; right: 0; margin: 0; }\n"
        # What stands across a flow page's columns, above their boxes.
        ".hwpx-engine-column-across > .hwpx-table { margin-top: 0 !important; }\n"
        # What stands at a place the engine does not give is marked as approximate.
        "[data-approx] { outline: 1px dashed #d08a3a; outline-offset: -1px; }\n"
        ".hwpx-page-fill { position: absolute; inset: 0; z-index: -1; margin: 0; "
        "background-repeat: repeat-y; }\n"
        ".hwpx-engine-page-status { position: absolute; top: 1mm; inset-inline: 2mm; "
        "margin: 0; color: #6b4a1a; font-size: 8pt; text-align: right; }\n"
        ".hwpx-paragraph { white-space: pre-wrap; word-break: break-word; }\n"
        ".hwpx-empty-paragraph { min-height: 1em; }\n"
        ".hwpx-table { font-size: 10pt; }\n"
        ".hwpx-table td { box-sizing: border-box; overflow-wrap: anywhere; }\n"
        ".hwpx-equation { display: inline-block; vertical-align: middle; }\n"
        ".hwpx-equation math { font-size: 1.08em; }\n"
        ".hwpx-equation-fallback { display: inline-flex; align-items: baseline; "
        "gap: 0.4em; padding: 0.05em 0.4em; border: 1px solid #d7b48a; "
        "border-radius: 4px; background: #fff7ec; white-space: normal; }\n"
        ".hwpx-equation-tag { font-size: 0.72em; color: #8a5a12; "
        "font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif; }\n"
        ".hwpx-equation-fallback code { font-size: 0.9em; color: #40320f; "
        "font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace; }\n"
        ".hwpx-object-marker { display: inline-block; padding: 0 0.3em; "
        "border: 1px dashed #9aa2ad; border-radius: 4px; color: #4b5563; "
        "font-size: 0.9em; background: #eef1f5; }\n"
        ".hwpx-shape-text { margin-left: 0.3em; }\n"
        "@media print { body { padding: 0; background: #fff; } "
        ".hwpx-preview-page { margin: 0; box-shadow: none; page-break-after: always; } }\n"
        f"{long_page_css}"
    )


#: Markup the page script works on besides flow pages: cell lines to narrow, tables over or under the text.
_SCRIPTED = ("hwpx-engine-cell-line", "hwpx-floating-table")


def _flow_overflow_script() -> str:
    return """<script>
(() => {
  // A cell line is the engine's line: where this browser's glyphs run wider than the cell,
  // the line is narrowed to its room (to three fifths at most) instead of breaking anew.
  document.querySelectorAll('.hwpx-engine-cell-line[data-text-start]').forEach(line => {
    const room = line.clientWidth, need = line.scrollWidth;
    if (room > 0 && need > room + 1) {
      const scale = Math.max(room / need, 0.6);
      line.style.transformOrigin = 'left center';
      line.style.transform = 'scaleX(' + scale.toFixed(4) + ')';
      line.dataset.fitted = scale.toFixed(3);
    }
  });
  // A flow page keeps its paper's height. What its approximate flow stacks past the body's foot
  // (in each column) moves, in order, into the overflow band under the page box, which shows it.
  // What stands on the paper (headers, footers, objects over or under the text) stays.
  function inFlow(item) {
    const position = getComputedStyle(item).position;
    return position !== 'absolute' && position !== 'fixed';
  }
  // The rows of a table (alone, or the one table a line holds) below the foot, moved into a copy of
  // the table (and of the line holding it); null when no row above the foot stays.
  function splitRows(item, foot) {
    const table = item.tagName === 'TABLE' ? item : item.querySelector(':scope > table');
    if (!table || (item !== table && item.querySelectorAll(':scope > table').length !== 1)) return null;
    const rows = [...table.rows].filter(row => row.parentElement.closest('table') === table);
    const at = rows.findIndex(row => row.getBoundingClientRect().bottom > foot);
    if (at <= 0) return null;
    const rest = table.cloneNode(false);
    table.querySelectorAll(':scope > colgroup').forEach(group => rest.appendChild(group.cloneNode(true)));
    const part = document.createElement('tbody');
    rows.slice(at).forEach(row => part.appendChild(row));
    rest.appendChild(part);
    rest.dataset.continued = '1';
    if (item === table) return rest;
    const holder = item.cloneNode(false);
    holder.appendChild(rest);
    return holder;
  }
  function spill(page) {
    const body = page.querySelector(':scope > .hwpx-engine-flow');
    const band = page.querySelector(':scope > .hwpx-engine-spill');
    if (!body || !band) return;
    const foot = body.getBoundingClientRect().top + parseFloat(getComputedStyle(body).minHeight) + 0.5;
    const into = band.querySelector('.hwpx-engine-spill-flow');
    const copies = new Map();
    function copy(holder) {
      if (holder === body) return into;
      if (!copies.has(holder)) {
        const row = holder.parentElement;
        if (!copies.has(row)) {
          const rowCopy = row.cloneNode(false);
          into.appendChild(rowCopy);
          copies.set(row, rowCopy);
        }
        const holderCopy = holder.cloneNode(false);
        copies.get(row).appendChild(holderCopy);
        copies.set(holder, holderCopy);
      }
      return copies.get(holder);
    }
    const room = parseFloat(getComputedStyle(body).minHeight);
    const holders = body.querySelectorAll(':scope > .hwpx-engine-column-area > .hwpx-engine-column');
    let moved = 0, shows = 0;
    const drawn = 'img, svg, table, math, [style*="border"], .hwpx-placed-object';
    const shown = item => (item.textContent.trim() || item.matches(drawn) || item.querySelector(drawn)) ? 1 : 0;
    for (const holder of (holders.length ? holders : [body])) {
      const items = [...holder.children].filter(inFlow);
      let first = items.findIndex(item => item.getBoundingClientRect().bottom > foot);
      if (first < 0) continue;
      const target = copy(holder);
      const across = items[first];
      if (across.getBoundingClientRect().top < foot) {
        // Across the foot: a table keeps the rows above it and moves the rest; anything else
        // taller than half the body stays whole (the page box grows), a shorter one moves.
        const rest = splitRows(across, foot);
        if (rest) {
          target.appendChild(rest);
          moved += 1;
          shows += 1;
          first += 1;
        } else if (across.getBoundingClientRect().height > room / 2) {
          first += 1;
        }
      }
      items.slice(first).forEach(item => { target.appendChild(item); moved += 1; shows += shown(item); });
    }
    if (moved && !shows) {
      // Only lines showing nothing ran past the foot (empty paragraphs): the band stays hidden.
      moved = 0;
    }
    if (moved) {
      // The band runs on from the page: the page's fill is behind it too (light text on it stays legible).
      const fill = page.querySelector(':scope > .hwpx-page-fill');
      if (fill && !band.querySelector(':scope > .hwpx-page-fill')) band.prepend(fill.cloneNode(true));
      band.hidden = false;
      const base = parseFloat(page.dataset.flowMargin || getComputedStyle(page).marginBottom) || 0;
      page.dataset.flowMargin = String(base);
      page.style.marginBottom = (base + band.getBoundingClientRect().height) + 'px';
    }
    const spilled = !band.hidden;
    page.dataset.flowOverflow = String(spilled);
    page.dataset.flowSpilled = String(Number(page.dataset.flowSpilled || 0) + moved);
    page.dataset.flowHeight = Math.ceil(page.getBoundingClientRect().height + (spilled ? band.getBoundingClientRect().height : 0));
    page.querySelector('.hwpx-engine-overflow').hidden = !spilled;
  }
  // A table over or under the text stands at an approximate place on its page; what of it runs past
  // the paper's foot is not hidden under the next page: the page box grows (its fill with it), marked.
  function hang(page) {
    const canvas = page.querySelector(':scope > .hwpx-engine-canvas');
    if (!canvas) return;
    const paper = parseFloat(canvas.dataset.paperHeight || getComputedStyle(canvas).height);
    canvas.dataset.paperHeight = String(paper);
    const top = canvas.getBoundingClientRect().top;
    let below = 0;
    canvas.querySelectorAll('.hwpx-floating-table').forEach(table => {
      below = Math.max(below, table.getBoundingClientRect().bottom - top - paper);
    });
    page.dataset.floatOverflow = String(below > 0.5);
    canvas.style.height = (paper + Math.max(0, below)) + 'px';
  }
  const pages = [...document.querySelectorAll('.hwpx-engine-flow-page')];
  const hung = [...document.querySelectorAll('.hwpx-engine-page')].filter(page => page.querySelector('.hwpx-floating-table'));
  pages.forEach(spill);
  hung.forEach(hang);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { pages.forEach(spill); hung.forEach(hang); });
})();
</script>
"""


def _document_html(
    *,
    title: str,
    mode: str,
    body: str,
    screenshot: bool = False,
    fidelity_tier: str = _APPROX,
    has_flow: bool = False,
) -> str:
    extra_css = ""
    if screenshot:
        extra_css = (
            "html, body { background: #fff; }\n"
            "body { padding: 0; }\n"
            ".hwpx-preview-page { margin: 0; box-shadow: none; }\n"
        )
    else:
        extra_css = (
            'body::before { display: block; margin: 0 auto 3mm; text-align: center; '
            f'font-size: 9pt; color: #4b5563; content: "{_BADGES[fidelity_tier]}"; }}'
        )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="ko">\n'
        "<head>\n"
        '  <meta charset="utf-8" />\n'
        f"  <title>{html.escape(title)}</title>\n"
        f'  <meta name="hwpx-preview-fidelity" content="{fidelity_tier}" />\n'
        f"  <style>{_base_css(mode)}{extra_css}</style>\n"
        "</head>\n"
        f'<body data-hwpx-preview-mode="{html.escape(mode)}">\n'
        f"{body}\n"
        f"{_flow_overflow_script() if has_flow or any(mark in body for mark in _SCRIPTED) else ''}"
        "</body>\n"
        "</html>\n"
    )


def _styled_line_text(
    line: Any, styles: Mapping[str, Any], inserts: tuple[tuple[int, str, str], ...] = (),
) -> str:
    """A line's text in its runs' character styles; each of *inserts* (offset in the line's text, text,
    character style reference) is set in at its offset: a page number the engine's text leaves out."""
    runs = list(getattr(line, "runs", ()))
    if not runs:
        if not inserts:
            return html.escape(line.text.removesuffix("\n"))
        runs = [(inserts[0][2], line.text)]
    pieces: list[tuple[str, str, bool]] = []
    offset = 0
    pending = sorted(inserts)
    for index, (reference, text) in enumerate(runs):
        if index == len(runs) - 1:
            text = text.removesuffix("\n")
        while pending and pending[0][0] <= offset + len(text):
            at, number, own = pending.pop(0)
            cut = max(0, at - offset)
            pieces.append((reference, text[:cut], False))
            pieces.append((own, number, True))
            text, offset = text[cut:], offset + cut
        pieces.append((reference, text, False))
        offset += len(text)
    pieces.extend((own, number, True) for _, number, own in pending)
    spans = []
    for reference, text, inserted in pieces:
        if not text:
            continue
        css = _character_css(styles["char"].get(reference, {}), extended=True)
        spans.append(_number_span(text, css) if inserted else f'<span style="{css}">{html.escape(text)}</span>')
    return "".join(spans)


def _line_frame(line: Any, page: Any) -> tuple[float, float | None, float, bool]:
    """Paper x, column-area offset and width of a line, and whether its horizontal placement is incomplete."""
    left, _, body_width, _ = page.body
    area = next((area for area in reversed(page.column_areas) if area.top <= line.top), None)
    column = line.position.column
    # The first column starts at the body's left edge whatever columns are set (a header's line stands above them).
    column_x = 0 if column == 0 else None if area is None or column >= len(area.widths) or area.gap is None else (
        sum(area.widths[:column]) + column * area.gap
    )
    offset = column_x + line.x if column_x is not None and line.x is not None else None
    approximate = bool(line.text) and (offset is None or line.width is None)
    width = line.width if line.width is not None else (
        area.widths[column] if area is not None and column < len(area.widths) else body_width
    )
    return left + (column_x or 0) + (line.x or 0), offset, width, approximate


def _line_advance(line: Any, following: Any) -> int | None:
    """The engine's distance from this line's top to the next line's, in the same page and column."""
    if following is None or following.position.page != line.position.page:
        return None
    if following.position.column != line.position.column or following.top <= line.top:
        return None
    return following.top - line.top


def _engine_line(
    line: Any, paragraph: Any, styles: Mapping[str, Any], page: Any, *, area_line: bool = False,
    advance: int | None = None, hosted: str = "", in_column: bool = False,
    inserts: tuple[tuple[int, str, str], ...] = (),
) -> tuple[str, bool]:
    """One engine line. In a flow page it takes *advance*, and *hosted* is drawn inside it; *in_column*,
    it stands in its column's own box, its offset taken from the column's left edge. *inserts* are
    page numbers set into its text (see :func:`_styled_line_text`)."""
    paper_x, offset, width, approximate = _line_frame(line, page)
    if in_column:
        offset = line.x
    column = line.position.column
    run = next((run for run in paragraph.findall(f"{_HP}run") if _find_text_in_run(run)), None)
    char = styles["char"].get(run.get("charPrIDRef", "0") if run is not None else "0", {})
    para_style = styles["para"].get(paragraph.get("paraPrIDRef", "0"), {})
    css = _style_attr({
        "left": _fmt_mm(_hwp_to_mm(paper_x)),
        "--hwpx-line-offset": _fmt_mm(_hwp_to_mm(offset)) if offset is not None else None,
        "top": _fmt_mm(_hwp_to_mm(line.top)),
        "width": _fmt_mm(_hwp_to_mm(width)),
        "--hwpx-line-height": _fmt_mm(_hwp_to_mm(line.height)),
        "--hwpx-line-advance": _fmt_mm(_hwp_to_mm(advance)) if advance is not None else None,
        # The objects a host line holds keep their own text metrics.
        "line-height": None if hosted else "var(--hwpx-line-height)",
        "font-size": None if hosted else _fmt_pt(char.get("font_size_pt", 10.0)),
        "color": None if hosted else char.get("color", "#000000"),
        "text-align": None if hosted else para_style.get("align", "left"),
    })
    text = _label_markup(paragraph, styles, line) + _styled_line_text(line, styles, inserts)
    css_class = "hwpx-engine-area-line" if area_line else "hwpx-engine-line"
    attrs = f' data-engine-advance="{advance}"' if advance is not None else ""
    if hosted:
        attrs += ' data-engine-host="1"'
    markup = (
        f'<div class="{css_class}" data-column="{column}" data-text-start="{line.text_start}" '
        f'data-text-end="{line.text_end}"{attrs} style="{css}">{text}{hosted}</div>'
    )
    return markup, approximate


def _open_for_estimate(source: str | Path | bytes) -> tuple[HwpxDocument | None, Exception | None]:
    """Open *source* as the layout estimate reads it: the document, or why python-hwpx refused it.

    The refusal is not raised here. The package's own reader still decides what an
    unreadable source raises, and :func:`_engine_preview` reports or re-raises the rest.
    """
    if getattr(experimental, "estimate_layout", None) is None:
        return None, None
    try:
        return HwpxDocument.open(io.BytesIO(source) if isinstance(source, bytes) else str(source)), None
    except Exception as exc:  # noqa: BLE001 - kept for _engine_preview, which raises what it does not report
        return None, exc


def _document_parts(document: HwpxDocument) -> dict[str, bytes]:
    """The package parts python-hwpx read when it opened the document (one reader for both)."""
    package = document.package
    return {name: package.get_part(name) for name in package.part_names()}


def _conversion_notes(document: HwpxDocument) -> list[tuple[str, int]]:
    """What opening an HWP 5.0 source left out of the document the preview is drawn from."""
    report = getattr(document, "conversion_report", None)
    if report is None:
        return []
    notes = [(f"{kind} is not converted into the previewed document", count)
             for kind, count in sorted(report.unconverted.items())]
    notes += [(f"{kind} has no HWPX form and is left out", count) for kind, count in sorted(report.dropped.items())]
    return notes


def _engine_preview(
    document: HwpxDocument | None, refused: Exception | None, mode: str, title: str,
    styles: Mapping[str, Any], warnings: list[str], parts: Mapping[str, bytes],
) -> LayoutPreview | None:
    estimate_layout = getattr(experimental, "estimate_layout", None)
    if estimate_layout is None:
        warnings.append("layout estimate unavailable in the installed python-hwpx")
        return None
    try:
        if document is None:
            assert refused is not None
            raise refused
        layout = estimate_layout(document)
    except (HwpxError, ValueError, OSError) as exc:
        warnings.append(f"layout estimate unavailable: {type(exc).__name__}")
        return None
    if layout.estimate.pages is None:
        warnings.extend(f"layout estimate declined: {reason}" for reason in layout.estimate.unsupported)
        warnings.extend(f"HWP 5.0 source: {reason} ({count})" for reason, count in _conversion_notes(document))
        return None
    return _render_engine_preview(document, layout, mode, title, styles, warnings, parts)


def _outer_tables(element: ET.Element, *, areas: bool = True) -> Iterator[ET.Element]:
    """Yield tables owned by this anchor. A nested table belongs to its cell.

    Without *areas*, what a header, footer or note holds is left to that area.
    """
    if element.tag == f"{_HP}tbl":
        yield element
    elif areas or element.tag not in _AREA_LABELS:
        for child in element:
            yield from _outer_tables(child, areas=areas)


def _anchored_tables(paragraph: ET.Element, *, areas: bool = True) -> Iterator[ET.Element]:
    for run in paragraph.findall(f"{_HP}run"):
        yield from _outer_tables(run, areas=areas)


def _flow_anchors(
    paragraph: ET.Element, styles: Mapping[str, Any], counter: _ObjectCounter,
    issues: Counter[tuple[str, str]], home: int, sources: _ParagraphSources, table_counts: Counter[int],
    pages: tuple[Any, ...],
) -> list[_AnchorMarkup]:
    anchors = []
    for run in paragraph.findall(f"{_HP}run"):
        for child in run:
            if child.tag == f"{_HP}t":
                continue
            obj = child if child.tag in _OBJECT_TAGS else None
            if child.tag == f"{_HP}switch":
                options = [node for node in child.iter() if node.tag in _OBJECT_TAGS]
                obj = next((node for node in options if node in sources.objects and sources.objects[node].page is not None),
                           options[0] if options else None)
            if obj is not None:
                anchors.append(_object_anchor(
                    obj, home, sources.objects.get(obj), sources.images, issues, counter, styles, sources.objects,
                    lines=sources.lines, pages=pages, paragraph=paragraph,
                ))
            # What a header, footer or note holds is drawn with it, in its room.
            for table in _outer_tables(child, areas=False):
                anchors.extend(_table_anchors(table, styles, counter, issues, home, sources, table_counts, pages))
            for area in child.iter():
                if area.tag in _AREA_LABELS:
                    anchors.extend(_engine_area_anchors(
                        area, home, sources.areas.get(area, []), pages, styles, issues, counter, sources.margins,
                        table_counts, sources.numbering,
                    ))
    return anchors


def _placed_as_character(element: ET.Element) -> bool:
    position = element.find(f"{_HP}pos")
    return position is not None and position.get("treatAsChar") == "1"


def _table_anchors(
    table: ET.Element, styles: Mapping[str, Any], counter: _ObjectCounter, issues: Counter[tuple[str, str]],
    home: int, sources: _ParagraphSources, table_counts: Counter[int], pages: tuple[Any, ...] | None = None,
) -> list[_AnchorMarkup]:
    """A table's markup on each page the engine sets its rows. A page's rows are drawn at the engine's
    coordinates where every value they need is given; else, and on a page drawn as flow, they flow."""
    placements = sources.tables
    placed = placements.get(table)
    inline = _placed_as_character(table)
    if placed is None or not placed.rows:
        count = sum(1 for _ in table.iter(f"{_HP}tbl"))
        issues[("table", "row and cell placement is unavailable")] += count
        table_counts[home] += count
        markup = _render_table(
            table, styles, counter, flow=True, show_approx_caption=True, issues=issues, sources=sources,
        )
        floating = _floating_table(table, markup, sources.lines, pages[home] if pages and 0 <= home < len(pages) else None)
        if floating is not None:
            issues[_APPROX_FLOATING_TABLE] += 1
            return [_AnchorMarkup(home, floating, flow=False, overlay=True)]
        return [_AnchorMarkup(home, markup, inline=inline)]
    plans = _cell_plans(table, placed)
    for nested in table.iter(f"{_HP}tbl"):
        found = placements.get(nested)
        if found is None or not found.rows:
            issues[("table", "nested row placement is unavailable")] += 1
        else:
            for reason in found.unavailable:
                issues[("table", reason)] += 1
            for row in found.rows:
                for cell in row.cells:
                    for reason in cell.unavailable:
                        if not reason.startswith("the cell holds tables"):  # where its lines are, not a lack
                            issues[("table-cell", reason)] += 1
    rows_by_page: dict[int, list[Any]] = {}
    for row in placed.rows:
        rows_by_page.setdefault(row.page, []).append(row)
    fallback_caption = table.find(f"{_HP}caption") is not None and not placed.captions
    if fallback_caption:
        issues[("table", "caption placement is unavailable")] += 1
    anchors = []
    seen: set[int] = set()
    drawable = _drawable_at_coordinates(table, sources.objects, placements)
    held = [node for child in _table_tree(table) for node in _cell_held_objects(child)] if drawable else []
    for page, rows in sorted(rows_by_page.items()):
        table_counts[page] += 1
        captions = tuple(caption for caption in placed.captions if caption.page == page)
        closing = rows[-1] is placed.rows[-1]
        flowing: Counter[tuple[str, str]] = Counter()
        numbered = counter.pictures
        flowing_markup = _render_table(
            table, styles, counter, flow=True, row_parts=tuple(rows), table_index=placed.table,
            table_placements=placements, continued_rows=frozenset(seen), captions=captions,
            show_approx_caption=fallback_caption and page == min(rows_by_page), issues=flowing, sources=sources,
            plans=plans, closing=closing,
        )
        seen.update(row.row for row in rows if not row.repeated)
        at_coordinates: Counter[tuple[str, str]] = Counter()
        positioned = None
        if drawable and pages is not None and 0 <= page < len(pages):
            positioned = _positioned_table(
                table, tuple(rows), placed.table, pages[page], styles, plans, at_coordinates,
                unplaced=closing and _has_unplaced_cells(table, plans), placements=placements,
            )
        box = _rows_box(table, rows)
        if positioned is None:
            anchors.append(_AnchorMarkup(page, flowing_markup, inline=inline, issues=flowing, table=id(table), box=box))
        else:
            anchors.append(_AnchorMarkup(
                page, positioned, flow=False, inline=inline, flow_html=flowing_markup, issues=at_coordinates,
                flow_issues=flowing, table=id(table), box=box,
            ))
            # The objects its cells hold stand at their own places; a flow page draws them in the flowing rows.
            # Either way a picture takes the number the flowing rows gave it.
            flowed, counter.pictures = counter.pictures, numbered
            for node in held:
                found = sources.objects.get(node)
                if found is None or found.page != page:
                    continue
                drawn: Counter[tuple[str, str]] = Counter()
                anchor = _object_anchor(node, page, found, sources.images, drawn, counter, styles, sources.objects,
                                        pages=pages or ())
                anchors.append(_AnchorMarkup(page, anchor.html, flow=False, overlay=anchor.overlay, flow_html="",
                                             issues=drawn))
            counter.pictures = max(flowed, counter.pictures)
    return anchors


def _rows_box(table: ET.Element, rows: list[Any]) -> tuple[int, int, int] | None:
    """The engine's box of a table's rows on one page: (paper top of the first, foot of the last, the table's
    width), HWPUNIT; ``None`` when a row has no top or height."""
    if not rows or any(row.top is None or row.height is None for row in rows):
        return None
    size = table.find(f"{_HP}sz")
    return (min(row.top for row in rows), max(row.top + row.height for row in rows),
            _safe_int(size.get("width")) if size is not None else 0)


_FLOWING_TABLE = ("table", "table content uses approximate flow within engine row pages")
_APPROX_FLOATING_TABLE = ("table", "table in front of or behind the text is drawn at an approximate place")


def _floating_table(table: ET.Element, markup: str, lines: tuple[Any, ...], page: Any) -> str | None:
    """A table set in front of or behind the text, which the engine does not place, drawn over the page at
    an approximate place: its ``hp:pos`` offset from what it is set against (the paper, the body, its
    paragraph's column or first line on *page*), aligned as the file says. It takes no room from the
    text, so its page keeps the engine's lines. ``None`` for any other table (it flows)."""
    position = table.find(f"{_HP}pos")
    wrap = table.get("textWrap") or ""
    if page is None or position is None or wrap not in _FLOATING or _placed_as_character(table):
        return None
    own = [line for line in lines if line.position.page == page.page]
    first = own[0] if own else None
    size = table.find(f"{_HP}sz")
    width, height = (_safe_int(size.get("width")), _safe_int(size.get("height"))) if size is not None else (0, 0)
    body_x, body_top, body_width, body_height = page.body

    def start(relative: str, *, across: bool) -> tuple[int, int]:
        """Where the reference begins and how long it is, across the page (x) or down it (top)."""
        if relative == "PAPER":
            return 0, page.paper_width if across else page.paper_height
        if relative == "PAGE" or first is None:
            return (body_x, body_width) if across else (body_top, body_height)
        if not across:
            return first.top, first.height
        if relative == "COLUMN":
            left = _column_left(page, first.position.column, first.top)
            area = next((area for area in reversed(page.column_areas) if area.top <= first.top), None)
            room = area.widths[first.position.column] if area is not None and first.position.column < len(
                area.widths) else body_width
            return (left, room) if left is not None else (body_x, body_width)
        frame = _line_frame(first, page)
        return round(frame[0]), round(frame[2])

    def place(relative: str, align: str, offset: int, extent: int, *, across: bool) -> int:
        origin, room = start(relative, across=across)
        if align in ("RIGHT", "BOTTOM"):
            return origin + room - extent - offset
        if align == "CENTER":
            return origin + (room - extent) // 2 + offset
        return origin + offset

    x = place((position.get("horzRelTo") or "COLUMN").upper(), (position.get("horzAlign") or "LEFT").upper(),
              _safe_int(position.get("horzOffset")), width, across=True)
    top = place((position.get("vertRelTo") or "PARA").upper(), (position.get("vertAlign") or "TOP").upper(),
                _safe_int(position.get("vertOffset")), height, across=False)
    layer = "front" if wrap == "IN_FRONT_OF_TEXT" else "behind"
    css = _style_attr({"left": _fmt_mm(_hwp_to_mm(x)), "top": _fmt_mm(_hwp_to_mm(top)),
                       "width": _fmt_mm(_hwp_to_mm(width)) if width > 0 else None})
    return (f'<div class="hwpx-placed-object hwpx-floating-table" data-object-kind="table" data-overlay="{layer}" '
            f'data-approx="place" style="{css}">{markup}</div>')


def _cell_held_objects(table: ET.Element) -> list[ET.Element]:
    """The objects the cells of *table* anchor in their own paragraphs (a nested table's are its own)."""
    return [
        node for cell in table.findall(f"{_HP}tr/{_HP}tc") for paragraph in cell.findall(f"{_HP}subList/{_HP}p")
        for run in paragraph.findall(f"{_HP}run") for node in _run_objects(run)
    ]


def _cell_tables(table: ET.Element) -> list[ET.Element]:
    """The tables the cells of *table* anchor in their own paragraphs (not a header's or footer's)."""
    return [
        nested for cell in table.findall(f"{_HP}tr/{_HP}tc") for paragraph in cell.findall(f"{_HP}subList/{_HP}p")
        for nested in _anchored_tables(paragraph, areas=False)
    ]


def _holds_tables(line: Any) -> bool:
    """Whether a cell line is one the engine gives for the tables it holds."""
    return bool(getattr(line, "tables", ()))


def _table_tree(table: ET.Element) -> list[ET.Element]:
    """*table* and the tables its cells anchor, theirs in turn."""
    return [table] + [node for child in _cell_tables(table) for node in _table_tree(child)]


def _rows_at_coordinates(placed: Any) -> bool:
    """Whether the engine gives every row of a table its paper top, height and left edge."""
    return placed is not None and bool(placed.rows) and all(
        None not in (row.top, row.height, row.x) for row in placed.rows
    )


_PAGE_AREAS = frozenset({f"{_HP}header", f"{_HP}footer"})


def _drawable_at_coordinates(
    table: ET.Element, objects: Mapping[Any, Any] | None = None, placements: Mapping[Any, Any] | None = None,
) -> bool:
    """Whether a table holds only what is drawn at coordinates: its engine cell lines, objects its cells
    anchor that the engine gives a rectangle (with what they hold), and tables its cells set on a line of
    their own that the engine gives every row's place (*placements*), each drawable in turn. A header or
    footer control a cell holds is drawn in its own room, so it takes nothing from the cell. No note or
    caption, and no other table or object: the engine sets no lines for those in a cell, and a table
    holding any of them flows.
    """
    if table.find(f"{_HP}caption") is not None:
        return False
    held = _cell_held_objects(table)
    if any(_object_rect((objects or {}).get(node)) is None for node in held):
        return False
    inside = {node for holder in held for node in holder.iter()}
    nested = _cell_tables(table)
    for node in nested:
        if not _rows_at_coordinates((placements or {}).get(node)) or not _drawable_at_coordinates(
            node, objects, placements,
        ):
            return False
    within = {node for child in nested for node in child.iter()}
    areas = {node for area in table.iter() if area.tag in _PAGE_AREAS for node in area.iter()}
    return not any(
        node is not table and node not in within and node not in areas and (
            node.tag == f"{_HP}tbl" or node.tag in _AREA_LABELS or (node.tag in _OBJECT_TAGS and node not in inside)
        )
        for node in table.iter()
    )


def _has_unplaced_cells(table: ET.Element, plans: Mapping[int, _CellPlan]) -> bool:
    """Whether a cell with content is in no row the engine placed."""
    return any(
        number not in plans and _holds_content(cell) for number, cell in enumerate(table.findall(f"{_HP}tr/{_HP}tc"))
    )


def _column_left(page: Any, column: int, top: int) -> int | None:
    """Paper x of the left edge of *column* on *page*, for the column configuration in force at *top*."""
    area = next((area for area in reversed(page.column_areas) if area.top <= top), None)
    if area is None or column >= len(area.widths) or (column and area.gap is None):
        return None
    left: int = page.body[0] + sum(area.widths[:column]) + column * (area.gap or 0)
    return left


def _half_border(border: str | None) -> str:
    """Half the width of a CSS border side, as the distance its line stands out of the cell's edge."""
    width = (border or "none").split(" ", 1)[0]
    if width.endswith("mm"):
        return f"-{float(width[:-2]) / 2:.3f}mm"
    if width.endswith("px"):
        return f"-{float(width[:-2]) / 2:g}px"
    return "0mm"


def _positioned_table(
    table: ET.Element, rows: tuple[Any, ...], number: int, page: Any, styles: Mapping[str, Any],
    plans: Mapping[int, _CellPlan], issues: Counter[tuple[str, str]], *, unplaced: bool,
    placements: Mapping[Any, Any] | None = None,
) -> str | None:
    """The rows the engine set on one page, drawn at the engine's coordinates; ``None`` when a value is missing.

    Every row needs its paper top, height and left edge; every cell its rectangle; every cell line
    its top, left, width and text, and no paragraph of a cell may need drawing whole. A cell's
    rectangle is the engine's; its border lines stand on the cell's edges (half inside, half out,
    so two cells share one line); its lines stand at the engine's tops, left edges and widths.
    A cell line holding a table (its text not given) draws nothing itself: the table's rows on this
    page are drawn after the outer table, at the engine's coordinates in turn (*placements*).
    """
    if unplaced:
        return None
    nested = []
    for child in _cell_tables(table):
        found: Any = (placements or {}).get(child)
        if not _rows_at_coordinates(found):
            return None
        here = tuple(row for row in found.rows if row.page == page.page)
        if not here:
            continue
        child_plans = _cell_plans(child, found)
        markup = _positioned_table(
            child, here, found.table, page, styles, child_plans, issues,
            unplaced=here[-1] is found.rows[-1] and _has_unplaced_cells(child, child_plans), placements=placements,
        )
        if markup is None:
            return None
        nested.append(markup)
    sources = table.findall(f"{_HP}tr/{_HP}tc")
    boxes = []
    for row in rows:
        if row.top is None or row.height is None or row.x is None:
            return None
        column_left = _column_left(page, row.column, row.top)
        if column_left is None:
            return None
        origin_x, origin_top = column_left + row.x, row.top - row.table_offset
        for cell in row.cells:
            if None in (cell.x, cell.top, cell.width, cell.height, cell.source_index):
                return None
            if cell.source_index >= len(sources):
                return None
            source = sources[cell.source_index]
            own = source.findall(f"{_HP}subList/{_HP}p")
            # A line holding tables, its text not given, is drawn by those tables (below).
            lines = tuple(line for line in _fragment_lines(cell) if line.text is not None or not _holds_tables(line))
            if any(
                line.top is None or line.x is None or line.width is None or line.text is None
                or line.paragraph >= len(own) for line in lines
            ):
                return None
            plan = None if row.repeated else plans.get(cell.source_index)
            if plan is not None and plan.whole - plan.for_objects:
                return None
            boxes.append((row, cell, source, own, lines, origin_x + cell.x, origin_top + cell.top))
    if not boxes:
        return None
    left = min(box[5] for box in boxes)
    top = min(box[6] for box in boxes)
    right = max(box[5] + box[1].width for box in boxes)
    bottom = max(box[6] + box[1].height for box in boxes)
    cells = []
    for row, cell, source, own, lines, cell_x, cell_top in boxes:
        border_ref = source.get("borderFillIDRef") or table.get("borderFillIDRef")
        css = _border_style(border_ref, styles, issues=issues)
        diagonal = _cell_diagonal(border_ref, styles, issues)
        frame = _style_attr({
            **{f"border-{side}": css[f"border-{side}"] for side in ("top", "right", "bottom", "left")},
            **{side: _half_border(css[f"border-{side}"]) for side in ("top", "right", "bottom", "left")},
        })
        box = _style_attr({
            "left": _fmt_mm(_hwp_to_mm(cell_x - left)), "top": _fmt_mm(_hwp_to_mm(cell_top - top)),
            "width": _fmt_mm(_hwp_to_mm(cell.width)), "height": _fmt_mm(_hwp_to_mm(cell.height)),
            "background": css["background"] if css["background"] != "transparent" else None,
        })
        drawn = "".join(_positioned_cell_line(line, own[line.paragraph], styles) for line in lines)
        cells.append(
            f'<div class="hwpx-engine-cell" data-engine-row="{row.row}" data-engine-column="{cell.column}" '
            f'data-engine-repeated="{int(row.repeated)}" '
            f'data-border-fill-id="{html.escape(source.get("borderFillIDRef") or "")}" style="{box}">'
            f'<i class="hwpx-cell-frame" style="{frame}"></i>{diagonal}{drawn}</div>'
        )
    extent = _style_attr({
        "left": _fmt_mm(_hwp_to_mm(left)), "top": _fmt_mm(_hwp_to_mm(top)),
        "width": _fmt_mm(_hwp_to_mm(right - left)), "height": _fmt_mm(_hwp_to_mm(bottom - top)),
    })
    return (
        f'<div class="hwpx-engine-table" data-engine-table="{number}" data-engine-page="{page.page}" '
        f'style="{extent}">{"".join(cells)}</div>{"".join(nested)}'
    )


def _positioned_cell_line(line: Any, paragraph: ET.Element, styles: Mapping[str, Any]) -> str:
    """One text line of a cell at the engine's top, left edge and width (cell-relative), as tall as the line."""
    text = _label_markup(paragraph, styles, line) + _styled_line_text(line, styles)
    if not text:
        return ""  # a line with nothing to show (an empty paragraph's) keeps its room without markup
    run = next((run for run in paragraph.findall(f"{_HP}run") if _find_text_in_run(run)), None)
    char = styles["char"].get(run.get("charPrIDRef", "0") if run is not None else "0", {})
    align = styles["para"].get(paragraph.get("paraPrIDRef") or "0", {}).get("align", "left")
    css = _style_attr({
        "left": _fmt_mm(_hwp_to_mm(line.x)), "top": _fmt_mm(_hwp_to_mm(line.top)),
        "width": _fmt_mm(_hwp_to_mm(line.width)),
        "height": _fmt_mm(_hwp_to_mm(line.height)), "line-height": _fmt_mm(_hwp_to_mm(line.height)),
        "font-size": _fmt_pt(char.get("font_size_pt", 10.0)), "color": char.get("color", "#000000"),
        "text-align": align if align != "left" else None,
    })
    return (
        f'<div class="hwpx-engine-cell-line" data-text-start="{line.text_start}" data-text-end="{line.text_end}" '
        f'data-engine-top="{line.top}" style="{css}">{text}</div>'
    )


def _picture_sources(document: HwpxDocument, parts: Mapping[str, bytes]) -> dict[str, tuple[str, bytes]]:
    supported = {
        "png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
        "jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
        "jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
        "gif": ("image/gif", (b"GIF87a", b"GIF89a")),
        "bmp": ("image/bmp", (b"BM",)),
        "webp": ("image/webp", (b"RIFF",)),
    }
    result = {}
    for item in document.media.images:
        data = parts.get(item.href)
        found = supported.get(item.format.lower())
        if data is not None and found is not None and data.startswith(found[1]):
            if found[0] != "image/webp" or data[8:12] == b"WEBP":
                result[item.item_id] = (found[0], data)
    return result


#: Wrapping in front of or behind the text: the object takes no room from it.
_FLOATING = frozenset({"IN_FRONT_OF_TEXT", "BEHIND_TEXT"})
_GROUP_TAG = f"{_HP}container"
_APPROX_FLOATING = "object in front of or behind the text is drawn at an approximate place"
_APPROX_INLINE = "object set as a character is drawn at an approximate place on its line"
_APPROX_MEMBER = "a member of a group without a place is drawn at the group's top left"
_BOX_TEXT_WHOLE = "text box text is drawn whole in its box: the engine's lines do not give it"


def _object_kind(element: ET.Element) -> str:
    return _OBJECT_KINDS.get(element.tag, "shape" if element.tag in _SHAPE_TAGS else element.tag.removeprefix(_HP))


def _object_size(placed: Any) -> tuple[int, int] | None:
    """The engine's width and height of an object; a line may be flat (one of them 0), not both."""
    if placed is None or placed.width is None or placed.height is None:
        return None
    if placed.width < 0 or placed.height < 0 or placed.width + placed.height <= 0:
        return None
    return placed.width, placed.height


def _object_rect(placed: Any) -> tuple[int, int, int, int] | None:
    """The engine's paper rectangle of an object (x, top, width, height), when it gives all of it."""
    size = _object_size(placed)
    if size is None or placed.page is None or placed.x is None or placed.top is None:
        return None
    return placed.x, placed.top, size[0], size[1]


def _approximate_place(
    placed: Any, size: tuple[int, int], lines: tuple[Any, ...], page: Any, styles: Mapping[str, Any],
    paragraph: ET.Element | None, number: int,
) -> tuple[int, int, str] | None:
    """Where a sized object the engine gives a page but no place is drawn on a page at coordinates, and why
    that is approximate; ``None`` where the object may take room the engine's lines do not show (the page flows).

    The decision rule: an object takes no room from the text when it stands in front of or behind it, or
    when it is set as a character with its size known and its paragraph has a line on that page -- the
    engine set that line with the object in it, so the line's top and height already hold it. Such an
    object stands on the first of those lines as tall as it (else the tallest), its foot on the line's foot,
    at the line's start (moved as the paragraph aligns a line holding no text); one in front of or behind
    the text at its paragraph's first line there. A value the engine gives (its left edge, its top) is kept.
    """
    own = [line for line in lines if line.position.page == number]
    if placed.wrap in _FLOATING:
        x = placed.x if placed.x is not None else (round(_line_frame(own[0], page)[0]) if own else page.body[0])
        top = placed.top if placed.top is not None else (own[0].top if own else page.body[1])
        return x, top, _APPROX_FLOATING
    if placed.wrap != "AS_CHARACTER" or not own:
        return None
    holder = next((line for line in own if line.height >= size[1]), max(own, key=lambda line: line.height))
    top = placed.top if placed.top is not None else holder.top + max(0, holder.height - size[1])
    if placed.x is not None:
        x = placed.x
    else:
        line_x, _, room, _ = _line_frame(holder, page)
        align = "left"
        if paragraph is not None and not (holder.text or "").strip():
            align = styles["para"].get(paragraph.get("paraPrIDRef") or "0", {}).get("align", "left")
        shift = {"center": (room - size[0]) / 2, "right": room - size[0]}.get(align, 0)
        x = round(line_x + max(0, shift))
    return x, top, _APPROX_INLINE


def _shape_fill(element: ET.Element, issues: Counter[tuple[str, str]], kind: str) -> str | None:
    """The one colour a drawing's fill (``hc:fillBrush``) is drawn as; what is reduced is counted."""
    brush = element.find(f"{_HC}fillBrush")
    if brush is None:
        return None
    face = None
    win = brush.find(f"{_HC}winBrush")
    if win is not None and (win.get("faceColor") or "none").lower() != "none":
        face = _css_color(win.get("faceColor"), default="")
        if win.get("alpha") not in (None, "0", "0.0") and face:
            issues[(kind, "shape fill transparency is not drawn")] += 1
    if win is not None and (win.get("hatchStyle") or "NONE").upper() != "NONE":
        issues[(kind, "shape fill pattern or gradient is drawn as one colour")] += 1
    gradation = brush.find(f"{_HC}gradation")
    if gradation is not None:
        stops = [_css_color(stop.get("value"), default="") for stop in gradation.findall(f"{_HC}color")]
        face = _mean_color([stop for stop in stops if stop]) or face
        issues[(kind, "shape fill pattern or gradient is drawn as one colour")] += 1
    if brush.find(f"{_HC}imgBrush") is not None:
        issues[(kind, "shape fill picture is not drawn")] += 1
    return face or None


def _shape_points(element: ET.Element, width: int, height: int) -> list[tuple[float, float]] | None:
    """A line's or polygon's points in the drawn box (HWPUNIT), scaled from its own size (``hp:orgSz``)."""
    nodes: list[ET.Element | None] = (
        [element.find(f"{_HC}startPt"), element.find(f"{_HC}endPt")]
        if element.tag in (f"{_HP}line", f"{_HP}connectLine") else list(element.findall(f"{_HC}pt"))
    )
    if len(nodes) < 2 or any(node is None for node in nodes):
        return None
    size = element.find(f"{_HP}orgSz")
    own_width = _safe_int(size.get("width") if size is not None else None, width) or width or 1
    own_height = _safe_int(size.get("height") if size is not None else None, height) or height or 1
    return [
        (_safe_int(node.get("x")) * width / own_width, _safe_int(node.get("y")) * height / own_height)
        for node in nodes if node is not None
    ]


def _shape_drawing(element: ET.Element, width: int, height: int, issues: Counter[tuple[str, str]], kind: str
                   ) -> tuple[dict[str, str | None], str]:
    """The outline of a drawing in its box: (CSS of the box, markup inside it).

    Its line colour and width are the file's (``hp:lineShape``; a dashed or doubled line is drawn solid
    and counted); its fill one colour (:func:`_shape_fill`). A rectangle or an ellipse is the box's own
    border, a line or polygon an SVG path through its points; any other drawing is drawn as its
    bounding box, and counted.
    """
    line = element.find(f"{_HP}lineShape")
    style = ((line.get("style") if line is not None else None) or "SOLID").upper()
    color = _css_color(line.get("color") if line is not None else None)
    stroke_mm = max(_hwp_to_mm(line.get("width") if line is not None else None), 0.1)
    if style not in ("SOLID", "NONE"):
        issues[(kind, "shape line style is drawn solid")] += 1
    border = "none" if style == "NONE" else f"{_fmt_mm(stroke_mm)} solid {color}"
    fill = _shape_fill(element, issues, kind)
    local = element.tag.removeprefix(_HP)
    if local in ("rect", "ellipse"):
        radius = "50%" if local == "ellipse" else (f"{min(_safe_int(element.get('ratio')), 50)}%"
                                                   if _safe_int(element.get("ratio")) else None)
        return {"border": border, "background": fill, "border-radius": radius}, ""
    points = _shape_points(element, width, height) if local in ("line", "connectLine", "polygon") else None
    if points is None:
        issues[(kind, "shape is drawn as its bounding box")] += 1
        return {"border": border if style != "NONE" else "none", "border-style": "dashed", "background": fill}, ""
    coordinates = " ".join(f"{x:.0f},{y:.0f}" for x, y in points)
    stroke = "none" if style == "NONE" else color
    stroke_px = f"{stroke_mm * 96 / 25.4:.2f}"
    figure = "polygon" if local == "polygon" else "polyline"
    svg = (
        f'<svg class="hwpx-shape-svg" viewBox="0 0 {max(width, 1)} {max(height, 1)}" preserveAspectRatio="none" '
        f'aria-hidden="true"><{figure} points="{coordinates}" fill="{html.escape(fill or "none")}" '
        f'stroke="{html.escape(stroke)}" stroke-width="{stroke_px}" vector-effect="non-scaling-stroke"/></svg>'
    )
    return {"border": "none"}, svg


def _box_text(
    element: ET.Element, placed: Any, styles: Mapping[str, Any], issues: Counter[tuple[str, str]], kind: str,
) -> str:
    """The text a drawing holds (``hp:drawText``): the engine's lines at their places in the box when they give
    all of it, else the text whole in the box (counted with the engine's reasons)."""
    holder = element.find(f"{_HP}drawText")
    if holder is None:
        return ""
    paragraphs = holder.findall(f"{_HP}subList/{_HP}p")
    text = _characters("".join(_paragraph_text(paragraph) for paragraph in paragraphs))
    lines = placed.lines if placed is not None else ()
    complete = bool(lines) and all(
        None not in (line.top, line.x, line.width, line.text) and line.paragraph < len(paragraphs) for line in lines
    ) and not (text - _characters("".join(line.text or "" for line in lines)))
    if complete:
        return "".join(_positioned_cell_line(line, paragraphs[line.paragraph], styles) for line in lines)
    shown = _shape_text_lines(holder)  # the text of drawings it holds too (tables in it are drawn as tables)
    if not shown:
        return ""
    issues[(kind, _BOX_TEXT_WHOLE)] += 1
    for reason in (placed.unavailable if placed is not None else ()):
        if "line" in reason or "text" in reason:
            issues[(kind, reason)] += 1
    # Where the engine gives its first line a place, the text begins there.
    first = lines[0] if lines and lines[0].top is not None and lines[0].x is not None else None
    css = "" if first is None else ' style="{}"'.format(_style_attr({
        "position": "absolute", "left": _fmt_mm(_hwp_to_mm(first.x)), "top": _fmt_mm(_hwp_to_mm(first.top)),
    }))
    return f'<div class="hwpx-box-text" aria-label="글상자"{css}>{"<br>".join(html.escape(line) for line in shown)}</div>'


def _object_box(
    element: ET.Element, placed: Any, box: tuple[int, int, int, int], images: Mapping[str, tuple[str, bytes]],
    issues: Counter[tuple[str, str]], counter: _ObjectCounter, styles: Mapping[str, Any], objects: Mapping[Any, Any],
    *, origin: tuple[int, int] = (0, 0), attrs: str = "",
) -> str:
    """An object drawn in its *box* (paper x, top, width, height; *origin* is where its holder stands).

    A picture shows the document's picture file, a drawing its outline (:func:`_shape_drawing`) and the
    text it holds (:func:`_box_text`), a group its members at their places in it, an equation its MathML;
    a chart, an embedded object or a form object a marker in the box (counted).
    """
    kind = _object_kind(element)
    x, top, width, height = box
    classes = "hwpx-placed-object"
    look: dict[str, str | None] = {}
    if element.tag == _PICTURE_TAG:
        label = f"그림 {counter.next_picture()}"
        image = element.find(f".//{_HC}img")
        asset = images.get(image.get("binaryItemIDRef", "")) if image is not None else None
        if asset is not None:
            content = f'<img alt="{label}" src="data:{asset[0]};base64,{base64.b64encode(asset[1]).decode("ascii")}">'
        else:
            classes += " hwpx-object-placeholder"
            content = _render_object_marker(label)
            issues[(kind, "embedded image is missing or unsupported in the browser")] += 1
    elif element.tag == _GROUP_TAG:
        classes += " hwpx-group"
        content = "".join(
            _group_member(member, box, images, issues, counter, styles, objects)
            for member in element if member.tag in _OBJECT_TAGS
        )
    elif element.tag in _SHAPE_TAGS:
        classes += " hwpx-shape-outline"
        look, content = _shape_drawing(element, width, height, issues, kind)
        content += _box_text(element, placed, styles, issues, kind)
    elif element.tag == _EQUATION_TAG:
        content = _render_equation_element(element)
    else:
        classes += " hwpx-object-placeholder"
        content = _render_object_marker(_OTHER_OBJECT_LABELS.get(element.tag, "개체"))
        issues[(kind, _PLACEHOLDER)] += 1
    css = _style_attr({
        "left": _fmt_mm(_hwp_to_mm(x - origin[0])), "top": _fmt_mm(_hwp_to_mm(top - origin[1])),
        "width": _fmt_mm(_hwp_to_mm(width)), "height": _fmt_mm(_hwp_to_mm(height)), **look,
    })
    return f'<div class="{classes}" data-object-kind="{kind}"{attrs} style="{css}">{content}</div>'


def _group_member(
    member: ET.Element, group: tuple[int, int, int, int], images: Mapping[str, tuple[str, bytes]],
    issues: Counter[tuple[str, str]], counter: _ObjectCounter, styles: Mapping[str, Any], objects: Mapping[Any, Any],
) -> str:
    """A member of a group at its place in the group's box; one the engine gives no place stands at the
    box's top left the approximate way (counted with the engine's reasons)."""
    placed = objects.get(member)
    rect = _object_rect(placed)
    if rect is not None:
        return _object_box(member, placed, rect, images, issues, counter, styles, objects, origin=group[:2])
    kind = _object_kind(member)
    for reason in (placed.unavailable if placed is not None and placed.unavailable else
                   ("object placement is unavailable",)):
        issues[(kind, reason)] += 1
    issues[(kind, _APPROX_MEMBER)] += 1
    if member.tag in _SHAPE_TAGS and member.tag != _GROUP_TAG:
        content = _render_shape(member, captions=False)
    elif member.tag == _GROUP_TAG:
        content = "".join(_group_member(inner, group, images, issues, counter, styles, objects)
                          for inner in member if inner.tag in _OBJECT_TAGS)
    else:
        content = _render_inline_object(member, counter) or _render_object_marker(
            _OTHER_OBJECT_LABELS.get(member.tag, "개체"))
    return f'<div class="hwpx-group-member-approx" data-object-kind="{kind}" data-approx="place">{content}</div>'


def _object_anchor(
    element: ET.Element, home: int, placed: Any, images: Mapping[str, tuple[str, bytes]],
    issues: Counter[tuple[str, str]], counter: _ObjectCounter, styles: Mapping[str, Any],
    objects: Mapping[Any, Any] | None = None, *, lines: tuple[Any, ...] = (), pages: tuple[Any, ...] = (),
    paragraph: ET.Element | None = None,
) -> _AnchorMarkup:
    """An object on its page: in its engine rectangle, at an approximate place where it takes no room the
    engine's lines do not hold (:func:`_approximate_place`), or flowing (its page flows) otherwise."""
    kind = _object_kind(element)
    page = home if placed is None or placed.page is None else placed.page
    size = _object_size(placed)
    rect = _object_rect(placed)
    if rect is None:
        for reason in (placed.unavailable if placed is not None and placed.unavailable else
                       ("object placement is unavailable",)):
            issues[(kind, reason)] += 1
    approximate = None
    if rect is None and placed is not None and size is not None and 0 <= page < len(pages) and (
        placed.page is not None or placed.wrap in _FLOATING  # one taking no room stands on its paragraph's page
    ):
        approximate = _approximate_place(placed, size, lines, pages[page], styles, paragraph, page)
        if approximate is not None:
            issues[(kind, approximate[2])] += 1
            rect = (approximate[0], approximate[1], *size)
    positioned = rect is not None
    overlay = ""
    wrap = placed.wrap if placed is not None else ""
    if positioned:
        layer = {"IN_FRONT_OF_TEXT": "front", "BEHIND_TEXT": "behind"}.get(wrap)
        if layer:
            overlay = f' data-overlay="{layer}"'
    if rect is not None:
        attrs = overlay + (f' data-wrap="{html.escape(wrap)}"' if wrap else "")
        if approximate is not None:
            attrs += ' data-approx="place"'
        markup = _object_box(element, placed, rect, images, issues, counter, styles, objects or {}, attrs=attrs)
    else:
        markup = _unplaced_object(element, kind, placed, images, issues, counter)
    left, top = (rect[0], rect[1]) if rect is not None else (None, None)
    width, height = (rect[2], rect[3]) if rect is not None else (None, None)
    caption = _caption_text(element, styles, counter)
    if caption:
        # The engine places no caption: it is drawn next to its object (under it; above it when the
        # file sets it at the top), with the object's width when the object has a place.
        issues[(kind, "caption placement is unavailable")] += 1
        holder = element.find(f"{_HP}caption")
        above = holder is not None and (holder.get("side") or "").upper() == "TOP"
        place = None
        if positioned and left is not None and top is not None and width is not None and height is not None:
            place = _style_attr({
                "left": _fmt_mm(_hwp_to_mm(left)), "width": _fmt_mm(_hwp_to_mm(width)), "height": "auto",
                "top": _fmt_mm(_hwp_to_mm(top if above else top + height)),
                "transform": "translateY(-100%)" if above else None,
            })
        style = f' style="{place}"' if place else ""
        label = f'<div class="hwpx-placed-object hwpx-object-caption" data-caption-of="{kind}"{overlay}{style}>{caption}</div>'
        markup = label + markup if above else markup + label
    return _AnchorMarkup(page, markup, flow=not positioned, inline=_placed_as_character(element), overlay=bool(overlay))


def _unplaced_object(
    element: ET.Element, kind: str, placed: Any, images: Mapping[str, tuple[str, bytes]],
    issues: Counter[tuple[str, str]], counter: _ObjectCounter,
) -> str:
    """An object without a place, flowing in its page: itself in its size where the engine gives one."""
    width, height = (None, None) if placed is None else (placed.width, placed.height)
    sized = width is not None and height is not None and width > 0 and height > 0
    classes = "hwpx-placed-object"
    if element.tag == _PICTURE_TAG:
        label = f"그림 {counter.next_picture()}"
        image = element.find(f".//{_HC}img")
        asset = images.get(image.get("binaryItemIDRef", "")) if image is not None else None
        if asset is not None and sized:
            content = f'<img alt="{label}" src="data:{asset[0]};base64,{base64.b64encode(asset[1]).decode("ascii")}">'
        else:
            content = _render_object_marker(label)
            if asset is None:
                issues[(kind, "embedded image is missing or unsupported in the browser")] += 1
    elif element.tag in _SHAPE_TAGS:
        if sized:
            classes += " hwpx-shape-outline"
        content = _render_shape(element, captions=False)
    elif element.tag in _OTHER_OBJECT_LABELS or element.tag == _OLE_TAG:
        content = _render_object_marker(_OTHER_OBJECT_LABELS.get(element.tag, "개체"))
        issues[(kind, _PLACEHOLDER)] += 1
    else:
        content = _render_inline_object(element, counter)
    css = _style_attr({
        key: _fmt_mm(_hwp_to_mm(value)) for key, value in (("width", width), ("height", height)) if value is not None
    })
    return f'<div class="{classes}" data-object-kind="{kind}" style="{css}">{content}</div>'


_AREA_WHOLE = "area is drawn whole in its room: its lines do not give all it holds"
_AREA_MARGIN = "area without a page is drawn in the margin of its paragraph's page"
_NOTE_FOOT = "note without a place is drawn at the foot of its paragraph's page body"


def _area_line_paragraphs(lines: tuple[Any, ...], own: list[ET.Element]) -> list[ET.Element] | None:
    """The paragraph of each of an area's lines: a paragraph's lines begin at its text position 0."""
    if not own:
        return None
    result, index = [], -1
    for line in lines:
        if line.text_start == 0 or index < 0:
            index += 1
        if index >= len(own):
            return None
        result.append(own[index])
    return result if index == len(own) - 1 else None


def _area_room(placed: Any, pages: tuple[Any, ...]) -> tuple[int, tuple[int, int, int, int]] | None:
    """The page an area stands on and its room there (x, top, width, height on the paper), when given."""
    if placed is None or None in (placed.page, placed.x, placed.top, placed.width, placed.height):
        return None
    if not 0 <= placed.page < len(pages):
        return None
    return placed.page, (placed.x, placed.top, placed.width, placed.height)


def _area_numbers(area: ET.Element) -> list[list[tuple[int, ET.Element, str]]]:
    """For each of an area's own paragraphs, its page numbers (``hp:autoNum`` in a run's ``hp:ctrl``):
    how many characters of the paragraph's text stand before each, the node, and its run's character style."""
    result = []
    for paragraph in area.findall(f"{_HP}subList/{_HP}p"):
        found: list[tuple[int, ET.Element, str]] = []
        offset = 0
        for run in paragraph.findall(f"{_HP}run"):
            reference = run.get("charPrIDRef") or "0"
            for child in run:
                if child.tag == f"{_HP}ctrl":
                    found.extend((offset, node, reference) for node in child.findall(f"{_HP}autoNum"))
                    offset += 1 if (child.get("id") or "").lower() == "tab" else 0
                elif child.tag == f"{_HP}t":
                    offset += len(_text_node_content(child))
                elif child.tag in (f"{_HP}tab", f"{_HP}lineBreak"):
                    offset += 1
        result.append(found)
    return result


def _line_numbers(
    lines: tuple[Any, ...], holders: list[ET.Element], own: list[ET.Element], area: ET.Element,
) -> list[tuple[tuple[int, str, str], ...]]:
    """The page numbers to set into each of an area's engine lines, as the page being drawn shows them.

    The engine's line text leaves a page number out. It goes into the line of its paragraph that holds
    the characters before it (at its offset there), the paragraph's last line when they end the paragraph.
    """
    numbers = _area_numbers(area)
    result: list[list[tuple[int, str, str]]] = [[] for _ in lines]
    starts: dict[int, int] = {}
    places: dict[int, list[tuple[int, int, int]]] = {}  # paragraph -> (line, start, length)
    for index, (line, holder) in enumerate(zip(lines, holders)):
        number = next((at for at, paragraph in enumerate(own) if paragraph is holder), -1)
        start = starts.get(number, 0)
        length = len((line.text or "").removesuffix("\n"))
        places.setdefault(number, []).append((index, start, length))
        starts[number] = start + length
    for number, found in enumerate(numbers):
        held = places.get(number)
        if not held:
            continue
        for offset, node, reference in found:
            text = _auto_number(node)
            if text is None:
                continue
            index, start, _ = next((place for place in held if offset < place[1] + place[2]), held[-1])
            result[index].append((max(0, offset - start), text, reference))
    return [tuple(found) for found in result]


@dataclass(frozen=True)
class _Numbering:
    """The numbers of the document's pages in the engine's page order, and its page count."""

    numbers: tuple[int, ...]
    issues: Counter[tuple[str, str]]
    #: Pages the engine gives no number: the preview's own count stands in (counted when drawn).
    counted: frozenset[int] = frozenset()

    def on(self, page: int) -> _PageNumbers | None:
        if not 0 <= page < len(self.numbers):
            return None
        return _PageNumbers(self.numbers[page], len(self.numbers), self.issues, page in self.counted)


@contextmanager
def _numbers_of(numbering: _Numbering | None, page: int) -> Iterator[None]:
    """Within it, the page numbers drawn are written as page *page*'s."""
    token = _PAGE_NUMBERS.set(numbering.on(page) if numbering is not None else None)
    try:
        yield
    finally:
        _PAGE_NUMBERS.reset(token)


def _tables_at_its_top(paragraph: ET.Element) -> bool:
    """Whether a paragraph holds tables standing at its top -- each set as a character, or set at no offset from
    the paragraph with the text above and below it -- and nothing else to show (no text, object, note or label):
    the tables are what it shows."""
    tables = paragraph.findall(f"{_HP}run/{_HP}tbl")
    labels = _LABELS.get()

    def on_top(table: ET.Element) -> bool:
        if _placed_as_character(table):
            return True
        position = table.find(f"{_HP}pos")
        return position is not None and (table.get("textWrap") or "") == "TOP_AND_BOTTOM" and (
            (position.get("vertRelTo") or "PARA").upper() == "PARA" and _safe_int(position.get("vertOffset")) == 0
            and (position.get("vertAlign") or "TOP").upper() == "TOP")

    return bool(tables) and all(on_top(table) for table in tables) and not (
        _paragraph_text(paragraph).strip() or _has_objects(paragraph)
        or any(node.tag in _AREA_LABELS for node in paragraph.iter())
        or (labels is not None and labels.label(paragraph) is not None)
    )


def _area_whole(
    area: ET.Element, kind: str, room: tuple[int, int, int | None, int | None], styles: Mapping[str, Any],
    counter: _ObjectCounter, *, foot: bool = False, lines: tuple[Any, ...] = (),
    issues: Counter[tuple[str, str]] | None = None,
) -> str:
    """All an area holds, its paragraphs and tables the approximate way, in its *room* on the paper
    (with *foot*, standing on the room's top: a note above the body's foot). A paragraph that holds only
    tables standing at its top draws no empty line of its own: the tables are what it shows. Where the
    engine's *lines* give each paragraph its first line's top, the paragraph begins there in the room.
    The tables' cell diagonals are drawn, what of them is approximate counted in *issues*."""
    issues = issues if issues is not None else Counter()
    own = area.findall(f"{_HP}subList/{_HP}p")
    holders = _area_line_paragraphs(lines, own) if lines and all(line.top is not None for line in lines) else None
    tops: dict[int, int] = {}
    for line, holder in zip(lines, holders or ()):
        tops.setdefault(id(holder), line.top - room[1])
    parts = []
    for paragraph in own:
        drawn = (
            "".join(_render_table(table, styles, counter, diagonals=issues)
                    for table in paragraph.findall(f"{_HP}run/{_HP}tbl"))
            if _tables_at_its_top(paragraph)
            else _render_paragraph(paragraph, styles, counter, extended_styles=True, diagonals=issues)
        )
        if id(paragraph) in tops:
            css = _style_attr({"top": _fmt_mm(_hwp_to_mm(max(0, tops[id(paragraph)])))})
            drawn = f'<div class="hwpx-area-paragraph" style="{css}">{drawn}</div>'
        parts.append(drawn)
    css = _style_attr({
        "left": _fmt_mm(_hwp_to_mm(room[0])), "top": _fmt_mm(_hwp_to_mm(room[1])),
        "width": _fmt_mm(_hwp_to_mm(room[2])) if room[2] is not None else None,
        "height": _fmt_mm(_hwp_to_mm(room[3])) if room[3] is not None else None,
        "transform": "translateY(-100%)" if foot else None,
    })
    return (f'<div class="hwpx-placed-object hwpx-area-room" data-area-kind="{kind}" data-approx="area" '
            f'style="{css}">{"".join(parts)}</div>')


def _engine_area_anchors(
    area: ET.Element, home: int, placements: list[Any], pages: tuple[Any, ...], styles: Mapping[str, Any],
    issues: Counter[tuple[str, str]], counter: _ObjectCounter, margins: Mapping[str, int],
    table_counts: Counter[int], numbering: _Numbering | None = None,
) -> list[_AnchorMarkup]:
    """A header, footer or note on each page the engine gives it, over or beside the body: it takes no room
    in a flow page, which only stacks the body.

    Its lines stand at the engine's places when they give all its text. Otherwise it is drawn whole,
    the approximate way, in the room the engine gives it on that page; one the engine gives no page is
    drawn once on its paragraph's page, a header or footer in that page's header or footer margin, a
    note at the foot of the body. Each approximation is counted. A page number it holds shows the
    number of the page it is drawn on (*numbering*).

    On a flow page a footer stands on the foot of the page box, at its place in a paper-high layer.
    """
    anchors = _area_anchors(area, home, placements, pages, styles, issues, counter, margins, table_counts, numbering)
    if area.tag != f"{_HP}footer":
        return anchors
    return [replace(anchor, flow_html=f'<div class="hwpx-area-foot">{anchor.html}</div>') for anchor in anchors]


def _area_anchors(
    area: ET.Element, home: int, placements: list[Any], pages: tuple[Any, ...], styles: Mapping[str, Any],
    issues: Counter[tuple[str, str]], counter: _ObjectCounter, margins: Mapping[str, int],
    table_counts: Counter[int], numbering: _Numbering | None,
) -> list[_AnchorMarkup]:
    """See :func:`_engine_area_anchors`."""
    kind = area.tag.removeprefix(_HP)
    own = area.findall(f"{_HP}subList/{_HP}p")
    every = list(area.iter(f"{_HP}p"))
    tables = sum(1 for _ in area.iter(f"{_HP}tbl"))
    if not placements:
        placements = [None]
    given: Counter[str] = Counter()
    for placed in placements:
        for line in (placed.lines if placed is not None else ()):
            given.update(_characters(line.text or ""))
    covered = not tables and not (_characters("".join(_paragraph_text(paragraph) for paragraph in every)) - given)
    if not covered and given:
        issues[(kind, "area lines do not give all its text: the area is shown whole")] += 1
    result = []
    unplaced = False
    for placed in placements:
        lines = placed.lines if placed is not None else ()
        found = _area_room(placed, pages)
        reasons = (placed.unavailable if placed is not None and placed.unavailable else ())
        if found is not None and covered and lines and all(line.text is not None for line in lines):
            page = found[0]
            holders = _area_line_paragraphs(lines, own) or [own[0] if own else every[0]] * len(lines)
            with _numbers_of(numbering, page):
                inserts = _line_numbers(lines, holders, own, area)
            rendered = [
                _engine_line(line, holder, styles, pages[page], area_line=True, inserts=numbers)
                for line, holder, numbers in zip(lines, holders, inserts)
            ]
            partial = any(approximate for _, approximate in rendered)
            if partial:
                issues[(kind, "area coordinates are incomplete")] += 1
            markup = "".join(markup for markup, _ in rendered)
            attrs = ' data-approx-lines="1"' if partial else ""
            result.append(_AnchorMarkup(
                page, f'<div class="hwpx-area-layer" data-area-kind="{kind}"{attrs}>{markup}</div>',
                flow=False, overlay=True,
            ))
            continue
        for reason in reasons or ("area placement is unavailable",):
            issues[(kind, reason)] += 1
        if found is not None:
            issues[(kind, _AREA_WHOLE)] += 1
            if not result:
                table_counts[found[0]] += tables
            with _numbers_of(numbering, found[0]):
                whole = _area_whole(area, kind, found[1], styles, counter, lines=tuple(lines), issues=issues)
            result.append(_AnchorMarkup(found[0], whole, flow=False, overlay=True))
            continue
        if unplaced or not 0 <= home < len(pages):
            continue
        unplaced = True  # drawn once, on its paragraph's page
        left, top, width, height = pages[home].body
        if kind == "header":
            margin_room = (left, top - margins.get("header", 0), width, margins.get("header", 0))
        elif kind == "footer":
            margin_room = (left, top + height, width, margins.get("footer", 0))
        else:
            margin_room = None
        issues[(kind, _AREA_MARGIN if margin_room is not None else _NOTE_FOOT)] += 1
        table_counts[home] += tables
        with _numbers_of(numbering, home):
            markup = (_area_whole(area, kind, margin_room, styles, counter, issues=issues) if margin_room is not None
                      else _area_whole(area, kind, (left, top + height, width, None), styles, counter, foot=True,
                                       issues=issues))
        result.append(_AnchorMarkup(home, markup, flow=False, overlay=True))
    return result


#: Bytes of fill pictures a document may repeat over its pages before they are left out.
_PAGE_FILL_PICTURE_BUDGET = 4 * 1024 * 1024


@dataclass(frozen=True)
class _PageFill:
    """What a section's page border fill (``hp:pageBorderFill``) puts behind its pages."""

    color: str | None = None
    picture: tuple[str, bytes] | None = None
    visibility: str = "SHOW_ALL"
    notes: tuple[str, ...] = ()

    def shows_on(self, first_page: bool) -> bool:
        return {"HIDE_FIRST": not first_page, "SHOW_FIRST": first_page}.get(self.visibility, True)

    def markup(self, page: Any, *, with_picture: bool) -> str:
        """The fill under the whole page box. A flow page that grows past the paper is
        painted again for every paper height, as the sheets it would run onto are."""
        picture = self.picture if with_picture else None
        if self.color is None and picture is None:
            return ""
        source = None
        if picture is not None:  # a type this module names and bytes it checked, in base64
            source = f"url(data:{picture[0]};base64,{base64.b64encode(picture[1]).decode('ascii')})"
        css = _style_attr({
            "background-color": self.color,
            "background-image": source,
            "background-size": f"100% {_fmt_mm(_hwp_to_mm(page.paper_height))}" if source else None,
        })
        return f'<div class="hwpx-page-fill" style="{css}"></div>'


def _page_fill(
    section: ET.Element, styles: Mapping[str, Any], images: Mapping[str, tuple[str, bytes]],
) -> _PageFill | None:
    """The fill behind a section's pages, as far as the file states it plainly.

    Drawn: a fill over the whole paper set for both odd and even pages, as a colour
    and/or a picture stretched over the paper with no picture effect. Anything else
    is left out and named in ``notes``.
    """
    properties = section.find(f".//{_HP}secPr")
    if properties is None:
        return None
    entries = {node.get("type") or "BOTH": node for node in properties.findall(f"{_HP}pageBorderFill")}

    def brush(kind: str) -> Mapping[str, Any]:
        node = entries.get(kind)
        return styles["border"].get(node.get("borderFillIDRef") or "", {}) if node is not None else {}

    def filled(border: Mapping[str, Any]) -> bool:
        return border.get("shown_fill", "transparent") != "transparent" or bool(border.get("fill_notes"))

    both = brush("BOTH")
    notes = []
    if any(filled(brush(kind)) and brush(kind) is not both for kind in ("EVEN", "ODD")):
        notes.append("page fill set for odd or even pages only is not drawn")
    if not filled(both):
        return _PageFill(notes=tuple(notes)) if notes else None
    shown = properties.find(f"{_HP}visibility")
    visibility = (shown.get("fill") if shown is not None else None) or "SHOW_ALL"
    if entries["BOTH"].get("fillArea") != "PAPER":
        notes.append("page fill over an area other than the whole paper is not drawn")
        return _PageFill(visibility=visibility, notes=tuple(notes))
    if {"pattern", "gradient"} & set(both["fill_notes"]):
        notes.append("page fill pattern or gradient is drawn as one colour")
    if "bare-pattern" in both["fill_notes"]:
        notes.append("page fill pattern is not drawn")
    picture = None
    if both["fill_picture"] is not None:
        picture = _stretched_picture(both["fill_picture"], images)
        if picture is None:
            notes.append("page fill picture is not drawn")
    color = both["shown_fill"] if both["shown_fill"] != "transparent" else None
    return _PageFill(color, picture, visibility, tuple(notes))


def _stretched_picture(brush: ET.Element, images: Mapping[str, tuple[str, bytes]]) -> tuple[str, bytes] | None:
    """The embedded picture of an ``hc:imgBrush`` that fills its area whole, with no picture effect."""
    image = brush.find(f"{_HC}img")
    if image is None or brush.get("mode") != "TOTAL":
        return None
    if (image.get("effect") or "REAL_PIC") != "REAL_PIC":
        return None
    if any((image.get(name) or "0") != "0" for name in ("bright", "contrast", "alpha")):
        return None
    return images.get(image.get("binaryItemIDRef") or "")


def _slot(page: Any, line: Any) -> tuple[int, int]:
    """The column a body line stands in: (the page's column area in force at its top, its column)."""
    areas = page.column_areas
    area = next((number for number in range(len(areas) - 1, -1, -1) if areas[number].top <= line.top), 0)
    return area, line.position.column


def _bare_line_tops(items: list[str | _PlacedLine | _AnchorMarkup]) -> list[tuple[int, int, int | None] | None]:
    """The engine's box of each item, (paper top, paper foot, width or ``None``), where it is known: a body line
    whose paragraph draws nothing after it on the page that takes room (a table it anchors below its line), and
    a table fragment the engine sets in the body (not over or under the text); else ``None``."""
    tops: list[tuple[int, int, int | None] | None] = []
    for index, item in enumerate(items):
        top: tuple[int, int, int | None] | None = None
        if isinstance(item, _PlacedLine) and not item.hosted:
            top = (item.line.top, item.line.top + item.line.height, None)
            for after in items[index + 1:]:
                if isinstance(after, _PlacedLine):
                    if after.paragraph is not item.paragraph:
                        break
                elif not (isinstance(after, _AnchorMarkup) and after.overlay):
                    top = None
                    break
        elif isinstance(item, _AnchorMarkup) and item.box is not None and not item.overlay:
            top = item.box
        tops.append(top)
    return tops


#: HWPUNIT a table may run past its column's width and still stand in it (its border, rounding).
_ACROSS_TOLERANCE = 284


def _has_columns(page: Any) -> bool:
    return any(len(area.widths) > 1 for area in page.column_areas)


def _column_flow(
    parts: list[str], slots: list[tuple[int, int] | None], page: Any, issues: Counter[tuple[str, str]],
    tops: list[tuple[int, int, int | None] | None],
) -> str:
    """A flow page set in its columns: each column area of the page (``ColumnArea``) a row as high as the
    engine gives it at least, each of its columns a box at the column's width and gap, holding what the
    engine sets in that column, in the document's order. An item without a column of its own stands in the
    column of the item before it (the first column at first).

    What the engine sets first in a column area and wider than its column (a table across the columns) stands
    across them, above their boxes: the columns start under it, never beside it. A column whose first item
    the engine gives a top (*tops*: the box of each item where known) starts at that top: the room above it,
    which the engine leaves to what stands across the columns, stays free."""
    areas = page.column_areas
    held: dict[tuple[int, int], list[str]] = {}
    across: dict[int, list[str]] = {}
    under: dict[int, int] = {}  # the engine's foot of what stands across an area's columns
    current = (0, 0)
    _, body_top, body_width, body_height = page.body
    for part, slot, top in zip(parts, slots, tops):
        current = slot if slot is not None else current
        area = min(current[0], len(areas) - 1)
        key = (area, min(current[1], max(len(areas[area].widths), 1) - 1))
        widths = areas[area].widths
        if (len(widths) > 1 and not any(column[0] == area for column in held) and top is not None
                and top[2] is not None and top[2] > widths[key[1]] + _ACROSS_TOLERANCE):
            across.setdefault(area, []).append(part)
            under[area] = max(under.get(area, 0), top[1])
            continue
        start = max(areas[area].top, body_top, under.get(area, 0))
        if key not in held and top is not None and top[0] > start:
            lead = _style_attr({"height": _fmt_mm(_hwp_to_mm(top[0] - start))})
            held[key] = [f'<div class="hwpx-engine-column-lead" style="{lead}"></div>']
        held.setdefault(key, []).append(part)
    rows = []
    for number, area in enumerate(areas):
        widths = area.widths or (body_width,)
        gap = area.gap
        if gap is None and len(widths) > 1:
            issues[("page-flow", "column gap is not given: the columns are spaced evenly")] += 1
            gap = max(0, (body_width - sum(widths)) // (len(widths) - 1))
        foot = areas[number + 1].top if number + 1 < len(areas) else body_top + body_height
        if number in across:
            rows.append(f'<div class="hwpx-engine-column-across" data-column-area="{number}">'
                        f'{"".join(across[number])}</div>')
        columns = []
        for column, width in enumerate(widths):
            css = _style_attr({
                "width": _fmt_mm(_hwp_to_mm(width)),
                "margin-left": _fmt_mm(_hwp_to_mm(gap)) if column and gap else None,
            })
            columns.append(f'<div class="hwpx-engine-column" data-column="{column}" style="{css}">'
                           f'{"".join(held.get((number, column), []))}</div>')
        height = _style_attr({"min-height": _fmt_mm(_hwp_to_mm(
            max(0, foot - max(area.top, body_top, under.get(number, 0)))))})
        rows.append(f'<div class="hwpx-engine-column-area" data-column-area="{number}" style="{height}">'
                    f'{"".join(columns)}</div>')
    return "".join(rows)


def _page_content(
    items: list[str | _PlacedLine | _AnchorMarkup], page: Any, styles: Mapping[str, Any], *, flow: bool,
    issues: Counter[tuple[str, str]], flowing_tables: set[int], slots: list[tuple[int, int] | None] | None = None,
) -> str:
    """The markup of one page. A flow page stacks its lines at the engine's line advance.

    The advance is the distance between the tops of two lines that follow each other in the
    same column with nothing between them taking room. A line without such a successor keeps
    its own height: the page stays marked as an approximate vertical placement. A flow page
    with more than one column stacks each column apart, in its own box (*slots*: the column of
    each item, see :func:`_column_flow`).

    What the drawn markup of an anchor counts goes into *issues*; an engine-placed table drawn
    with its rows flowing goes into *flowing_tables*.
    """
    in_columns = flow and slots is not None and len(slots) == len(items) and _has_columns(page)

    def drawn(anchor: _AnchorMarkup) -> str:
        markup, counted = anchor.markup(flow)
        if counted:
            issues.update(counted)
        if anchor.table is not None and (flow or anchor.flow):
            flowing_tables.add(anchor.table)
        return markup

    advances: dict[int, int | None] = {}
    below: Any = None
    for index in range(len(items) - 1, -1, -1):
        item = items[index]
        if isinstance(item, _PlacedLine):
            advances[index] = _line_advance(item.line, below) if flow else None
            below = item.line
        elif not (isinstance(item, _AnchorMarkup) and item.overlay):
            below = None
    parts = []
    for index, item in enumerate(items):
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, _AnchorMarkup):
            parts.append(drawn(item))
        elif flow:
            hosted = "".join(drawn(anchor) for anchor in item.hosted)
            parts.append(_engine_line(item.line, item.paragraph, styles, page, advance=advances[index], hosted=hosted,
                                      in_column=in_columns)[0])
        else:  # at coordinates: the line, then what it holds, each at its own place
            parts.append(_engine_line(item.line, item.paragraph, styles, page)[0]
                         + "".join(drawn(anchor) for anchor in item.hosted))
    if in_columns:
        assert slots is not None
        return _column_flow(parts, slots, page, issues, _bare_line_tops(items))
    return "".join(parts)


_COLUMN_LINE_STYLE = ("column-line", "column separator line style is drawn solid")
_COLUMN_LINE_WIDTH = ("column-line", "column separator width is not given: it is drawn a pixel wide")
_COLUMN_LINE_GAP = ("column-line", "column separator is not drawn: the gap between the columns is not given")


def _rows_across(page: Any, tables: tuple[Any, ...]) -> list[tuple[int, int, float, float]]:
    """The engine's boxes of the table rows set on *page*: (top, foot, left, right) on the paper, where the row's
    top, height, left edge and cells' widths are all given."""
    areas = page.column_areas
    boxes = []
    for table in tables:
        for row in table.rows:
            if row.page != page.page or None in (row.top, row.height, row.x) or not row.cells:
                continue
            if any(cell.x is None or cell.width is None for cell in row.cells):
                continue
            area = next((area for area in reversed(areas) if area.top <= row.top), None)
            if area is None or row.column >= max(len(area.widths), 1):
                continue
            gaps = _area_gaps(area)
            if row.column and gaps is None:
                continue
            left = page.body[0] + sum(area.widths[:row.column]) + sum((gaps or ())[:row.column]) + row.x
            right = left + max(cell.x + cell.width for cell in row.cells)
            boxes.append((row.top, row.top + row.height, left, right))
    return boxes


def _area_gaps(area: Any) -> tuple[int, ...] | None:
    """The gap after each column of a column area but the last (``gaps``, or the one ``gap`` of equal columns);
    ``None`` when neither is given."""
    gaps = tuple(getattr(area, "gaps", ()) or ())
    if len(gaps) == len(area.widths) - 1:
        return gaps
    return (area.gap,) * (len(area.widths) - 1) if area.gap is not None else None


def _column_lines(page: Any, issues: Counter[tuple[str, str]], tables: tuple[Any, ...] = ()) -> str:
    """The lines between the columns of each column area of *page* that has one (``ColumnArea.separator``), on the
    paper: in the middle of each gap (the layout gives no x: column *n*'s gap runs from ``sum(widths[:n + 1]) +
    sum(gaps[:n])`` right of the body's left edge, ``gaps[n]`` wide), from the area's top to the next area's top or
    the body's foot, broken where an engine table row set on the page (*tables*) stands across the gap (a table
    across the columns is not struck through). A line style other than solid is drawn solid; what is drawn
    otherwise is counted in *issues*."""
    body_left, body_top, _, body_height = page.body
    areas = page.column_areas
    across = _rows_across(page, tables) if tables else []
    lines = []
    for number, area in enumerate(areas):
        separator = getattr(area, "separator", None)
        if separator is None or len(area.widths) < 2:
            continue
        gaps = _area_gaps(area)
        if gaps is None:
            issues[_COLUMN_LINE_GAP] += 1
            continue
        if (separator.type or "").upper() != "SOLID":
            issues[_COLUMN_LINE_STYLE] += 1
        if separator.width_mm is None:
            issues[_COLUMN_LINE_WIDTH] += 1
        width = f"{separator.width_mm:g}mm" if separator.width_mm is not None else "0mm"
        top = area.top
        foot = areas[number + 1].top if number + 1 < len(areas) else body_top + body_height
        if foot <= top:
            continue
        for column in range(len(area.widths) - 1):
            middle = body_left + sum(area.widths[:column + 1]) + sum(gaps[:column]) + gaps[column] / 2
            breaks = sorted((max(row_top, top), min(row_foot, foot)) for row_top, row_foot, left, right in across
                            if left < middle < right and row_top < foot and row_foot > top)
            start = top
            for stop, resume in [*breaks, (foot, foot)]:
                if stop > start:
                    css = _style_attr({
                        "left": _fmt_mm(_hwp_to_mm(middle)), "top": _fmt_mm(_hwp_to_mm(start)),
                        "height": _fmt_mm(_hwp_to_mm(stop - start)),
                        "border-left": f"max(1px, {width}) solid {_css_color(separator.color)}",
                        "transform": "translateX(-50%)",
                    })
                    lines.append(f'<i class="hwpx-column-line" data-column-area="{number}" data-column="{column}" '
                                 f'style="{css}"></i>')
                start = max(start, resume)
    return "".join(lines)


def _engine_page_fragment(page: Any, page_id: str, content: str, *, flow: bool, backdrop: str = "") -> str:
    """One page box. A flow page is as high as its paper: what its approximate flow stacks past the body's
    foot is moved (by the page's script) into the overflow band under the box, so its footer stays in the
    footer's place; without the script the box grows, its footer still on the box's foot."""
    width, height = map(_hwp_to_mm, (page.paper_width, page.paper_height))
    if flow:
        left, top, body_width, body_height = map(_hwp_to_mm, page.body)
        right = max(0, width - left - body_width)
        bottom = max(0, height - top - body_height)
        padding = " ".join(map(_fmt_mm, (max(top, 6), right, bottom, left)))
        style = (f"width:{_fmt_mm(width)};padding:{padding};min-height:{_fmt_mm(height)};"
                 f"--hwpx-paper-height:{_fmt_mm(height)}")
        body = (
            f"{backdrop}"
            '<p class="hwpx-engine-page-status">세로 배치 근사'
            '<span class="hwpx-engine-overflow" hidden> · 근사 배치가 엔진 본문 높이를 넘어 넘친 부분은 쪽 아래 띠에</span></p>'
            f'<div class="hwpx-engine-flow" style="min-height:{_fmt_mm(body_height)}">{content}</div>'
            f'<div class="hwpx-engine-spill" hidden style="padding:0 {_fmt_mm(right)} 0 {_fmt_mm(left)}">'
            '<div class="hwpx-engine-spill-flow"></div></div>'
        )
    else:
        style = f"width:{_fmt_mm(width)};padding:0"
        body = f'<div class="hwpx-engine-canvas" style="height:{_fmt_mm(height)}">{backdrop}{content}</div>'
    classes = "hwpx-preview-page hwpx-engine-page"
    if flow:
        classes += " hwpx-engine-flow-page"
    return (
        f'<section id="{page_id}" class="{classes}" data-layout-mode="{"flow" if flow else "positioned"}" '
        f'data-page-index="{page.page}" data-section-index="{page.section}" style="{style}">{body}</section>'
    )


def _header_footer_margins(section: ET.Element) -> dict[str, int]:
    """The header and footer margins a section's page sets (``hp:pagePr/hp:margin``), in HWPUNIT."""
    margin = section.find(f".//{_HP}pagePr/{_HP}margin")
    defaults = {key: round(_DEFAULT_MARGINS_MM[key] * _HWP_UNITS_PER_MM) for key in ("header", "footer")}
    if margin is None:
        return defaults
    return {key: _safe_int(margin.get(key), defaults[key]) for key in defaults}


def _paragraph_pages(layout: Any) -> dict[tuple[int, int], int]:
    """The page each body paragraph the engine lists starts on (its first visible line's)."""
    found = {}
    for placed in layout.paragraphs:
        visible = [line for line in placed.lines if not line.hidden] or list(placed.lines)
        if visible:
            found[(placed.section, placed.paragraph)] = visible[0].position.page
    return found


def _page_controls(
    body_paragraphs: list[list[ET.Element]], starts: Mapping[tuple[int, int], int], name: str,
) -> list[tuple[int, int, ET.Element]]:
    """The page controls *name* (``hp:ctrl/hp:<name>``) of the body, with their section and their paragraph's page."""
    return [
        (number, starts[(number, index)], node)
        for number, paragraphs in enumerate(body_paragraphs) for index, paragraph in enumerate(paragraphs)
        if (number, index) in starts for node in paragraph.findall(f"{_HP}run/{_HP}ctrl/{_HP}{name}")
    ]


def _page_numbering(
    layout: Any, sections: list[ET.Element], body_paragraphs: list[list[ET.Element]],
    starts: Mapping[tuple[int, int], int], issues: Counter[tuple[str, str]],
) -> _Numbering:
    """The number of each page in the engine's page order: the engine's (``PagePlacement.number``) where it
    gives one. Where it does not, the preview's own count stands in, as an approximation: one more than the
    page before, from 1; a section whose ``hp:startNum@page`` is set starts at it, and a page a body
    paragraph sets a new page number on (``hp:newNum@numType=PAGE``) takes it."""
    renumbered = {
        page: _safe_int(node.get("num"), 1) for _, page, node in _page_controls(body_paragraphs, starts, "newNum")
        if node.get("numType") == "PAGE"
    }
    first: dict[int, int] = {}
    for page in layout.pages:
        first.setdefault(page.section, page.page)
    numbers: list[int] = []
    counted: set[int] = set()
    for page in layout.pages:
        engine = getattr(page, "number", None)
        start = sections[page.section].find(f".//{_HP}secPr/{_HP}startNum") if page.section < len(sections) else None
        if engine is not None:
            number = engine
        elif page.page in renumbered:
            number = renumbered[page.page]
        elif first[page.section] == page.page and start is not None and _safe_int(start.get("page")) > 0:
            number = _safe_int(start.get("page"))
        else:
            number = numbers[-1] + 1 if numbers else 1
        if engine is None:
            counted.add(page.page)
        numbers.append(number)
    return _Numbering(tuple(numbers), issues, frozenset(counted))


_PAGE_NUMBER_PLACE = ("page-number", "page number is drawn at an approximate place in the header or footer margin")


def _page_number_anchors(
    layout: Any, body_paragraphs: list[list[ET.Element]], starts: Mapping[tuple[int, int], int],
    numbering: _Numbering, margins: list[dict[str, int]], issues: Counter[tuple[str, str]],
) -> list[_AnchorMarkup]:
    """The page number a body paragraph's ``hp:pageNum`` shows on each page from its own to the next one's,
    in the header or footer margin of the page at its side (outside or inside by the number's parity), its
    number in its number style between its side characters. A page a ``hp:pageHiding@hidePageNum`` hides
    shows none. Each is drawn at an approximate place, counted. The number is shown by the style sheet
    (``data-number-text``), not as text of the page."""
    controls = _page_controls(body_paragraphs, starts, "pageNum")
    hidden = {
        page for _, page, node in _page_controls(body_paragraphs, starts, "pageHiding")
        if node.get("hidePageNum") in ("1", "true")
    }
    anchors = []
    for page in layout.pages:
        control = next((node for section, start, node in reversed(controls)
                        if section == page.section and start <= page.page), None)
        position = (control.get("pos") or "NONE").upper() if control is not None else "NONE"
        if control is None or position == "NONE" or page.page in hidden:
            continue
        number = numbering.numbers[page.page]
        if page.page in numbering.counted:
            issues[_NUMBER_COUNTED] += 1
        vertical, _, side = position.partition("_")
        if vertical in ("OUTSIDE", "INSIDE"):
            vertical, side = side, ("RIGHT" if (number % 2 == 1) == (vertical == "OUTSIDE") else "LEFT")
        left, top, width, height = page.body
        own = margins[page.section] if page.section < len(margins) else {}
        room = (top - own.get("header", 0), own.get("header", 0)) if vertical == "TOP" else (
            top + height, own.get("footer", 0))
        text = _number_text(number, control.get("formatType"), issues)
        side_char = control.get("sideChar") or ""
        if side_char:
            text = f"{side_char} {text} {side_char}"
        css = _style_attr({
            "left": _fmt_mm(_hwp_to_mm(left)), "top": _fmt_mm(_hwp_to_mm(room[0])),
            "width": _fmt_mm(_hwp_to_mm(width)), "height": _fmt_mm(_hwp_to_mm(room[1])),
            "justify-content": {"LEFT": "flex-start", "RIGHT": "flex-end"}.get(side, "center"),
        })
        # Drawn by the style sheet from the attribute: a page number control is not text of the document
        # (Hangul gives none for it when it lists a page's text), so it stays out of the page's text.
        markup = (f'<div class="hwpx-page-number" data-approx="page-number" data-number-position="{position}" '
                  f'data-number-text="{html.escape(text, quote=True)}" style="{css}"></div>')
        issues[_PAGE_NUMBER_PLACE] += 1
        anchors.append(_AnchorMarkup(
            page.page, markup, flow=False, overlay=True,
            flow_html=f'<div class="hwpx-area-foot">{markup}</div>' if vertical == "BOTTOM" else None,
        ))
    return anchors


def _memo_count(sections: list[ET.Element]) -> int:
    """The memos of the document: its MEMO fields, and the ``hp:memogroup`` memos no field anchors.

    Hangul keeps a memo's text off the page, so the preview does not draw it; the count says so.
    """
    count = 0
    for section in sections:
        anchored: set[str] = set()
        for begin in section.iter(f"{_HP}fieldBegin"):
            if begin.get("type") == "MEMO":
                count += 1
                anchored.update(param.text or "" for param in begin.iter(f"{_HP}stringParam") if param.get("name") == "ID")
        count += sum(1 for memo in section.findall(f"{_HP}memogroup/{_HP}memo") if memo.get("id") not in anchored)
    return count


def _render_engine_preview(
    document: HwpxDocument, layout: Any, mode: str, title: str,
    styles: Mapping[str, Any], warnings: list[str], parts: Mapping[str, bytes],
) -> LayoutPreview:
    """The engine preview, the numbers and bullets of its paragraphs drawn before their first lines."""
    labels = _Labels.of(document, styles["char"])
    token = _LABELS.set(labels)
    try:
        return _draw_engine_preview(document, layout, mode, title, styles, warnings, parts, labels)
    finally:
        _LABELS.reset(token)


def _draw_engine_preview(
    document: HwpxDocument, layout: Any, mode: str, title: str,
    styles: Mapping[str, Any], warnings: list[str], parts: Mapping[str, bytes], labels: _Labels,
) -> LayoutPreview:
    sections = [section.element for section in document.sections]
    body_paragraphs = [section.findall(f"{_HP}p") for section in sections]
    content: list[list[str | _PlacedLine | _AnchorMarkup]] = [[] for _ in layout.pages]
    flow_pages: set[int] = set()
    paragraphs_by_page: list[set[tuple[int, int]]] = [set() for _ in layout.pages]
    table_counts: Counter[int] = Counter()
    issues: Counter[tuple[str, str]] = Counter()
    for reason, count in _conversion_notes(document):
        issues[("hwp-conversion", reason)] += count
    counter = _ObjectCounter()
    tables_by_paragraph: dict[tuple[int, int], dict[int, Any]] = {}
    for table in getattr(layout, "tables", ()):
        if all(0 <= row.page < len(layout.pages) for row in table.rows):
            tables_by_paragraph.setdefault((table.section, table.paragraph), {})[table.table] = table
    objects_by_paragraph: dict[tuple[int, int], dict[int, Any]] = {}
    for obj in getattr(layout, "objects", ()):
        objects_by_paragraph.setdefault((obj.section, obj.paragraph), {})[obj.object_index] = obj
    areas_by_paragraph: dict[tuple[int, int], dict[int, list[Any]]] = {}
    for area in getattr(layout, "areas", ()):
        areas_by_paragraph.setdefault((area.section, area.paragraph), {}).setdefault(area.area, []).append(area)
    fill_pictures = any(border["fill_picture"] is not None for border in styles["border"].values())
    images = _picture_sources(document, parts) if objects_by_paragraph or fill_pictures else {}
    section_starts: dict[int, int] = {}
    for page in layout.pages:
        section_starts.setdefault(page.section, page.page)
    area_margins = [_header_footer_margins(section) for section in sections]
    starts = _paragraph_pages(layout)
    numbering = _page_numbering(layout, sections, body_paragraphs, starts, issues)
    # The column each item of a page stands in, as (column area, column); None: the one of the item before.
    slots: list[list[tuple[int, int] | None]] = [[] for _ in layout.pages]

    def put(page: int, item: str | _PlacedLine | _AnchorMarkup, line: Any = None, at: int | None = None) -> None:
        slot = _slot(layout.pages[page], line) if line is not None else None
        if at is None:
            content[page].append(item)
            slots[page].append(slot)
        else:
            content[page].insert(at, item)
            slots[page].insert(at, slot)

    for placed in layout.paragraphs:
        key = placed.section, placed.paragraph
        paragraph = body_paragraphs[key[0]][key[1]]
        visible = [line for line in placed.lines if not line.hidden]
        first_on: dict[int, Any] = {}
        for line in visible:
            first_on.setdefault(line.position.page, line)
        home = placed.lines[0].position.page if placed.lines else section_starts[key[0]]
        table_results = tables_by_paragraph.get(key, {})
        table_placements = {
            table: table_results[index] for index, table in enumerate(paragraph.iter(f"{_HP}tbl"))
            if index in table_results
        }
        objects = objects_by_paragraph.get(key, {})
        areas = areas_by_paragraph.get(key, {})
        sources = _ParagraphSources(
            table_placements,
            {node: objects[index] for index, node in enumerate(
                child for child in paragraph.iter() if child.tag in _OBJECT_TAGS) if index in objects},
            {node: areas[index] for index, node in enumerate(
                child for child in paragraph.iter() if child.tag in _AREA_LABELS) if index in areas},
            images,
            frozenset(
                number for table in table_results.values() for row in table.rows for cell in row.cells
                for line in getattr(cell, "lines_with_tables", ()) for number in line.tables
            ),
            tuple(visible),
            area_margins[key[0]],
            numbering,
        )
        without_text_range = [line for line in visible if line.text is None]
        missing_pages = {line.position.page for line in without_text_range}
        flow_pages.update(missing_pages)
        text = _paragraph_text(paragraph)
        uncovered = bool(
            placed.lines and not without_text_range
            and _characters(text) - _characters("".join(line.text for line in visible))
        )
        fallback = (without_text_range or not placed.lines or uncovered) and text
        shown: list[_PlacedLine] = []
        # Where the paragraph's items begin on each page: a table it anchors that the engine sets above its
        # first line there goes before that line, as it stands on the paper.
        opened = {page: len(content[page]) for page in first_on}
        if fallback:
            issues[("paragraph", "engine lines do not give all the paragraph's text" if uncovered
                    else "engine text ranges are unavailable")] += 1
            flow_pages.add(home)
            put(home, _render_paragraph(
                paragraph, styles, counter, include_tables=False, include_objects=False, extended_styles=True,
            ), first_on.get(home))
            paragraphs_by_page[home].add(key)
            for page in sorted({line.position.page for line in visible} - {home}):
                flow_pages.add(page)
                paragraphs_by_page[page].add(key)
                marker = _render_object_marker("이어지는 문단의 줄 위치 미확인")
                put(page, f'<p class="hwpx-paragraph">{marker}</p>', first_on.get(page))
        else:
            if without_text_range:
                issues[("line", "engine text ranges are unavailable")] += len(without_text_range)
            for line in visible:
                page = line.position.page
                paragraphs_by_page[page].add(key)
                if line.text is not None:
                    shown.append(_PlacedLine(line, paragraph))
                    put(page, shown[-1], line)
                    if _line_frame(line, layout.pages[page])[3]:
                        flow_pages.add(page)
                        issues[("line", "horizontal placement is incomplete")] += 1
                    if line.text and hasattr(line, "runs") and not line.runs:
                        issues[("line", "original character run could not be matched")] += 1
        # A paragraph's only line, when empty, is the line its objects placed as characters stand in.
        # They go into that line until something else of the paragraph is drawn on its page,
        # so the page keeps the document's order.
        host = shown[0] if len(visible) == 1 and shown and shown[0].line.text == "" else None
        for anchor in _flow_anchors(paragraph, styles, counter, issues, home, sources, table_counts, layout.pages):
            if anchor.flow:
                flow_pages.add(anchor.page)
            paragraphs_by_page[anchor.page].add(key)
            hostable = anchor.flow or anchor.table is not None  # a table's flowing rows stand in the line
            if host is not None and hostable and anchor.inline and anchor.page == host.line.position.page:
                host.hosted.append(anchor)
                continue
            if host is not None and anchor.page == host.line.position.page:
                host = None
            first = first_on.get(anchor.page)
            above = (anchor.box is not None and first is not None and not anchor.inline and not anchor.overlay
                     and anchor.box[0] < first.top and opened.get(anchor.page, 0) < len(content[anchor.page]))
            put(anchor.page, anchor, first, at=opened[anchor.page] if above else None)
            if above:
                opened[anchor.page] += 1

    # A body paragraph the engine lists nowhere is still shown, on its section's first page; what a header,
    # footer or note of it holds stands beside the body, in its margin, as one the engine gives no page.
    listed = {(placed.section, placed.paragraph) for placed in layout.paragraphs}
    for number, paragraphs in enumerate(body_paragraphs):
        for index, paragraph in enumerate(paragraphs):
            if (number, index) not in listed and number in section_starts and (
                _paragraph_text(paragraph).strip() or _has_objects(paragraph)
                or next(_anchored_tables(paragraph), None) is not None
                or any(node.tag in _AREA_LABELS for node in paragraph.iter())
            ):
                page = section_starts[number]
                issues[("paragraph", "paragraph the engine places nowhere is shown on its section's first page")] += 1
                flow_pages.add(page)
                paragraphs_by_page[page].add((number, index))
                put(page, _render_paragraph(paragraph, styles, counter, include_tables=False, extended_styles=True)
                    + "".join(_render_table(table, styles, counter, diagonals=issues)
                              for table in _anchored_tables(paragraph, areas=False)))
                for area in (node for node in paragraph.iter() if node.tag in _AREA_LABELS):
                    for anchor in _engine_area_anchors(area, page, [], layout.pages, styles, issues, counter,
                                                       area_margins[number], table_counts, numbering):
                        put(anchor.page, anchor)
    for anchor in _page_number_anchors(layout, body_paragraphs, starts, numbering, area_margins, issues):
        put(anchor.page, anchor)
    fills = [_page_fill(section, styles, images) for section in sections]
    filled = {
        page.page: fill for page in layout.pages
        if (fill := fills[page.section]) is not None and fill.shows_on(page.page == section_starts[page.section])
    }
    with_pictures = sum(len(fill.picture[1]) for fill in filled.values() if fill.picture) <= _PAGE_FILL_PICTURE_BUDGET
    flowing_tables: set[int] = set()
    fragments, pages = [], []
    for page in layout.pages:
        index = page.page
        width, height = map(_hwp_to_mm, (page.paper_width, page.paper_height))
        _, _, margins = _page_spec(sections[page.section])
        page_id = f"hwpx-preview-page-{index + 1}"
        flow = index in flow_pages
        backdrop = ""
        if index in filled:
            backdrop = filled[index].markup(page, with_picture=with_pictures)
            for note in filled[index].notes:
                issues[("page-fill", note)] += 1
            if filled[index].picture is not None and not with_pictures:
                issues[("page-fill", "page fill picture is not drawn")] += 1
        backdrop += _column_lines(page, issues, layout.tables)
        fragments.append(_engine_page_fragment(
            page, page_id,
            _page_content(content[index], page, styles, flow=flow, issues=issues, flowing_tables=flowing_tables,
                          slots=slots[index]),
            flow=flow, backdrop=backdrop,
        ))
        pages.append(PreviewPage(index, page.section, page_id, width, height, margins,
                                 len(paragraphs_by_page[index]), table_counts[index]))
    if flowing_tables:
        issues[_FLOWING_TABLE] += len(flowing_tables)
    issues.update(labels.issues)
    if labels.drawn:
        issues[_LABEL_ROOM] += len(labels.drawn)
    if memos := _memo_count(sections):
        issues[("memo", "memo text is not part of the page")] += memos
    if flow_pages:
        issues[("page-flow", "vertical placement is approximate and may exceed the engine body")] = len(flow_pages)
    limitations = tuple(_Limitation(kind, reason, count) for (kind, reason), count in sorted(issues.items()))
    warnings.extend(f"{item.kind}: {item.reason} ({item.count})" for item in limitations)
    tier = _PARTIAL if limitations else _ENGINE
    document_html = _document_html(
        title=title, mode=mode, body="".join(fragments), fidelity_tier=tier, has_flow=bool(flow_pages),
    )
    return LayoutPreview(document_html, tuple(pages), tuple(warnings), mode, tuple(fragments), tier, limitations)


def render_layout_preview(
    source: str | Path | bytes,
    *,
    mode: str = "pages",
    title: str = "HWPX Layout Preview",
) -> LayoutPreview:
    """Render an HWPX package into layout-aware HTML.

    Args:
        source: HWPX file path or raw HWPX bytes. A document python-hwpx opens by
            converting it (HWP 5.0) is previewed as that conversion.
        mode: ``"pages"`` for page boxes or ``"long"`` for continuous scrolling.
        title: HTML document title.
    """

    if mode not in {"pages", "long"}:
        raise ValueError("mode must be 'pages' or 'long'")

    # One reader: the parts come from the document python-hwpx opened for the estimate.
    # A source it refuses is read as before, with the same error for an unreadable package.
    opened, refused = _open_for_estimate(source)
    warnings: list[str]
    if opened is not None:
        parts, warnings = _document_parts(opened), []
    else:
        parts, warnings = _read_package_parts(source)
    header = _parse_xml(parts, "Contents/header.xml", warnings)
    styles = _collect_style_maps(header)
    pre_estimate_warnings = len(warnings)
    engine_preview = _engine_preview(opened, refused, mode, title, styles, warnings, parts)
    if engine_preview is not None:
        return engine_preview

    approximation = tuple(_Limitation("document", reason, 1) for reason in warnings[pre_estimate_warnings:])
    counter = _ObjectCounter()
    pages_html: list[str] = []
    pages: list[PreviewPage] = []
    for section_index, name in enumerate(_section_names(parts)):
        section = _parse_xml(parts, name, warnings)
        if section is None:
            continue
        split_pages = _split_section_pages(section)
        if mode == "long":
            split_pages = [_section_blocks(section)]
        for paragraphs in split_pages:
            page_html, page = _render_page(
                len(pages),
                section_index,
                paragraphs,
                section,
                styles,
                counter,
            )
            pages_html.append(page_html)
            pages.append(page)

    if not pages:
        warnings.append("no renderable HWPX sections were found")

    document = _document_html(title=title, mode=mode, body="".join(pages_html))
    return LayoutPreview(
        html=document,
        pages=tuple(pages),
        warnings=tuple(warnings),
        mode=mode,
        page_fragments=tuple(pages_html),
        limitations=approximation,
    )


__all__ = ["LayoutPreview", "PreviewPage", "render_layout_preview"]
