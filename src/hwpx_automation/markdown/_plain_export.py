# SPDX-License-Identifier: Apache-2.0
"""HWPX → plain Markdown and HTML (what ``doc.text.markdown()`` / ``doc.text.html()`` wrote in python-hwpx 6.x).

Moved from ``hwpx.tools.exporter`` (its Markdown/HTML half and the XML walk it
shares with the engine's ``export_text``, copied here). The walk reads the
document's own XML (``doc.oxml.sections[i].element``); list labels, note
numbers and Hancom's number forms come from the engine's public reads
(``hwpx.tools.exporter.ListLabels``, ``NoteLabels``, ``number_text``) and the
text of an ``hp:t`` from ``hwpx.oxml.run.text_element_content``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from hwpx.oxml.namespaces import HH, HP
from hwpx.oxml.paragraph_heading import heading_outline_level, outline_style_level
from hwpx.oxml.run import text_element_content
from hwpx.tools.exporter import ListLabels, NoteLabels, number_text

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element

    from hwpx import HwpxDocument

__all__ = [
    "HEADING_MAX_CHARS",
    "TextSanitizer",
    "escape_line_starts",
    "escape_markdown",
    "export_html",
    "export_markdown",
]

#: A caller-supplied redaction step (``masking_policy=``).
TextSanitizer = Callable[[str], str]

_HP = HP
_HH = HH
#: Elements whose sub-lists hold text outside the body: headers and footers,
#: foot/end notes, memos (a memo's text sits under its ``hp:fieldBegin``) and
#: hidden comments. The exporters do not read below them.
_NOT_BODY_TAGS = frozenset(
    f"{_HP}{name}"
    for name in ("header", "footer", "footNote", "endNote", "fieldBegin", "hiddenComment")
)

#: Placed blocks whose own paragraphs are exported in place: text boxes and captions.
_PARAGRAPH_BLOCKS = frozenset((f"{_HP}drawText", f"{_HP}caption"))


# --------------------------------------------------------------------------- #
# The document's XML, and the engine's labels behind the walk's interface
# --------------------------------------------------------------------------- #


def _section_xmls(document: HwpxDocument) -> list[Element]:
    """The section root elements of *document*, in order."""

    return [section.element for section in document.oxml.sections]


def _header_xml(document: HwpxDocument) -> Element | None:
    """The document's ``header.xml`` root (styles, numberings, bullets), if it has one."""

    headers = document.oxml.headers
    return headers[0].element if headers else None


class _ListLabels:
    """The label Hancom draws before each paragraph (``ListLabels(doc)``), as the walk asks for it.

    The engine counts the whole document once, in Hancom's reading order, so the
    walk's own counting calls (a table left out, a new section) have nothing to do.
    """

    def __init__(self, document: HwpxDocument) -> None:
        self._labels = ListLabels(document)

    def label(self, p: Element) -> str:
        return self._labels.label(p)

    def kind(self, p: Element) -> str | None:
        return self._labels.kind(p)

    def count(self, table: Element) -> None:
        """A table that is not written: its paragraphs are counted already."""

    def start_section(self, section: Element) -> None:
        """A new section: its outline numbering is the engine's to follow."""


class _NoteLabels:
    """The numbers of foot and end notes (``NoteLabels(doc)``) and their text where they sit.

    With *deferred*, :meth:`text` writes a marker where a note sits and keeps the
    note's text in :attr:`deferred` as ``(marker name, note text)`` for the caller
    to write after.
    """

    def __init__(self, document: HwpxDocument, *, deferred: bool = False) -> None:
        self.deferred: list[tuple[str, str]] | None = [] if deferred else None
        self._names: dict[Any, str] = {}
        self._counts: dict[str, int] = {}
        self._labels = NoteLabels(document)

    def text(self, child: Element, tab_token: str) -> str | None:
        """The notes run child *child* holds, as Hancom's text save writes them where they
        sit: the label, then each paragraph of the note (its own number as the label)
        followed by a line break. ``None`` when *child* holds no note."""
        if child.tag in _NOTE_TAGS:
            notes = [child]
        elif child.tag == f"{_HP}ctrl":
            notes = [note for note in child if note.tag in _NOTE_TAGS]
        else:
            notes = []
        if not notes:
            return None
        parts: list[str] = []
        if self.deferred is not None:
            for note in notes:
                name = self._names.get(note)
                if name is None:
                    kind = "fn" if note.tag == f"{_HP}footNote" else "en"
                    self._counts[kind] = self._counts.get(kind, 0) + 1
                    name = f"{kind}{self._counts[kind]}"
                    self._names[note] = name
                    text = " ".join(
                        _note_paragraph_text(paragraph, "", tab_token).strip()
                        for paragraph in note.findall(f"{_HP}subList/{_HP}p")
                    ).strip()
                    self.deferred.append((name, " ".join(text.split("\n"))))
                parts.append(_NOTE_MARK_OPEN + name + _NOTE_MARK_CLOSE)
            return "".join(parts)
        for note in notes:
            label = self._labels.label(note)
            parts.append(label)
            for paragraph in note.findall(f"{_HP}subList/{_HP}p"):
                parts.append(_note_paragraph_text(paragraph, label, tab_token) + "\n")
        return "".join(parts)


_NOTE_TAGS = frozenset((f"{_HP}footNote", f"{_HP}endNote"))

#: A note's place in deferred text, from private use characters escaping leaves alone.
_NOTE_MARK_OPEN = ""
_NOTE_MARK_CLOSE = ""
_NOTE_MARK = re.compile("(\\w+)")


def _note_marks(text: str, form: str) -> str:
    """Write the deferred note markers of *text* in *form* (``{name}`` is the marker name)."""
    return _NOTE_MARK.sub(lambda match: form.format(name=match.group(1)), text)


def _note_paragraph_text(p: Element, label: str, tab_token: str) -> str:
    """The text of a note's paragraph, its auto number written as *label*."""
    parts: list[str] = []
    for run in p.findall(f"{_HP}run"):
        for child in run:
            auto_num = child.find(f"{_HP}autoNum") if child.tag == f"{_HP}ctrl" else None
            if auto_num is not None and auto_num.get("numType") in ("FOOTNOTE", "ENDNOTE"):
                parts.append(label)
            else:
                parts.append(_run_child_text(child, tab_token) or "")
    return "".join(parts)


# --------------------------------------------------------------------------- #
# The walk (a copy of the one the engine's export_text keeps)
# --------------------------------------------------------------------------- #


def _labelled(text: str, label: str) -> str:
    if not label:
        return text
    return label + (" " if text and not text[0].isspace() else "") + text


def _section_blocks(section: Element) -> list[Element]:
    """The section's paragraphs in order, with the tables (and their captions) placed in the
    section itself rather than in a paragraph where they sit. Hancom writes tables in
    paragraphs; other writers sometimes do not, and their text is still the document's."""
    blocks: list[Element] = []
    for child in section:
        if child.tag == f"{_HP}p":
            blocks.append(child)
        elif child.tag == f"{_HP}tbl":
            blocks.extend(_blocks_in(child))
    return blocks


def _is_tab_control(child: Element) -> bool:
    return child.tag == f"{_HP}ctrl" and (child.get("id") or "").lower() == "tab"


def _run_child_text(child: Element, tab_token: str) -> str | None:
    """The text a run child adds, or ``None`` when it is a control or an object."""
    if child.tag == f"{_HP}t":
        # 한/글의 하이픈(hp:hyphen)은 보이는 붙임표다. U+00AD(보이지 않는 하이픈)가 아니라 "-"로 쓴다.
        return text_element_content(child, tab_token=tab_token).replace("\xad", "-")
    if child.tag == f"{_HP}tab" or _is_tab_control(child):
        return tab_token
    if child.tag == f"{_HP}lineBreak":
        return "\n"
    if child.tag == f"{_HP}dutmal":
        return _dutmal_text(child)
    if child.tag == f"{_HP}ctrl" and (auto_num := child.find(f"{_HP}autoNum")) is not None:
        return _auto_number_text(auto_num)
    return None


def _auto_number_text(auto_num: Element) -> str:
    """An auto number (a caption's picture or table number, ...) as Hancom shows it: the
    number it holds, in its format, between its prefix and suffix characters."""
    value = _int_attribute(auto_num, "num")
    if value is None:
        return ""
    number_format = auto_num.find(f"{_HP}autoNumFormat")
    kind = number_format.get("type", "DIGIT") if number_format is not None else "DIGIT"
    text = number_text(value, kind)
    if text is None:
        text = str(value)
    if number_format is None:
        return text
    return f"{number_format.get('prefixChar', '')}{text}{number_format.get('suffixChar', '')}"


def _paragraph_pieces(
    p: Element, *, tab_token: str = "\t", notes: _NoteLabels | None = None
) -> list[str | Element]:
    """The text of paragraph *p* and the tables, text boxes and captions placed in it, in order.

    With *notes*, the foot and end notes in it too, as text where they sit.
    """
    pieces: list[str | Element] = []
    for run in p.findall(f"{_HP}run"):
        for child in run:
            text = _run_child_text(child, tab_token)
            if text is None and notes is not None:
                text = notes.text(child, tab_token)
            if text is None:
                pieces.extend(_blocks_in(child))
            elif text:
                pieces.append(text)
    return pieces


def _emit_paragraph(
    p: Element,
    *,
    tab_token: str,
    labels: _ListLabels | None,
    masking_policy: TextSanitizer | None,
    write_text: Callable[[str], None],
    write_block: Callable[[Element], None],
    notes: _NoteLabels | None = None,
    escape: Callable[[str], str] | None = None,
) -> None:
    """Write paragraph *p*, its text split where a table, text box or caption sits.

    Hancom's text save writes a placed object where its control sits in the paragraph;
    a numbered paragraph's label goes with the first piece of text. With *escape*, the
    (masked) text is escaped and the label is put before it as it is.
    """
    label = labels.label(p) if labels is not None else ""
    buffer: list[str] = []
    for piece in [*_paragraph_pieces(p, tab_token=tab_token, notes=notes), None]:
        if isinstance(piece, str):
            buffer.append(piece)
            continue
        if escape is None:
            text = _mask_text(_labelled("".join(buffer), label), masking_policy)
        else:
            text = _labelled(escape(_mask_text("".join(buffer), masking_policy)), label)
        if text:
            write_text(text)
        label = ""
        buffer.clear()
        if piece is not None:
            write_block(piece)


def _dutmal_text(dutmal: Element) -> str:
    """덧말 as Hancom's text save writes it: the main text, then ``(덧말:<sub text>)``."""
    main = dutmal.findtext(f"{_HP}mainText") or ""
    sub = dutmal.findtext(f"{_HP}subText") or ""
    return f"{main}(덧말:{sub})" if sub else main


def _mask_text(text: str, masking_policy: TextSanitizer | None) -> str:
    """Apply the caller's sanitizer, if one was supplied (``None``: unmasked)."""

    if masking_policy is None:
        return text
    return masking_policy(text)


def _table_cells_text(
    tbl: Element,
    *,
    tab_token: str = "\t",
    masking_policy: TextSanitizer | None = None,
    labels: _ListLabels | None = None,
    notes: _NoteLabels | None = None,
) -> list[list[str]]:
    """Return a row-major 2D list of cell texts from a table element."""
    rows: list[list[str]] = []
    for tr in tbl.findall(f"{_HP}tr"):
        row: list[str] = []
        for tc in tr.findall(f"{_HP}tc"):
            row.append(_cell_text(tc, tab_token=tab_token, masking_policy=masking_policy, labels=labels, notes=notes))
        rows.append(row)
    return rows


def _span(value: str | None) -> int:
    """A ``hp:cellSpan`` count as a positive int; anything unreadable is 1."""

    try:
        return max(1, int(value or "1"))
    except ValueError:
        return 1


def _table_cell_spans(tbl: Element) -> list[list[tuple[int, int]]]:
    """Return ``(colspan, rowspan)`` per cell, in the order of :func:`_table_cells_text`."""

    spans: list[list[tuple[int, int]]] = []
    for tr in tbl.findall(f"{_HP}tr"):
        row: list[tuple[int, int]] = []
        for tc in tr.findall(f"{_HP}tc"):
            span = tc.find(f"{_HP}cellSpan")
            if span is None:
                row.append((1, 1))
            else:
                row.append((_span(span.get("colSpan")), _span(span.get("rowSpan"))))
        spans.append(row)
    return spans


def _cell_text(
    tc: Element,
    *,
    tab_token: str = "\t",
    masking_policy: TextSanitizer | None = None,
    labels: _ListLabels | None = None,
    notes: _NoteLabels | None = None,
) -> str:
    """The text of cell *tc*, a line per paragraph.

    Tables, text boxes and captions in the cell come where they sit, as in the body: a
    nested table's cells in order, then its caption.
    """
    lines: list[str] = []
    for paragraph in _cell_paragraphs(tc):
        _emit_nested_paragraph(paragraph, lines, tab_token=tab_token, labels=labels, notes=notes)
    # blank lines at the cell's ends go; the spaces the text itself holds stay, as Hancom keeps them
    return _mask_text("\n".join(lines).strip("\n"), masking_policy)


def _cell_paragraphs(tc: Element) -> list[Element]:
    """A cell's paragraphs: in its ``hp:subList``, or (as some other writers put them) right in the cell."""
    return tc.findall(f"{_HP}subList/{_HP}p") or tc.findall(f"{_HP}p")


def _emit_nested_paragraph(
    p: Element,
    lines: list[str],
    *,
    tab_token: str,
    labels: _ListLabels | None,
    notes: _NoteLabels | None = None,
) -> None:
    """Add paragraph *p* of a cell, text box or caption to *lines*, its objects where they sit."""

    def write_block(block: Element) -> None:
        if block.tag in _PARAGRAPH_BLOCKS:
            for inner in _text_box_paragraphs(block):
                _emit_nested_paragraph(inner, lines, tab_token=tab_token, labels=labels, notes=notes)
            return
        for tc in block.findall(f"{_HP}tr/{_HP}tc"):
            text = _cell_text(tc, tab_token=tab_token, labels=labels, notes=notes)
            if text:
                lines.append(text)

    _emit_paragraph(p, tab_token=tab_token, labels=labels, masking_policy=None,
                    write_text=lines.append, write_block=write_block, notes=notes)


def _int_attribute(element: Element | None, name: str) -> int | None:
    if element is None:
        return None
    try:
        return int(element.get(name) or "")
    except ValueError:
        return None


def _table_grid_text(
    tbl: Element,
    *,
    tab_token: str = "\t",
    masking_policy: TextSanitizer | None = None,
    labels: _ListLabels | None = None,
    notes: _NoteLabels | None = None,
) -> list[list[str]]:
    """Cell texts laid on the table's column grid (``hwpx.tools.exporter.table_grid_text``
    with masking, labels and notes).

    Each cell goes to its ``hp:cellAddr`` position (a cell without one follows
    the previous cell of its row), and the grid is as wide as the widest row,
    so no cell is dropped. The positions a merged cell covers stay empty.
    """
    placed: dict[tuple[int, int], str] = {}
    width = 0
    for row_index, tr in enumerate(tbl.findall(f"{_HP}tr")):
        column = 0
        for tc in tr.findall(f"{_HP}tc"):
            address = tc.find(f"{_HP}cellAddr")
            row_addr = _int_attribute(address, "rowAddr")
            col_addr = _int_attribute(address, "colAddr")
            if row_addr is None or col_addr is None or row_addr < 0 or col_addr < 0:
                row_addr, col_addr = row_index, column
            while (row_addr, col_addr) in placed:
                col_addr += 1
            placed[(row_addr, col_addr)] = _cell_text(
                tc, tab_token=tab_token, masking_policy=masking_policy, labels=labels, notes=notes
            )
            span = _int_attribute(tc.find(f"{_HP}cellSpan"), "colSpan")
            column = col_addr + max(span or 1, 1)
            width = max(width, column)
    if not placed:
        return []
    height = max(row for row, _ in placed) + 1
    return [[placed.get((row, col), "") for col in range(width)] for row in range(height)]


def _blocks_in(element: Element) -> list[Element]:
    """Tables, text boxes and captions in *element* (a run child), in document order, outermost only.

    A text box is returned as its ``hp:drawText``. A table's caption follows the
    table, where Hancom's text save puts it; the caption of a picture or a shape
    comes where it sits. A table or text box nested in a cell is already part of
    that cell's text, and one in a header, footer, note or memo is not body text.
    """
    if element.tag in _NOT_BODY_TAGS:
        return []
    if element.tag == f"{_HP}switch":
        # the same object twice: one branch (hp:case, else hp:default) is read
        branch = element.find(f"{_HP}case")
        if branch is None:
            branch = element.find(f"{_HP}default")
        return [] if branch is None else _blocks_in(branch)
    if element.tag == f"{_HP}tbl":
        return [element, *element.findall(f"{_HP}caption")]
    if element.tag in _PARAGRAPH_BLOCKS:
        return [element]
    return [block for child in element for block in _blocks_in(child)]


def _text_box_paragraphs(block: Element) -> list[Element]:
    """The paragraphs of a text box (``hp:drawText``) or a caption."""
    return block.findall(f"{_HP}subList/{_HP}p")


# --------------------------------------------------------------------------- #
# Markdown escaping
# --------------------------------------------------------------------------- #

#: Characters a Markdown reader would take as markup, escaped with a backslash in document text.
_MARKDOWN_ESCAPES = {ord(char): "\\" + char for char in "\\`*_~[]|"}
#: ``$…$`` the way Markdown math extensions read it: no space inside the dollars, no digit after.
_MATH_SPAN = re.compile(r"\$([^\s$](?:[^$\n]*?[^\s$\\])?)\$(?!\d)")
#: What a ``$…$`` span may not hold to be left unescaped: HTML, a link, a code span.
_UNSAFE_IN_MATH = re.compile(r"[<>&`]|\]\(")
_HEADING_LINE = re.compile(r"#{1,6}(?:[ \t]|$)")
_LIST_LINE = re.compile(r"[-+](?:[ \t]|$)")
_RULE_LINE = re.compile(r"(?:-[ \t]*)+|=+[ \t]*")
_ORDERED_LINE = re.compile(r"(\d{1,9})[.)](?:[ \t]|$)")


def _escape_markdown_plain(text: str) -> str:
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return escaped.translate(_MARKDOWN_ESCAPES)


def escape_markdown(text: str, *, pipe: bool = False) -> str:
    """Document text as Markdown that reads back as the same text.

    ``& < >`` become entities and ``\\ ` * _ ~ [ ] |`` take a backslash, so the text
    cannot open emphasis, a link, raw HTML or a table cell. A ``$…$`` span (a formula
    typed as text) is left as it is for math extensions; only ``|`` in it is escaped,
    and only in a table cell (*pipe*). A span holding HTML, a link or a code span is
    escaped like any text.
    """

    out: list[str] = []
    last = 0
    for match in _MATH_SPAN.finditer(text):
        body = match.group(1)
        if _UNSAFE_IN_MATH.search(body):
            continue
        out.append(_escape_markdown_plain(text[last : match.start()]))
        out.append("$" + (body.replace("|", "\\|") if pipe else body) + "$")
        last = match.end()
    out.append(_escape_markdown_plain(text[last:]))
    return "".join(out)


def _escape_line_start(line: str) -> str:
    body = line.lstrip(" \t")
    lead = line[: len(line) - len(body)]
    if _HEADING_LINE.match(body) or _LIST_LINE.match(body) or (body and _RULE_LINE.fullmatch(body)):
        return lead + "\\" + body
    ordered = _ORDERED_LINE.match(body)
    if ordered:
        digits = ordered.group(1)
        return lead + digits + "\\" + body[len(digits) :]
    return line


def escape_line_starts(markdown: str) -> str:
    """Escape what would start a heading, list, rule or setext underline at the start of a line.

    For text that was already escaped by :func:`escape_markdown` (``>`` is an entity there).
    """

    return "\n".join(_escape_line_start(line) for line in markdown.split("\n"))


def _escape_markdown_block(text: str) -> str:
    """Document text written as its own lines: escaped, and so are its line starts."""
    return escape_line_starts(escape_markdown(text))


#: An outline paragraph longer than this is body text set in an outline level, not a heading.
HEADING_MAX_CHARS = 80


class _Headings:
    """Which paragraphs are headings, and their level, from the document's own structure.

    A paragraph is a heading of level L when its paragraph shape numbers it as outline
    level L (``hh:heading type="OUTLINE"``), else when its style is an outline style
    (``개요 L`` / ``Outline L``). Levels deeper than 6 are not headings.
    """

    def __init__(self, header: Element | None) -> None:
        self._shapes: dict[str, int] = {}
        self._styles: dict[str, int] = {}
        if header is None:
            return
        for para_pr in header.iter(f"{_HH}paraPr"):
            level = heading_outline_level(para_pr)
            if level is not None:
                self._shapes[para_pr.get("id") or ""] = level
        for style in header.iter(f"{_HH}style"):
            # 한/글 기본 개요 스타일 이름(개요 N / Outline N): 차례 만들기와 같은 어휘를 쓴다.
            for name in (style.get("name") or "", style.get("engName") or ""):
                style_level = outline_style_level(name)
                if style_level is not None:
                    self._styles[style.get("id") or ""] = style_level
                    break

    def level(self, p: Element) -> int | None:
        level = self._shapes.get(p.get("paraPrIDRef") or "")
        if level is None:
            level = self._styles.get(p.get("styleIDRef") or "")
        return level if level is not None and 1 <= level <= 6 else None

    def any_in(self, sections: list[Element]) -> bool:
        """Whether a body paragraph (one placed in a section) of *sections* that holds text is a heading."""
        if not self._shapes and not self._styles:
            return False
        for section in sections:
            for p in section.findall(f"{_HP}p"):
                if self.level(p) is not None and any(
                    "".join(t.itertext()).strip() for t in p.iterfind(f"{_HP}run/{_HP}t")
                ):
                    return True
        return False


def _markdown_cell(text: str) -> str:
    """Cell text on one Markdown table line: escaped, line breaks as ``<br>``, note markers as references."""
    return _note_marks(escape_markdown(text, pipe=True).replace("\n", "<br>"), "[^{name}]")


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# --------------------------------------------------------------------------- #
# HTML and Markdown
# --------------------------------------------------------------------------- #


def export_html(
    document: HwpxDocument,
    *,
    include_tables: bool = True,
    full_document: bool = True,
    title: str = "HWPX Document",
    tab_token: str = "\t",
    masking_policy: TextSanitizer | None = None,
    list_labels: bool = False,
    notes: bool | str = False,
    headings: bool = True,
    nested_tables: bool = True,
) -> str:
    """Export document content as HTML.

    A paragraph's tables, text boxes and captions come where they sit in its text, as in
    Hancom's text save (a table's caption after the table). A 덧말 is its main text and
    ``(덧말:<sub text>)``.
    With *headings*, a paragraph the document makes a heading (as in
    :func:`export_markdown`) is ``<h1>`` … ``<h6>``.
    With *nested_tables*, a table in a cell is a table in that cell; ``False`` writes its
    cells' text in the cell, a line each.
    With *list_labels*, numbered, outline and bullet paragraphs start with their label.
    With *notes*, a foot or end note is a reference (``<sup>``) where it sits and its text
    at the end; ``notes="inline"`` writes it where it sits, as ``export_text``.
    """
    sections = _section_xmls(document)
    header = _header_xml(document) if headings else None
    labels = _ListLabels(document) if list_labels else None
    heading_levels = _Headings(header) if headings else None
    note_labels = _NoteLabels(document, deferred=notes != "inline") if notes else None
    body_parts: list[str] = []
    note_form = '<sup><a href="#{name}">{name}</a></sup>'

    def html_text(text: str) -> str:
        return _note_marks(_escape_html(text), note_form)

    def html_table(block: Element) -> str:
        spans = _table_cell_spans(block)
        out = ['<table border="1">']
        for tr, row_spans in zip(block.findall(f"{_HP}tr"), spans):
            out.append("  <tr>")
            for tc, (colspan, rowspan) in zip(tr.findall(f"{_HP}tc"), row_spans):
                attrs = (f' colspan="{colspan}"' if colspan > 1 else "") + (
                    f' rowspan="{rowspan}"' if rowspan > 1 else ""
                )
                out.append(f"    <td{attrs}>{html_cell(tc)}</td>")
            out.append("  </tr>")
        out.append("</table>")
        return "\n".join(out)

    def html_cell(tc: Element) -> str:
        parts: list[str] = []

        def write_cell_block(block: Element) -> None:
            if block.tag in _PARAGRAPH_BLOCKS:
                for inner in _text_box_paragraphs(block):
                    emit_cell(inner)
            else:
                parts.append(html_table(block))

        def emit_cell(p: Element) -> None:
            _emit_paragraph(p, tab_token=tab_token, labels=labels, masking_policy=masking_policy,
                            write_text=lambda text: parts.append(html_text(text)),
                            write_block=write_cell_block, notes=note_labels)

        for paragraph in _cell_paragraphs(tc):
            emit_cell(paragraph)
        return "\n".join(parts).strip("\n")

    left_out: set[Element] = set()

    def write_block(block: Element) -> None:
        if block in left_out:
            return
        if block.tag in _PARAGRAPH_BLOCKS:
            for inner in _text_box_paragraphs(block):
                emit(inner)
            return
        if include_tables and nested_tables:
            body_parts.append(html_table(block))
            return
        rows = (
            _table_cells_text(block, tab_token=tab_token, masking_policy=masking_policy, labels=labels, notes=note_labels)
            if include_tables
            else []
        )
        if not include_tables:
            left_out.update(block.findall(f"{_HP}caption"))  # a left-out table's captions go with it
            if labels is not None:
                labels.count(block)
        if rows:
            # A merged cell is one hp:tc with a span; the cells it covers are
            # absent, so without the span attributes later cells shift left.
            spans = _table_cell_spans(block)
            body_parts.append('<table border="1">')
            for row, row_spans in zip(rows, spans):
                body_parts.append("  <tr>")
                for cell, (colspan, rowspan) in zip(row, row_spans):
                    attrs = (f' colspan="{colspan}"' if colspan > 1 else "") + (
                        f' rowspan="{rowspan}"' if rowspan > 1 else ""
                    )
                    body_parts.append(f"    <td{attrs}>{html_text(cell)}</td>")
                body_parts.append("  </tr>")
            body_parts.append("</table>")

    def emit(p: Element) -> None:
        level = [heading_levels.level(p) if heading_levels is not None else None]

        def write_text(text: str) -> None:
            tag = f"h{level[0]}" if level[0] is not None and len(text) <= HEADING_MAX_CHARS else "p"
            level[0] = None  # the paragraph's first piece of text is the heading
            body_parts.append(f"<{tag}>{html_text(text)}</{tag}>")

        _emit_paragraph(p, tab_token=tab_token, labels=labels, masking_policy=masking_policy,
                        write_text=write_text, write_block=write_block, notes=note_labels)

    for sec_idx, section_root in enumerate(sections):
        if sec_idx > 0:
            body_parts.append("<hr />")
        if labels is not None:
            labels.start_section(section_root)
        for block in _section_blocks(section_root):
            if block.tag == f"{_HP}p":
                emit(block)
            else:
                write_block(block)
    if note_labels is not None and note_labels.deferred:
        body_parts.append('<section class="notes">')
        for name, text in note_labels.deferred:
            # A note's text goes through the caller's sanitizer too, as the body does.
            body_parts.append(f'<p id="{name}">{name}: {_escape_html(_mask_text(text, masking_policy))}</p>')
        body_parts.append("</section>")
    body = "\n".join(body_parts)
    if full_document:
        return (
            "<!DOCTYPE html>\n"
            '<html lang="ko">\n'
            "<head>\n"
            '  <meta charset="utf-8" />\n'
            f"  <title>{_escape_html(title)}</title>\n"
            "</head>\n"
            "<body>\n"
            f"{body}\n"
            "</body>\n"
            "</html>"
        )
    return body


def export_markdown(
    document: HwpxDocument,
    *,
    include_tables: bool = True,
    section_separator: str = "\n---\n\n",
    tab_token: str = "\t",
    masking_policy: TextSanitizer | None = None,
    list_labels: bool = False,
    notes: bool | str = False,
    headings: bool = True,
) -> str:
    """Export document content as Markdown.

    A paragraph's tables, text boxes and captions come where they sit in its text, as in
    Hancom's text save (a table's caption after the table). A 덧말 is its main text and
    ``(덧말:<sub text>)``. Document text is escaped (:func:`escape_markdown`), so it reads
    back as the same text and cannot become markup, HTML or a link.
    With *headings*, a paragraph the document makes a heading (an outline paragraph, or
    one in an outline style ``개요 N``) is a Markdown heading of its level (``#`` …
    ``######``); ``headings=False`` writes it as a plain paragraph.
    With *list_labels*, numbered, outline and bullet paragraphs start with their label.
    With *notes*, foot and end notes are Markdown footnotes: ``[^fn1]`` where the note
    sits and its text after the last section. ``notes="inline"`` writes them where they
    sit as ``export_text`` does (the note's number twice, as Hancom's text save).
    """
    sections = _section_xmls(document)
    header = _header_xml(document) if headings else None
    labels = _ListLabels(document) if list_labels else None
    heading_levels = _Headings(header) if headings else None
    note_labels = _NoteLabels(document, deferred=notes != "inline") if notes else None
    section_parts: list[str] = []
    for section_root in sections:
        lines: list[str] = []
        if labels is not None:
            labels.start_section(section_root)
        heading_of: dict[int, int] = {}

        def write_text(text: str) -> None:
            text = _note_marks(text, "[^{name}]")
            level = heading_of.pop(0, None)
            if level is not None and len(text) <= HEADING_MAX_CHARS:
                lines.append("#" * level + " " + " ".join(text.split()))
            else:
                lines.append(text)
            lines.append("")

        left_out: set[Element] = set()

        def write_block(block: Element) -> None:
            if block in left_out:
                return
            if block.tag in _PARAGRAPH_BLOCKS:
                for inner in _text_box_paragraphs(block):
                    emit(inner)
                return
            rows = (
                _table_grid_text(block, tab_token=tab_token, masking_policy=masking_policy, labels=labels, notes=note_labels)
                if include_tables
                else []
            )
            if not include_tables:
                left_out.update(block.findall(f"{_HP}caption"))  # a left-out table's captions go with it
                if labels is not None:
                    labels.count(block)
            if rows:
                header_row = rows[0]
                lines.append("| " + " | ".join(_markdown_cell(cell) for cell in header_row) + " |")
                lines.append("| " + " | ".join("---" for _ in header_row) + " |")
                for row in rows[1:]:
                    lines.append("| " + " | ".join(_markdown_cell(cell) for cell in row) + " |")
                lines.append("")

        def emit(p: Element) -> None:
            heading_of.clear()
            level = heading_levels.level(p) if heading_levels is not None else None
            if level is not None:
                heading_of[0] = level  # the paragraph's first piece of text is the heading
            _emit_paragraph(p, tab_token=tab_token, labels=labels, masking_policy=masking_policy,
                            write_text=write_text, write_block=write_block, notes=note_labels,
                            escape=escape_markdown if level is not None else _escape_markdown_block)
            heading_of.clear()

        for block in _section_blocks(section_root):
            if block.tag == f"{_HP}p":
                emit(block)
            else:
                write_block(block)
        section_parts.append("\n".join(lines).rstrip())
    body = section_separator.join(section_parts)
    if note_labels is not None and note_labels.deferred:
        # A note's text goes through the caller's sanitizer too, as the body does.
        definitions = "\n".join(
            f"[^{name}]: {escape_markdown(_mask_text(text, masking_policy))}"
            for name, text in note_labels.deferred
        )
        body = f"{body}\n\n{definitions}" if body else definitions
    return body
