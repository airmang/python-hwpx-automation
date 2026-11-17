# SPDX-License-Identifier: Apache-2.0
"""Boxed organization-chart composition (table canvas, real-Hancom idiom).

The measured operating-plan genre draws organization charts as a borderless
table canvas with merged label boxes and cell-border connectors — no drawing
objects at all. This module owns that composition: it turns a hierarchy tree
into an explicit grid spec (boxes, merges, per-cell border sides, row
heights) and lowers it onto a document through generic core primitives only
(``add_table`` / ``merge_cells`` / ``ensure_border_fill`` /
``set_cell_border_fill`` / ``set_cell_shading``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, field_validator

MAX_DEPTH = 4
MAX_BOXES = 40

_BOX_ROW_HEIGHT = 2600  # about 9 mm: a box reads as a box, not a ruled line (8.0)
_CONNECTOR_ROW_HEIGHT = 700  # the connector rows: room between the levels
#: The type size of a box's label by level (root first); deeper levels take the last.
_BOX_FONT_PT = (15.0, 13.0, 12.0)
#: The least a label is set in before it is let wrap in its box.
_MIN_FONT_PT = 9.0
#: A label wraps onto at most this many lines; past it the chart says it does not fit.
_MOST_LINES = 3
_CELL_SIDE_PADDING = 2 * 510
_NEWLINE = chr(10)
#: A box's line takes this much of its type size in height, line spacing and padding included.
_LINE_PITCH = 1.7
_BOX_COLUMN_WEIGHT = 3.0
_GAP_COLUMN_WEIGHT = 1.0
_BORDER_WIDTH_MM = 0.12
_BORDER_COLOR = "#000000"


class OrgNode(BaseModel):
    """One labelled box in the chart."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    sublabel: str | None = None
    children: tuple["OrgNode", ...] = ()

    @field_validator("label")
    @classmethod
    def _label_nonempty(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("org-chart node label must be non-empty")
        return normalized


@dataclass(frozen=True)
class _Box:
    row: int
    col_start: int
    col_end: int
    text: str
    fill_color: str | None
    level: int = 0


@dataclass
class BoxedOrgChartSpec:
    """Explicit grid lowering spec — everything the renderer needs."""

    rows: int
    cols: int
    column_weights: list[float]
    row_heights: list[int]
    boxes: list[_Box] = field(default_factory=list)
    # (row, col) -> border side set among {"left","right","top","bottom"}
    cell_sides: dict[tuple[int, int], frozenset[str]] = field(default_factory=dict)


def _parse_hierarchy(hierarchy: Mapping[str, Any]) -> OrgNode:
    if not isinstance(hierarchy, Mapping):
        raise TypeError("hierarchy must be a mapping with label/children")
    root = OrgNode.model_validate(hierarchy)
    depth = _tree_depth(root)
    if depth > MAX_DEPTH:
        raise ValueError(f"org-chart depth {depth} exceeds the supported {MAX_DEPTH}")
    count = _tree_count(root)
    if count > MAX_BOXES:
        raise ValueError(f"org-chart box count {count} exceeds the supported {MAX_BOXES}")
    return root


def _tree_depth(node: OrgNode) -> int:
    if not node.children:
        return 1
    return 1 + max(_tree_depth(child) for child in node.children)


def _tree_count(node: OrgNode) -> int:
    return 1 + sum(_tree_count(child) for child in node.children)


def _leaf_count(node: OrgNode) -> int:
    if not node.children:
        return 1
    return sum(_leaf_count(child) for child in node.children)


def _box_text(node: OrgNode) -> str:
    if node.sublabel:
        return f"{node.label}\n{node.sublabel.strip()}"
    return node.label


def compose_boxed_org_chart(
    hierarchy: Mapping[str, Any],
    *,
    accent_color: str | None = None,
) -> BoxedOrgChartSpec:
    """Compose the grid spec for a boxed org chart.

    Layout: every leaf owns two box columns; adjacent leaves are separated by
    one gap column. Each level occupies one box row; between levels sit two
    short connector rows — the parent stub drops through the upper row, the
    horizontal rail rides the boundary between the two, and child stubs drop
    through the lower row. Connectors are cell borders on that grid.
    """

    root = _parse_hierarchy(hierarchy)
    depth = _tree_depth(root)
    leaves = _leaf_count(root)
    cols = leaves * 3 - 1
    rows = depth * 3 - 2
    spec = BoxedOrgChartSpec(
        rows=rows,
        cols=cols,
        column_weights=[
            _GAP_COLUMN_WEIGHT if index % 3 == 2 else _BOX_COLUMN_WEIGHT
            for index in range(cols)
        ],
        row_heights=[
            _BOX_ROW_HEIGHT if index % 3 == 0 else _CONNECTOR_ROW_HEIGHT
            for index in range(rows)
        ],
    )
    _place_subtree(spec, root, level=0, leaf_offset=0, accent_color=accent_color)
    return spec


def _center_edge(leaf_offset: int, leaves: int) -> int:
    """Column index whose RIGHT edge is the subtree's visual center."""

    first_col = leaf_offset * 3
    last_col = (leaf_offset + leaves - 1) * 3 + 1
    return (first_col + last_col - 1) // 2


def _add_sides(spec: BoxedOrgChartSpec, row: int, col: int, *sides: str) -> None:
    key = (row, col)
    current = set(spec.cell_sides.get(key, frozenset()))
    current.update(sides)
    spec.cell_sides[key] = frozenset(current)


def _place_subtree(
    spec: BoxedOrgChartSpec,
    node: OrgNode,
    *,
    level: int,
    leaf_offset: int,
    accent_color: str | None,
) -> int:
    """Place *node*'s box and connectors; return its center edge column."""

    leaves = _leaf_count(node)
    box_row = level * 3
    center = _center_edge(leaf_offset, leaves)
    subtree_first = leaf_offset * 3
    subtree_last = (leaf_offset + leaves - 1) * 3 + 1
    if node.children and leaves > 1:
        col_start = max(center - 1, subtree_first)
        col_end = min(center + 2, subtree_last)
    else:
        col_start, col_end = center, center + 1
    spec.boxes.append(
        _Box(
            row=box_row,
            col_start=col_start,
            col_end=col_end,
            text=_box_text(node),
            fill_color=accent_color if level == 0 else None,
            level=level,
        )
    )
    if not node.children:
        return center

    child_centers: list[int] = []
    offset = leaf_offset
    for child in node.children:
        child_centers.append(
            _place_subtree(
                spec,
                child,
                level=level + 1,
                leaf_offset=offset,
                accent_color=accent_color,
            )
        )
        offset += _leaf_count(child)

    upper = box_row + 1
    lower = box_row + 2
    # Parent stub: full height of the upper connector row at the parent centre.
    _add_sides(spec, upper, center, "right")
    # Rail: the boundary between the two connector rows, spanning child centres.
    for col in range(min(child_centers) + 1, max(child_centers) + 1):
        _add_sides(spec, upper, col, "bottom")
    # Child stubs: full height of the lower connector row at each child centre.
    for child_center in child_centers:
        _add_sides(spec, lower, child_center, "right")
    return center


def lower_boxed_org_chart(
    document: Any,
    hierarchy: Mapping[str, Any],
    *,
    section_index: int = 0,
    accent_color: str | None = None,
) -> dict[str, Any]:
    """Render the chart into *document* using generic core primitives only."""

    spec = compose_boxed_org_chart(hierarchy, accent_color=accent_color)
    table = document.add_table(spec.rows, spec.cols, section=section_index)

    invisible = document.styles.ensure_border_fill(active_borders=[])
    table.border_fill_id_ref = invisible
    for row in range(spec.rows):
        for col in range(spec.cols):
            table.set_cell_border_fill(row, col, invisible)

    for (row, col), sides in sorted(spec.cell_sides.items()):
        fill = document.styles.ensure_border_fill(
            border_color=_BORDER_COLOR,
            border_width_mm=_BORDER_WIDTH_MM,
            active_borders=sorted(sides),
        )
        table.set_cell_border_fill(row, col, fill)

    table_width = sum(table.cell(0, col).width for col in range(spec.cols))
    table.set_column_widths(_column_widths(spec, table_width))
    widths = [table.cell(0, col).width for col in range(spec.cols)]
    fitted = [_fit_label(box, sum(widths[box.col_start : box.col_end + 1])) for box in spec.boxes]
    row_heights = list(spec.row_heights)
    for box, (size, lines, _fits) in zip(spec.boxes, fitted):
        needed = round(size * 100 * _LINE_PITCH * lines) + 2 * 141
        row_heights[box.row] = max(row_heights[box.row], needed)

    for box, (size, _lines, _fits) in zip(spec.boxes, fitted):
        merged = table.merge_cells(box.row, box.col_start, box.row, box.col_end)
        box_fill = document.styles.ensure_border_fill(
            border_color=_BORDER_COLOR,
            border_width_mm=_BORDER_WIDTH_MM,
            fill_color=box.fill_color,
        )
        table.set_cell_border_fill(box.row, box.col_start, box_fill)
        merged.text = box.text
        merged.vertical_alignment = "CENTER"
        label = document.styles.ensure_run(bold=True, size=size)
        for paragraph in merged.paragraphs:
            for run in paragraph.runs:
                run.char_pr_id_ref = label
            paragraph.char_pr_id_ref = label
        document.styles.apply_paragraph_format(paragraphs=list(merged.paragraphs), alignment="center")

    table.set_row_heights(row_heights)  # every cell of a row, the merged boxes too
    table.mark_dirty()

    too_wide = [box.text.replace(_NEWLINE, " ") for box, (_size, _lines, fits) in zip(spec.boxes, fitted) if not fits]
    summary: dict[str, Any] = {
        "rows": spec.rows,
        "cols": spec.cols,
        "boxes": len(spec.boxes),
        "connectorCells": len(spec.cell_sides),
        "fontPt": sorted({size for size, _lines, _fits in fitted}, reverse=True),
        "fits": not too_wide,
    }
    if too_wide:
        summary["warnings"] = [
            f"상자 {len(too_wide)}개의 이름이 칸 폭에 {_MOST_LINES}줄로도 들지 않습니다: "
            + ", ".join(too_wide[:5])
            + ". 이름을 줄이거나 가지를 나눠 주세요."
        ]
    return summary


#: Hancom draws no column narrower than its cells' side margins (510 each) and 283 more
#: (python-hwpx ``NEW_TABLE_COLUMN_FLOOR``); a narrower one widens the table past the page's text.
_COLUMN_FLOOR = 2 * 510 + 283


def _column_widths(spec: BoxedOrgChartSpec, table_width: int) -> list[int]:
    """The columns' widths in HWPUNIT, adding up to *table_width*: the gaps their share, but never
    under Hancom's least column, and the box columns the rest."""

    total = sum(spec.column_weights)
    gaps = [index for index, weight in enumerate(spec.column_weights) if weight == _GAP_COLUMN_WEIGHT]
    gap = max(round(table_width * _GAP_COLUMN_WEIGHT / total), _COLUMN_FLOOR) if gaps else 0
    boxes = spec.cols - len(gaps)
    box = max((table_width - gap * len(gaps)) // max(boxes, 1), _COLUMN_FLOOR)
    widths = [gap if index in gaps else box for index in range(spec.cols)]
    widths[-1] += table_width - sum(widths)  # the rounding, on the last column
    return widths


def _fit_label(box: _Box, width: int) -> tuple[float, int, bool]:
    """``(type size, lines, fits)`` for *box*'s label in a box *width* wide: its level's size, made
    smaller (down to the least) until each line fits, then let wrap onto up to a few lines."""

    from hwpx.form_fit import estimate_text_width

    inner = max(width - _CELL_SIDE_PADDING, 1)
    lines_text = box.text.split(_NEWLINE)
    size = _BOX_FONT_PT[min(box.level, len(_BOX_FONT_PT) - 1)]
    while True:
        longest = max(estimate_text_width(line, size) for line in lines_text)
        if longest <= inner or size <= _MIN_FONT_PT:
            break
        size -= 1.0
    wrapped = sum(max(1, -(-int(estimate_text_width(line, size)) // inner)) for line in lines_text)
    return size, wrapped, wrapped <= _MOST_LINES * len(lines_text)


__all__ = [
    "MAX_BOXES",
    "MAX_DEPTH",
    "BoxedOrgChartSpec",
    "OrgNode",
    "compose_boxed_org_chart",
    "lower_boxed_org_chart",
]
