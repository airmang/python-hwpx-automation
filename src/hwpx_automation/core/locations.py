# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator


@dataclass(frozen=True, slots=True)
class ResolvedParagraph:
    paragraph: Any
    location: dict[str, Any]


def body_paragraph_location(paragraph_index: int) -> dict[str, Any]:
    return {"kind": "body_paragraph", "paragraph_index": paragraph_index}


def table_cell_paragraph_location(
    table_index: int,
    row: int,
    col: int,
    cell_paragraph_index: int,
) -> dict[str, Any]:
    return {
        "kind": "table_cell_paragraph",
        "table_index": table_index,
        "row": row,
        "col": col,
        "cell_paragraph_index": cell_paragraph_index,
    }


def location_anchor(location: dict[str, Any], position: int | None = None) -> dict[str, Any]:
    anchor_id = _anchor_id(location, position)
    payload: dict[str, Any] = {"anchor_id": anchor_id, "location": dict(location)}
    if position is not None:
        payload["position"] = position
    return payload


def location_from_anchor(anchor: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(anchor, dict):
        if isinstance(anchor.get("location"), dict):
            return dict(anchor["location"])
        if "kind" in anchor:
            return dict(anchor)
    if not isinstance(anchor, str):
        raise ValueError("anchor must be an object with location or an anchor_id string")

    head = anchor.split("@", 1)[0]
    parts = head.split(":")
    if parts[0] == "body" and len(parts) == 2:
        return body_paragraph_location(_int(parts[1], "paragraph_index"))
    if parts[0] == "table" and len(parts) == 5:
        return table_cell_paragraph_location(
            _int(parts[1], "table_index"),
            _int(parts[2], "row"),
            _int(parts[3], "col"),
            _int(parts[4], "cell_paragraph_index"),
        )
    raise ValueError(f"unsupported anchor_id: {anchor}")


def iter_indexed_tables(doc: Any) -> Iterator[tuple[int, Any]]:
    table_index = 0
    for paragraph in getattr(doc, "paragraphs", []):
        for table in _iter_tables_from_paragraph(paragraph):
            yield table_index, table
            table_index += 1


def iter_paragraph_locations(doc: Any) -> Iterator[ResolvedParagraph]:
    for paragraph_index, paragraph in enumerate(getattr(doc, "paragraphs", [])):
        yield ResolvedParagraph(paragraph, body_paragraph_location(paragraph_index))

    for table_index, table in iter_indexed_tables(doc):
        for row, col, cell in _iter_anchor_cells(table):
            for cell_paragraph_index, paragraph in enumerate(getattr(cell, "paragraphs", []) or []):
                yield ResolvedParagraph(
                    paragraph,
                    table_cell_paragraph_location(table_index, row, col, cell_paragraph_index),
                )


def resolve_paragraph_reference(
    doc: Any,
    *,
    paragraph_index: int | None = None,
    location: dict[str, Any] | None = None,
    create: bool = False,
) -> ResolvedParagraph:
    if location is None:
        if paragraph_index is None:
            raise ValueError("paragraph_index 또는 location 중 하나를 제공해야 합니다.")
        return _resolve_body_paragraph(doc, paragraph_index)

    kind = str(location.get("kind") or "").strip()
    if kind in {"body", "paragraph", "body_paragraph"}:
        index_value = location.get("paragraph_index", paragraph_index)
        if index_value is None:
            raise ValueError("body_paragraph location에는 paragraph_index가 필요합니다.")
        return _resolve_body_paragraph(doc, int(index_value))

    if kind in {"table_cell_paragraph", "cell_paragraph"}:
        return _resolve_table_cell_paragraph(doc, location, create=create)

    raise ValueError(f"지원하지 않는 location kind: {kind or '<missing>'}")


def _resolve_body_paragraph(doc: Any, paragraph_index: int) -> ResolvedParagraph:
    paragraphs = list(getattr(doc, "paragraphs", []))
    if paragraph_index < 0 or paragraph_index >= len(paragraphs):
        raise ValueError(f"유효하지 않은 paragraph_index: {paragraph_index}")
    return ResolvedParagraph(paragraphs[paragraph_index], body_paragraph_location(paragraph_index))


def _resolve_table_cell_paragraph(
    doc: Any,
    location: dict[str, Any],
    *,
    create: bool,
) -> ResolvedParagraph:
    table_index = _int(location.get("table_index"), "table_index")
    row = _int(location.get("row"), "row")
    col = _int(location.get("col"), "col")
    cell_paragraph_index = _int(
        location.get("cell_paragraph_index", location.get("p", 0)),
        "cell_paragraph_index",
    )

    tables = [table for _, table in iter_indexed_tables(doc)]
    if table_index < 0 or table_index >= len(tables):
        raise ValueError(f"유효하지 않은 table_index: {table_index}")

    try:
        cell = tables[table_index].cell(row, col)
    except (IndexError, ValueError) as exc:
        raise ValueError(f"유효하지 않은 table cell 좌표: table={table_index}, row={row}, col={col}") from exc

    paragraphs = list(getattr(cell, "paragraphs", []) or [])
    if create and not paragraphs and hasattr(cell, "add_paragraph"):
        paragraphs = [cell.add_paragraph("")]

    if cell_paragraph_index < 0 or cell_paragraph_index >= len(paragraphs):
        raise ValueError(
            "유효하지 않은 cell_paragraph_index: "
            f"{cell_paragraph_index} (table={table_index}, row={row}, col={col})"
        )

    normalized = table_cell_paragraph_location(table_index, row, col, cell_paragraph_index)
    return ResolvedParagraph(paragraphs[cell_paragraph_index], normalized)


def _iter_tables_from_paragraph(paragraph: Any) -> Iterator[Any]:
    for table in getattr(paragraph, "tables", []) or []:
        yield table
        yield from _iter_nested_tables(table)


def _iter_nested_tables(table: Any) -> Iterator[Any]:
    for row in getattr(table, "rows", []) or []:
        for cell in getattr(row, "cells", []) or []:
            for paragraph in getattr(cell, "paragraphs", []) or []:
                yield from _iter_tables_from_paragraph(paragraph)


def _iter_anchor_cells(table: Any) -> Iterator[tuple[int, int, Any]]:
    if hasattr(table, "iter_grid"):
        seen: set[Any] = set()  # 칸 객체는 같은 요소면 같고 해시도 같다(python-hwpx)
        for position in table.iter_grid():
            if not getattr(position, "is_anchor", False):
                continue
            cell = position.cell
            if cell in seen:
                continue
            seen.add(cell)
            row, col = getattr(position, "anchor", (position.row, position.column))
            yield int(row), int(col), cell
        return

    for row_index, row in enumerate(getattr(table, "rows", []) or []):
        for col_index, cell in enumerate(getattr(row, "cells", []) or []):
            yield row_index, col_index, cell


def _int(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _anchor_id(location: dict[str, Any], position: int | None) -> str:
    suffix = "" if position is None else f"@{position}"
    kind = location.get("kind")
    if kind == "body_paragraph":
        return f"body:{location['paragraph_index']}{suffix}"
    if kind == "table_cell_paragraph":
        return (
            "table:"
            f"{location['table_index']}:{location['row']}:{location['col']}:"
            f"{location['cell_paragraph_index']}{suffix}"
        )
    return f"{kind or 'unknown'}{suffix}"
