# SPDX-License-Identifier: Apache-2.0
"""Authoring automation handlers for the optional MCP adapter."""

from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from ..office.utilities import report_utils as hwpx_report_utils
from ..office.authoring.report_parser import (
    parse_government_report_text as parse_hwpx_government_report_text,
)

from .. import quality as quality_contract
from ..core.content import (
    copy_document_file,
)
from ..core.document import create_blank
from ..document_state import document_state_payload
from ..office.authoring import (
    _create_document_from_plan as _build_document_from_plan_with_notices,
)
from ..office.authoring import (
    create_document_from_plan as build_document_from_plan,
)
from ..office.authoring import (
    get_document_plan_schema as get_hwpx_document_plan_schema,
)
from ..office.authoring import (
    inspect_document_authoring_quality as inspect_authoring_document_quality,
)
from ..office.authoring import (
    normalize_document_plan as normalize_hwpx_document_plan,
)
from ..office.authoring import (
    validate_document_plan as validate_hwpx_document_plan,
)
from ..office.authoring.presets import (
    create_proposal_document as build_proposal_document,
)
from ..office.authoring.presets import (
    inspect_proposal_quality as inspect_proposal_document_quality,
)
from ..office.authoring.style_profile import (
    describe_template as describe_hwpx_template,
)
from ..office.authoring.style_profile import (
    list_templates as list_hwpx_templates,
)
from ..office.authoring.style_profile import (
    register_template as register_hwpx_template,
)
from ..office.document_ops import (
    build_comparison_table_plan as build_hwpx_comparison_table_plan,
)
from ..quality_generation import (
    create_quality_document_fallback,
)
from ..storage import (
    build_hwpx_open_safety_report,
    build_hwpx_verification_report,
)
from ..utils.helpers import resolve_path
from ._shared import (
    _diff_sources,
    _inspect_authoring_quality,
    _proposal_quality_fallback,
    _quality_profile_argument,
    _revision_guard,
)

_VERBOSITY_MODES = {"compact", "full"}


def _normalize_verbosity(verbosity: str | None) -> str:
    value = (verbosity or "compact").strip().lower()
    if value not in _VERBOSITY_MODES:
        expected = ", ".join(sorted(_VERBOSITY_MODES))
        raise ValueError(f"verbosity must be one of: {expected}")
    return value


def _compact_open_safety(open_safety: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(open_safety, dict):
        return None
    compact: dict[str, Any] = {
        "ok": bool(open_safety.get("ok")),
        "summary": open_safety.get("summary"),
    }
    for key in ("validatePackage", "validateDocument", "reopen"):
        value = open_safety.get(key)
        if isinstance(value, dict):
            compact[key] = {"ok": bool(value.get("ok"))}
    return compact


def _verification_is_successful(verification: dict[str, Any] | None) -> bool:
    if not isinstance(verification, dict):
        return False
    open_safety = verification.get("openSafety")
    if isinstance(open_safety, dict) and not bool(open_safety.get("ok")):
        return False
    return bool(verification.get("ok", True))


def _compact_verification_report(verification: dict[str, Any]) -> dict[str, Any]:
    if not _verification_is_successful(verification):
        return verification
    compact: dict[str, Any] = {
        "ok": bool(verification.get("ok", True)),
        "summary": verification.get("summary", "verification passed"),
    }
    for key in ("filePath", "fileSizeBytes", "warnings"):
        if key in verification:
            compact[key] = verification[key]
    open_safety = _compact_open_safety(verification.get("openSafety"))
    if open_safety is not None:
        compact["openSafety"] = open_safety
    return compact


def _apply_write_verbosity(
    payload: dict[str, Any], verbosity: str | None
) -> dict[str, Any]:
    if _normalize_verbosity(verbosity) == "full":
        return payload
    compacted = dict(payload)
    for key in ("verification", "verificationReport"):
        verification = compacted.get(key)
        if isinstance(verification, dict):
            compacted[key] = _compact_verification_report(verification)
    open_safety = compacted.get("openSafety")
    if isinstance(open_safety, dict) and bool(open_safety.get("ok")):
        compacted["openSafety"] = _compact_open_safety(open_safety)
    return compacted


def create_document(
    filename: str,
    title: str = None,
    author: str = None,
    expected_revision: str = None,
) -> dict:
    """새 HWPX 문서를 생성하고 즉시 저장합니다."""
    del title, author
    path = resolve_path(filename)
    if Path(path).exists():
        guard = _revision_guard(path, expected_revision)
        if guard is not None:
            return guard
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    verification = create_blank(path)
    return {
        "filename": filename,
        "created": True,
        "verification": verification,
        "openSafety": verification["openSafety"],
        **document_state_payload(path),
    }


def _save_generated_document(doc: Any, path: str, *, quality: Any = None) -> dict:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Phase F: generation also funnels through the one SavePipeline gate.
    quality_contract.assert_write_capability()
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.stem}.",
        suffix=target.suffix or ".hwpx",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        os.close(fd)
        report = quality_contract.save_through_pipeline(doc, tmp_path, quality=quality)
        verification = build_hwpx_verification_report(tmp_path)
        if not verification["openSafety"]["ok"]:
            raise RuntimeError(
                "generated HWPX failed open-safety verification: "
                + verification["openSafety"]["summary"]
            )
        os.replace(tmp_path, target)
        verification["filePath"] = str(target)
        verification["visualComplete"] = quality_contract.visual_complete_block(report)
        return verification
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _handoff_status(quality: dict) -> str:
    return "ready" if bool(quality.get("pass")) else "needs_revision"


def _next_action(quality: dict) -> str:
    if bool(quality.get("pass")):
        return "structural handoff is ready; complete visual review before final submission"
    return "review quality.gaps and profile repair_hints, then rerun validate/analyze/create"


def get_document_plan_schema() -> dict:
    """document_plan(생성 계획)의 JSON Schema를 반환합니다.

    Structured Outputs/외부 검증 계약으로 직접 사용하세요 — 자유형 JSON을 만들고
    validate_document_plan에서 거부당하는 대신, 이 스키마로 생성을 제약합니다.
    """
    if get_hwpx_document_plan_schema is None:
        raise RuntimeError(
            "installed python-hwpx does not provide document-plan authoring"
        )
    return get_hwpx_document_plan_schema()


def validate_document_plan(document_plan: dict) -> dict:
    """선언형 hwpx.document_plan.v1 생성 계획을 검증합니다. 파일은 쓰지 않습니다."""
    if validate_hwpx_document_plan is None or normalize_hwpx_document_plan is None:
        raise RuntimeError(
            "installed python-hwpx does not provide document-plan authoring"
        )
    report = validate_hwpx_document_plan(document_plan or {})
    result = report.to_dict()
    if report.ok:
        result["can_create"] = True
        result["normalizedPlan"] = normalize_hwpx_document_plan(
            document_plan or {}
        ).to_dict()
        result["next_tool"] = "create_document_from_plan"
    else:
        result["can_create"] = False
        result["next_tool"] = "validate_document_plan"
        result["next_action"] = (
            "repair document_plan using repairHints, then rerun validate_document_plan"
        )
    return result


def markdown_to_document_plan(
    markdown: str,
    title: str = None,
    metadata: dict = None,
    style_preset: str = "standard_korean_business",
) -> dict:
    """Markdown을 검증 가능한 hwpx.document_plan.v1 초안으로 변환합니다. 파일은 쓰지 않습니다."""
    if validate_hwpx_document_plan is None or normalize_hwpx_document_plan is None:
        raise RuntimeError(
            "installed python-hwpx does not provide document-plan authoring"
        )
    from ..markdown_plan import (
        markdown_to_document_plan as _build_markdown_document_plan,
    )

    converted = _build_markdown_document_plan(
        markdown or "",
        title=title,
        metadata=metadata or {},
        style_preset=style_preset,
    )
    plan = converted.plan
    report = validate_hwpx_document_plan(plan)
    validation = report.to_dict()
    result: dict[str, Any] = {
        "ok": report.ok,
        "can_create": report.ok,
        "document_plan": plan,
        "validation": validation,
        "warnings": list(converted.warnings),
        "next_tool": "create_document_from_plan"
        if report.ok
        else "markdown_to_document_plan",
    }
    if report.ok:
        result["normalizedPlan"] = normalize_hwpx_document_plan(plan).to_dict()
    else:
        result["next_action"] = (
            "repair Markdown or document_plan using validation.repairHints, then rerun markdown_to_document_plan"
        )
    return result


def analyze_document_plan(
    document_plan: dict,
    destination_filename: str = None,
    style_preset: str = "standard_korean_business",
    quality_profile: str = None,
    profile: dict = None,
) -> dict:
    """선언형 document_plan을 파일 쓰기 없이 분석하고 품질 미리보기를 반환합니다."""
    if (
        build_document_from_plan is None
        or validate_hwpx_document_plan is None
        or normalize_hwpx_document_plan is None
    ):
        raise RuntimeError(
            "installed python-hwpx does not provide document-plan authoring"
        )
    validation = validate_hwpx_document_plan(document_plan or {})
    validation_payload = validation.to_dict()
    result = {
        **validation_payload,
        "mutated": False,
        "destination": {
            "filename": destination_filename,
            "path": resolve_path(destination_filename)
            if destination_filename
            else None,
            "required_for_create": bool(destination_filename),
        },
        "style_preset": style_preset,
        "quality_profile": _quality_profile_argument(quality_profile, profile),
    }
    if not validation.ok:
        result.update(
            {
                "can_create": False,
                "handoff_status": "needs_revision",
                "next_tool": "validate_document_plan",
                "next_action": (
                    "repair document_plan using repairHints, then rerun analyze_document_plan"
                ),
            }
        )
        return result

    normalized = normalize_hwpx_document_plan(document_plan or {})
    quality: dict | None = None
    doc = build_document_from_plan(document_plan or {}, preset=style_preset)
    try:
        quality = _inspect_authoring_quality(
            doc,
            document_plan=document_plan or {},
            quality_profile=quality_profile,
            profile=profile,
        )
    finally:
        doc.close()

    result.update(
        {
            "can_create": True,
            "normalizedPlan": normalized.to_dict(),
            "quality_preview": quality,
            "handoff_status": _handoff_status(quality),
            "next_tool": "create_document_from_plan",
            "next_action": _next_action(quality),
        }
    )
    return result


def create_document_from_plan(
    filename: str,
    document_plan: dict,
    style_preset: str = "standard_korean_business",
    quality_profile: str = None,
    profile: dict = None,
    verify_render: bool = False,
    verbosity: str = "compact",
) -> dict:
    """선언형 document_plan으로 HWPX를 생성하고 즉시 저장/검증합니다.

    document_plan.metadata.document_type 이 '공문'/'보고서'/'가정통신문'이면 실제
    한컴-harvest 프로파일로 생성됩니다. 공문은 결문 메타
    document_plan.gyeolmun = {issuer, productionNumber, enforcementDate,
    disclosure} 를 지원하고, 공문서 작성규정 구조 hard-gate 결과가
    quality.gongmun_structure(structure_pass)로 반환됩니다. 맞춤법은
    quality.korean_proofing_status(정직 'unverified', 거짓 통과 없음)로 보고합니다.
    출력은 **HWPX 전용**입니다(.odt/.docx/.pdf 등 비-HWPX 미지원; 기안문 ODT는
    별도 트랙). verify_render=True 이고 Mac 한컴 오라클이 가용하면
    quality.render_checked/visual_complete 가 실제 렌더 영수증이 됩니다.
    """
    return _create_document_from_plan_impl(
        filename,
        document_plan,
        style_preset=style_preset,
        quality_profile=quality_profile,
        profile=profile,
        verify_render=verify_render,
        verbosity=verbosity,
    )


def _create_document_from_plan_impl(
    filename: str,
    document_plan: dict,
    *,
    style_preset: str = "standard_korean_business",
    quality_profile: str | dict | None = None,
    profile: dict | None = None,
    verify_render: bool = False,
    verbosity: str | None = "compact",
) -> dict:
    if (
        build_document_from_plan is None
        or inspect_authoring_document_quality is None
        or validate_hwpx_document_plan is None
    ):
        raise RuntimeError(
            "installed python-hwpx does not provide document-plan authoring"
        )
    # FR-011: HWPX-only output. Non-HWPX formats (ODT/기안문, docx, pdf) are a
    # separate track — never silently attempt them.
    suffix = Path(filename).suffix.lower()
    if suffix and suffix != ".hwpx":
        return {
            "filename": filename,
            "created": False,
            "error": f"unsupported output format {suffix!r}; only .hwpx is supported",
            "handoff_status": "unsupported_format",
            "next_action": "use a .hwpx filename (ODT 기안문 등 비-HWPX 포맷은 별도 트랙)",
        }
    validation = validate_hwpx_document_plan(document_plan or {})
    if not validation.ok:
        return {
            "filename": filename,
            "created": False,
            "error": "document plan failed validation",
            "plan_validation": validation.to_dict(),
            "handoff_status": "needs_revision",
            "next_tool": "validate_document_plan",
            "next_action": (
                "repair document_plan using repairHints, then rerun validate_document_plan"
            ),
        }
    path = resolve_path(filename)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    notices: list[str] = []
    doc = _build_document_from_plan_with_notices(document_plan or {}, preset=style_preset, notices=notices)
    try:
        verification = _save_generated_document(doc, path)
    finally:
        doc.close()
    report = _inspect_authoring_quality(
        path,
        document_plan=document_plan or {},
        quality_profile=quality_profile,
        profile=profile,
        verify_render=verify_render,
    )
    result = {
        "filename": filename,
        "created": True,
        "style_preset": style_preset,
        "quality_profile": _quality_profile_argument(quality_profile, profile),
        "plan_validation": validation.to_dict(),
        "handoff_status": _handoff_status(report),
        "next_action": _next_action(report),
        "quality": report,
        "verification": verification,
    }
    if notices:
        # What was made differently from the plan (e.g. a plain table where the profile has none).
        result["warnings"] = notices
    return _apply_write_verbosity(result, verbosity)


def create_government_report_document(
    filename: str,
    document_plan: dict,
    profile: dict = None,
    verbosity: str = "compact",
) -> dict:
    """정부보고서 프리셋으로 document_plan을 생성하고 즉시 저장/검증합니다."""
    return _create_document_from_plan_impl(
        filename,
        document_plan,
        style_preset="government_report",
        quality_profile="government_report",
        profile=profile,
        verbosity=verbosity,
    )


def _report_values(values: list | tuple | dict | None) -> tuple[list, dict]:
    if isinstance(values, dict):
        args = values.get("args")
        if args is None:
            args = values.get("values")
        if args is None:
            args = []
        if not isinstance(args, list | tuple):
            args = [args]
        kwargs = {
            str(key): value
            for key, value in values.items()
            if key not in {"args", "values"}
        }
        return list(args), kwargs
    if isinstance(values, list | tuple):
        args = list(values)
        if args and isinstance(args[-1], dict):
            kwargs = dict(args.pop())
        else:
            kwargs = {}
        return args, kwargs
    if values is None:
        return [], {}
    return [values], {}


def _optional_int(value: Any, default: int) -> int:
    if value is None:
        return default
    return int(value)


def compute_report_value(
    operation: str,
    values: list | dict = None,  # type: ignore[assignment]  # Frozen ToolSpec default.
) -> dict:
    """정부보고서 표/문장에 넣을 계산값을 python-hwpx report_utils로 계산합니다."""
    normalized = str(operation or "").strip().lower().replace("-", "_")
    args, kwargs = _report_values(values)
    value: Any
    try:
        if normalized in {"krw_hangul", "hangul_krw"}:
            value = hwpx_report_utils.format_krw_hangul(args[0])
        elif normalized in {"commas", "number_commas"}:
            value = hwpx_report_utils.format_number_commas(args[0])
        elif normalized == "age":
            today_arg = kwargs.get("today")
            today = date.fromisoformat(today_arg) if today_arg else None
            value = hwpx_report_utils.calculate_age(args[0], today=today)
        elif normalized == "delta":
            value = hwpx_report_utils.format_delta(
                args[0],
                negative_prefix=str(kwargs.get("negative_prefix", "△")),
            )
        elif normalized == "delta_percent":
            value = hwpx_report_utils.format_delta_percent(
                args[0],
                args[1],
                digits=_optional_int(kwargs.get("digits"), 1),
            )
        elif normalized in {"ratio", "ratios"}:
            value = hwpx_report_utils.calculate_ratios(
                args[0],
                args[1],
                digits=_optional_int(kwargs.get("digits"), 1),
            )
        elif normalized in {"date", "normalize_date", "korean_date"}:
            value = hwpx_report_utils.normalize_korean_date(args[0])
        else:
            return {
                "operation": operation,
                "value": None,
                "warnings": [f"unsupported report value operation: {operation}"],
            }
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        return {"operation": operation, "value": None, "warnings": [str(exc)]}

    return {"operation": normalized, "value": value, "warnings": []}


def register_template(
    name: str,
    source_filename: str,
    registry_path: str = None,
    description: str = "",
    tags: list[str] = None,
) -> dict:
    """사용자 템플릿을 등록하고 style profile과 placeholder contract를 저장합니다."""
    if register_hwpx_template is None:
        raise RuntimeError(
            "installed python-hwpx does not provide template registry tools"
        )
    return register_hwpx_template(
        name,
        resolve_path(source_filename),
        registry_path=resolve_path(registry_path) if registry_path else None,
        description=description,
        tags=tags or [],
    )


def list_templates(registry_path: str = None) -> dict:
    """등록된 템플릿 목록을 반환합니다."""
    if list_hwpx_templates is None:
        raise RuntimeError(
            "installed python-hwpx does not provide template registry tools"
        )
    return list_hwpx_templates(
        registry_path=resolve_path(registry_path) if registry_path else None
    )


def describe_template(
    name: str,
    registry_path: str = None,
    values: dict = None,
) -> dict:
    """등록 템플릿 상세와 placeholder 미충전 리포트를 반환합니다."""
    if describe_hwpx_template is None:
        raise RuntimeError(
            "installed python-hwpx does not provide template registry tools"
        )
    return describe_hwpx_template(
        name,
        registry_path=resolve_path(registry_path) if registry_path else None,
        values=values or {},
    )


def parse_government_report_text(text: str, title: str = "") -> dict:
    """붙여넣은 정부보고서 텍스트를 document_plan으로 파싱하고 검증합니다."""
    if parse_hwpx_government_report_text is None or validate_hwpx_document_plan is None:
        raise RuntimeError(
            "installed python-hwpx does not provide government-report parsing"
        )

    document_plan = parse_hwpx_government_report_text(text or "", title=title or "")
    validation = validate_hwpx_document_plan(document_plan)
    result = {
        "document_plan": document_plan,
        "plan_validation": validation.to_dict(),
        "can_create": bool(validation.ok),
    }
    if validation.ok:
        result["next_tool"] = "create_government_report_document"
        result["next_action"] = (
            "review document_plan, then call create_government_report_document"
        )
    else:
        result["next_tool"] = "parse_government_report_text"
        result["next_action"] = (
            "repair source text or document_plan using plan_validation"
        )
    return result


def create_comparison_table_document(
    filename: str,
    old_filename: str = None,
    new_filename: str = None,
    old_paragraphs: list[str] = None,
    new_paragraphs: list[str] = None,
    title: str = "신구대조표",
    include_equal: bool = True,
    verbosity: str = "compact",
) -> dict:
    """두 문서/문단을 좌우 신구대조표 HWPX로 생성하고 검증합니다."""
    if (
        build_hwpx_comparison_table_plan is None
        or build_document_from_plan is None
        or validate_hwpx_document_plan is None
    ):
        raise RuntimeError(
            "installed python-hwpx does not provide comparison table generation"
        )
    old_source, new_source = _diff_sources(
        old_filename=old_filename,
        new_filename=new_filename,
        old_paragraphs=old_paragraphs,
        new_paragraphs=new_paragraphs,
    )
    document_plan = build_hwpx_comparison_table_plan(
        old_source,
        new_source,
        title=title,
        include_equal=include_equal,
    )
    validation = validate_hwpx_document_plan(document_plan)
    if not validation.ok:
        return {
            "filename": filename,
            "created": False,
            "error": "comparison table plan failed validation",
            "plan_validation": validation.to_dict(),
        }
    path = resolve_path(filename)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    doc = build_document_from_plan(document_plan, preset="government_report")
    try:
        verification = _save_generated_document(doc, path)
    finally:
        doc.close()
    result = {
        "filename": filename,
        "created": True,
        "document_plan": document_plan,
        "plan_validation": validation.to_dict(),
        "verification": verification,
        "openSafety": verification.get("openSafety"),
    }
    return _apply_write_verbosity(result, verbosity)


def create_proposal_document(
    filename: str,
    proposal_spec: dict,
    style_preset: str = "clean_korean_proposal",
    verbosity: str = "compact",
) -> dict:
    """자연어에서 추출한 proposal_spec으로 제안서형 HWPX 문서를 생성합니다."""
    path = resolve_path(filename)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    doc = (
        build_proposal_document(proposal_spec or {}, preset=style_preset)
        if build_proposal_document is not None
        else create_quality_document_fallback(proposal_spec or {})
    )
    try:
        verification = _save_generated_document(doc, path)
    finally:
        doc.close()

    report = (
        inspect_proposal_document_quality(path)
        if inspect_proposal_document_quality is not None
        else _proposal_quality_fallback(path)
    )
    result = {
        "filename": filename,
        "created": True,
        "style_preset": style_preset,
        "quality": report,
        "verification": verification,
    }
    return _apply_write_verbosity(result, verbosity)


def copy_document(source_filename: str, destination_filename: str = None) -> dict:
    """HWPX 문서를 새 경로로 복사합니다. 원본은 유지됩니다."""
    source = resolve_path(source_filename)
    destination = destination_filename
    if destination_filename is not None:
        destination = resolve_path(destination_filename)
    dest = copy_document_file(source, destination)
    open_safety = build_hwpx_open_safety_report(Path(dest))
    return {
        "source": source_filename,
        "destination": os.path.basename(dest),
        "openSafety": open_safety,
    }


__all__ = [
    "create_document",
    "create_document_from_plan",
    "copy_document",
    "create_government_report_document",
    "create_proposal_document",
    "create_comparison_table_document",
    "get_document_plan_schema",
    "validate_document_plan",
    "analyze_document_plan",
    "markdown_to_document_plan",
    "parse_government_report_text",
    "compute_report_value",
    "register_template",
    "list_templates",
    "describe_template",
]
