# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Sequence

from ..upstream import (
    HP_NS,
)

from .context import DocumentContext
from .save_policy import SavePolicy
from .transactions import TransactionService
from .memo_style import MemoStyleService

logger = logging.getLogger("hwpx_automation.hwpx_ops")


class ContentLayoutService:
    def __init__(
        self,
        context: DocumentContext,
        save: SavePolicy,
        transactions: TransactionService,
        styles: MemoStyleService,
    ) -> None:
        self._context = context
        self._save = save
        self._transactions = transactions
        self._styles = styles

    def replace_text_in_runs(
        self,
        path: str,
        search: str,
        replacement: str,
        *,
        style_filter: Optional[Dict[str, Any]] = None,
        limit_per_run: Optional[int] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        document, resolved = self._context._open_document(path)
        filter_args: Dict[str, Any] = {}
        if style_filter:
            if "colorHex" in style_filter and style_filter["colorHex"]:
                filter_args["text_color"] = self._styles._normalize_color(
                    style_filter["colorHex"]
                )
            if "underline" in style_filter:
                filter_args["underline_type"] = (
                    "BOTTOM" if style_filter["underline"] else "NONE"
                )
            if "charPrIDRef" in style_filter and style_filter["charPrIDRef"]:
                filter_args["char_pr_id_ref"] = style_filter["charPrIDRef"]
        replaced = document.text.replace(
            search,
            replacement,
            limit=limit_per_run,
            **filter_args,
        )
        if not dry_run and replaced:
            self._save._save_document(document, resolved)
        return {"replacedCount": replaced}

    def add_paragraph(
        self,
        path: str,
        text: str = "",
        *,
        section_index: Optional[int] = None,
        run_style: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        document, resolved = self._context._open_document(path)
        char_id = self._styles._ensure_char_style(document, run_style)
        paragraph = document.add_paragraph(
            text,
            section_index=section_index,
            char_pr_id_ref=char_id,
        )
        paragraphs = self._context._iter_paragraphs(document)
        index = len(paragraphs) - 1
        element_id = id(paragraph.element)
        for idx, candidate in enumerate(paragraphs):
            if id(candidate.element) == element_id:
                index = idx
                break
        self._save._save_document(document, resolved)
        return {"paragraphIndex": index}

    def _equation_script_from_input(
        self, latex: Optional[str], script: Optional[str]
    ) -> str:
        from hwpx.equation import (
            EquationConversionError,
            UnsupportedLatexError,
            latex_to_eqedit,
        )

        if (latex is None) == (script is None):
            raise self._context._new_error(
                "EQUATION_INPUT_INVALID",
                "provide exactly one of latex or script",
            )
        if latex is None:
            assert script is not None
            return script
        try:
            return latex_to_eqedit(latex)
        except UnsupportedLatexError as exc:
            raise self._context._new_error(
                "EQUATION_LATEX_UNSUPPORTED",
                f"LaTeX outside the render-verified token set: {exc}",
                details={"latex": latex},
            ) from exc
        except EquationConversionError as exc:
            raise self._context._new_error(
                "EQUATION_INPUT_INVALID",
                f"LaTeX input rejected: {exc}",
            ) from exc

    def _resolve_equation_target(
        self,
        document: Any,
        *,
        paragraph_index: Optional[int],
        table_index: Optional[int],
        row: Optional[int],
        col: Optional[int],
        target_error_code: str = "EQUATION_TARGET_INVALID",
    ) -> Any:
        cell_parts = (table_index, row, col)
        use_cell = any(part is not None for part in cell_parts)
        if use_cell and not all(part is not None for part in cell_parts):
            raise self._context._new_error(
                target_error_code,
                "provide tableIndex, row, and col together for a cell target",
            )
        if use_cell and paragraph_index is not None:
            raise self._context._new_error(
                target_error_code,
                "paragraphIndex cannot be combined with a cell target",
            )
        if use_cell:
            assert table_index is not None and row is not None and col is not None
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
                return table.cell(row, col).paragraphs[-1]
            except (IndexError, ValueError) as exc:
                raise self._context._new_error(
                    "TABLE_CELL_OPERATION_FAILED",
                    f"failed to resolve table cell for the equation: {exc}",
                ) from exc
        if paragraph_index is not None:
            try:
                return self._context._iter_paragraphs(document)[paragraph_index]
            except IndexError as exc:
                raise self._context._new_error(
                    "PARAGRAPH_INDEX_OUT_OF_RANGE",
                    "paragraphIndex out of range",
                    details={"paragraphIndex": paragraph_index},
                ) from exc
        return None

    def add_chart(
        self,
        path: str,
        *,
        chart_type: str,
        categories: list[str],
        series: list[dict],
        title: Optional[str] = None,
        paragraph_index: Optional[int] = None,
        table_index: Optional[int] = None,
        row: Optional[int] = None,
        col: Optional[int] = None,
        treat_as_char: bool = False,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        from ..office.charting import (
            ChartSeries,
            UnsupportedChartError,
            build_chart_ml,
        )

        try:
            parsed_series = [
                ChartSeries(
                    name=str(item.get("name", "")),
                    values=tuple(float(v) for v in item.get("values", ())),
                )
                for item in series
            ]
        except (TypeError, ValueError) as exc:
            raise self._context._new_error(
                "CHART_INPUT_INVALID",
                f"series values must be numbers: {exc}",
            ) from exc
        try:
            chart_ml = build_chart_ml(
                chart_type, categories, parsed_series, title=title
            )
        except UnsupportedChartError as exc:
            raise self._context._new_error(
                "CHART_UNSUPPORTED", str(exc)
            ) from exc

        document, resolved = self._context._open_document(path)
        paragraph = self._resolve_equation_target(
            document,
            paragraph_index=paragraph_index,
            table_index=table_index,
            row=row,
            col=col,
            target_error_code="CHART_TARGET_INVALID",
        )
        try:
            inline_object = document.shapes.add_chart(
                chart_ml, paragraph=paragraph, treat_as_char=treat_as_char
            )
        except ValueError as exc:
            raise self._context._new_error(
                "CHART_INPUT_INVALID", str(exc)
            ) from exc
        result = {
            "ok": True,
            "filename": path,
            "chart": {
                "chartType": chart_type,
                "chartIDRef": inline_object.element.get("chartIDRef"),
                "seriesCount": len(parsed_series),
                "categoryCount": len(categories),
            },
        }
        return self._transactions._with_transaction_verification(
            result, document, resolved, dry_run=dry_run
        )

    def add_equation(
        self,
        path: str,
        *,
        latex: Optional[str] = None,
        script: Optional[str] = None,
        paragraph_index: Optional[int] = None,
        table_index: Optional[int] = None,
        row: Optional[int] = None,
        col: Optional[int] = None,
        base_unit: int = 1100,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        from hwpx.equation import EquationConversionError, eqedit_to_latex

        script = self._equation_script_from_input(latex, script)
        document, resolved = self._context._open_document(path)
        paragraph = self._resolve_equation_target(
            document,
            paragraph_index=paragraph_index,
            table_index=table_index,
            row=row,
            col=col,
        )
        try:
            document.shapes.add_equation(script, paragraph=paragraph, base_unit=base_unit)
        except ValueError as exc:
            raise self._context._new_error(
                "EQUATION_INPUT_INVALID", str(exc)
            ) from exc
        try:
            reader_latex = eqedit_to_latex(script)
        except EquationConversionError:
            reader_latex = None
        result = {
            "ok": True,
            "filename": path,
            "equation": {
                "script": script,
                "readerLatex": reader_latex,
                "baseUnit": base_unit,
            },
        }
        return self._transactions._with_transaction_verification(
            result, document, resolved, dry_run=dry_run
        )

    def insert_paragraphs_bulk(
        self,
        path: str,
        paragraphs: Sequence[str],
        *,
        section_index: Optional[int] = None,
        run_style: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        if not paragraphs:
            return {"added": 0}

        if dry_run:
            return {"added": len(paragraphs)}

        document, resolved = self._context._open_document(path)
        char_id = self._styles._ensure_char_style(document, run_style)
        count = 0
        for text in paragraphs:
            document.add_paragraph(
                text,
                section_index=section_index,
                char_pr_id_ref=char_id,
            )
            count += 1
        self._save._save_document(document, resolved)
        return {"added": count}

    def set_paragraph_format(
        self,
        path: str,
        *,
        paragraph_index: Optional[int] = None,
        paragraph_indexes: Optional[Sequence[int]] = None,
        alignment: Optional[str] = None,
        line_spacing_percent: Optional[float] = None,
        indent_left_mm: Optional[float] = None,
        indent_right_mm: Optional[float] = None,
        first_line_indent_mm: Optional[float] = None,
        spacing_before_pt: Optional[float] = None,
        spacing_after_pt: Optional[float] = None,
        outline_level: Optional[int] = None,
        keep_with_next: Optional[bool] = None,
        keep_lines: Optional[bool] = None,
        page_break_before: Optional[bool] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        document, resolved = self._context._open_document(path)
        # apply_paragraph_format now returns a frozen ParagraphFormatResult
        # (design §2.4) rather than a dict — .to_dict() keeps this service's
        # own dict-shaped op envelope (ok/filename merged below) unchanged.
        result = document.styles.apply_paragraph_format(
            paragraph_index=paragraph_index,
            paragraph_indexes=paragraph_indexes,
            alignment=alignment,
            line_spacing_percent=line_spacing_percent,
            indent_left_mm=indent_left_mm,
            indent_right_mm=indent_right_mm,
            first_line_indent_mm=first_line_indent_mm,
            spacing_before_pt=spacing_before_pt,
            spacing_after_pt=spacing_after_pt,
            outline_level=outline_level,
            keep_with_next=keep_with_next,
            keep_lines=keep_lines,
            page_break_before=page_break_before,
        ).to_dict()
        result.update({"ok": True, "filename": path})
        return self._transactions._with_transaction_verification(
            result, document, resolved, dry_run=dry_run
        )

    def set_page_setup(
        self,
        path: str,
        *,
        paper_size: Optional[str] = None,
        width_mm: Optional[float] = None,
        height_mm: Optional[float] = None,
        orientation: Optional[str] = None,
        margins_mm: Optional[Dict[str, float]] = None,
        margin_left_mm: Optional[float] = None,
        margin_right_mm: Optional[float] = None,
        margin_top_mm: Optional[float] = None,
        margin_bottom_mm: Optional[float] = None,
        header_margin_mm: Optional[float] = None,
        footer_margin_mm: Optional[float] = None,
        gutter_mm: Optional[float] = None,
        columns: Optional[int] = None,
        column_gap_mm: Optional[float] = None,
        section_index: Optional[int] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        document, resolved = self._context._open_document(path)
        # page.setup now returns a frozen PageSetup (design §2.4) rather than
        # a dict — .to_dict() keeps this service's own dict-shaped op
        # envelope (ok/filename merged below) unchanged.
        result = document.page.setup(
            paper_size=paper_size,
            width_mm=width_mm,
            height_mm=height_mm,
            orientation=orientation,
            margins_mm=margins_mm,
            margin_left_mm=margin_left_mm,
            margin_right_mm=margin_right_mm,
            margin_top_mm=margin_top_mm,
            margin_bottom_mm=margin_bottom_mm,
            header_margin_mm=header_margin_mm,
            footer_margin_mm=footer_margin_mm,
            gutter_mm=gutter_mm,
            columns=columns,
            column_gap_mm=column_gap_mm,
            section_index=section_index,
        ).to_dict()
        result.update({"ok": True, "filename": path})
        return self._transactions._with_transaction_verification(
            result, document, resolved, dry_run=dry_run
        )

    def _header_footer_payload(
        self,
        wrapper: Any,
        *,
        kind: str,
        page_type: str,
    ) -> Dict[str, Any]:
        element = getattr(wrapper, "element", None)
        page_number_count = 0
        if element is not None and hasattr(element, "iter"):
            page_number_count = sum(1 for _ in element.iter(f"{HP_NS}pageNum"))
        return {
            "kind": kind,
            "pageType": page_type,
            "id": getattr(wrapper, "id", None),
            "text": getattr(wrapper, "text", ""),
            "pageNumberCount": page_number_count,
        }

    def set_header_footer(
        self,
        path: str,
        *,
        kind: str,
        text: Optional[str] = None,
        content: Optional[Sequence[Dict[str, Any]]] = None,
        section_index: Optional[int] = None,
        page_type: str = "BOTH",
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        document, resolved = self._context._open_document(path)
        # set_header_footer is demoted in 6.0 with no namespace replacement
        # (design table row 102, kind= dispatch removed) — dispatch here
        # instead, replicating the normalization the removed method used to do.
        normalized_kind = kind.strip().lower() if isinstance(kind, str) else kind
        if normalized_kind == "header":
            wrapper = document.page.set_header(
                text=text,
                content=content,
                section_index=section_index,
                page_type=page_type,
            )
        elif normalized_kind == "footer":
            wrapper = document.page.set_footer(
                text=text,
                content=content,
                section_index=section_index,
                page_type=page_type,
            )
        else:
            raise ValueError("kind must be 'header' or 'footer'")
        result = {
            "ok": True,
            "filename": path,
            "headerFooter": self._header_footer_payload(
                wrapper,
                kind=kind,
                page_type=page_type,
            ),
        }
        return self._transactions._with_transaction_verification(
            result, document, resolved, dry_run=dry_run
        )

    def set_page_number(
        self,
        path: str,
        *,
        target: str = "footer",
        page_type: str = "BOTH",
        format: str = "page",
        align: str = "CENTER",
        position: str = "BOTTOM_CENTER",
        prefix: str = "",
        suffix: str = "",
        format_type: Optional[str] = None,
        section_index: Optional[int] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        document, resolved = self._context._open_document(path)
        wrapper = document.page.set_page_number(
            target=target,
            page_type=page_type,
            format=format,
            align=align,
            position=position,
            prefix=prefix,
            suffix=suffix,
            format_type=format_type,
            section_index=section_index,
        )
        result = {
            "ok": True,
            "filename": path,
            "target": target,
            "format": format,
            "headerFooter": self._header_footer_payload(
                wrapper,
                kind=target,
                page_type=page_type,
            ),
        }
        return self._transactions._with_transaction_verification(
            result, document, resolved, dry_run=dry_run
        )

    def set_list_format(
        self,
        path: str,
        *,
        paragraph_index: Optional[int] = None,
        paragraph_indexes: Optional[Sequence[int]] = None,
        kind: str = "bullet",
        level: int = 1,
        bullet_char: Optional[str] = None,
        number_format: Optional[str] = None,
        start: Optional[int] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        document, resolved = self._context._open_document(path)
        # apply_list_format now returns a frozen ListFormatResult (design
        # §2.4) rather than a dict — .to_dict() keeps this service's own
        # dict-shaped op envelope (ok/filename merged below) unchanged.
        result = document.styles.apply_list_format(
            paragraph_index=paragraph_index,
            paragraph_indexes=paragraph_indexes,
            kind=kind,
            level=level,
            bullet_char=bullet_char,
            number_format=number_format,
            start=start,
        ).to_dict()
        result.update({"ok": True, "filename": path})
        return self._transactions._with_transaction_verification(
            result, document, resolved, dry_run=dry_run
        )
