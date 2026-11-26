# SPDX-License-Identifier: Apache-2.0
"""Layout-oriented HTML preview rendering for HWPX packages.

This renderer is intentionally approximate: it exposes page boxes, margins,
paragraph alignment, table geometry, and table borders so agents can cheaply
inspect layout before the final Hancom viewer check.

Moved from ``hwpx.tools.layout_preview`` (python-hwpx 6.x) unchanged; it reads
the package through python-hwpx's public input guards.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import html
import re
import io
from pathlib import Path
from typing import Any, Mapping
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
        chars[node.get("id", "")] = {
            "font_size_pt": _char_height_to_pt(node.get("height")),
            "color": _css_color(node.get("textColor")),
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
    return {
        "align": _TEXT_ALIGN.get(horizontal.lower(), "left"),
        "line_spacing_percent": _safe_int(
            line_spacing.get("value") if line_spacing is not None else None,
            160,
        ),
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

    return {"sides": sides, "fill": fill}


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


def _shape_text_lines(element: ET.Element) -> list[str]:
    """The text of a drawing object's text boxes (a group's too), one line per paragraph.

    Tables inside are rendered as tables after the paragraph and are not read here.
    """
    lines: list[str] = []
    for child in element:
        if child.tag == f"{_HP}tbl":
            continue
        if child.tag == f"{_HP}p":
            text = _paragraph_text(child)
            if text.strip():
                lines.append(text)
        lines.extend(_shape_text_lines(child))
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


def _render_shape(shape: ET.Element) -> str:
    lines = _shape_text_lines(shape)
    text = "<br>".join(html.escape(line) for line in lines)
    return _render_object_marker("도형") + (f'<span class="hwpx-shape-text">{text}</span>' if lines else "")


def _render_inline_runs(
    paragraph: ET.Element,
    styles: Mapping[str, Any],
    counter: _ObjectCounter,
    *,
    include_text: bool = True,
) -> str:
    spans: list[str] = []
    char_styles = styles["char"]
    for run in paragraph.findall(f"{_HP}run"):
        text = _find_text_in_run(run) if include_text else ""
        if text:
            char_style = char_styles.get(run.get("charPrIDRef") or "0", {})
            style = _style_attr(
                {
                    "font-size": _fmt_pt(char_style.get("font_size_pt", 10.0)),
                    "color": char_style.get("color", "#000000"),
                }
            )
            spans.append(f'<span style="{style}">{html.escape(text)}</span>')
        # Inline objects that carry no text are rendered as real content or an
        # honest marker -- never dropped to a blank (Constitution VI).
        for child in run:
            if child.tag == _EQUATION_TAG:
                spans.append(_render_equation_element(child))
            elif child.tag == _PICTURE_TAG:
                spans.append(_render_object_marker(f"그림 {counter.next_picture()}"))
            elif child.tag == _OLE_TAG:
                spans.append(_render_object_marker("개체"))
            elif child.tag in _SHAPE_TAGS:
                spans.append(_render_shape(child))
    return "".join(spans)


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


def _border_style(border_ref: str | None, styles: Mapping[str, Any]) -> dict[str, str | None]:
    border = styles["border"].get(border_ref or "", {})
    sides = border.get("sides") or {}
    return {
        "border-left": sides.get("left", "1px solid #b9c0c7"),
        "border-right": sides.get("right", "1px solid #b9c0c7"),
        "border-top": sides.get("top", "1px solid #b9c0c7"),
        "border-bottom": sides.get("bottom", "1px solid #b9c0c7"),
        "background": border.get("fill", "transparent"),
    }


def _render_table(
    table: ET.Element,
    styles: Mapping[str, Any],
    counter: _ObjectCounter,
) -> str:
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
    for tr in table.findall(f"{_HP}tr"):
        cells: list[str] = []
        for tc in tr.findall(f"{_HP}tc"):
            cell_size = tc.find(f"{_HP}cellSz")
            # The cell's effective margins (``cell.margins``): the table's
            # hp:inMargin unless the cell's hasMargin is on.
            cell_margins = cell_margins_of(tc, table)
            width = _hwp_to_mm(cell_size.get("width") if cell_size is not None else None)
            height = _hwp_to_mm(cell_size.get("height") if cell_size is not None else None)
            padding = {
                key: _hwp_to_mm(getattr(cell_margins, key)) if cell_margins is not None else 0.5
                for key in ("top", "right", "bottom", "left")
            }
            css = _border_style(tc.get("borderFillIDRef") or table.get("borderFillIDRef"), styles)
            css.update(
                {
                    "width": _fmt_mm(width) if width > 0 else None,
                    "min-height": _fmt_mm(height) if height > 0 else None,
                    "padding": (
                        f"{_fmt_mm(padding['top'])} {_fmt_mm(padding['right'])} "
                        f"{_fmt_mm(padding['bottom'])} {_fmt_mm(padding['left'])}"
                    ),
                    "vertical-align": "middle",
                }
            )
            body_parts = []
            for para in _cell_paragraphs(tc):
                body_parts.append(
                    _render_paragraph(para, styles, counter, include_tables=False)
                )
            if not body_parts:
                body_parts.append("&nbsp;")
            span = tc.find(f"{_HP}cellSpan")
            colspan = _safe_int(span.get("colSpan") if span is not None else None, 1)
            rowspan = _safe_int(span.get("rowSpan") if span is not None else None, 1)
            attrs = [
                f'style="{_style_attr(css)}"',
                f'data-border-fill-id="{html.escape(tc.get("borderFillIDRef") or "")}"',
            ]
            if colspan > 1:
                attrs.append(f'colspan="{colspan}"')
            if rowspan > 1:
                attrs.append(f'rowspan="{rowspan}"')
            cells.append(f"<td {' '.join(attrs)}>{''.join(body_parts)}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return f'<table class="hwpx-table" style="{table_style}"><tbody>{"".join(rows)}</tbody></table>'


def _render_paragraph(
    paragraph: ET.Element,
    styles: Mapping[str, Any],
    counter: _ObjectCounter,
    *,
    include_tables: bool = True,
) -> str:
    text_html = _render_inline_runs(paragraph, styles, counter)
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
        ".hwpx-engine-canvas { position: relative; }\n"
        ".hwpx-engine-line { position: absolute; margin: 0; white-space: pre; "
        "overflow: visible; overflow-wrap: normal; word-break: normal; }\n"
        ".hwpx-engine-approx { padding: 2mm; border-top: 1px dashed #9aa2ad; }\n"
        ".hwpx-engine-approx p:first-child { margin-top: 0; }\n"
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


def _document_html(
    *,
    title: str,
    mode: str,
    body: str,
    screenshot: bool = False,
    fidelity_tier: str = _APPROX,
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
        "</body>\n"
        "</html>\n"
    )


def _engine_line(
    line: Any, paragraph: Any, styles: Mapping[str, Any], page: Any,
) -> tuple[str, bool]:
    left, _, body_width, _ = page.body
    area = next((area for area in reversed(page.column_areas) if area.top <= line.top), None)
    column = line.position.column
    column_x = None if area is None or (column and area.gap is None) else (
        sum(area.widths[:column]) + column * (area.gap or 0)
    )
    approximate = column_x is None or line.x is None or line.width is None
    width = line.width if line.width is not None else (
        area.widths[column] if area is not None and column < len(area.widths) else body_width
    )
    run = next((run for run in paragraph.findall(f"{_HP}run") if _find_text_in_run(run)), None)
    char = styles["char"].get(run.get("charPrIDRef", "0") if run is not None else "0", {})
    para_style = styles["para"].get(paragraph.get("paraPrIDRef", "0"), {})
    css = _style_attr({
        "left": _fmt_mm(_hwp_to_mm(left + (column_x or 0) + (line.x or 0))),
        "top": _fmt_mm(_hwp_to_mm(line.top)),
        "width": _fmt_mm(_hwp_to_mm(width)),
        "line-height": _fmt_mm(_hwp_to_mm(line.height)),
        "font-size": _fmt_pt(char.get("font_size_pt", 10.0)),
        "color": char.get("color", "#000000"),
        "text-align": para_style.get("align", "left"),
    })
    text = html.escape(line.text.removesuffix("\n"))
    return (
        f'<div class="hwpx-engine-line" data-column="{column}" data-text-start="{line.text_start}" '
        f'data-text-end="{line.text_end}" style="{css}">{text}</div>',
        approximate,
    )


def _engine_preview(
    source: str | Path | bytes, mode: str, title: str,
    styles: Mapping[str, Any], warnings: list[str],
) -> LayoutPreview | None:
    estimate_layout = getattr(experimental, "estimate_layout", None)
    if estimate_layout is None:
        warnings.append("layout estimate unavailable in the installed python-hwpx")
        return None
    try:
        document = HwpxDocument.open(io.BytesIO(source) if isinstance(source, bytes) else str(source))
        layout = estimate_layout(document)
    except (HwpxError, ValueError, OSError) as exc:
        warnings.append(f"layout estimate unavailable: {type(exc).__name__}")
        return None
    if layout.estimate.pages is None:
        warnings.extend(f"layout estimate declined: {reason}" for reason in layout.estimate.unsupported)
        return None
    return _render_engine_preview(document, layout, mode, title, styles, warnings)


def _render_engine_preview(
    document: HwpxDocument, layout: Any, mode: str, title: str,
    styles: Mapping[str, Any], warnings: list[str],
) -> LayoutPreview:
    sections = [section.element for section in document.sections]
    body_paragraphs = [section.findall(f"{_HP}p") for section in sections]
    lines: list[list[str]] = [[] for _ in layout.pages]
    approximate: list[list[str]] = [[] for _ in layout.pages]
    paragraphs_by_page: list[set[tuple[int, int]]] = [set() for _ in layout.pages]
    table_counts = Counter()
    issues: Counter[tuple[str, str]] = Counter()
    counter = _ObjectCounter()
    section_starts: dict[int, int] = {}
    for page in layout.pages:
        section_starts.setdefault(page.section, page.page)
    object_kinds = {_PICTURE_TAG: "picture", _OLE_TAG: "embedded-object", _EQUATION_TAG: "equation"}
    for placed in layout.paragraphs:
        key = placed.section, placed.paragraph
        paragraph = body_paragraphs[key[0]][key[1]]
        visible = [line for line in placed.lines if not line.hidden]
        home = placed.lines[0].position.page if placed.lines else section_starts[key[0]]
        tables = paragraph.findall(f".//{_HP}tbl")
        table_counts[home] += len(tables)
        if tables:
            issues[("table", "row and cell placement is unavailable")] += len(tables)
        for run in paragraph.findall(f"{_HP}run"):
            for child in run:
                kind = object_kinds.get(child.tag, "shape" if child.tag in _SHAPE_TAGS else None)
                if kind is not None:
                    issues[(kind, "object placement is unavailable")] += 1
                label = _OTHER_OBJECT_LABELS.get(child.tag)
                if child.tag == f"{_HP}switch" and label is None:
                    label = next((_OTHER_OBJECT_LABELS[node.tag] for node in child.iter()
                                  if node.tag in _OTHER_OBJECT_LABELS), None)
                if label is not None:
                    issues[(label, "object is shown as a placeholder")] += 1
                    approximate[home].append(f'<p class="hwpx-paragraph">{_render_object_marker(label)}</p>')
        without_text_range = [line for line in visible if line.text is None]
        if without_text_range or (not placed.lines and _paragraph_text(paragraph)):
            if _paragraph_text(paragraph):
                issues[("paragraph", "engine text ranges are unavailable")] += 1
                approximate[home].append(_render_paragraph(paragraph, styles, counter))
                paragraphs_by_page[home].add(key)
                continue
            if without_text_range:
                issues[("line", "engine text ranges are unavailable")] += len(without_text_range)
        for line in visible:
            if line.text is None:
                continue
            page = line.position.page
            paragraphs_by_page[page].add(key)
            markup, partial = _engine_line(line, paragraph, styles, layout.pages[page])
            lines[page].append(markup)
            if partial:
                issues[("line", "horizontal placement is incomplete")] += 1
        objects = _render_inline_runs(paragraph, styles, counter, include_text=False)
        if objects:
            approximate[home].append(f'<p class="hwpx-paragraph">{objects}</p>')
        approximate[home].extend(_render_table(table, styles, counter) for table in tables)

    for kind, label in (("header", "머리말"), ("footer", "꼬리말"),
                        ("footNote", "각주"), ("endNote", "미주")):
        for index, section in enumerate(sections):
            for area in section.iter(f"{_HP}{kind}"):
                issues[(kind, "area placement is unavailable")] += 1
                text = " ".join(_paragraph_text(p) for p in area.iter(f"{_HP}p"))
                approximate[section_starts[index]].append(
                    f'<p class="hwpx-paragraph">{_render_object_marker(label)} {html.escape(text)}</p>'
                )

    fragments, pages = [], []
    for page in layout.pages:
        index = page.page
        width, height = map(_hwp_to_mm, (page.paper_width, page.paper_height))
        _, _, margins = _page_spec(sections[page.section])
        page_id = f"hwpx-preview-page-{index + 1}"
        canvas = f'<div class="hwpx-engine-canvas" style="height:{_fmt_mm(height)}">{"".join(lines[index])}</div>'
        extra = ""
        if approximate[index]:
            extra = (
                '<aside class="hwpx-engine-approx"><p>이 쪽의 배치 미확인 요소</p>'
                f'{"".join(approximate[index])}</aside>'
            )
        fragments.append(
            f'<section id="{page_id}" class="hwpx-preview-page hwpx-engine-page" '
            f'data-page-index="{index}" data-section-index="{page.section}" '
            f'style="width:{_fmt_mm(width)};padding:0">{canvas}{extra}</section>'
        )
        pages.append(PreviewPage(index, page.section, page_id, width, height, margins,
                                 len(paragraphs_by_page[index]), table_counts[index]))
    limitations = tuple(_Limitation(kind, reason, count) for (kind, reason), count in sorted(issues.items()))
    warnings.extend(f"{item.kind}: {item.reason} ({item.count})" for item in limitations)
    tier = _PARTIAL if limitations else _ENGINE
    document_html = _document_html(title=title, mode=mode, body="".join(fragments), fidelity_tier=tier)
    return LayoutPreview(document_html, tuple(pages), tuple(warnings), mode, tuple(fragments), tier, limitations)


def render_layout_preview(
    source: str | Path | bytes,
    *,
    mode: str = "pages",
    title: str = "HWPX Layout Preview",
) -> LayoutPreview:
    """Render an HWPX package into layout-aware HTML.

    Args:
        source: HWPX file path or raw HWPX bytes.
        mode: ``"pages"`` for page boxes or ``"long"`` for continuous scrolling.
        title: HTML document title.
    """

    if mode not in {"pages", "long"}:
        raise ValueError("mode must be 'pages' or 'long'")

    parts, warnings = _read_package_parts(source)
    header = _parse_xml(parts, "Contents/header.xml", warnings)
    styles = _collect_style_maps(header)
    pre_estimate_warnings = len(warnings)
    engine_preview = _engine_preview(source, mode, title, styles, warnings)
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
