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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from hwpx import HwpxDocument, experimental
from hwpx.errors import HwpxError
from hwpx.opc.security import guard_zip_file, parse_xml_stdlib, read_member
from hwpx.oxml.section_format import PAGE_PORTRAIT
from hwpx.oxml.table_sizes import cell_margins_of

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
    #: What a flow page shows instead of *html* (area lines at the engine's pitch).
    flow_html: str | None = None


@dataclass
class _PlacedLine:
    """A body line waiting for its page: a flow page gives it the engine's advance to the next line."""

    line: Any
    paragraph: ET.Element
    hosted: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _ParagraphSources:
    tables: Mapping[Any, Any]
    objects: Mapping[Any, Any]
    areas: Mapping[Any, list[Any]]
    images: Mapping[str, tuple[str, bytes]]
    #: Tables (by ``TablePlacement.table``) the engine sets on a line of some cell of this paragraph.
    hosted_tables: frozenset[int] = frozenset()


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

    return {"sides": sides, "fill": fill, "shown_fill": shown, "fill_notes": tuple(notes), "fill_picture": image}


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
        _render_inline_runs(paragraph, styles, counter, include_objects=False, extended_styles=True)
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
        if text:
            char_style = char_styles.get(run.get("charPrIDRef") or "0", {})
            style = _character_css(char_style, extended=extended_styles)
            spans.append(f'<span style="{style}">{html.escape(text)}</span>')
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
) -> str:
    """One table, or the rows of it the engine set on one page (*row_parts*).

    *plans* say where each placed cell draws what the engine's lines do not show. The part
    that is *closing* (it holds the table's last placed row) also draws, from the file, the
    rows of cells the engine placed in no row at all.
    """
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
            css = _border_style(tc.get("borderFillIDRef") or table.get("borderFillIDRef"), styles, issues=issues)
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
            cells.append(f"<td {' '.join(attrs)}>{''.join(body_parts)}</td>")
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
        plans[number] = _CellPlan(id(parts[0]), home, frozenset(whole), bool(shown))
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
    text = _styled_line_text(line, styles) if line.text is not None else ""
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
) -> str:
    text_html = _render_inline_runs(
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
            result.append(_render_table(table, styles, counter))
    return "".join(result)


def _split_section_pages(section: ET.Element) -> list[list[ET.Element]]:
    pages: list[list[ET.Element]] = [[]]
    for paragraph in section.findall(f"{_HP}p"):
        if paragraph.get("pageBreak") == "1" and pages[-1]:
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
    body = "".join(_render_paragraph(p, styles, counter) for p in paragraphs)
    table_count = sum(len(p.findall(f".//{_HP}tbl")) for p in paragraphs)
    page = PreviewPage(
        index=page_index,
        section_index=section_index,
        page_id=page_id,
        width_mm=width_mm,
        height_mm=height_mm,
        margins_mm=margins_mm,
        paragraph_count=len(paragraphs),
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
        ".hwpx-placed-object { display: block; box-sizing: border-box; margin: 0; }\n"
        ".hwpx-placed-object[data-overlay] { position: absolute; }\n"
        ".hwpx-placed-object[data-overlay=behind] { z-index: -1; }\n"
        ".hwpx-placed-object[data-overlay=front] { z-index: 2; }\n"
        ".hwpx-placed-object img { display: block; width: 100%; height: 100%; }\n"
        ".hwpx-placed-object.hwpx-shape-outline { border: 1px solid #646e79; }\n"
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
  function measure(body) {
    const page = body.parentElement;
    const engineHeight = parseFloat(getComputedStyle(body).minHeight);
    const overflows = body.getBoundingClientRect().height > engineHeight + 0.5;
    page.dataset.flowHeight = Math.ceil(page.getBoundingClientRect().height);
    page.dataset.flowOverflow = String(overflows);
    page.querySelector('.hwpx-engine-overflow').hidden = !overflows;
  }
  const observer = new ResizeObserver(entries => entries.forEach(entry => measure(entry.target)));
  document.querySelectorAll('.hwpx-engine-flow').forEach(body => {
    measure(body);
    observer.observe(body);
  });
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
        f"{_flow_overflow_script() if has_flow else ''}"
        "</body>\n"
        "</html>\n"
    )


def _styled_line_text(line: Any, styles: Mapping[str, Any]) -> str:
    runs = getattr(line, "runs", ())
    if not runs:
        return html.escape(line.text.removesuffix("\n"))
    spans = []
    for index, (reference, text) in enumerate(runs):
        if index == len(runs) - 1:
            text = text.removesuffix("\n")
        if not text:
            continue
        char = styles["char"].get(reference, {})
        css = _character_css(char, extended=True)
        spans.append(f'<span style="{css}">{html.escape(text)}</span>')
    return "".join(spans)


def _line_frame(line: Any, page: Any) -> tuple[float, float | None, float, bool]:
    """Paper x, column-area offset and width of a line, and whether its horizontal placement is incomplete."""
    left, _, body_width, _ = page.body
    area = next((area for area in reversed(page.column_areas) if area.top <= line.top), None)
    column = line.position.column
    column_x = None if area is None or column >= len(area.widths) or (column and area.gap is None) else (
        sum(area.widths[:column]) + column * (area.gap or 0)
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
    advance: int | None = None, hosted: str = "",
) -> tuple[str, bool]:
    """One engine line. In a flow page it takes *advance*, and *hosted* is drawn inside it."""
    paper_x, offset, width, approximate = _line_frame(line, page)
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
    text = _styled_line_text(line, styles)
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
                anchors.append(_object_anchor(obj, home, sources.objects.get(obj), sources.images, issues, counter, styles))
            for table in _outer_tables(child):
                anchors.extend(_table_anchors(table, styles, counter, issues, home, sources, table_counts))
            for area in child.iter():
                if area.tag in _AREA_LABELS:
                    anchors.extend(_area_anchors(area, home, sources.areas.get(area, []), pages, styles, issues))
    return anchors


def _placed_as_character(element: ET.Element) -> bool:
    position = element.find(f"{_HP}pos")
    return position is not None and position.get("treatAsChar") == "1"


def _table_anchors(
    table: ET.Element, styles: Mapping[str, Any], counter: _ObjectCounter, issues: Counter[tuple[str, str]],
    home: int, sources: _ParagraphSources, table_counts: Counter[int],
) -> list[_AnchorMarkup]:
    placements = sources.tables
    placed = placements.get(table)
    inline = _placed_as_character(table)
    if placed is None or not placed.rows:
        count = sum(1 for _ in table.iter(f"{_HP}tbl"))
        issues[("table", "row and cell placement is unavailable")] += count
        table_counts[home] += count
        return [_AnchorMarkup(
            home, _render_table(
                table, styles, counter, flow=True, show_approx_caption=True, issues=issues, sources=sources,
            ),
            inline=inline,
        )]
    plans = _cell_plans(table, placed)
    issues[("table", "table content uses approximate flow within engine row pages")] += 1
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
    for page, rows in sorted(rows_by_page.items()):
        table_counts[page] += 1
        captions = tuple(caption for caption in placed.captions if caption.page == page)
        anchors.append(_AnchorMarkup(page, _render_table(
            table, styles, counter, flow=True, row_parts=tuple(rows), table_index=placed.table,
            table_placements=placements, continued_rows=frozenset(seen), captions=captions,
            show_approx_caption=fallback_caption and page == min(rows_by_page), issues=issues, sources=sources,
            plans=plans, closing=rows[-1] is placed.rows[-1],
        ), inline=inline))
        seen.update(row.row for row in rows if not row.repeated)
    return anchors


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


def _object_anchor(
    element: ET.Element, home: int, placed: Any, images: Mapping[str, tuple[str, bytes]],
    issues: Counter[tuple[str, str]], counter: _ObjectCounter, styles: Mapping[str, Any],
) -> _AnchorMarkup:
    kind = _OBJECT_KINDS.get(element.tag, "shape" if element.tag in _SHAPE_TAGS else element.tag.removeprefix(_HP))
    page = home if placed is None or placed.page is None else placed.page
    width, height = (None, None) if placed is None else (placed.width, placed.height)
    left, top = (None, None) if placed is None else (placed.x, placed.top)
    sized = width is not None and height is not None and width > 0 and height > 0
    positioned = sized and left is not None and top is not None
    if not positioned:
        for reason in (placed.unavailable if placed is not None and placed.unavailable else
                       ("object placement is unavailable",)):
            issues[(kind, reason)] += 1
    classes = "hwpx-placed-object"
    overlay = ""
    if positioned:
        layer = {"IN_FRONT_OF_TEXT": "front", "BEHIND_TEXT": "behind"}.get(placed.wrap if placed is not None else "")
        if layer:
            overlay = f' data-overlay="{layer}"'
    if element.tag == _PICTURE_TAG:
        label = f"그림 {counter.next_picture()}"
        image = element.find(f".//{_HC}img")
        asset = images.get(image.get("binaryItemIDRef", "")) if image is not None else None
        if asset is not None and sized:
            mime, data = asset
            encoded = base64.b64encode(data).decode("ascii")
            content = f'<img alt="{label}" src="data:{mime};base64,{encoded}">'
        else:
            content = _render_object_marker(label)
            if asset is None:
                issues[(kind, "embedded image is missing or unsupported in the browser")] += 1
    elif element.tag in _SHAPE_TAGS and sized:
        classes += " hwpx-shape-outline"
        if positioned:
            text = "<br>".join(html.escape(line) for line in _shape_text_lines(element, captions=False))
            content = f'<div aria-label="도형">{text}</div>'
        else:
            content = _render_shape(element, captions=False)
    elif element.tag in _OTHER_OBJECT_LABELS:
        content = _render_object_marker(_OTHER_OBJECT_LABELS[element.tag])
        issues[(kind, _PLACEHOLDER)] += 1
    elif element.tag in _SHAPE_TAGS:
        content = _render_shape(element, captions=False)
    else:
        content = _render_inline_object(element, counter)
    css = _style_attr({
        key: _fmt_mm(_hwp_to_mm(value)) for key, value in (
            ("left", left), ("top", top), ("width", width), ("height", height),
        ) if value is not None
    })
    markup = f'<div class="{classes}" data-object-kind="{kind}"{overlay} style="{css}">{content}</div>'
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


def _area_anchors(area: ET.Element, home: int, placements: list[Any], pages: tuple[Any, ...],
                  styles: Mapping[str, Any], issues: Counter[tuple[str, str]]) -> list[_AnchorMarkup]:
    label = _AREA_LABELS[area.tag]
    kind = area.tag.removeprefix(_HP)
    paragraphs = list(area.iter(f"{_HP}p"))
    if not placements:
        placements = [None]
    # The lines of all the area's parts must give all its text, or it is shown whole the approximate way.
    given: Counter[str] = Counter()
    for placed in placements:
        for line in (placed.lines if placed is not None else ()):
            given.update(_characters(line.text or ""))
    covered = not (_characters("".join(_paragraph_text(paragraph) for paragraph in paragraphs)) - given)
    if not covered and any(placed is not None and placed.lines for placed in placements):
        issues[(kind, "area lines do not give all its text: the area is shown whole")] += 1
    result = []
    for index, placed in enumerate(placements):
        page = placed.page if placed is not None and placed.page is not None else home
        lines = placed.lines if placed is not None else ()
        if covered and lines and all(line.text is not None for line in lines) and paragraphs:
            rendered = [_engine_line(line, paragraphs[0], styles, pages[page], area_line=True) for line in lines]
            exact = (placed is not None and placed.top is not None and placed.x is not None
                     and not any(partial for _, partial in rendered))
            if not exact:
                issues[(kind, "area coordinates are incomplete")] += 1
            prefix = "" if exact else _render_object_marker(label)
            content = prefix + "".join(markup for markup, _ in rendered)
            paced = prefix + "".join(
                _engine_line(line, paragraphs[0], styles, pages[page], area_line=True,
                             advance=_line_advance(line, following))[0]
                for line, following in zip(lines, (*lines[1:], None))
            )
            result.append(_AnchorMarkup(
                page, f'<div data-area-kind="{kind}">{content}</div>', flow=not exact,
                flow_html=f'<div data-area-kind="{kind}">{paced}</div>',
            ))
        else:
            for reason in (placed.unavailable if placed is not None and placed.unavailable else
                           ("area placement is unavailable",)):
                issues[(kind, reason)] += 1
            text = " ".join(_paragraph_text(p) for p in paragraphs) if index == 0 else ""
            result.append(_AnchorMarkup(
                page, f'<p class="hwpx-paragraph" data-area-kind="{kind}">{_render_object_marker(label)} {html.escape(text)}</p>',
            ))
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


def _page_content(
    items: list[str | _PlacedLine | _AnchorMarkup], page: Any, styles: Mapping[str, Any], *, flow: bool,
) -> str:
    """The markup of one page. A flow page stacks its lines at the engine's line advance.

    The advance is the distance between the tops of two lines that follow each other in the
    same column with nothing between them taking room. A line without such a successor keeps
    its own height: the page stays marked as an approximate vertical placement.
    """
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
            parts.append(item.flow_html if flow and item.flow_html is not None else item.html)
        else:
            parts.append(_engine_line(
                item.line, item.paragraph, styles, page, advance=advances[index], hosted="".join(item.hosted),
            )[0])
    return "".join(parts)


def _engine_page_fragment(page: Any, page_id: str, content: str, *, flow: bool, backdrop: str = "") -> str:
    width, height = map(_hwp_to_mm, (page.paper_width, page.paper_height))
    if flow:
        left, top, body_width, body_height = map(_hwp_to_mm, page.body)
        right = max(0, width - left - body_width)
        bottom = max(0, height - top - body_height)
        padding = " ".join(map(_fmt_mm, (max(top, 6), right, bottom, left)))
        style = f"width:{_fmt_mm(width)};padding:{padding}"
        body = (
            f"{backdrop}"
            '<p class="hwpx-engine-page-status">세로 배치 근사'
            '<span class="hwpx-engine-overflow" hidden> · 근사 배치가 엔진 본문 높이를 넘습니다</span></p>'
            f'<div class="hwpx-engine-flow" style="min-height:{_fmt_mm(body_height)}">{content}</div>'
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


def _render_engine_preview(
    document: HwpxDocument, layout: Any, mode: str, title: str,
    styles: Mapping[str, Any], warnings: list[str], parts: Mapping[str, bytes],
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
    for placed in layout.paragraphs:
        key = placed.section, placed.paragraph
        paragraph = body_paragraphs[key[0]][key[1]]
        visible = [line for line in placed.lines if not line.hidden]
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
        if fallback:
            issues[("paragraph", "engine lines do not give all the paragraph's text" if uncovered
                    else "engine text ranges are unavailable")] += 1
            flow_pages.add(home)
            content[home].append(_render_paragraph(
                paragraph, styles, counter, include_tables=False, include_objects=False, extended_styles=True,
            ))
            paragraphs_by_page[home].add(key)
            for page in {line.position.page for line in visible} - {home}:
                flow_pages.add(page)
                paragraphs_by_page[page].add(key)
                marker = _render_object_marker("이어지는 문단의 줄 위치 미확인")
                content[page].append(f'<p class="hwpx-paragraph">{marker}</p>')
        else:
            if without_text_range:
                issues[("line", "engine text ranges are unavailable")] += len(without_text_range)
            for line in visible:
                page = line.position.page
                paragraphs_by_page[page].add(key)
                if line.text is not None:
                    shown.append(_PlacedLine(line, paragraph))
                    content[page].append(shown[-1])
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
            if host is not None and anchor.flow and anchor.inline and anchor.page == host.line.position.page:
                host.hosted.append(anchor.html)
                continue
            if host is not None and anchor.page == host.line.position.page:
                host = None
            content[anchor.page].append(anchor)

    # A body paragraph the engine lists nowhere is still shown, on its section's first page.
    listed = {(placed.section, placed.paragraph) for placed in layout.paragraphs}
    for number, paragraphs in enumerate(body_paragraphs):
        for index, paragraph in enumerate(paragraphs):
            if (number, index) not in listed and number in section_starts and (
                _paragraph_text(paragraph).strip() or _has_objects(paragraph)
                or next(_anchored_tables(paragraph), None) is not None
            ):
                page = section_starts[number]
                issues[("paragraph", "paragraph the engine places nowhere is shown on its section's first page")] += 1
                flow_pages.add(page)
                paragraphs_by_page[page].add((number, index))
                content[page].append(_render_paragraph(paragraph, styles, counter, extended_styles=True))
    fills = [_page_fill(section, styles, images) for section in sections]
    filled = {
        page.page: fill for page in layout.pages
        if (fill := fills[page.section]) is not None and fill.shows_on(page.page == section_starts[page.section])
    }
    with_pictures = sum(len(fill.picture[1]) for fill in filled.values() if fill.picture) <= _PAGE_FILL_PICTURE_BUDGET
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
        fragments.append(_engine_page_fragment(
            page, page_id, _page_content(content[index], page, styles, flow=flow), flow=flow, backdrop=backdrop,
        ))
        pages.append(PreviewPage(index, page.section, page_id, width, height, margins,
                                 len(paragraphs_by_page[index]), table_counts[index]))
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
            split_pages = [section.findall(f"{_HP}p")]
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
