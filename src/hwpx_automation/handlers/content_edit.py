# SPDX-License-Identifier: Apache-2.0
"""Content-edit automation handlers for the optional MCP adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import zlib

from .. import quality as quality_contract
from ..core.content import (
    add_heading_to_doc,
    add_page_break_to_doc,
    add_paragraph_to_doc,
    add_table_to_doc,
    delete_paragraph_from_doc,
    fill_by_path_in_doc,
    format_table_in_doc,
    insert_paragraph_to_doc,
    merge_cells_in_table,
    set_cell_text,
    split_cell_in_table,
)
from ..core.document import open_doc
from ..core.locations import location_from_anchor, resolve_paragraph_reference
from ..core.search import _replace_in_runs, batch_replace_in_doc, replace_in_doc
from ..mutation_models import (
    EditOperation,
    operation_payloads,
)
from ..office.utilities import table_compute as build_hwpx_table_compute
from ..runtime_services import RUNTIME_SERVICES
from ..upstream import (
    repair_pathological_text_spacing,
)
from ..utils.helpers import resolve_path
from ._shared import (
    _decode_image_base64,
    _id_integrity_payload,
    _idempotency_fingerprint,
    _idempotency_replay,
    _idempotency_scope,
    _idempotency_store,
    _normalize_fill_mappings,
    _revision_guard,
    _save_doc_verification,
    _with_document_state,
    _with_dry_run_verification,
    _with_save_verification,
)


def table_compute(
    table: dict | list,
    value_columns: list = None,
    operations: list = None,
    append: str = "rows",
    group_by: str | int = None,  # type: ignore[assignment]  # Frozen ToolSpec default.
    label_column: str | int = None,  # type: ignore[assignment]  # Frozen ToolSpec default.
    labels: dict = None,
) -> dict:
    """일반 표에 합계·평균·소계 행/열을 추가하고 계산 근거를 반환합니다."""
    if build_hwpx_table_compute is None:
        raise RuntimeError("installed python-hwpx does not provide table compute tools")
    return build_hwpx_table_compute(
        table,
        value_columns=value_columns,
        operations=operations,
        append=append,
        group_by=group_by,
        label_column=label_column,
        labels=labels,
    )


def _operation_value(
    operation: dict[str, Any], *names: str, default: Any = None
) -> Any:
    for name in names:
        if name in operation:
            return operation[name]
    return default


def _apply_edit_operation(
    doc: Any, operation: dict[str, Any], index: int
) -> dict[str, Any]:
    if not isinstance(operation, dict):
        raise TypeError(f"operation {index} must be an object")
    raw_type = _operation_value(operation, "type", "op", "operation")
    if not isinstance(raw_type, str) or not raw_type.strip():
        raise ValueError(f"operation {index} must include a type")
    op_type = raw_type.strip().replace("-", "_")

    if op_type == "replace_text":
        find = _operation_value(operation, "findText", "find_text", "find")
        replace = _operation_value(
            operation, "replaceText", "replace_text", "replace", default=""
        )
        if find is None:
            raise ValueError("replace_text requires findText")
        count = replace_in_doc(doc, find_text=str(find), replace_text=str(replace))
        return {"type": op_type, "replaced_count": count}

    if op_type == "batch_replace":
        replacements = _operation_value(operation, "replacements")
        if not isinstance(replacements, list):
            raise ValueError("batch_replace requires a replacements list")
        result = batch_replace_in_doc(doc, replacements)
        return {"type": op_type, **result}

    if op_type == "add_heading":
        text = _operation_value(operation, "text", default="")
        level = int(_operation_value(operation, "level", default=1))
        paragraph_index = add_heading_to_doc(doc, str(text), level)
        return {"type": op_type, "paragraph_index": paragraph_index}

    if op_type == "add_paragraph":
        text = _operation_value(operation, "text", default="")
        style = _operation_value(operation, "style")
        paragraph_index = add_paragraph_to_doc(doc, str(text), style)
        return {"type": op_type, "paragraph_index": paragraph_index}

    if op_type == "insert_paragraph":
        paragraph_index = _operation_value(
            operation, "paragraphIndex", "paragraph_index"
        )
        if paragraph_index is None:
            raise ValueError("insert_paragraph requires paragraphIndex")
        text = _operation_value(operation, "text", default="")
        style = _operation_value(operation, "style")
        inserted = insert_paragraph_to_doc(doc, int(paragraph_index), str(text), style)
        return {"type": op_type, "inserted_index": inserted}

    if op_type == "delete_paragraph":
        paragraph_index = _operation_value(
            operation, "paragraphIndex", "paragraph_index"
        )
        if paragraph_index is None:
            raise ValueError("delete_paragraph requires paragraphIndex")
        remaining = delete_paragraph_from_doc(doc, int(paragraph_index))
        return {
            "type": op_type,
            "deleted_index": int(paragraph_index),
            "remaining_paragraphs": remaining,
        }

    if op_type == "add_table":
        rows = _operation_value(operation, "rows")
        cols = _operation_value(operation, "cols", "columns")
        if rows is None or cols is None:
            raise ValueError("add_table requires rows and cols")
        data = _operation_value(operation, "data")
        table_index = add_table_to_doc(doc, int(rows), int(cols), data)
        return {"type": op_type, "table_index": table_index}

    if op_type == "set_table_cell_text":
        table_index = _operation_value(
            operation, "tableIndex", "table_index", default=0
        )
        row = _operation_value(operation, "row")
        col = _operation_value(operation, "col", "column")
        text = _operation_value(operation, "text", default="")
        if row is None or col is None:
            raise ValueError("set_table_cell_text requires row and col")
        preserve_format = bool(
            _operation_value(
                operation, "preserveFormat", "preserve_format", default=True
            )
        )
        split_paragraphs = bool(
            _operation_value(
                operation, "splitParagraphs", "split_paragraphs", default=False
            )
        )
        set_cell_text(
            doc,
            int(table_index),
            int(row),
            int(col),
            str(text),
            preserve_format=preserve_format,
            split_paragraphs=split_paragraphs,
        )
        return {
            "type": op_type,
            "table_index": int(table_index),
            "row": int(row),
            "col": int(col),
        }

    if op_type == "fill_by_path":
        mappings = _operation_value(operation, "mappings")
        if not isinstance(mappings, dict):
            raise ValueError("fill_by_path requires mappings")
        result = fill_by_path_in_doc(doc, _normalize_fill_mappings(mappings))
        return {"type": op_type, **result}

    if op_type == "add_page_break":
        add_page_break_to_doc(doc)
        return {"type": op_type, "success": True}

    raise ValueError(f"unsupported operation type: {raw_type}")


def search_and_replace(
    filename: str,
    find_text: str,
    replace_text: str,
    dry_run: bool = False,
    expected_revision: str = None,
    idempotency_key: str = None,
) -> dict:
    """문서에서 텍스트를 치환합니다. dry_run=True이면 원본을 저장하지 않습니다."""
    path = resolve_path(filename)
    scope = _idempotency_scope("search_and_replace", path, idempotency_key)
    fingerprint = _idempotency_fingerprint(
        {
            "filename": filename,
            "find_text": find_text,
            "replace_text": replace_text,
            "dry_run": dry_run,
            "expected_revision": expected_revision,
        }
    )
    replay = _idempotency_replay(scope, fingerprint=fingerprint)
    if replay is not None:
        return replay
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    doc = open_doc(path)
    replaced_count = replace_in_doc(doc, find_text=find_text, replace_text=replace_text)
    result = {
        "replaced_count": replaced_count,
        "find_text": find_text,
        "replace_text": replace_text,
    }
    if dry_run:
        return _idempotency_store(
            scope,
            fingerprint=fingerprint,
            payload=_with_dry_run_verification(result, doc, path),
        )
    verification = _save_doc_verification(doc, path)
    return _idempotency_store(
        scope,
        fingerprint=fingerprint,
        payload=_with_save_verification(result, verification),
    )


def batch_replace(
    filename: str,
    replacements: list[dict[str, str]],
    dry_run: bool = False,
    expected_revision: str = None,
    idempotency_key: str = None,
) -> dict:
    """여러 치환 규칙을 순서대로 적용합니다. dry_run=True이면 원본을 저장하지 않습니다."""
    path = resolve_path(filename)
    scope = _idempotency_scope("batch_replace", path, idempotency_key)
    fingerprint = _idempotency_fingerprint(
        {
            "filename": filename,
            "replacements": replacements,
            "dry_run": dry_run,
            "expected_revision": expected_revision,
        }
    )
    replay = _idempotency_replay(scope, fingerprint=fingerprint)
    if replay is not None:
        return replay
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    doc = open_doc(path)
    result = batch_replace_in_doc(doc, replacements)
    if dry_run:
        return _idempotency_store(
            scope,
            fingerprint=fingerprint,
            payload=_with_dry_run_verification(result, doc, path),
        )
    verification = _save_doc_verification(doc, path)
    return _idempotency_store(
        scope,
        fingerprint=fingerprint,
        payload=_with_save_verification(result, verification),
    )


def apply_edits(
    filename: str,
    operations: list[EditOperation],
    dry_run: bool = False,
    expected_revision: str = None,
    idempotency_key: str = None,
    quality: dict[str, Any] | str | None = None,
) -> dict:
    """여러 편집 operation을 원자적으로 적용합니다. 실패 시 원본 파일은 변경하지 않습니다.

    ``quality``는 저장 게이트 정책입니다(생략 시 transparent = 열림안전만). ``"strict"``
    또는 ``{"mode":"strict","overflowPolicy":"fail","layoutLint":"strict"}`` 처럼 올리면
    SavePipeline이 FormFit/레이아웃/시각 게이트를 적용하고, 실패 시 저장을 보류하며
    ``visualComplete`` 블록과 구조화된 오류 코드를 반환합니다.
    """
    operations_payload = operation_payloads(operations)
    path = resolve_path(filename)
    scope = _idempotency_scope("apply_edits", path, idempotency_key)
    fingerprint = _idempotency_fingerprint(
        {
            "filename": filename,
            "operations": operations_payload,
            "dry_run": dry_run,
            "expected_revision": expected_revision,
        }
    )
    replay = _idempotency_replay(scope, fingerprint=fingerprint)
    if replay is not None:
        return replay
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    if not isinstance(operations, list):
        raise TypeError("operations must be a list")

    doc = open_doc(path)
    operation_results: list[dict[str, Any]] = []
    try:
        for index, operation in enumerate(operations_payload):
            result = _apply_edit_operation(doc, operation, index)
            result["operationIndex"] = index
            operation_results.append(result)
    except Exception as exc:
        return {
            "ok": False,
            "rolledBack": True,
            "dryRun": dry_run,
            "filename": filename,
            "failedOperationIndex": len(operation_results),
            "error": str(exc),
            "operationsApplied": 0,
        }

    result = {
        "ok": True,
        "rolledBack": False,
        "filename": filename,
        "operationsApplied": len(operation_results),
        "operationResults": operation_results,
    }
    if dry_run:
        return _idempotency_store(
            scope,
            fingerprint=fingerprint,
            payload=_with_dry_run_verification(result, doc, path, quality=quality),
        )
    verification = _save_doc_verification(doc, path, quality=quality)
    return _idempotency_store(
        scope,
        fingerprint=fingerprint,
        payload=_with_save_verification(result, verification),
    )


def undo_last_edit(filename: str) -> dict:
    """마지막 저장 전 .bak 백업과 현재 문서를 교체해 직전 편집을 되돌립니다."""
    path = resolve_path(filename)
    return RUNTIME_SERVICES.ops.undo_last_edit(path)


def byte_preserving_patch(
    filename: str,
    patches: list[dict[str, Any]],
    output: str | None = None,
) -> dict:
    """section XML 바이트 splice 기반 문단 텍스트 패치를 적용합니다.

    바이트 보존 fast path: python-hwpx의 ``patch`` → SavePipeline(open-safety)로 게이트되고
    capability handshake로 fail-closed 됩니다. 단, 바이트를 보존하므로 전체 재렌더(VisualComplete
    render) 게이트는 적용되지 않습니다(설계상 카브아웃).
    """
    quality_contract.assert_write_capability()  # fail-closed on capability skew
    return RUNTIME_SERVICES.ops.byte_preserving_patch(filename, patches, output=output)


def add_heading(
    filename: str,
    text: str,
    level: int = 1,
    dry_run: bool = False,
    expected_revision: str = None,
    idempotency_key: str = None,
) -> dict:
    """문서 끝에 제목 문단을 추가합니다. dry_run=True이면 원본을 저장하지 않습니다."""
    path = resolve_path(filename)
    scope = _idempotency_scope("add_heading", path, idempotency_key)
    fingerprint = _idempotency_fingerprint(
        {
            "filename": filename,
            "text": text,
            "level": level,
            "dry_run": dry_run,
            "expected_revision": expected_revision,
        }
    )
    replay = _idempotency_replay(scope, fingerprint=fingerprint)
    if replay is not None:
        return replay
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    doc = open_doc(path)
    idx = add_heading_to_doc(doc, text, level)
    if dry_run:
        return _idempotency_store(
            scope,
            fingerprint=fingerprint,
            payload=_with_dry_run_verification({"paragraph_index": idx}, doc, path),
        )
    verification = _save_doc_verification(doc, path)
    return _idempotency_store(
        scope,
        fingerprint=fingerprint,
        payload=_with_save_verification({"paragraph_index": idx}, verification),
    )


def add_paragraph(
    filename: str,
    text: str,
    style: str | None = None,
    dry_run: bool = False,
    expected_revision: str = None,
    idempotency_key: str = None,
) -> dict:
    """문서 끝에 문단을 추가합니다. dry_run=True이면 원본을 저장하지 않습니다."""
    path = resolve_path(filename)
    scope = _idempotency_scope("add_paragraph", path, idempotency_key)
    fingerprint = _idempotency_fingerprint(
        {
            "filename": filename,
            "text": text,
            "style": style,
            "dry_run": dry_run,
            "expected_revision": expected_revision,
        }
    )
    replay = _idempotency_replay(scope, fingerprint=fingerprint)
    if replay is not None:
        return replay
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    doc = open_doc(path)
    idx = add_paragraph_to_doc(doc, text, style)
    if dry_run:
        return _idempotency_store(
            scope,
            fingerprint=fingerprint,
            payload=_with_dry_run_verification({"paragraph_index": idx}, doc, path),
        )
    verification = _save_doc_verification(doc, path)
    return _idempotency_store(
        scope,
        fingerprint=fingerprint,
        payload=_with_save_verification({"paragraph_index": idx}, verification),
    )


def insert_paragraph(
    filename: str,
    paragraph_index: int,
    text: str,
    style: str | None = None,
    dry_run: bool = False,
    expected_revision: str = None,
    idempotency_key: str = None,
) -> dict:
    """지정 위치 앞에 문단을 삽입합니다. dry_run=True이면 원본을 저장하지 않습니다."""
    path = resolve_path(filename)
    scope = _idempotency_scope("insert_paragraph", path, idempotency_key)
    fingerprint = _idempotency_fingerprint(
        {
            "filename": filename,
            "paragraph_index": paragraph_index,
            "text": text,
            "style": style,
            "dry_run": dry_run,
            "expected_revision": expected_revision,
        }
    )
    replay = _idempotency_replay(scope, fingerprint=fingerprint)
    if replay is not None:
        return replay
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    doc = open_doc(path)
    idx = insert_paragraph_to_doc(doc, paragraph_index, text, style)
    if dry_run:
        return _idempotency_store(
            scope,
            fingerprint=fingerprint,
            payload=_with_dry_run_verification({"inserted_index": idx}, doc, path),
        )
    verification = _save_doc_verification(doc, path)
    return _idempotency_store(
        scope,
        fingerprint=fingerprint,
        payload=_with_save_verification({"inserted_index": idx}, verification),
    )


def delete_paragraph(
    filename: str,
    paragraph_index: int,
    dry_run: bool = False,
    expected_revision: str = None,
    idempotency_key: str = None,
) -> dict:
    """지정 문단을 삭제합니다. dry_run=True이면 원본을 저장하지 않습니다."""
    path = resolve_path(filename)
    scope = _idempotency_scope("delete_paragraph", path, idempotency_key)
    fingerprint = _idempotency_fingerprint(
        {
            "filename": filename,
            "paragraph_index": paragraph_index,
            "dry_run": dry_run,
            "expected_revision": expected_revision,
        }
    )
    replay = _idempotency_replay(scope, fingerprint=fingerprint)
    if replay is not None:
        return replay
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    doc = open_doc(path)
    remaining = delete_paragraph_from_doc(doc, paragraph_index)
    result = {"deleted_index": paragraph_index, "remaining_paragraphs": remaining}
    if dry_run:
        return _idempotency_store(
            scope,
            fingerprint=fingerprint,
            payload=_with_dry_run_verification(result, doc, path),
        )
    verification = _save_doc_verification(doc, path)
    return _idempotency_store(
        scope,
        fingerprint=fingerprint,
        payload=_with_save_verification(result, verification),
    )


def add_table(
    filename: str,
    rows: int,
    cols: int,
    data: list[list[str]] = None,
    dry_run: bool = False,
    expected_revision: str = None,
    idempotency_key: str = None,
) -> dict:
    """문서 끝에 표를 추가합니다. dry_run=True이면 원본을 저장하지 않습니다."""
    path = resolve_path(filename)
    scope = _idempotency_scope("add_table", path, idempotency_key)
    fingerprint = _idempotency_fingerprint(
        {
            "filename": filename,
            "rows": rows,
            "cols": cols,
            "data": data,
            "dry_run": dry_run,
            "expected_revision": expected_revision,
        }
    )
    replay = _idempotency_replay(scope, fingerprint=fingerprint)
    if replay is not None:
        return replay
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    doc = open_doc(path)
    idx = add_table_to_doc(doc, rows, cols, data)
    if dry_run:
        return _idempotency_store(
            scope,
            fingerprint=fingerprint,
            payload=_with_dry_run_verification({"table_index": idx}, doc, path),
        )
    verification = _save_doc_verification(doc, path)
    return _idempotency_store(
        scope,
        fingerprint=fingerprint,
        payload=_with_save_verification({"table_index": idx}, verification),
    )


def set_table_cell_text(
    filename: str,
    table_index: int,
    row: int,
    col: int,
    text: str,
    preserve_format: bool = True,
    split_paragraphs: bool = False,
    dry_run: bool = False,
    expected_revision: str = None,
    idempotency_key: str = None,
) -> dict:
    """표 셀 텍스트를 변경합니다. dry_run=True이면 원본을 저장하지 않습니다."""
    path = resolve_path(filename)
    scope = _idempotency_scope("set_table_cell_text", path, idempotency_key)
    fingerprint = _idempotency_fingerprint(
        {
            "filename": filename,
            "table_index": table_index,
            "row": row,
            "col": col,
            "text": text,
            "preserve_format": preserve_format,
            "split_paragraphs": split_paragraphs,
            "dry_run": dry_run,
            "expected_revision": expected_revision,
        }
    )
    replay = _idempotency_replay(scope, fingerprint=fingerprint)
    if replay is not None:
        return replay
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    doc = open_doc(path)
    set_cell_text(
        doc,
        table_index,
        row,
        col,
        text,
        preserve_format=preserve_format,
        split_paragraphs=split_paragraphs,
    )
    result = {
        "table_index": table_index,
        "row": row,
        "col": col,
        "text": text,
        "preserve_format": preserve_format,
        "split_paragraphs": split_paragraphs,
    }
    if dry_run:
        return _idempotency_store(
            scope,
            fingerprint=fingerprint,
            payload=_with_dry_run_verification(result, doc, path),
        )
    verification = _save_doc_verification(doc, path)
    return _idempotency_store(
        scope,
        fingerprint=fingerprint,
        payload=_with_save_verification(result, verification),
    )


def add_page_break(
    filename: str,
    dry_run: bool = False,
    expected_revision: str = None,
) -> dict:
    """문서 끝에 페이지 나누기를 추가합니다. dry_run=True이면 원본을 저장하지 않습니다."""
    path = resolve_path(filename)
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    doc = open_doc(path)
    add_page_break_to_doc(doc)
    if dry_run:
        return _with_dry_run_verification({"success": True}, doc, path)
    verification = _save_doc_verification(doc, path)
    return _with_save_verification({"success": True}, verification)


def add_chart(
    filename: str,
    chart_type: str,
    categories: list,
    series: list,
    title: str = None,
    paragraph_index: int = None,
    table_index: int = None,
    row: int = None,
    col: int = None,
    treat_as_char: bool = False,
    dry_run: bool = False,
    expected_revision: str = None,
) -> dict:
    """네이티브 차트(<hp:chart>+ECMA-376 chartML part)를 삽입합니다. 렌더 검증된
    MVP 3종(bar·line·pie)만 지원 — 밖이면 CHART_UNSUPPORTED로 typed 거부(무음
    근사 없음). series=[{"name": str, "values": [number,...]}], values 길이는
    categories와 일치해야 합니다. 실한컴은 chartML만으로 차트를 그립니다(OLE
    폴백·사전렌더 이미지 불요). 배치: 기본=문서 끝 새 문단(float),
    paragraph_index=기존 문단, tableIndex+row+col=표 셀, treat_as_char=인라인."""
    path = resolve_path(filename)
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    result = RUNTIME_SERVICES.ops.add_chart(
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
    return _with_document_state(result, path)


def add_equation(
    filename: str,
    latex: str = None,
    script: str = None,
    paragraph_index: int = None,
    table_index: int = None,
    row: int = None,
    col: int = None,
    base_unit: int = 1100,
    dry_run: bool = False,
    expected_revision: str = None,
) -> dict:
    """네이티브 수식(<hp:equation>)을 삽입합니다. latex(권장) 또는 EqEdit script 중
    하나만 지정 — LaTeX는 렌더 검증된 토큰셋만 EqEdit로 변환하고, 밖이면
    EQUATION_LATEX_UNSUPPORTED로 거부합니다(무음 근사 없음). 산출 수식은 실한컴이
    조판하고 기존 리더(eqedit_to_latex)가 되읽습니다(응답 readerLatex).
    배치: 기본=문서 끝 새 문단, paragraph_index=기존 문단, tableIndex+row+col=표 셀."""
    path = resolve_path(filename)
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    result = RUNTIME_SERVICES.ops.add_equation(
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
    return _with_document_state(result, path)


def insert_picture(
    filename: str,
    image_base64: str,
    image_format: str = "png",
    width: int | None = None,
    height: int | None = None,
    width_mm: float | None = None,
    height_mm: float | None = None,
    section_index: int | None = None,
    align: str | None = None,
    output: str | None = None,
    dry_run: bool = False,
    expected_revision: str = None,
) -> dict:
    """본문에 그림 객체를 삽입하고 BinData/manifest 참조를 함께 저장합니다."""
    path = resolve_path(filename)
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    target_path = resolve_path(output) if output else path
    doc = open_doc(path)
    image_data = _decode_image_base64(image_base64)
    doc.add_picture(
        image_data,
        image_format,
        width=width,
        height=height,
        width_mm=width_mm,
        height_mm=height_mm,
        section_index=section_index,
        align=align,
    )
    # media.picture_references now returns tuple[PictureRef, ...] rather
    # than list[dict] (design §2.5) — .to_dict() per entry keeps this
    # handler's own dict-shaped response unchanged.
    picture_refs = [ref.to_dict() for ref in doc.media.picture_references()]
    result = {
        "ok": True,
        "filename": filename,
        "outputPath": target_path,
        "picture": picture_refs[-1] if picture_refs else None,
        "pictureReferences": picture_refs,
        "idIntegrity": _id_integrity_payload(doc),
    }
    if dry_run:
        return _with_dry_run_verification(result, doc, target_path)
    verification = _save_doc_verification(doc, target_path)
    return _with_save_verification(result, verification)


def _validate_workspace_image(data: bytes, image_format: str) -> None:
    """Check bounded file input before inserting its bytes into a package."""
    fmt = image_format.casefold().lstrip(".")
    if fmt == "png":
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("image_filename content does not match image_format")
        offset = 8
        chunks: list[bytes] = []
        while offset + 12 <= len(data):
            length = int.from_bytes(data[offset:offset + 4], "big")
            end = offset + 12 + length
            if end > len(data):
                break
            kind = data[offset + 4:offset + 8]
            payload = data[offset + 8:offset + 8 + length]
            crc = int.from_bytes(data[end - 4:end], "big")
            if zlib.crc32(kind + payload) != crc:
                break
            chunks.append(kind)
            offset = end
            if kind == b"IEND":
                if length == 0 and offset == len(data) and chunks[0] == b"IHDR" and b"IDAT" in chunks:
                    return
                break
    elif fmt in {"jpg", "jpeg"} and data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9"):
        return
    elif fmt == "gif" and data.startswith((b"GIF87a", b"GIF89a")) and data.endswith(b";"):
        return
    raise ValueError("image_filename content does not match image_format or is incomplete")


def replace_picture(
    filename: str,
    image_base64: str | None = None,
    image_format: str = "png",
    picture_index: int = 0,
    binary_item_id_ref: str | None = None,
    remove_orphaned: bool = True,
    output: str | None = None,
    dry_run: bool = False,
    expected_revision: str = None,
    image_filename: str | None = None,
) -> dict:
    """그림 geometry를 유지하고 base64 또는 workspace 이미지 파일로 교체합니다."""
    if (image_base64 is None) == (image_filename is None):
        raise ValueError("provide exactly one of image_base64 or image_filename")
    path = resolve_path(filename)
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    target_path = resolve_path(output) if output else path
    if image_filename is not None:
        image_path = Path(resolve_path(image_filename))
        with image_path.open("rb") as image_file:
            image_data = image_file.read(20 * 1024 * 1024 + 1)
        if len(image_data) > 20 * 1024 * 1024:
            raise ValueError("image_filename must be at most 20 MiB")
        _validate_workspace_image(image_data, image_format)
    else:
        assert image_base64 is not None
        image_data = _decode_image_base64(image_base64)
    doc = open_doc(path)
    # media.replace_picture now returns a frozen PictureReplacement (design
    # §2.4) whose own .to_dict() uses different field names than this op's
    # established response contract (old_binaryItemIDRef/new_binaryItemIDRef/
    # removedOldImage/geometryPreserved/picture_index/section_index), which
    # existing callers/tests depend on — rebuild that exact shape instead.
    replacement = doc.media.replace_picture(
        image_data,
        image_format,
        picture_index=picture_index,
        binary_item_id_ref=binary_item_id_ref,
        remove_orphaned=remove_orphaned,
    )
    replaced_section_index = next(
        (
            index
            for index, section in enumerate(doc.sections)
            if section.element is replacement.picture.paragraph.section.element
        ),
        None,
    )
    replacement_payload = {
        "picture_index": picture_index,
        "section_index": replaced_section_index,
        "old_binaryItemIDRef": replacement.previous_item_id,
        "new_binaryItemIDRef": replacement.item_id,
        "removedOldImage": bool(replacement.removed_orphans),
        "geometryPreserved": True,
    }
    result = {
        "ok": True,
        "filename": filename,
        "outputPath": target_path,
        "replacement": replacement_payload,
        "pictureReferences": [ref.to_dict() for ref in doc.media.picture_references()],
        "idIntegrity": _id_integrity_payload(doc),
    }
    if dry_run:
        return _with_dry_run_verification(result, doc, target_path)
    verification = _save_doc_verification(doc, target_path)
    return _with_save_verification(result, verification)


def _anchor_position(anchor: dict[str, Any] | str) -> int | None:
    if isinstance(anchor, dict):
        value = anchor.get("position")
        if value is None:
            return None
        return int(value)
    if isinstance(anchor, str) and "@" in anchor:
        return int(anchor.rsplit("@", 1)[1])
    return None


def _replace_visible_span_in_runs(
    runs: list[Any],
    start: int,
    end: int,
    replacement: str,
) -> int:
    if start < 0 or end < start:
        raise ValueError("invalid replacement span")

    boundaries: list[tuple[int, int, Any]] = []
    cursor = 0
    for run in runs:
        text = run.text or ""
        next_cursor = cursor + len(text)
        boundaries.append((cursor, next_cursor, run))
        cursor = next_cursor

    affected = [
        (run_start, run_end, run)
        for run_start, run_end, run in boundaries
        if start < run_end and end > run_start
    ]
    if not affected:
        return 0

    first_start, first_end, first_run = affected[0]
    last_start, last_end, last_run = affected[-1]
    first_text = first_run.text or ""
    last_text = last_run.text or ""
    prefix = first_text[: max(0, start - first_start)]
    suffix = last_text[max(0, end - last_start) :]

    first_run.text = prefix + replacement + (suffix if first_run is last_run else "")
    for _, _, run in affected[1:-1]:
        run.text = ""
    if last_run is not first_run:
        last_run.text = suffix
    return 1


def replace_in_paragraph(
    filename: str,
    old_text: str,
    new_text: str,
    paragraph_index: int | None = None,
    location: dict[str, Any] | None = None,
    count: int | None = None,
    dry_run: bool = False,
    expected_revision: str = None,
) -> dict:
    """본문/표 셀 문단 하나에서 run 서식을 유지하며 부분 텍스트를 치환합니다."""
    if old_text == "":
        raise ValueError("old_text는 빈 문자열일 수 없습니다.")
    if count is not None and count <= 0:
        return {
            "replaced_count": 0,
            "location": location or {"paragraph_index": paragraph_index},
            "dryRun": dry_run,
        }

    path = resolve_path(filename)
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    doc = open_doc(path)
    resolved = resolve_paragraph_reference(
        doc, paragraph_index=paragraph_index, location=location
    )
    paragraph = resolved.paragraph
    runs = list(getattr(paragraph, "runs", []))
    before_run_texts = [run.text or "" for run in runs]

    if count is None:
        replaced = _replace_in_runs(runs, old_text, new_text) if runs else 0
    else:
        replaced = 0
        for run in runs:
            remaining = count - replaced
            if remaining <= 0:
                break
            if not (run.text or ""):
                continue
            if hasattr(run, "replace_text"):
                replaced += int(run.replace_text(old_text, new_text, count=remaining))
            else:
                before = run.text or ""
                after = before.replace(old_text, new_text, remaining)
                if after != before:
                    run.text = after
                    replaced += before.count(old_text) - after.count(old_text)

    if replaced == 0 and not runs:
        before = paragraph.text or ""
        limit = -1 if count is None else count
        after = before.replace(old_text, new_text, limit)
        if after != before:
            paragraph.text = after
            replaced = (
                before.count(old_text)
                if count is None
                else min(before.count(old_text), count)
            )

    if replaced:
        changed_runs = [
            run
            for index, run in enumerate(getattr(paragraph, "runs", []) or [])
            if (run.text or "")
            and (
                index >= len(before_run_texts)
                or (run.text or "") != before_run_texts[index]
            )
        ]
        repair_pathological_text_spacing(
            doc,
            paragraph=paragraph,
            runs=changed_runs,
        )
        result = {"replaced_count": replaced, "location": resolved.location}
        if dry_run:
            return _with_dry_run_verification(result, doc, path)
        verification = _save_doc_verification(doc, path)
        return _with_save_verification(result, verification)
    return {
        "replaced_count": replaced,
        "location": resolved.location,
        "dryRun": dry_run,
    }


def replace_by_anchor(
    filename: str,
    anchor: dict[str, Any] | str,
    old_text: str,
    new_text: str,
    dry_run: bool = False,
    expected_revision: str = None,
) -> dict:
    """find_text가 반환한 anchor 위치에서 run 서식을 유지하며 텍스트를 치환합니다."""
    if old_text == "":
        raise ValueError("old_text는 빈 문자열일 수 없습니다.")

    location = location_from_anchor(anchor)
    position = _anchor_position(anchor)
    if position is None:
        return replace_in_paragraph(
            filename,
            old_text,
            new_text,
            location=location,
            count=1,
            dry_run=dry_run,
            expected_revision=expected_revision,
        )

    path = resolve_path(filename)
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    doc = open_doc(path)
    resolved = resolve_paragraph_reference(doc, location=location)
    paragraph = resolved.paragraph
    before = paragraph.text or ""
    end = position + len(old_text)
    if before[position:end] != old_text:
        raise ValueError("anchor position does not match old_text")

    runs = list(getattr(paragraph, "runs", []))
    before_run_texts = [run.text or "" for run in runs]
    if runs:
        replaced = _replace_visible_span_in_runs(runs, position, end, new_text)
    else:
        paragraph.text = before[:position] + new_text + before[end:]
        replaced = 1

    changed_runs = [
        run
        for index, run in enumerate(getattr(paragraph, "runs", []) or [])
        if (run.text or "")
        and (
            index >= len(before_run_texts)
            or (run.text or "") != before_run_texts[index]
        )
    ]
    repair_pathological_text_spacing(
        doc,
        paragraph=paragraph,
        runs=changed_runs,
    )

    result = {
        "replaced_count": replaced,
        "location": resolved.location,
        "position": position,
    }
    if dry_run:
        return _with_dry_run_verification(result, doc, path)
    verification = _save_doc_verification(doc, path)
    return _with_save_verification(result, verification)


def merge_table_cells(
    filename: str,
    table_index: int,
    start_row: int,
    start_col: int,
    end_row: int,
    end_col: int,
    dry_run: bool = False,
    expected_revision: str = None,
) -> dict:
    """표 셀 범위를 병합합니다. dry_run=True이면 원본을 저장하지 않습니다."""
    path = resolve_path(filename)
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    doc = open_doc(path)
    merge_cells_in_table(doc, table_index, start_row, start_col, end_row, end_col)
    result = {
        "merged": True,
        "range": f"({start_row},{start_col})~({end_row},{end_col})",
    }
    if dry_run:
        return _with_dry_run_verification(result, doc, path)
    verification = _save_doc_verification(doc, path)
    return _with_save_verification(result, verification)


def split_table_cell(
    filename: str,
    table_index: int,
    row: int,
    col: int,
    dry_run: bool = False,
    expected_revision: str = None,
) -> dict:
    """병합된 셀을 분할합니다. dry_run=True이면 원본을 저장하지 않습니다."""
    path = resolve_path(filename)
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    doc = open_doc(path)
    span_info = split_cell_in_table(doc, table_index, row, col)
    if dry_run:
        return _with_dry_run_verification(
            {"split": True, "original_span": span_info}, doc, path
        )
    verification = _save_doc_verification(doc, path)
    return _with_save_verification(
        {"split": True, "original_span": span_info}, verification
    )


def format_table(
    filename: str,
    table_index: int,
    has_header_row: bool = None,
    border_type: str = None,
    border_color: str = None,
    border_width: str = None,
    fill_color: str = None,
    row: int = None,
    col: int = None,
    dry_run: bool = False,
    expected_revision: str = None,
) -> dict:
    """표 서식을 적용합니다. 헤더 행 강조 외에 테두리 선 종류(OWPML 어휘:
    SOLID/DASH/DOT/DOUBLE_SLIM/WAVE 등)·색·굵기와 셀 음영(fill_color)을
    표 전체 또는 (row, col) 한 셀에 적용합니다. dry_run=True이면 원본을
    저장하지 않습니다."""
    path = resolve_path(filename)
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    doc = open_doc(path)
    applied = format_table_in_doc(
        doc,
        table_index,
        has_header_row=has_header_row,
        border_type=border_type,
        border_color=border_color,
        border_width=border_width,
        fill_color=fill_color,
        row=row,
        col=col,
    )
    result = {"formatted": True, "table_index": table_index, **applied}
    if dry_run:
        return _with_dry_run_verification(result, doc, path)
    verification = _save_doc_verification(doc, path)
    return _with_save_verification(result, verification)


__all__ = [
    "add_heading",
    "add_paragraph",
    "insert_paragraph",
    "delete_paragraph",
    "add_page_break",
    "add_equation",
    "add_chart",
    "apply_edits",
    "undo_last_edit",
    "replace_by_anchor",
    "replace_in_paragraph",
    "search_and_replace",
    "batch_replace",
    "byte_preserving_patch",
    "insert_picture",
    "replace_picture",
    "add_table",
    "set_table_cell_text",
    "merge_table_cells",
    "split_table_cell",
    "format_table",
    "table_compute",
]
