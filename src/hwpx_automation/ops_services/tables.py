# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging
import math
import re as _re
from typing import Any, Dict, List, Optional, Sequence, TypedDict
from xml.etree import ElementTree as ET

from ..upstream import (
    HH_NS,
    HP_NS,
    HwpxDocument,
    HwpxOxmlTable,
    default_cell_width,
)

from ._border_fill import (
    _build_border_fill_element,
    _find_matching_border_fill,
    _resolve_border_fill_spec,
    _shortcut_border_fill_id,
)
from .context import DocumentContext
from .save_policy import SavePolicy
from .memo_style import MemoStyleService

logger = logging.getLogger("hwpx_automation.hwpx_ops")


class _CellAddressingKwargs(TypedDict, total=False):
    """Optional addressing flags forwarded to ``HwpxOxmlTable.set_cell_text``.

    Restricting the mapping to these two keys keeps ``**kwargs`` from being read
    as also supplying ``fit`` (a ``FitPolicy | None`` parameter), which a bare
    ``Dict[str, bool]`` would imply.
    """

    logical: bool
    split_merged: bool


_CELL_TEXT_ILLEGAL = _re.compile(r"[\x00-\x08\x09\x0b\x0c\x0d\x0e-\x1f\ufffe\uffff]")


def _sanitize_cell_text(value: str) -> str:
    """Remove characters illegal inside HWPML <hp:t> nodes.

    Tab (U+0009) is stripped - it must live in a separate cell column,
    not be concatenated with the text. \r is stripped; \n is kept.
    Logs a warning when anything is actually removed.
    """
    cleaned = _CELL_TEXT_ILLEGAL.sub("", value)
    if cleaned != value:
        logger.warning(
            "cell text contained illegal characters and was sanitised",
            extra={"original_len": len(value), "cleaned_len": len(cleaned)},
        )
    return cleaned


_DEFAULT_CELL_WIDTH = default_cell_width()

_AUTO_FIT_CHAR_UNIT = max(360, _DEFAULT_CELL_WIDTH // 10)
_AUTO_FIT_PADDING_CHARS = 2
_AUTO_FIT_MIN_COLUMN_WIDTH = max(
    _AUTO_FIT_CHAR_UNIT * (_AUTO_FIT_PADDING_CHARS + 1), _DEFAULT_CELL_WIDTH // 2
)
_AUTO_FIT_MAX_COLUMN_WIDTH = _DEFAULT_CELL_WIDTH * 12


DEFAULT_PAGING_PARAGRAPH_LIMIT = 200


class TableService:
    def __init__(
        self, context: DocumentContext, save: SavePolicy, styles: MemoStyleService
    ) -> None:
        self._context = context
        self._save = save
        self._styles = styles

    def _auto_fit_table_columns(self, table: HwpxOxmlTable) -> List[int]:
        column_count = table.column_count
        if column_count <= 0:
            return []

        char_requirements: List[float] = [0.0] * column_count
        for position in table.iter_grid():
            if not position.is_anchor:
                continue
            text = position.cell.text or ""
            lines = text.splitlines()
            if not lines:
                lines = [text]
            longest = max(len(line) for line in lines)
            span = max(1, position.col_span)
            per_column = longest / span if span else float(longest)
            for offset in range(span):
                column_index = position.column + offset
                if 0 <= column_index < column_count:
                    char_requirements[column_index] = max(
                        char_requirements[column_index],
                        per_column,
                    )

        column_widths: List[int] = []
        for requirement in char_requirements:
            width = int(
                math.ceil((requirement + _AUTO_FIT_PADDING_CHARS) * _AUTO_FIT_CHAR_UNIT)
            )
            width = max(width, _AUTO_FIT_MIN_COLUMN_WIDTH)
            width = min(width, _AUTO_FIT_MAX_COLUMN_WIDTH)
            column_widths.append(width)

        total_width = sum(column_widths)
        if total_width <= 0:
            column_widths = [
                max(_AUTO_FIT_MIN_COLUMN_WIDTH, _AUTO_FIT_CHAR_UNIT)
            ] * column_count
            total_width = sum(column_widths)

        size_element = table.element.find(f"{HP_NS}sz")
        if size_element is not None:
            size_element.set("width", str(total_width))

        for position in table.iter_grid():
            if not position.is_anchor:
                continue
            span = max(1, position.col_span)
            start = position.column
            width_value = 0
            for offset in range(span):
                column_index = start + offset
                if 0 <= column_index < column_count:
                    width_value += column_widths[column_index]
            if width_value <= 0:
                continue
            cell_size = position.cell.element.find(f"{HP_NS}cellSz")
            if cell_size is not None:
                cell_size.set("width", str(width_value))

        table.mark_dirty()
        return column_widths

    def _ensure_table_border_fill(
        self,
        document: HwpxDocument,
        *,
        border_style: Optional[str] = None,
        border_color: Optional[str] = None,
        border_width: Optional[str | float | int] = None,
        fill_color: Optional[str] = None,
    ) -> str:
        normalized_style = (border_style or "").strip().lower() or None
        if normalized_style not in {None, "solid", "none"}:
            raise ValueError(f"Unsupported border style: {border_style}")

        normalized_border_color = self._styles._normalize_color(border_color)
        normalized_fill_color = self._styles._normalize_color(fill_color)

        shortcut = _shortcut_border_fill_id(
            document,
            normalized_style,
            normalized_border_color,
            normalized_fill_color,
            border_width,
        )
        if shortcut is not None:
            return shortcut

        if not document.parts.headers:
            raise self._context._new_error(
                "STYLE_BORDER_FILL_HEADER_MISSING",
                "document does not contain any headers to host border fills",
            )

        header = document.parts.headers[0]
        spec = _resolve_border_fill_spec(
            normalized_style,
            normalized_border_color,
            normalized_fill_color,
            border_width,
        )

        ref_list = header.element.find(f"{HH_NS}refList")
        if ref_list is None:
            ref_list = ET.SubElement(header.element, f"{HH_NS}refList")
            header.mark_dirty()

        border_fills_element = ref_list.find(f"{HH_NS}borderFills")
        if border_fills_element is None:
            border_fills_element = ET.SubElement(
                ref_list, f"{HH_NS}borderFills", {"itemCnt": "0"}
            )
            header.mark_dirty()

        matched = _find_matching_border_fill(border_fills_element, spec)
        if matched is not None:
            return matched

        # Upstream still does not expose a public border-fill creation API.
        # Keep the private helper usage isolated here until python-hwpx offers one.
        if not hasattr(header, "_allocate_border_fill_id"):
            raise self._context._new_error(
                "STYLE_ID_ALLOCATOR_MISSING",
                "header does not expose ID allocation helpers",
            )

        new_id = header._allocate_border_fill_id(border_fills_element)
        _build_border_fill_element(border_fills_element, new_id, spec)

        count = len(border_fills_element.findall(f"{HH_NS}borderFill"))
        border_fills_element.set("itemCnt", str(count))
        header.mark_dirty()
        return new_id

    def add_table(
        self,
        path: str,
        rows: int,
        cols: int,
        *,
        section_index: Optional[int] = None,
        border_style: str | None = None,
        border_color: Optional[str] = None,
        border_width: Optional[str | float | int] = None,
        fill_color: Optional[str] = None,
        auto_fit: bool = False,
    ) -> Dict[str, Any]:
        document, resolved = self._context._open_document(path)
        border_fill = self._ensure_table_border_fill(
            document,
            border_style=border_style,
            border_color=border_color,
            border_width=border_width,
            fill_color=fill_color,
        )
        table = document.add_table(
            rows,
            cols,
            section_index=section_index,
            border_fill_id_ref=border_fill,
        )
        if auto_fit:
            self._auto_fit_table_columns(table)
        tables = self._context._iter_tables(document)
        element_id = id(table.element)
        index = len(tables) - 1
        for idx, candidate in enumerate(tables):
            if id(candidate.element) == element_id:
                index = idx
                break
        self._save._save_document(document, resolved)
        return {"tableIndex": index, "cellCount": rows * cols}

    def set_table_border_fill(
        self,
        path: str,
        table_index: int,
        *,
        border_style: str | None = None,
        border_color: Optional[str] = None,
        border_width: Optional[str | float | int] = None,
        fill_color: Optional[str] = None,
    ) -> Dict[str, Any]:
        document, resolved = self._context._open_document(path)
        tables = self._context._iter_tables(document)
        try:
            table = tables[table_index]
        except IndexError as exc:
            raise self._context._new_error(
                "TABLE_INDEX_OUT_OF_RANGE",
                "tableIndex out of range",
                details={"tableIndex": table_index},
            ) from exc

        border_fill = self._ensure_table_border_fill(
            document,
            border_style=border_style,
            border_color=border_color,
            border_width=border_width,
            fill_color=fill_color,
        )

        table.element.set("borderFillIDRef", border_fill)
        anchor_elements: set[int] = set()
        for position in table.iter_grid():
            if getattr(position, "is_anchor", False):
                cell_element = position.cell.element
                cell_element.set("borderFillIDRef", border_fill)
                anchor_elements.add(id(cell_element))

        table.mark_dirty()
        self._save._save_document(document, resolved)
        return {"borderFillIDRef": border_fill, "anchorCells": len(anchor_elements)}

    def get_table_cell_map(
        self,
        path: str,
        table_index: int,
    ) -> Dict[str, Any]:
        document, _ = self._context._open_document(path)
        tables = self._context._iter_tables(document)
        try:
            table = tables[table_index]
        except IndexError as exc:
            raise self._context._new_error(
                "TABLE_INDEX_OUT_OF_RANGE",
                "tableIndex out of range",
                details={"tableIndex": table_index},
            ) from exc

        grid_positions = table.get_cell_map()
        serialized: List[List[Dict[str, Any]]] = []
        for row in grid_positions:
            row_payload: List[Dict[str, Any]] = []
            for position in row:
                anchor_row, anchor_col = position.anchor
                row_span, col_span = position.span
                cell_text: Optional[str] = None
                cell = position.cell
                if cell is not None:
                    cell_text = cell.text
                row_payload.append(
                    {
                        "row": position.row,
                        "column": position.column,
                        "anchor": {"row": anchor_row, "column": anchor_col},
                        "rowSpan": row_span,
                        "colSpan": col_span,
                        "text": cell_text,
                    }
                )
            serialized.append(row_payload)
        row_count = len(serialized)
        column_count = len(serialized[0]) if serialized else 0
        return {"grid": serialized, "rowCount": row_count, "columnCount": column_count}

    def set_table_cell_text(
        self,
        path: str,
        table_index: int,
        row: int,
        col: int,
        text: str,
        *,
        dry_run: bool = False,
        logical: Optional[bool] = None,
        split_merged: Optional[bool] = None,
        auto_fit: bool = False,
    ) -> Dict[str, Any]:
        document, resolved = self._context._open_document(path)
        tables = self._context._iter_tables(document)
        try:
            table = tables[table_index]
        except IndexError as exc:
            raise self._context._new_error(
                "TABLE_INDEX_OUT_OF_RANGE",
                "tableIndex out of range",
                details={"tableIndex": table_index},
            ) from exc
        kwargs: _CellAddressingKwargs = {}
        if logical is not None:
            kwargs["logical"] = logical
        if split_merged is not None:
            kwargs["split_merged"] = split_merged
        guidance = (
            "failed to update table cell; check indexes, enable logical addressing, "
            "or split merged cells first"
        )
        try:
            table.set_cell_text(row, col, _sanitize_cell_text(text), **kwargs)
        except (IndexError, ValueError) as exc:
            raise self._context._new_error(
                "TABLE_CELL_OPERATION_FAILED", f"{guidance}: {exc}"
            ) from exc
        if auto_fit and not dry_run:
            self._auto_fit_table_columns(table)
        if not dry_run:
            self._save._save_document(document, resolved)
        return {"ok": True}

    def replace_table_region(
        self,
        path: str,
        table_index: int,
        start_row: int,
        start_col: int,
        values: Sequence[Sequence[str]],
        *,
        dry_run: bool = False,
        logical: Optional[bool] = None,
        split_merged: Optional[bool] = None,
        auto_fit: bool = False,
    ) -> Dict[str, Any]:
        document, resolved = self._context._open_document(path)
        tables = self._context._iter_tables(document)
        try:
            table = tables[table_index]
        except IndexError as exc:
            raise self._context._new_error(
                "TABLE_INDEX_OUT_OF_RANGE",
                "tableIndex out of range",
                details={"tableIndex": table_index},
            ) from exc
        kwargs: _CellAddressingKwargs = {}
        if logical is not None:
            kwargs["logical"] = logical
        if split_merged is not None:
            kwargs["split_merged"] = split_merged
        guidance = (
            "failed to update table cell; check indexes, enable logical addressing, "
            "or split merged cells first"
        )
        updated = 0
        for row_offset, row_values in enumerate(values):
            for col_offset, cell_text in enumerate(row_values):
                logical_row = start_row + row_offset
                logical_col = start_col + col_offset
                try:
                    table.set_cell_text(
                        logical_row,
                        logical_col,
                        _sanitize_cell_text(cell_text),
                        **kwargs,
                    )
                except (IndexError, ValueError) as exc:
                    message = (
                        f"{guidance} while writing cell ({logical_row}, {logical_col})"
                    )
                    raise self._context._new_error(
                        "TABLE_CELL_OPERATION_FAILED",
                        f"{message}: {exc}",
                        details={"row": logical_row, "col": logical_col},
                    ) from exc
                updated += 1
        if auto_fit and not dry_run and updated > 0:
            self._auto_fit_table_columns(table)
        if not dry_run:
            self._save._save_document(document, resolved)
        return {"updatedCells": updated}

    def split_table_cell(
        self,
        path: str,
        table_index: int,
        row: int,
        col: int,
    ) -> Dict[str, Any]:
        document, resolved = self._context._open_document(path)
        tables = self._context._iter_tables(document)
        try:
            table = tables[table_index]
        except IndexError as exc:
            raise self._context._new_error(
                "TABLE_INDEX_OUT_OF_RANGE",
                "tableIndex out of range",
                details={"tableIndex": table_index},
            ) from exc
        try:
            target = table.cell(row, col)
        except (IndexError, ValueError) as exc:
            raise self._context._new_error(
                "TABLE_CELL_INDEX_OUT_OF_RANGE",
                "table cell coordinates out of range; enable logical addressing to verify merged grids",
                details={"row": row, "col": col},
            ) from exc
        anchor_row, anchor_col = target.address
        span_row, span_col = target.span
        changed = span_row > 1 or span_col > 1
        guidance = "failed to split merged cell; check indexes or split manually if logical addressing shows overlaps"
        try:
            table.split_merged_cell(row, col)
        except (IndexError, ValueError) as exc:
            raise self._context._new_error(
                "TABLE_CELL_OPERATION_FAILED", f"{guidance}: {exc}"
            ) from exc
        if changed:
            self._save._save_document(document, resolved)
        return {
            "startRow": anchor_row,
            "startCol": anchor_col,
            "rowSpan": span_row,
            "colSpan": span_col,
        }

    def copy_table_between_documents(
        self,
        source_path: str,
        source_table_index: int,
        target_path: str,
        *,
        target_section_index: Optional[int] = None,
        auto_fit: bool = False,
    ) -> Dict[str, Any]:
        source_map = self.get_table_cell_map(source_path, source_table_index)
        row_count = int(source_map["rowCount"])
        column_count = int(source_map["columnCount"])
        if row_count <= 0 or column_count <= 0:
            raise self._context._new_error(
                "TABLE_EMPTY",
                "복사할 표 셀이 비어 있습니다.",
                details={"tableIndex": source_table_index},
            )

        values: List[List[str]] = []
        for row in source_map["grid"]:
            row_values: List[str] = []
            for cell in row:
                row_values.append((cell.get("text") or "").strip())
            values.append(row_values)

        created = self.add_table(
            target_path,
            rows=row_count,
            cols=column_count,
            section_index=target_section_index,
            auto_fit=auto_fit,
        )
        target_table_index = int(created["tableIndex"])
        updated = self.replace_table_region(
            target_path,
            table_index=target_table_index,
            start_row=0,
            start_col=0,
            values=values,
            auto_fit=auto_fit,
        )
        return {
            "targetTableIndex": target_table_index,
            "copiedCells": updated["updatedCells"],
            "rowCount": row_count,
            "columnCount": column_count,
        }
