# SPDX-License-Identifier: Apache-2.0

""":mod:`python-hwpx` 위에 구축한 고수준 연산 호환 facade."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Collection, Dict, List, Optional, Sequence, Tuple, cast

from .core.plan import PlanManager
from .core.locator import RegisteredHandle
from .storage import DocumentStorage, LocalDocumentStorage
from .workspace import WorkspaceMissingParentGuard, WorkspaceOutputGuard
from .upstream import HH_NS as HH_NS
from .upstream import HP_NS as HP_NS
from .upstream import (
    HwpxDocument,
    HwpxOxmlMemo,
    HwpxOxmlParagraph,
    HwpxOxmlTable,
)
from .errors import build_error_payload
from .ops_services.composition import HwpxOpsServices, build_hwpx_ops_services
from .ops_services.context import DocumentContext
from .ops_services.save_policy import (
    SavePolicy,
    _ExactBackupResult,
    _ExactRecoveryPublication,
    _ExactSidecarMutation,
)
from .ops_services.tables import DEFAULT_PAGING_PARAGRAPH_LIMIT

logger = logging.getLogger(__name__)


class HwpxOperationError(RuntimeError):
    """문서 단위 작업이 실패했을 때 사용하는 예외."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "OPERATION_FAILED",
        details: Optional[Dict[str, Any]] = None,
        hint: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.hint = hint

    def to_payload(self) -> Dict[str, Any]:
        return build_error_payload(
            code=self.code,
            message=self.message,
            details=self.details,
            hint=self.hint,
        )


class HwpxHandleNotFoundError(HwpxOperationError):
    """등록되지 않은 핸들 조회 시 사용하는 예외."""


#: HwpxOps methods 8.0 removed, each with where to go instead (python-hwpx 7.0 refuses to save
#: what they made: a memo on no paragraph, a bare shape or control element).
_REMOVED_IN_8: Dict[str, str] = {
    "add_memo": (
        "python-hwpx 7.0 keeps a memo only in a paragraph's MEMO field and refuses to save one on no "
        "paragraph. Use add_memo_with_anchor(path, text=...)."
    ),
    "attach_memo_field": (
        "a memo is made on its paragraph now. Use add_memo_with_anchor(path, text=...)."
    ),
    "add_shape": (
        "it appended a bare shape element python-hwpx 7.0 refuses to save. Use doc.shapes.add_rectangle, "
        "add_ellipse, add_line, add_polygon, add_container ... of python-hwpx."
    ),
    "add_control": (
        "it appended an empty hp:ctrl python-hwpx 7.0 refuses to save. Use the typed doc.shapes.add_* "
        "calls of python-hwpx."
    ),
}


class HwpxOps:
    """MCP 도구에서 활용하는 안전한 고수준 헬퍼 모음."""

    def __init__(
        self,
        *,
        base_directory: Path | None = None,
        paging_paragraph_limit: int = DEFAULT_PAGING_PARAGRAPH_LIMIT,
        auto_backup: bool = False,
        storage: DocumentStorage | None = None,
    ) -> None:
        if storage is not None and (base_directory is not None or auto_backup):
            logger.debug(
                "Ignoring base_directory/auto_backup parameters because explicit storage was provided",
                extra={
                    "base_directory": str(base_directory) if base_directory else None
                },
            )

        if storage is None:
            storage = LocalDocumentStorage(
                base_directory=base_directory,
                auto_backup=auto_backup,
                logger=logger,
            )

        context = DocumentContext(
            storage=storage,
            paging_paragraph_limit=paging_paragraph_limit,
            error_type=HwpxOperationError,
            handle_error_type=HwpxHandleNotFoundError,
        )
        self._services: HwpxOpsServices = build_hwpx_ops_services(context)
        self.storage = storage
        self.base_directory = storage.base_directory
        self.paging_limit = context.paging_limit
        self._plan_manager = self._services.planning.plan_manager
        self._registered_handles = context.registered_handles

    if not TYPE_CHECKING:  # runtime only: type checkers keep flagging unknown names

        def __getattr__(self, name: str) -> Any:
            hint = _REMOVED_IN_8.get(name)
            if hint is None:
                raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")
            raise AttributeError(f"HwpxOps.{name} was removed in python-hwpx-automation 8.0: {hint}")

    @property
    def plan_manager(self) -> PlanManager:
        return self._services.planning.plan_manager

    def _new_error(
        self,
        code: str,
        message: str,
        *,
        details: Optional[Dict[str, Any]] = None,
        hint: Optional[str] = None,
    ) -> HwpxOperationError:
        return cast(HwpxOperationError, self._services.context._new_error(
            code, message, details=details, hint=hint
        ))

    def _resolve_path(self, path: str, *, must_exist: bool = True) -> Path:
        return self._services.context._resolve_path(path, must_exist=must_exist)

    def _make_handle_id(self, path: str, backend: Optional[str] = None) -> str:
        return self._services.context._make_handle_id(path, backend)

    def _register_handle(self, path: str, resolved: Path) -> RegisteredHandle:
        return self._services.context._register_handle(path, resolved)

    def list_registered_handles(self) -> List[RegisteredHandle]:
        return self._services.context.list_registered_handles()

    def open_document_handle(self, path: str) -> Dict[str, Any]:
        return self._services.context.open_document_handle(path)

    def list_open_documents(self) -> Dict[str, Any]:
        return self._services.context.list_open_documents()

    def close_document_handle(self, handle_id: str) -> Dict[str, Any]:
        return self._services.context.close_document_handle(handle_id)

    def get_registered_handle(self, handle_id: str) -> RegisteredHandle:
        return self._services.context.get_registered_handle(handle_id)

    def resolve_document_path(
        self,
        *,
        path: Optional[str] = None,
        handle_id: Optional[str] = None,
    ) -> str:
        return self._services.context.resolve_document_path(
            path=path, handle_id=handle_id
        )

    def get_metadata_by_handle(self, handle_id: str) -> Dict[str, Any]:
        return self._services.read_query.get_metadata_by_handle(handle_id)

    def get_paragraphs_by_handle(self, handle_id: str) -> Dict[str, Any]:
        return self._services.read_query.get_paragraphs_by_handle(handle_id)

    def get_tables_by_handle(self, handle_id: str) -> Dict[str, Any]:
        return self._services.read_query.get_tables_by_handle(handle_id)

    def _resolve_output_path(self, path: str) -> Path:
        return self._services.context._resolve_output_path(path)

    def _ensure_backup(self, path: Path) -> Optional[Path]:
        return self._services.save._ensure_backup(path)

    def _relative_path(self, path: Path) -> str:
        return self._services.context._relative_path(path)

    def _maybe_backup(self, path: Path) -> None:
        return self._services.save._maybe_backup(path)

    def _open_document(self, path: str) -> Tuple[HwpxDocument, Path]:
        return self._services.context._open_document(path)

    def _read_only_hwp_paragraphs(self, path: str) -> Tuple[List[str], Path, str]:
        return self._services.context._read_only_hwp_paragraphs(path)

    def _ensure_planner_document(self, doc_id: str, path: str) -> None:
        return self._services.planning._ensure_planner_document(doc_id, path)

    def _save_document(
        self, document: HwpxDocument, target: Path, *, quality: Any = None
    ) -> Dict[str, Any]:
        return self._services.save._save_document(document, target, quality=quality)

    def _save_transaction_document(
        self, document: HwpxDocument, target: Path, *, quality: Any = None
    ) -> Dict[str, Any]:
        return self._services.save._save_transaction_document(
            document, target, quality=quality
        )

    @staticmethod
    def _report_for_bytes(data: bytes, *, file_path: Path) -> Dict[str, Any]:
        return SavePolicy._report_for_bytes(data, file_path=file_path)

    @staticmethod
    def _semantic_diff_bytes(before: bytes, after: bytes) -> Dict[str, Any]:
        return SavePolicy._semantic_diff_bytes(before, after)

    def _capture_exact_sidecar_guard(self, path: Path) -> WorkspaceOutputGuard:
        """Authorize one derived sidecar name without following a final alias."""
        return self._services.save._capture_exact_sidecar_guard(path)

    @staticmethod
    def _absent_publication_guard(
        guard: WorkspaceOutputGuard,
    ) -> WorkspaceOutputGuard:
        """Represent the exact absent state produced by a guarded deletion."""
        return SavePolicy._absent_publication_guard(guard)

    def _assert_exact_sidecar_publication(
        self,
        guard: WorkspaceOutputGuard,
    ) -> None:
        """Revalidate either an exact file publication or guarded absence."""
        return self._services.save._assert_exact_sidecar_publication(guard)

    def _publish_exact_recovery(
        self,
        base_path: Path,
        data: bytes,
        *,
        mode: int | None,
        marker: str,
        max_candidates: int = 32,
    ) -> _ExactRecoveryPublication:
        """Publish recovery bytes without overwriting an existing sidecar."""
        return self._services.save._publish_exact_recovery(
            base_path, data, mode=mode, marker=marker, max_candidates=max_candidates
        )

    def _preserve_exact_preimages(
        self,
        preimages: Sequence[tuple[Path, bytes, int | None]],
        *,
        marker: str,
    ) -> tuple[_ExactRecoveryPublication, ...] | None:
        """Preserve every preimage before any destructive mutation begins."""
        return self._services.save._preserve_exact_preimages(preimages, marker=marker)

    def _cleanup_exact_recoveries(
        self,
        recoveries: Sequence[_ExactRecoveryPublication],
    ) -> tuple[bool, bool]:
        """Remove proven recoveries, republishing all if any cleanup loses CAS."""
        return self._services.save._cleanup_exact_recoveries(recoveries)

    def _republish_exact_recoveries(
        self,
        recoveries: Sequence[_ExactRecoveryPublication],
    ) -> bool:
        """Recreate immutable recovery copies after cleanup or claim loss."""
        return self._services.save._republish_exact_recoveries(recoveries)

    def _rotate_and_backup_exact(
        self,
        target: Path,
        *,
        target_guard: WorkspaceOutputGuard | None = None,
        target_bytes: bytes | None = None,
        max_backups: int = 5,
    ) -> _ExactBackupResult:
        """Rotate local sidecars from no-follow guards and an exact preimage."""
        return self._services.save._rotate_and_backup_exact(
            target,
            target_guard=target_guard,
            target_bytes=target_bytes,
            max_backups=max_backups,
        )

    def _rollback_exact_backup_mutations(
        self,
        mutations: Sequence[_ExactSidecarMutation],
        *,
        preimages_preserved: bool = False,
    ) -> None:
        """Restore every sidecar candidate that is still exactly ours."""
        return self._services.save._rollback_exact_backup_mutations(
            mutations, preimages_preserved=preimages_preserved
        )

    def _decode_image_base64(self, image_base64: str) -> bytes:
        return self._services.media._decode_image_base64(image_base64)

    def _id_integrity_payload(self, document: HwpxDocument) -> Dict[str, Any]:
        return self._services.media._id_integrity_payload(document)

    def _with_transaction_verification(
        self,
        result: Dict[str, Any],
        document: HwpxDocument,
        target: Path,
        *,
        dry_run: bool,
        quality: Any = None,
    ) -> Dict[str, Any]:
        return self._services.transactions._with_transaction_verification(
            result, document, target, dry_run=dry_run, quality=quality
        )

    def _operation_value(
        self, operation: Dict[str, Any], *names: str, default: Any = None
    ) -> Any:
        return self._services.transactions._operation_value(
            operation, *names, default=default
        )

    def _apply_transaction_operation(
        self,
        document: HwpxDocument,
        operation: Dict[str, Any],
        index: int,
    ) -> Dict[str, Any]:
        return self._services.transactions._apply_transaction_operation(
            document, operation, index
        )

    def apply_edits(
        self,
        path: str,
        operations: Sequence[Dict[str, Any]],
        *,
        dry_run: bool = False,
        quality: Any = None,
    ) -> Dict[str, Any]:
        return self._services.transactions.apply_edits(
            path, operations, dry_run=dry_run, quality=quality
        )

    def undo_last_edit(self, path: str) -> Dict[str, Any]:
        return self._services.transactions.undo_last_edit(path)

    def _iter_paragraphs(self, document: HwpxDocument) -> List[HwpxOxmlParagraph]:
        return self._services.context._iter_paragraphs(document)

    def _iter_tables(self, document: HwpxDocument) -> List[HwpxOxmlTable]:
        return self._services.context._iter_tables(document)

    def _auto_fit_table_columns(self, table: HwpxOxmlTable) -> List[int]:
        return self._services.tables._auto_fit_table_columns(table)

    def _normalize_color(self, color: str | None) -> Optional[str]:
        return self._services.memo_style._normalize_color(color)

    def _ensure_char_style(
        self,
        document: HwpxDocument,
        run_style: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        return self._services.memo_style._ensure_char_style(document, run_style)

    def _ensure_table_border_fill(
        self,
        document: HwpxDocument,
        *,
        border_style: Optional[str] = None,
        border_color: Optional[str] = None,
        border_width: Optional[str | float | int] = None,
        fill_color: Optional[str] = None,
    ) -> str:
        return self._services.tables._ensure_table_border_fill(
            document,
            border_style=border_style,
            border_color=border_color,
            border_width=border_width,
            fill_color=fill_color,
        )

    def open_info(self, path: str) -> Dict[str, Any]:
        return self._services.read_query.open_info(path)

    def list_sections(self, path: str) -> Dict[str, Any]:
        return self._services.read_query.list_sections(path)

    def list_headers(self, path: str) -> Dict[str, Any]:
        return self._services.read_query.list_headers(path)

    def package_parts(self, path: str) -> Dict[str, Any]:
        return self._services.package_validation.package_parts(path)

    def package_get_text(
        self, path: str, part_name: str, encoding: str | None = None
    ) -> Dict[str, Any]:
        return self._services.package_validation.package_get_text(
            path, part_name, encoding
        )

    def repair_hwpx(
        self,
        source: str,
        output: str,
        *,
        recover: bool = False,
        overwrite: bool = False,
        max_entry_size: int = 64 * 1024 * 1024,
        max_total_size: int = 512 * 1024 * 1024,
        max_source_size: int = 512 * 1024 * 1024,
    ) -> Dict[str, Any]:
        return self._services.package_validation.repair_hwpx(
            source,
            output,
            recover=recover,
            overwrite=overwrite,
            max_entry_size=max_entry_size,
            max_total_size=max_total_size,
            max_source_size=max_source_size,
        )

    def read_text(
        self,
        path: str,
        *,
        offset: int = 0,
        limit: Optional[int] = None,
        with_highlights: bool = False,
        with_footnotes: bool = False,
    ) -> Dict[str, Any]:
        return self._services.read_query.read_text(
            path,
            offset=offset,
            limit=limit,
            with_highlights=with_highlights,
            with_footnotes=with_footnotes,
        )

    def get_paragraphs(
        self,
        path: str,
        paragraph_indexes: Sequence[int],
        *,
        with_highlights: bool = False,
        with_footnotes: bool = False,
    ) -> Dict[str, Any]:
        return self._services.read_query.get_paragraphs(
            path,
            paragraph_indexes,
            with_highlights=with_highlights,
            with_footnotes=with_footnotes,
        )

    def text_extract_report(self, path: str, mode: str = "plain") -> Dict[str, Any]:
        return self._services.read_query.text_extract_report(path, mode)

    def analyze_template_structure(
        self,
        path: str,
        *,
        placeholder_patterns: Optional[Sequence[str]] = None,
        lock_keywords: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        return self._services.read_query.analyze_template_structure(
            path, placeholder_patterns=placeholder_patterns, lock_keywords=lock_keywords
        )

    def find(
        self,
        path: str,
        query: str,
        *,
        is_regex: bool = False,
        max_results: int = 100,
        context_radius: int = 80,
    ) -> Dict[str, Any]:
        return self._services.read_query.find(
            path,
            query,
            is_regex=is_regex,
            max_results=max_results,
            context_radius=context_radius,
        )

    def find_runs_by_style(
        self,
        path: str,
        *,
        filters: Optional[Dict[str, Any]] = None,
        max_results: int = 200,
    ) -> Dict[str, Any]:
        return self._services.memo_style.find_runs_by_style(
            path, filters=filters, max_results=max_results
        )

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
        return self._services.content_layout.replace_text_in_runs(
            path,
            search,
            replacement,
            style_filter=style_filter,
            limit_per_run=limit_per_run,
            dry_run=dry_run,
        )

    def add_paragraph(
        self,
        path: str,
        text: str = "",
        *,
        section_index: Optional[int] = None,
        run_style: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self._services.content_layout.add_paragraph(
            path, text, section_index=section_index, run_style=run_style
        )

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
        return self._services.content_layout.add_chart(
            path,
            chart_type=chart_type,
            categories=categories,
            series=series,
            title=title,
            paragraph_index=paragraph_index,
            table_index=table_index,
            row=row,
            col=col,
            treat_as_char=treat_as_char,
            dry_run=dry_run,
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
        return self._services.content_layout.add_equation(
            path,
            latex=latex,
            script=script,
            paragraph_index=paragraph_index,
            table_index=table_index,
            row=row,
            col=col,
            base_unit=base_unit,
            dry_run=dry_run,
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
        return self._services.content_layout.insert_paragraphs_bulk(
            path,
            paragraphs,
            section_index=section_index,
            run_style=run_style,
            dry_run=dry_run,
        )

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
        return self._services.content_layout.set_paragraph_format(
            path,
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
            dry_run=dry_run,
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
        return self._services.content_layout.set_page_setup(
            path,
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
            dry_run=dry_run,
        )

    def _header_footer_payload(
        self,
        wrapper: Any,
        *,
        kind: str,
        page_type: str,
    ) -> Dict[str, Any]:
        return self._services.content_layout._header_footer_payload(
            wrapper, kind=kind, page_type=page_type
        )

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
        return self._services.content_layout.set_header_footer(
            path,
            kind=kind,
            text=text,
            content=content,
            section_index=section_index,
            page_type=page_type,
            dry_run=dry_run,
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
        return self._services.content_layout.set_page_number(
            path,
            target=target,
            page_type=page_type,
            format=format,
            align=align,
            position=position,
            prefix=prefix,
            suffix=suffix,
            format_type=format_type,
            section_index=section_index,
            dry_run=dry_run,
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
        return self._services.content_layout.set_list_format(
            path,
            paragraph_index=paragraph_index,
            paragraph_indexes=paragraph_indexes,
            kind=kind,
            level=level,
            bullet_char=bullet_char,
            number_format=number_format,
            start=start,
            dry_run=dry_run,
        )

    def list_form_fields(
        self,
        path: str,
    ) -> Dict[str, Any]:
        return self._services.form_fields.list_form_fields(path)

    def add_form_field(
        self,
        path: str,
        *,
        name: str,
        prompt: str = "",
        memo: str = "",
        paragraph_index: Optional[int] = None,
        table_index: Optional[int] = None,
        row: Optional[int] = None,
        col: Optional[int] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        return self._services.form_fields.add_form_field(
            path,
            name=name,
            prompt=prompt,
            memo=memo,
            paragraph_index=paragraph_index,
            table_index=table_index,
            row=row,
            col=col,
            dry_run=dry_run,
        )

    def fill_form_field(
        self,
        path: str,
        *,
        value: str,
        field_index: Optional[int] = None,
        field_id: Optional[str] = None,
        name: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        return self._services.form_fields.fill_form_field(
            path,
            value=value,
            field_index=field_index,
            field_id=field_id,
            name=name,
            dry_run=dry_run,
        )

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
        return self._services.tables.add_table(
            path,
            rows,
            cols,
            section_index=section_index,
            border_style=border_style,
            border_color=border_color,
            border_width=border_width,
            fill_color=fill_color,
            auto_fit=auto_fit,
        )

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
        return self._services.tables.set_table_border_fill(
            path,
            table_index,
            border_style=border_style,
            border_color=border_color,
            border_width=border_width,
            fill_color=fill_color,
        )

    def get_table_cell_map(
        self,
        path: str,
        table_index: int,
    ) -> Dict[str, Any]:
        return self._services.tables.get_table_cell_map(path, table_index)

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
        return self._services.tables.set_table_cell_text(
            path,
            table_index,
            row,
            col,
            text,
            dry_run=dry_run,
            logical=logical,
            split_merged=split_merged,
            auto_fit=auto_fit,
        )

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
        return self._services.tables.replace_table_region(
            path,
            table_index,
            start_row,
            start_col,
            values,
            dry_run=dry_run,
            logical=logical,
            split_merged=split_merged,
            auto_fit=auto_fit,
        )

    def byte_preserving_patch(
        self,
        path: str,
        patches: Sequence[Dict[str, Any]],
        *,
        output: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._services.transactions.byte_preserving_patch(
            path, patches, output=output
        )

    def _write_patched(
        self,
        target_path,
        data: bytes,
        payload: Dict[str, Any],
        *,
        output_guard: (
            WorkspaceOutputGuard | WorkspaceMissingParentGuard | None
        ) = None,
        output_precondition: (
            WorkspaceOutputGuard | WorkspaceMissingParentGuard | None
        ) = None,
        publication_sink: Callable[[WorkspaceOutputGuard], None] | None = None,
    ) -> Dict[str, Any]:
        """Atomic temp-write + open-safety gate for a byte-preserving result
        (shared by byte_preserving_patch / apply_table_ops)."""
        return self._services.save._write_patched(
            target_path,
            data,
            payload,
            output_guard=output_guard,
            output_precondition=output_precondition,
            publication_sink=publication_sink,
        )

    def run_edit_plan(
        self,
        plan: Dict[str, Any],
        *,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        return self._services.form_fields.run_edit_plan(plan, dry_run=dry_run)

    def apply_table_ops(
        self,
        path: str,
        ops: Sequence[Dict[str, Any]],
        *,
        output: Optional[str] = None,
        render_check: str = "off",
        dry_run: bool = False,
        output_guard: (
            WorkspaceOutputGuard | WorkspaceMissingParentGuard | None
        ) = None,
        publication_sink: Callable[[WorkspaceOutputGuard], None] | None = None,
    ) -> Dict[str, Any]:
        """Byte-preserving structural form-fill: apply cell fills + table structure
        ops (delete_column/row/table, insert_row_by_clone, insert_block_by_clone)
        preserving every untouched byte. Cells/tables may be addressed by
        tableAnchor/cellAnchor (unique-or-skip) as well as index. Optional
        real-Hancom render gate.

        dryRun=true: identical pipeline (resolution/validation/fail-closed all
        real) but writes NOTHING — returns transcript (per-op resolution + before/
        after dims) and applied old→new texts as approval evidence for the user
        consult loop. renderCheck still works on the would-be bytes."""
        return self._services.form_fields.apply_table_ops(
            path,
            ops,
            output=output,
            render_check=render_check,
            dry_run=dry_run,
            output_guard=output_guard,
            publication_sink=publication_sink,
        )

    def verify_form_fill(
        self,
        path: str,
        before_path: str,
        *,
        require: bool = False,
    ) -> Dict[str, Any]:
        """Render before/after in REAL Hancom and judge overflow/overlap/layout.
        Honest degrade (renderChecked=false) with no oracle unless require=true."""
        return self._services.form_fields.verify_form_fill(
            path, before_path, require=require
        )

    def score_form_fill(
        self,
        path: str,
        gold_path: str,
        blank_path: str,
        *,
        run_render: bool = True,
        expected_pages: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Score a filled evaluation-plan form against a gold reference on 5 axes
        (A render cleanliness / B byte fidelity vs blank / C structure vs gold /
        D content completeness / E compliance) -> weighted 0-100 + per-axis gap
        report. The fitness function of the form-fill quality loop.

        ``path`` = produced fill, ``goldPath`` = accepted reference of the same
        form family, ``blankPath`` = the empty province form. A requires a real
        Hancom render (renderCheck); with no oracle A is ``unverified`` (never a
        silent pass). Set runRender=false for a fast structural-only pass."""
        return self._services.form_fields.score_form_fill(
            path,
            gold_path,
            blank_path,
            run_render=run_render,
            expected_pages=expected_pages,
        )

    def apply_body_ops(
        self,
        path: str,
        ops: Sequence[Dict[str, Any]],
        *,
        output: Optional[str] = None,
        dry_run: bool = False,
        output_guard: (
            WorkspaceOutputGuard | WorkspaceMissingParentGuard | None
        ) = None,
        publication_sink: Callable[[WorkspaceOutputGuard], None] | None = None,
    ) -> Dict[str, Any]:
        """Byte-preserving BODY(표 밖 직속 문단) ops — Stage 2 결정표의 본문 어휘.

        ops: replace_text{find,replace,count=1: <hp:t> 텍스트 안에서만, 개수 불일치
        refuse} · delete_paragraph{index: 표 품은 문단 refuse} ·
        insert_paragraph_by_clone{ref_index,count,texts?: 참조 문단 서식 verbatim
        상속} · reorder_paragraphs{start,end,order}. index는 op 실행 시점 기준.
        dryRun=true면 아무것도 쓰지 않고 transcript만(승인 근거)."""
        return self._services.form_fields.apply_body_ops(
            path,
            ops,
            output=output,
            dry_run=dry_run,
            output_guard=output_guard,
            publication_sink=publication_sink,
        )

    def inspect_fill_residue(
        self,
        path: str,
        *,
        blank_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """채움본 잔존물 zero-체크(비변형) — 제출 전 기계 게이트(Stage 3).

        blank를 주면 범례 기반 신호까지: 삭제색 잔존·미수정 샘플(수정색이 blank와
        동일=prose 샘플 미교체) = ERROR. placeholder ◯◯◯/□□□=ERROR, **=각주와
        중의적이라 needs_review, 고아 마커=needs_review. ok=true는 필요조건일 뿐 —
        제출 확언은 렌더 PDF를 사람이 전 페이지 본 뒤에만."""
        return self._services.form_fields.inspect_fill_residue(
            path, blank_path=blank_path
        )

    def scan_form_guidance(self, path: str, *, max_items: int = 60) -> Dict[str, Any]:
        """Recon an unfamiliar form (NON-MUTATING) — universal form-fill Stage 1.

        Walks every run INCLUDING table-cell interiors and table captions, parses
        the form's own colour legend (e.g. "검정 유지/파랑 수정/빨강 삭제"), and
        reports candidates with table_patch-compatible addresses: delete candidates
        (legend-delete colour + guidance keywords), modify targets, placeholder
        tokens (◯◯◯/**/□□□), conditional-choice blocks, empty cells with neighbour
        label + charPr format context, and an honest question list. Candidates are
        proposals — destructive ops still require user approval."""
        return self._services.form_fields.scan_form_guidance(path, max_items=max_items)

    def apply_evalplan_fill(
        self,
        path: str,
        review_md: str,
        *,
        phase: str = "all",
        output: Optional[str] = None,
        render_check: str = "off",
        score_gold_path: Optional[str] = None,
        expected_pages: Optional[int] = None,
        output_guard: (
            WorkspaceOutputGuard | WorkspaceMissingParentGuard | None
        ) = None,
        publication_sink: Callable[[WorkspaceOutputGuard], None] | None = None,
    ) -> Dict[str, Any]:
        """Whole-form 평가계획 fill: {blank province form + review markdown} ->
        byte-preserving gold-quality 채움본 in ONE call. Runs the structure-driven
        recipe (delete red/optional tables + 정기시험 column, fill 운영계획/성취기준/
        성취수준/성취율/반영비율/rubrics incl. 채점기준 ladder/prose sections),
        preserving the blank's formatting (never regenerates). Works on BOTH the
        2015-개정 and 2022-개정 form families (auto-detected from the blank + review).

        ``path`` = blank form, ``reviewMd`` = the structured review markdown
        (Ⅰ 운영계획 + [1]~[11]). ``phase`` = ``"structural"`` | ``"all"`` (default) |
        ``"clean"``; ``"clean"`` additionally runs core's deterministic post-fill
        cleanup so a submittable 채움본 comes back in one call (report under
        ``contentReport.finalize``). Returns the produced path + per-region
        contentReport with rubricNeedsReview (honest-defer count, never silent). Set
        renderCheck='required' to gate on a real Hancom render; pass scoreGoldPath
        (an accepted form of the same family) to also return the 5-axis scorecard."""
        return self._services.form_fields.apply_evalplan_fill(
            path,
            review_md,
            phase=phase,
            output=output,
            render_check=render_check,
            score_gold_path=score_gold_path,
            expected_pages=expected_pages,
            output_guard=output_guard,
            publication_sink=publication_sink,
        )

    def split_table_cell(
        self,
        path: str,
        table_index: int,
        row: int,
        col: int,
    ) -> Dict[str, Any]:
        return self._services.tables.split_table_cell(path, table_index, row, col)

    def copy_table_between_documents(
        self,
        source_path: str,
        source_table_index: int,
        target_path: str,
        *,
        target_section_index: Optional[int] = None,
        auto_fit: bool = False,
    ) -> Dict[str, Any]:
        return self._services.tables.copy_table_between_documents(
            source_path,
            source_table_index,
            target_path,
            target_section_index=target_section_index,
            auto_fit=auto_fit,
        )

    def insert_picture(
        self,
        path: str,
        image_base64: str,
        *,
        image_format: str = "png",
        width: Optional[int] = None,
        height: Optional[int] = None,
        width_mm: Optional[float] = None,
        height_mm: Optional[float] = None,
        section_index: Optional[int] = None,
        align: Optional[str] = None,
        output: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        return self._services.media.insert_picture(
            path,
            image_base64,
            image_format=image_format,
            width=width,
            height=height,
            width_mm=width_mm,
            height_mm=height_mm,
            section_index=section_index,
            align=align,
            output=output,
            dry_run=dry_run,
        )

    def replace_picture(
        self,
        path: str,
        image_base64: str,
        *,
        image_format: str = "png",
        picture_index: int = 0,
        binary_item_id_ref: Optional[str] = None,
        remove_orphaned: bool = True,
        output: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        return self._services.media.replace_picture(
            path,
            image_base64,
            image_format=image_format,
            picture_index=picture_index,
            binary_item_id_ref=binary_item_id_ref,
            remove_orphaned=remove_orphaned,
            output=output,
            dry_run=dry_run,
        )

    def add_memo_with_anchor(
        self,
        path: str,
        *,
        text: str,
        section_index: Optional[int] = None,
    ) -> Dict[str, Any]:
        return self._services.memo_style.add_memo_with_anchor(
            path, text=text, section_index=section_index
        )

    def set_memo_shape(
        self,
        path: str,
        memo_shape_id_ref: str | int | None,
        *,
        section_index: Optional[int] = None,
    ) -> Dict[str, Any]:
        return self._services.memo_style.set_memo_shape(
            path, memo_shape_id_ref, section_index=section_index
        )

    def remove_memo(
        self,
        path: str,
        memo_id: str,
        *,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        return self._services.memo_style.remove_memo(path, memo_id, dry_run=dry_run)

    def _find_memo(
        self, document: HwpxDocument, memo_id: str
    ) -> Optional[HwpxOxmlMemo]:
        return self._services.memo_style._find_memo(document, memo_id)

    def ensure_run_style(self, path: str, **run_style: Any) -> Dict[str, Any]:
        return self._services.memo_style.ensure_run_style(path, **run_style)

    def list_styles_and_bullets(self, path: str) -> Dict[str, Any]:
        return self._services.memo_style.list_styles_and_bullets(path)

    def apply_style_to_text_ranges(
        self,
        path: str,
        spans: Sequence[Dict[str, int]],
        char_pr_id_ref: str,
        *,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        return self._services.memo_style.apply_style_to_text_ranges(
            path, spans, char_pr_id_ref, dry_run=dry_run
        )

    def apply_style_to_paragraphs(
        self,
        path: str,
        paragraph_indexes: Sequence[int],
        char_pr_id_ref: str,
        *,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        return self._services.memo_style.apply_style_to_paragraphs(
            path, paragraph_indexes, char_pr_id_ref, dry_run=dry_run
        )

    def save(self, path: str) -> Dict[str, Any]:
        return self._services.save.save(path)

    def save_as(self, path: str, out: str) -> Dict[str, Any]:
        return self._services.save.save_as(path, out)

    def fill_template(
        self,
        source: str,
        output: str,
        replacements: Dict[str, str],
        *,
        preserve_style: bool = True,
        split_newlines: bool = True,
    ) -> Dict[str, Any]:
        return self._services.save.fill_template(
            source,
            output,
            replacements,
            preserve_style=preserve_style,
            split_newlines=split_newlines,
        )

    def export_text(self, path: str) -> Dict[str, Any]:
        """Export document content as plain text."""
        return self._services.preview_export.export_text(path)

    def export_html(self, path: str) -> Dict[str, Any]:
        """Export document content as HTML."""
        return self._services.preview_export.export_html(path)

    def export_markdown(self, path: str) -> Dict[str, Any]:
        """Export document content as Markdown."""
        return self._services.preview_export.export_markdown(path)

    def _preview_output_dir(self, source_path: Path, output_dir: Optional[str]) -> Path:
        return self._services.preview_export._preview_output_dir(
            source_path, output_dir
        )

    def _embed_screenshot_image(
        self,
        item: dict[str, Any],
        png_path: Path,
        *,
        embed_images: bool,
        max_image_bytes: int | None,
    ) -> None:
        """Attach a base64 PNG payload to a screenshot item, bounded by a byte cap.

        Keeps the on-disk artifact regardless; only the inline payload is gated so
        an oversized page degrades to "path only" instead of bloating the response.
        """
        return self._services.preview_export._embed_screenshot_image(
            item, png_path, embed_images=embed_images, max_image_bytes=max_image_bytes
        )

    def _capture_preview_pages(
        self,
        *,
        page_html_paths: Sequence[Path],
        pages: Sequence[Dict[str, Any]],
        output_dir: Path,
        max_pages: int | None,
        embed_images: bool = False,
        max_image_bytes: int | None = None,
        flow_pages: Collection[int] = (),
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return self._services.preview_export._capture_preview_pages(
            page_html_paths=page_html_paths,
            pages=pages,
            flow_pages=set(flow_pages),
            output_dir=output_dir,
            max_pages=max_pages,
            embed_images=embed_images,
            max_image_bytes=max_image_bytes,
        )

    def render_preview(
        self,
        path: str,
        output_dir: Optional[str] = None,
        mode: str = "pages",
        screenshot: str = "auto",
        max_pages: Optional[int] = None,
        embed_images: bool = False,
        max_image_bytes: Optional[int] = None,
        viewer: bool = False,
    ) -> Dict[str, Any]:
        """Generate layout-aware HTML and optional PNG preview artifacts.

        When *embed_images* is true, each captured screenshot item also carries
        an ``imageBase64``/``imageMime`` payload (bounded by *max_image_bytes*,
        defaulting to ``_DEFAULT_MAX_PREVIEW_IMAGE_BYTES``) so a caller can return
        the page as an inline image content block.

        When *viewer* is true, the manifest also carries a self-contained
        scrollable document viewer under ``viewer`` (equations as native MathML
        with ``python-hwpx-automation[preview]``).
        """
        return self._services.preview_export.render_preview(
            path,
            output_dir,
            mode,
            screenshot,
            max_pages,
            embed_images,
            max_image_bytes,
            viewer,
        )

    def make_blank(self, out: str) -> Dict[str, Any]:
        return self._services.save.make_blank(out)

    def convert_hwp_to_hwpx(
        self, source: str, output: Optional[str] = None
    ) -> Dict[str, Any]:
        return self._services.preview_export.convert_hwp_to_hwpx(source, output)

    def list_master_pages_histories_versions(self, path: str) -> Dict[str, Any]:
        return self._services.package_validation.list_master_pages_histories_versions(
            path
        )

    def object_find_by_tag(
        self,
        path: str,
        tag_name: str,
        *,
        max_results: int = 200,
    ) -> Dict[str, Any]:
        return self._services.read_query.object_find_by_tag(
            path, tag_name, max_results=max_results
        )

    def object_find_by_attr(
        self,
        path: str,
        element_type: str | None,
        attr: str,
        value: str | None,
        *,
        max_results: int = 200,
    ) -> Dict[str, Any]:
        return self._services.read_query.object_find_by_attr(
            path, element_type, attr, value, max_results=max_results
        )

    def validate_structure(self, path: str, level: str = "basic") -> Dict[str, Any]:
        return self._services.package_validation.validate_structure(path, level)

    def lint_text_conventions(
        self,
        path: str,
        *,
        max_line_len: Optional[int] = None,
        forbid_patterns: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        return self._services.package_validation.lint_text_conventions(
            path, max_line_len=max_line_len, forbid_patterns=forbid_patterns
        )

    def plan_edit(
        self,
        *,
        path: str,
        operations: Sequence[Dict[str, Any]],
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._services.planning.plan_edit(
            path=path, operations=operations, trace_id=trace_id
        )

    def preview_edit(
        self,
        *,
        plan_id: str,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._services.planning.preview_edit(plan_id=plan_id, trace_id=trace_id)

    def apply_edit(
        self,
        *,
        plan_id: str,
        confirm: bool,
        idempotency_key: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._services.planning.apply_edit(
            plan_id=plan_id,
            confirm=confirm,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
        )

    def search(
        self,
        *,
        path: str,
        pattern: str,
        scope: Optional[str] = None,
        is_regex: bool = False,
        limit: int = 20,
    ) -> Dict[str, Any]:
        return self._services.planning.search(
            path=path, pattern=pattern, scope=scope, is_regex=is_regex, limit=limit
        )

    def get_context(
        self,
        *,
        path: str,
        target: Dict[str, Any],
        window: int = 1,
    ) -> Dict[str, Any]:
        return self._services.planning.get_context(
            path=path, target=target, window=window
        )

    def package_get_xml(self, path: str, part_name: str) -> Dict[str, Any]:
        return self._services.package_validation.package_get_xml(path, part_name)
