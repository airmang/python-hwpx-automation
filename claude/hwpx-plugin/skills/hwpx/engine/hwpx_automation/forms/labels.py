# SPDX-License-Identifier: Apache-2.0
"""Label-addressed table cells: find a cell by the label beside it, list a form's blanks, fill by path.

Moved from python-hwpx 6.x (``hwpx.tools.table_navigation``, the label half, and the
``doc.tables.find_cell_by_label`` / ``form_slots`` / ``fill_by_path`` methods). The table map
(``doc.tables.map()``) stays in python-hwpx; ``table_index`` here counts tables as it does.
Only python-hwpx's public API is used.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, TypedDict, cast

if TYPE_CHECKING:
    from hwpx import HwpxDocument
    from hwpx.form_fit import FitPolicy
    from hwpx.model import Table, TableCell

__all__ = [
    "PathDirection",
    "SearchDirection",
    "TableCellReference",
    "TableFillApplied",
    "TableFillFailed",
    "TableFillResult",
    "TableFormSlot",
    "TableFormSlotsResult",
    "TableLabelCandidate",
    "TableLabelMatch",
    "TableLabelSearchResult",
    "fill_by_path",
    "find_cell_by_label",
    "form_slots",
]

_HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_HP = f"{{{_HP_NS}}}"
_WHITESPACE_RE = re.compile(r"\s+")
_HWPUNIT_PER_MM = 7200 / 25.4
#: ``label[2]``: the second cell, in document order, that the label matches.
_OCCURRENCE_RE = re.compile(r"^(?P<label>.*\S)\s*\[(?P<number>[1-9][0-9]*)\]$", re.DOTALL)

SearchDirection = Literal["right", "down"]
PathDirection = Literal["left", "right", "up", "down"]


class TableCellReference(TypedDict):
    """A logical table cell position and its current text."""

    row: int
    col: int
    text: str


class TableLabelMatch(TypedDict):
    """A label cell and the cell reached from it."""

    table_index: int
    label_cell: TableCellReference
    target_cell: TableCellReference


class TableLabelSearchResult(TypedDict):
    """Result payload returned by :func:`find_cell_by_label`."""

    matches: list[TableLabelMatch]
    count: int


class _TableFillAppliedRequired(TypedDict):
    path: str
    table_index: int
    row: int
    col: int
    value: str


class TableFillApplied(_TableFillAppliedRequired, total=False):
    """A successfully applied path-based fill operation.

    ``fit`` is present when the fill was given a fit policy: the measured
    outcome for this cell (``FitResult.to_dict()``: lines, font size, style
    changes, warnings).
    """

    fit: dict[str, Any]


class TableLabelCandidate(TypedDict):
    """One of several cells a label matched, with the label spelling that picks it."""

    table_index: int
    row: int
    col: int
    text: str
    selector: str


class _TableFillFailedRequired(TypedDict):
    path: str
    reason: str


class TableFillFailed(_TableFillFailedRequired, total=False):
    """A failed path-based fill operation and its reason.

    ``candidates`` is present when the reason is ``"ambiguous label"``: every
    cell the label matched, each with the ``selector`` (``"성명[2]"``) to write
    in the path instead of the bare label. ``fit`` is present when the reason
    is ``"value does not fit"``: the measured outcome that refused the value.
    """

    candidates: list[TableLabelCandidate]
    fit: dict[str, Any]


class TableFormSlot(TypedDict):
    """An empty cell next to a cell with text, and the path that fills it."""

    label: str
    path: str | None
    direction: SearchDirection
    table_index: int
    label_cell: TableCellReference
    target_cell: TableCellReference
    width_mm: float | None


class TableFormSlotsResult(TypedDict):
    """Result payload returned by :func:`form_slots`."""

    slots: list[TableFormSlot]
    count: int


class TableFillResult(TypedDict):
    """Batch fill summary for :func:`fill_by_path`."""

    applied: list[TableFillApplied]
    failed: list[TableFillFailed]
    applied_count: int
    failed_count: int


@dataclass(frozen=True, slots=True)
class _IndexedTable:
    table_index: int
    table: Table
    #: The body paragraph (index into ``doc.paragraphs``) the table, or the table holding it, sits in.
    paragraph_index: int


@dataclass(frozen=True, slots=True)
class _LabelCandidate:
    table_index: int
    table: Table
    row: int
    col: int
    text: str


def _collapse_whitespace(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()


def _normalize_label_text(value: str) -> str:
    """The form two labels are compared in: no whitespace, no case, no trailing colon.

    Forms spread a short label over its cell with spaces ("성  명", "주    소") or
    wrap it over lines; a person reading the form writes "성명". Whitespace
    therefore never distinguishes two labels.
    """

    return _WHITESPACE_RE.sub("", value).casefold().rstrip(":：")


def _document_tables(document: HwpxDocument) -> list[_IndexedTable]:
    """Every table of the body in the table map's order: a table, then the tables in its cells.

    Tables sit in body paragraphs or, nested, in table cells; tables in headers,
    footers, notes and text boxes are not read. ``table_index`` counts them as
    ``doc.tables.map()`` does.
    """

    # TODO(core-7.0-tables): use the engine's public "tables in map order" reader once it lands.
    found: list[tuple[Table, int]] = []

    def visit(table: Table, paragraph_index: int) -> None:
        found.append((table, paragraph_index))
        for row in table.rows:
            for cell in row.cells:
                for nested in cell.tables:
                    visit(nested, paragraph_index)

    for paragraph_index, paragraph in enumerate(document.paragraphs):
        for table in paragraph.tables:
            visit(table, paragraph_index)
    return [
        _IndexedTable(table_index=table_index, table=table, paragraph_index=paragraph_index)
        for table_index, (table, paragraph_index) in enumerate(found)
    ]


def _cell_text(table: Table, row_index: int, col_index: int) -> str:
    return table.cell(row_index, col_index).text


def _direction_delta(direction: PathDirection) -> tuple[int, int]:
    if direction == "right":
        return (0, 1)
    if direction == "left":
        return (0, -1)
    if direction == "down":
        return (1, 0)
    return (-1, 0)


def _move(
    table: Table,
    row_index: int,
    col_index: int,
    direction: PathDirection,
    grid: Any = None,
) -> tuple[int, int] | None:
    # A direction crosses the current physical cell's edge. Moving one grid
    # slot could otherwise stay inside a merged label and overwrite the label.
    if grid is None:
        grid = table.cell_map
    current = grid[row_index][col_index]
    anchor_row, anchor_col = current.anchor
    row_delta, col_delta = _direction_delta(direction)
    target_row = anchor_row + (current.row_span if row_delta > 0 else row_delta)
    target_col = anchor_col + (current.col_span if col_delta > 0 else col_delta)
    if target_row < 0 or target_col < 0:
        return None
    if target_row >= table.row_count or target_col >= table.column_count:
        return None
    anchor: tuple[int, int] = grid[target_row][target_col].anchor
    return anchor


class _LabelIndex:
    """Every table cell by the label it would be found under, read once.

    A cell whose whole text is the label wins. Only when there is none does a
    cell match by one of its lines: a two-language label ("성  명" over "Name")
    is found by either line. Cells are kept in document order.
    """

    def __init__(self, tables: list[_IndexedTable]) -> None:
        self.whole: dict[str, list[_LabelCandidate]] = {}
        self.by_line: dict[str, list[_LabelCandidate]] = {}
        for table_ref in tables:
            # Count physical cells, not every logical slot occupied by a merge.
            # Distinct cells with the same label remain ambiguous.
            for position in table_ref.table.iter_grid():
                if not position.is_anchor:
                    continue
                row_index, col_index = position.anchor
                cell_text = position.cell.text
                key = _normalize_label_text(cell_text)
                if not key:
                    continue
                candidate = _LabelCandidate(
                    table_index=table_ref.table_index,
                    table=table_ref.table,
                    row=row_index,
                    col=col_index,
                    text=cell_text,
                )
                self.whole.setdefault(key, []).append(candidate)
                if "\n" not in cell_text:
                    continue
                for line_key in dict.fromkeys(_normalize_label_text(line) for line in cell_text.splitlines()):
                    if line_key and line_key != key:
                        self.by_line.setdefault(line_key, []).append(candidate)

    def find(self, label_text: str) -> list[_LabelCandidate]:
        key = _normalize_label_text(label_text)
        if not key:
            raise ValueError("label_text must contain at least one non-whitespace character")
        return self.whole.get(key) or self.by_line.get(key) or []


def _select_label_candidates(
    index: _LabelIndex,
    label_text: str,
) -> tuple[list[_LabelCandidate], str | None]:
    """Candidates for a path's label token, honouring ``label[n]``.

    The token is tried as a label first, so a label that really ends in
    ``[1]`` still works. Returns ``(candidates, error)``.
    """

    candidates = index.find(label_text)
    if candidates:
        return candidates, None
    occurrence = _OCCURRENCE_RE.match(label_text)
    if occurrence is None:
        return [], None
    pool = index.find(occurrence["label"])
    number = int(occurrence["number"])
    if pool and number > len(pool):
        return [], f"label occurrence out of range: {number} of {len(pool)}"
    return pool[number - 1 : number], None


def _candidate_payload(label_text: str, candidates: list[_LabelCandidate]) -> list[TableLabelCandidate]:
    label = _collapse_whitespace(label_text)
    return [
        {
            "table_index": candidate.table_index,
            "row": candidate.row,
            "col": candidate.col,
            "text": candidate.text,
            "selector": f"{label}[{number}]",
        }
        for number, candidate in enumerate(candidates, start=1)
    ]


def _cell_is_blank(cell: TableCell) -> bool:
    """No text and nothing else either: a cell holding a picture, a nested
    table or a form field has no text but is not a blank to write into."""

    if cell.text.strip():
        return False
    element = getattr(cell, "element", None)
    if element is None:
        return True
    for run in element.iter(f"{_HP}run"):
        for child in run:
            if child.tag != f"{_HP}t" or len(child):
                return False
    return True


def _cell_reference(
    table: Table,
    row_index: int,
    col_index: int,
) -> TableCellReference:
    return {
        "row": row_index,
        "col": col_index,
        "text": _cell_text(table, row_index, col_index),
    }


def _escape_path_label(label: str) -> str:
    r"""Write *label* so :func:`_parse_path` reads it back: ``>`` as ``\>``, and a backslash
    that comes before ``\`` or ``>`` as ``\\``. Other backslashes stay as they are."""

    return re.sub(r"\\(?=[\\>])", r"\\\\", label).replace(">", "\\>")


def _split_path(path: str) -> list[str]:
    r"""Split *path* at each ``>`` that is not written ``\>``; ``\\`` is one backslash.

    A backslash before any other character is kept, so a path written before ``\>``
    existed reads as it did.
    """

    tokens: list[str] = []
    current: list[str] = []
    index = 0
    while index < len(path):
        char = path[index]
        if char == "\\" and index + 1 < len(path) and path[index + 1] in "\\>":
            current.append(path[index + 1])
            index += 2
            continue
        if char == ">":
            tokens.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    tokens.append("".join(current))
    return tokens


def _check_path_types(mappings: object) -> None:
    """Refuse a mapping that is not one, or a path that is not a ``str``, before anything is written."""

    from hwpx.errors import HwpxTypeError

    if not isinstance(mappings, Mapping):
        raise HwpxTypeError(
            f"fill_by_path takes a mapping of path to value, not {type(mappings).__name__}.",
            code="table-path-invalid-type",
            context={"type": type(mappings).__name__},
            suggestion='{"성명 > right": "홍길동"}처럼 경로를 키로 하는 dict를 넘기세요.',
        )
    bad = [path for path in mappings if not isinstance(path, str)]
    if bad:
        raise HwpxTypeError(
            f"fill_by_path paths must be str; got {bad[0]!r} ({type(bad[0]).__name__}).",
            code="table-path-invalid-type",
            context={"paths": [repr(path) for path in bad[:10]], "count": len(bad)},
            suggestion=(
                "form_slots()가 준 path(str)를 키로 쓰세요. path가 None인 칸은 이름표가 콜론뿐인 칸이니 "
                "그 칸의 table_index와 target_cell이 가리키는 칸에 직접 쓰세요."
            ),
        )


def _parse_path(path: str) -> tuple[str | None, list[str], str | None]:
    tokens = [token.strip() for token in _split_path(path)]
    if not tokens or not tokens[0]:
        return (None, [], "path must start with a label")

    label_text = tokens[0]
    raw_directions = [token for token in tokens[1:] if token]
    if not raw_directions:
        return (label_text, [], "path must include at least one direction")
    return (label_text, raw_directions, None)


def find_cell_by_label(
    doc: HwpxDocument,
    label_text: str,
    direction: SearchDirection = "right",
) -> TableLabelSearchResult:
    """Find label cells and return the adjacent target cells that remain in bounds.

    Replaces python-hwpx 6.x ``doc.tables.find_cell_by_label(label_text, direction)``.
    """

    if direction not in {"right", "down"}:
        raise ValueError("direction must be one of: right, down")

    matches: list[TableLabelMatch] = []
    for candidate in _LabelIndex(_document_tables(doc)).find(label_text):
        target = _move(candidate.table, candidate.row, candidate.col, direction)
        if target is None:
            continue
        target_row, target_col = target
        matches.append(
            {
                "table_index": candidate.table_index,
                "label_cell": {
                    "row": candidate.row,
                    "col": candidate.col,
                    "text": candidate.text,
                },
                "target_cell": _cell_reference(candidate.table, target_row, target_col),
            }
        )

    return {
        "matches": matches,
        "count": len(matches),
    }


def _cell_width_mm(cell: TableCell) -> float | None:
    # Read without ``cell.width``: that adds an ``hp:cellSz`` to a cell that has none.
    element = getattr(cell, "element", None)
    size = element.find(f"{_HP}cellSz") if element is not None else None
    try:
        return round(int(size.get("width")) / _HWPUNIT_PER_MM, 1)  # type: ignore[union-attr]
    except (AttributeError, TypeError, ValueError):
        return None


def form_slots(doc: HwpxDocument, *, min_width_mm: float = 5.0) -> TableFormSlotsResult:
    r"""List the blanks of a form: empty cells right of, or below, a cell with text.

    Replaces python-hwpx 6.x ``doc.tables.form_slots(min_width_mm=5.0)``.

    Forms put thin empty cells between a label and its boxes as spacing; a
    value written there comes out one character per line. Cells narrower than
    *min_width_mm* (``width_mm`` of each slot) are therefore left out; pass
    ``0`` to list them too. A path still reaches a cell this list leaves out.

    Each slot carries the ``path`` that :func:`fill_by_path` takes to fill it
    (``"성명 > right"``; ``"성명[2] > right"`` when the label occurs more than
    once). A blank is offered once, by the cell to its left when that has text,
    otherwise by the cell above. A ``>`` in the label is written ``\>`` in the
    path (``"수입 > 지출"`` becomes ``"수입 \> 지출 > right"``), and a backslash
    before ``\`` or ``>`` as ``\\``. ``path`` is None when the label is only a
    colon; the slot's ``table_index`` and ``target_cell`` still say where it
    is. ``table_index`` counts tables as ``doc.tables.map()`` does, tables
    inside cells included.

    This reads structure only. Whether a cell with text is a label, and what
    belongs in the blank, is for the caller to decide.
    """

    tables = _document_tables(doc)
    index = _LabelIndex(tables)

    slots: list[TableFormSlot] = []
    backwards: tuple[tuple[SearchDirection, PathDirection], ...] = (("right", "left"), ("down", "up"))
    for table_ref in tables:
        table = table_ref.table
        grid = table.cell_map
        texts: dict[tuple[int, int], str] = {}
        widths: dict[tuple[int, int], float | None] = {}
        blanks: list[tuple[int, int]] = []
        for position in table.iter_grid():
            if not position.is_anchor:
                continue
            texts[position.anchor] = position.cell.text
            if not _cell_is_blank(position.cell):
                continue
            width = _cell_width_mm(position.cell)
            if width is not None and width < min_width_mm:
                continue
            widths[position.anchor] = width
            blanks.append(position.anchor)
        for row_index, col_index in blanks:
            for direction, back in backwards:
                source = _move(table, row_index, col_index, back, grid)
                if source is None:
                    continue
                label_text = texts.get(source, "")
                if not label_text.strip():
                    continue
                # The path walks from the label; a merged label reaches only one
                # of the cells beside it.
                if _move(table, source[0], source[1], direction, grid) != (row_index, col_index):
                    continue
                label = _collapse_whitespace(label_text)
                path: str | None = None
                if _normalize_label_text(label_text):
                    same = index.whole.get(_normalize_label_text(label_text), [])
                    selector = _escape_path_label(label)
                    if len(same) > 1:
                        number = next(
                            number
                            for number, candidate in enumerate(same, start=1)
                            if candidate.table is table and (candidate.row, candidate.col) == source
                        )
                        selector = f"{selector}[{number}]"
                    path = f"{selector} > {direction}"
                slots.append(
                    {
                        "label": label,
                        "path": path,
                        "direction": direction,
                        "table_index": table_ref.table_index,
                        "label_cell": {"row": source[0], "col": source[1], "text": label_text},
                        "target_cell": {"row": row_index, "col": col_index, "text": texts[(row_index, col_index)]},
                        "width_mm": widths[(row_index, col_index)],
                    }
                )
                break
    return {"slots": slots, "count": len(slots)}


def fill_by_path(
    doc: HwpxDocument,
    mappings: Mapping[str, str],
    *,
    fit: FitPolicy | None = None,
) -> TableFillResult:
    r"""Fill multiple table cells using label-based navigation paths.

    Replaces python-hwpx 6.x ``doc.tables.fill_by_path(mappings, fit=None)``.

    A path is a label and one or more directions: ``"성명 > right"``. The label
    is compared without whitespace, case or a trailing colon, so ``"성명"``
    finds a cell that reads ``"성  명"``. When the label matches several cells
    the path fails as ``"ambiguous label"`` and lists them under
    ``candidates``; write ``"성명[2] > right"`` to pick the second in document
    order. A label holding ``>`` writes it ``\>`` (``"가 \> 나 > right"``).
    :func:`form_slots` lists the blanks with their paths. A path that is not a
    ``str`` raises :class:`hwpx.errors.HwpxTypeError` before any cell is
    written.

    Without *fit* a value is written as it is and Hancom grows the row when it
    needs more lines. With a :class:`hwpx.form_fit.FitPolicy` each
    value is measured against its cell: it wraps or shrinks as the policy
    allows, the outcome is reported under ``fit``, and a value the policy
    refuses fails as ``"value does not fit"`` with its cell left as it was.
    """

    # Labels are resolved against the document as it is when the call starts,
    # so the outcome does not depend on the order of the paths: a value written
    # for one path is never taken for the label of another.
    _check_path_types(mappings)
    index = _LabelIndex(_document_tables(doc))
    grids: dict[int, Any] = {}
    applied: list[TableFillApplied] = []
    failed: list[TableFillFailed] = []

    for path, value in mappings.items():
        label_text, raw_directions, path_error = _parse_path(path)
        if path_error is not None or label_text is None:
            failed.append({"path": path, "reason": path_error or "invalid path"})
            continue

        try:
            candidates, selection_error = _select_label_candidates(index, label_text)
        except ValueError as exc:
            failed.append({"path": path, "reason": str(exc)})
            continue

        if selection_error is not None:
            failed.append({"path": path, "reason": selection_error})
            continue
        if not candidates:
            failed.append({"path": path, "reason": "label not found"})
            continue
        if len(candidates) > 1:
            failed.append(
                {
                    "path": path,
                    "reason": "ambiguous label",
                    "candidates": _candidate_payload(label_text, candidates),
                }
            )
            continue

        candidate = candidates[0]
        grid = grids.get(candidate.table_index)
        if grid is None:
            grid = grids[candidate.table_index] = candidate.table.cell_map
        current_row = candidate.row
        current_col = candidate.col
        navigation_failed = False

        for raw_direction in raw_directions:
            direction = raw_direction.casefold()
            if direction not in {"left", "right", "up", "down"}:
                failed.append(
                    {
                        "path": path,
                        "reason": f"unsupported direction: {raw_direction}",
                    }
                )
                navigation_failed = True
                break

            next_position = _move(candidate.table, current_row, current_col, cast(PathDirection, direction), grid)
            if next_position is None:
                failed.append({"path": path, "reason": "navigation out of bounds"})
                navigation_failed = True
                break

            current_row, current_col = next_position

        if navigation_failed:
            continue

        text_value = str(value)
        outcome = candidate.table.set_cell_text(
            current_row, current_col, text_value, logical=True, fit=fit
        )
        if outcome is not None and not outcome.ok:
            failed.append({"path": path, "reason": "value does not fit", "fit": outcome.to_dict()})
            continue
        entry: TableFillApplied = {
            "path": path,
            "table_index": candidate.table_index,
            "row": current_row,
            "col": current_col,
            "value": text_value,
        }
        if outcome is not None:
            entry["fit"] = outcome.to_dict()
        applied.append(entry)

    return {
        "applied": applied,
        "failed": failed,
        "applied_count": len(applied),
        "failed_count": len(failed),
    }
