# SPDX-License-Identifier: Apache-2.0
"""Form-fill automation handlers for the optional MCP adapter."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from .. import quality as quality_contract
from ..core.content import (
    fill_by_path_in_doc,
    find_cell_by_label_in_doc,
)
from ..core.document import open_doc
from ..form_fill import (
    CanonicalFormFillInput,
    FormFillAnalyzeOptions,
    FormFillPlanInput,
    analyze_form_fill_workflow,
    apply_form_fill_workflow,
)
from ..form_output_models import (
    AnalyzeFormFillOutput,
    ApplyBodyOpsOutput,
    ApplyEvalplanFillOutput,
    ApplyFormFillOutput,
    ApplyTableOpsOutput,
    VerifyFormFillOutput,
)
from ..mixed_form import (
    MixedFormApplyInput,
    MixedFormCompiledPlanInput,
    MixedFormPlanInput,
    analyze_mixed_form_plan,
    apply_canonical_mixed_form_plan,
    run_specialized_form_operation,
    verify_canonical_mixed_form_plan,
)
from ..mutation_models import (
    BodyOperation,
    TableOperation,
    operation_payloads,
)

# Import the template-formfit callables from their submodule rather than the
# hwpx top level: at the core 4.0.0 boundary the top-level re-exports become
# deprecated shims that emit a DeprecationWarning on access, and these MCP tools
# (now DEPRECATED but still functional) must not trigger a runtime warning. The
# submodule path is stable across core 3.3.1 and 4.0.0.
from ..office.form_fill import (
    analyze_template_formfit as analyze_hwpx_template_formfit,
)
from ..office.form_fill import (
    apply_template_formfit as apply_hwpx_template_formfit,
)
from ..runtime_services import RUNTIME_SERVICES
from ..utils.helpers import resolve_path
from ._shared import (
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

_TABLE_LABEL_DIRECTIONS = ("right", "down")


def _normalize_table_label_direction(direction: str | None) -> str:
    value = (direction or "right").strip().lower()
    if value not in _TABLE_LABEL_DIRECTIONS:
        expected = ", ".join(_TABLE_LABEL_DIRECTIONS)
        raise ValueError(f"direction must be one of: {expected}")
    return value


def _template_formfit_baseline_arg(baseline: dict | str) -> dict | str:
    if isinstance(baseline, dict):
        return baseline
    text = str(baseline or "").strip()
    if text.endswith(".json") or Path(text).exists():
        return resolve_path(text)
    return text


def _confined_formfit_analysis(analysis: Any) -> dict | None:
    """Re-validate the paths carried inside a caller-supplied analysis."""

    if analysis is None:
        return None
    if not isinstance(analysis, Mapping):
        raise ValueError("analysis must be an object")
    plan = copy.deepcopy(dict(analysis))
    for key in ("source", "destination"):
        entry = plan.get(key)
        if entry is None:
            continue
        if not isinstance(entry, Mapping):
            raise ValueError(f"analysis.{key} must be an object with a path")
        entry = dict(entry)
        path = entry.get("path")
        if path is not None:
            if not isinstance(path, str) or not path.strip():
                raise ValueError(f"analysis.{key}.path must be a non-empty path")
            entry["path"] = resolve_path(path)
        plan[key] = entry
    return plan


def analyze_template_formfit(
    source_filename: str,
    baseline: dict | str,
    content: dict,
    destination_filename: str = None,
    options: dict = None,
) -> dict:
    """P6 baseline 기반 양식 보존 생성 계획을 비파괴 분석합니다."""
    if analyze_hwpx_template_formfit is None:
        raise RuntimeError("installed python-hwpx does not provide template form-fit")
    return analyze_hwpx_template_formfit(
        resolve_path(source_filename),
        baseline=_template_formfit_baseline_arg(baseline),
        content=content or {},
        destination=resolve_path(destination_filename)
        if destination_filename
        else None,
        options=options,
    )


def apply_template_formfit(
    analysis: dict = None,
    source_filename: str = None,
    baseline: dict | str = None,  # type: ignore[assignment]  # Frozen ToolSpec default.
    content: dict = None,
    destination_filename: str = None,
    confirm: bool = True,
) -> dict:
    """양식 보존 생성 계획을 복사본 destination에만 적용하고 검증합니다."""
    if apply_hwpx_template_formfit is None:
        raise RuntimeError("installed python-hwpx does not provide template form-fit")
    return apply_hwpx_template_formfit(
        analysis=_confined_formfit_analysis(analysis),
        source=resolve_path(source_filename) if source_filename else None,
        baseline=_template_formfit_baseline_arg(baseline)
        if baseline is not None
        else None,
        content=content,
        destination=resolve_path(destination_filename)
        if destination_filename
        else None,
        confirm=confirm,
    )


def run_edit_plan(
    plan: dict,
    dry_run: bool = False,
) -> dict:
    """선언적 편집 계획(hwpx.edit-plan/v1)을 all-or-nothing으로 실행합니다.

    plan.steps는 기존 바이트-스플라이스 op 이름 그대로(fill_cells·
    apply_table_ops·apply_body_ops·paragraph_patch·recolor_runs_by_color·
    strip_runs_by_color·strip_trailing_table_captions)를 지시합니다. 실행은
    정적 선검증→전 체인 인메모리→최종 open-safety 검증→단 1회 원자 쓰기 —
    중간 step 실패 시 output·source는 바이트 불변이고 ok=false 리포트
    (failedStepId·step error)가 돌아옵니다. dry_run=true는 동일 체인을 전부
    실행하되 쓰기만 생략합니다(미리보기=실행 정의상 동일). 반환은
    hwpx.plan-report/v1(step별+원본→최종 mutation-report/v1 실측 사영 포함).
    스키마는 hwpx://schemas/edit-plan-v1 리소스로 구독 가능합니다."""

    resolved = dict(plan) if plan else {}
    for key in ("source", "output", "journalPath"):
        value = resolved.get(key)
        if isinstance(value, str) and value:
            resolved[key] = resolve_path(value)
    if not dry_run:
        quality_contract.assert_write_capability()
    return RUNTIME_SERVICES.ops.run_edit_plan(resolved, dry_run=dry_run)


def apply_table_ops(
    filename: str,
    ops: list[TableOperation],
    output: str | None = None,
    render_check: str = "off",
    dry_run: bool = False,
) -> ApplyTableOpsOutput:
    """바이트 보존으로 표 셀/행/열/표 구조 연산을 원자 적용합니다."""

    source = Path(resolve_path(filename))
    target = Path(resolve_path(output)) if output else source
    if not dry_run:
        quality_contract.assert_write_capability()
    return run_specialized_form_operation(
        operation="apply_table_ops",
        source=source,
        output=target,
        dry_run=dry_run,
        execute_with_guard=lambda output_guard, publication_sink: (
            RUNTIME_SERVICES.ops.apply_table_ops(
                str(source),
                operation_payloads(ops),
                output=str(target) if output else None,
                render_check=render_check,
                dry_run=dry_run,
                output_guard=output_guard,
                publication_sink=publication_sink,
            )
        ),
    )


def verify_form_fill(
    filename: str = None,
    before_path: str = None,
    require: bool = False,
    plan: MixedFormCompiledPlanInput = None,
    expected_output_revision: Annotated[
        str | None,
        Field(pattern=r"^sha256:[0-9a-f]{64}$"),
    ] = None,
) -> VerifyFormFillOutput:
    """Compiled mixed-form 결과를 검증합니다. filename/before_path는 렌더 호환 경로입니다."""

    if plan is not None:
        if filename is not None or before_path is not None:
            raise ValueError(
                "plan cannot be combined with legacy filename/before_path arguments"
            )
        return verify_canonical_mixed_form_plan(
            plan,
            require=require,
            expected_output_revision=expected_output_revision,
            render_verifier=lambda after, before, required: (
                RUNTIME_SERVICES.ops.verify_form_fill(
                    after,
                    before,
                    require=required,
                )
            ),
        )
    if filename is None or before_path is None:
        raise ValueError("provide plan or both filename and before_path")
    if expected_output_revision is not None:
        raise ValueError("expected_output_revision requires plan")
    result = RUNTIME_SERVICES.ops.verify_form_fill(
        resolve_path(filename), resolve_path(before_path), require=require
    )
    result["compatibility"] = {
        "status": "retained-render-verifier",
        "canonicalInput": "plan: hwpx.mixed-form-compiled-plan/v1",
    }
    return result


def score_form_fill(
    filename: str,
    gold_path: str,
    blank_path: str,
    run_render: bool = True,
    expected_pages: int | None = None,
) -> dict:
    """채움본을 gold/blank와 비교해 렌더·서식·구조·내용·규정 5축으로 채점합니다."""

    return RUNTIME_SERVICES.ops.score_form_fill(
        resolve_path(filename),
        resolve_path(gold_path),
        resolve_path(blank_path),
        run_render=run_render,
        expected_pages=expected_pages,
    )


def apply_body_ops(
    filename: str,
    ops: list[BodyOperation],
    output: str | None = None,
    dry_run: bool = False,
) -> ApplyBodyOpsOutput:
    """표 밖 본문 문단에 바이트 보존 연산을 적용합니다."""

    source = Path(resolve_path(filename))
    target = Path(resolve_path(output)) if output else source
    if not dry_run:
        quality_contract.assert_write_capability()
    return run_specialized_form_operation(
        operation="apply_body_ops",
        source=source,
        output=target,
        dry_run=dry_run,
        execute_with_guard=lambda output_guard, publication_sink: (
            RUNTIME_SERVICES.ops.apply_body_ops(
                str(source),
                operation_payloads(ops),
                output=str(target) if output else None,
                dry_run=dry_run,
                output_guard=output_guard,
                publication_sink=publication_sink,
            )
        ),
    )


def inspect_fill_residue(
    filename: str,
    blank_path: str | None = None,
) -> dict:
    """채움본의 삭제색 안내문·미수정 샘플·placeholder 잔존을 검사합니다."""

    return RUNTIME_SERVICES.ops.inspect_fill_residue(
        resolve_path(filename),
        blank_path=resolve_path(blank_path) if blank_path else None,
    )


def scan_form_guidance(filename: str, max_items: int = 60) -> dict:
    """처음 보는 양식의 색 범례·삭제/수정 후보·빈 셀·질문을 비변형 정찰합니다."""

    return RUNTIME_SERVICES.ops.scan_form_guidance(
        resolve_path(filename), max_items=max_items
    )


def apply_evalplan_fill(
    filename: str,
    review_md: str,
    output: str | None = None,
    render_check: str = "off",
    score_gold_path: str | None = None,
    expected_pages: int | None = None,
    phase: str = "all",
) -> ApplyEvalplanFillOutput:
    """빈 평가계획 양식과 검토용 Markdown을 바이트 보존 채움본으로 만듭니다.

    phase: "structural"|"all"(기본)|"clean". "clean"은 채움 뒤 core의 결정론적
    정리(제목/교사/정의적 채움·지시문 스캐폴딩 prune·빨강 제거·파랑→검정·캡션 strip)까지
    한 번에 실행해 제출 가능한 채움본을 돌려줍니다(정리 리포트=contentReport.finalize)."""

    quality_contract.assert_write_capability()
    source = Path(resolve_path(filename))
    target = Path(resolve_path(output)) if output else source
    return run_specialized_form_operation(
        operation="apply_evalplan_fill",
        source=source,
        output=target,
        dry_run=False,
        execute_with_guard=lambda output_guard, publication_sink: (
            RUNTIME_SERVICES.ops.apply_evalplan_fill(
                str(source),
                resolve_path(review_md),
                phase=phase,
                output=str(target) if output else None,
                render_check=render_check,
                score_gold_path=resolve_path(score_gold_path)
                if score_gold_path
                else None,
                expected_pages=expected_pages,
                output_guard=output_guard,
                publication_sink=publication_sink,
            )
        ),
    )


def find_cell_by_label(
    filename: str, label_text: str, direction: str = "right"
) -> dict:
    """양식 문서에서 라벨 기준 인접 셀 후보를 조회합니다. direction: right 또는 down."""
    path = resolve_path(filename)
    doc = open_doc(path)
    safe_direction = _normalize_table_label_direction(direction)
    return _with_document_state(
        find_cell_by_label_in_doc(doc, label_text, direction=safe_direction), path
    )


def fill_by_path(
    filename: str,
    mappings: dict[str, str],
    dry_run: bool = False,
    expected_revision: str = None,
    idempotency_key: str = None,
) -> dict:
    """라벨 경로 문법으로 셀을 채웁니다. dry_run=True이면 원본을 저장하지 않습니다."""
    path = resolve_path(filename)
    scope = _idempotency_scope("fill_by_path", path, idempotency_key)
    fingerprint = _idempotency_fingerprint(
        {
            "filename": filename,
            "mappings": mappings,
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
    result = fill_by_path_in_doc(doc, _normalize_fill_mappings(mappings))
    if result.get("applied_count", 0) > 0:
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
    result["dryRun"] = dry_run
    return _idempotency_store(scope, fingerprint=fingerprint, payload=result)


def list_form_fields(filename: str) -> dict:
    """문서의 네이티브 누름틀/FORM 필드 목록과 현재 값을 반환합니다."""
    path = resolve_path(filename)
    return _with_document_state(RUNTIME_SERVICES.ops.list_form_fields(path), path)


def add_form_field(
    filename: str,
    name: str,
    prompt: str = "",
    memo: str = "",
    paragraph_index: int = None,
    table_index: int = None,
    row: int = None,
    col: int = None,
    dry_run: bool = False,
    expected_revision: str = None,
) -> dict:
    """누름틀(click-here) 필드를 생성합니다. 실한컴 CLICKHERE 형상 그대로 방출되어
    기존 list/fill/한컴이 특수분기 없이 소비합니다. prompt(안내문)는 화면 전용(미인쇄).
    배치: 기본=문서 끝 새 문단, paragraph_index=기존 문단, tableIndex+row+col=표 셀."""
    path = resolve_path(filename)
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    result = RUNTIME_SERVICES.ops.add_form_field(
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
    return _with_document_state(result, path)


def fill_form_field(
    filename: str,
    value: str,
    field_index: int = None,
    field_id: str = None,
    name: str = None,
    dry_run: bool = False,
    expected_revision: str = None,
) -> dict:
    """네이티브 누름틀/FORM 필드 하나를 채우고 open-safety 검증 증거를 반환합니다."""
    path = resolve_path(filename)
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    result = RUNTIME_SERVICES.ops.fill_form_field(
        path,
        value=value,
        field_index=field_index,
        field_id=field_id,
        name=name,
        dry_run=dry_run,
    )
    result["compatibility"] = {
        "status": "retained-native-field-facade",
        "canonicalTarget": "nativeField",
        "reason": "in-place/index compatibility semantics are preserved",
    }
    return _with_document_state(result, path)


def analyze_form_fill(
    source_filename: str = None,
    input_json: CanonicalFormFillInput | str = None,  # type: ignore[assignment]  # Frozen ToolSpec default.
    input_json_path: str = None,
    input_docx: str = None,
    destination_filename: str = None,
    options: FormFillAnalyzeOptions = None,
    plan: MixedFormPlanInput = None,
) -> AnalyzeFormFillOutput:
    """엄격한 혼합 양식 계획을 비변경 분석합니다. 기존 formfill.v1 인자는 호환 경로입니다."""
    if plan is not None:
        compatibility_args = (
            source_filename,
            input_json,
            input_json_path,
            input_docx,
            destination_filename,
            options,
        )
        if any(value is not None for value in compatibility_args):
            raise ValueError(
                "plan cannot be combined with hwpx.formfill.v1 compatibility arguments"
            )
        return analyze_mixed_form_plan(plan)
    if source_filename is None:
        raise ValueError(
            "provide plan or source_filename for the hwpx.formfill.v1 compatibility path"
        )
    result = analyze_form_fill_workflow(
        source_filename=source_filename,
        input_json=input_json,
        input_json_path=input_json_path,
        input_docx=input_docx,
        destination_filename=destination_filename,
        options=options,
    )
    result["compatibility"] = {
        "schemaVersion": "hwpx.formfill.v1",
        "status": "retained",
        "canonicalInput": "plan: hwpx.mixed-form-plan/v1",
    }
    return result


def apply_form_fill(
    plan_id: str = None,
    analysis: FormFillPlanInput = None,
    source_filename: str = None,
    destination_filename: str = None,
    canonical_input: CanonicalFormFillInput | str = None,  # type: ignore[assignment]  # Frozen ToolSpec default.
    confirm: bool = True,
    plan: MixedFormApplyInput = None,
) -> ApplyFormFillOutput:
    """엄격한 public/compiled 혼합 양식 계획을 원자 적용합니다. 기존 인자는 호환 경로입니다."""
    if plan is not None:
        compatibility_args = (
            plan_id,
            analysis,
            source_filename,
            destination_filename,
            canonical_input,
        )
        if (
            any(value is not None for value in compatibility_args)
            or confirm is not True
        ):
            raise ValueError(
                "plan cannot be combined with hwpx.formfill.v1 compatibility arguments"
            )
        quality_contract.assert_write_capability()
        return apply_canonical_mixed_form_plan(plan)
    result = apply_form_fill_workflow(
        plan_id=plan_id,
        analysis=analysis,
        source_filename=source_filename,
        destination_filename=destination_filename,
        canonical_input=canonical_input,
        confirm=confirm,
    )
    result["compatibility"] = {
        "schemaVersion": "hwpx.formfill.v1",
        "status": "retained",
        "canonicalInput": "plan: hwpx.mixed-form-plan/v1 or hwpx.mixed-form-compiled-plan/v1",
    }
    return result


verify_form_fill.__hwpx_input_schema_extra__ = {  # type: ignore[attr-defined]
    "oneOf": [
        {
            "required": ["plan"],
            "properties": {"plan": {"not": {"type": "null"}}},
            "not": {
                "anyOf": [
                    {
                        "required": [name],
                        "properties": {name: {"not": {"type": "null"}}},
                    }
                    for name in ("filename", "before_path")
                ]
            },
        },
        {
            "required": ["filename", "before_path"],
            "properties": {
                "filename": {"not": {"type": "null"}},
                "before_path": {"not": {"type": "null"}},
                "plan": {"type": "null"},
                "expected_output_revision": {"type": "null"},
            },
        },
    ]
}


analyze_form_fill.__hwpx_input_schema_extra__ = {  # type: ignore[attr-defined]
    "oneOf": [
        {
            "required": ["plan"],
            "properties": {"plan": {"not": {"type": "null"}}},
            "not": {
                "anyOf": [
                    {
                        "required": [name],
                        "properties": {name: {"not": {"type": "null"}}},
                    }
                    for name in (
                        "source_filename",
                        "input_json",
                        "input_json_path",
                        "input_docx",
                        "destination_filename",
                        "options",
                    )
                ]
            },
        },
        {
            "required": ["source_filename"],
            "properties": {
                "source_filename": {"not": {"type": "null"}},
                "plan": {"type": "null"},
            },
        },
    ]
}


apply_form_fill.__hwpx_input_schema_extra__ = {  # type: ignore[attr-defined]
    "oneOf": [
        {
            "required": ["plan"],
            "properties": {
                "plan": {"not": {"type": "null"}},
                "confirm": {"const": True},
            },
            "not": {
                "anyOf": [
                    {
                        "required": [name],
                        "properties": {name: {"not": {"type": "null"}}},
                    }
                    for name in (
                        "plan_id",
                        "analysis",
                        "source_filename",
                        "destination_filename",
                        "canonical_input",
                    )
                ]
            },
        },
        {"properties": {"plan": {"type": "null"}}},
    ]
}


__all__ = [
    "add_form_field",
    "analyze_form_fill",
    "analyze_template_formfit",
    "apply_body_ops",
    "apply_evalplan_fill",
    "apply_form_fill",
    "apply_table_ops",
    "apply_template_formfit",
    "fill_by_path",
    "fill_form_field",
    "find_cell_by_label",
    "inspect_fill_residue",
    "list_form_fields",
    "scan_form_guidance",
    "score_form_fill",
    "verify_form_fill",
]
