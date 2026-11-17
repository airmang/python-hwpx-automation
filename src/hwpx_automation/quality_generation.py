# SPDX-License-Identifier: Apache-2.0
"""Automation-owned HWPX quality-generation workflow.

The workflow is intentionally centered in ``python-hwpx-automation`` rather
than the core ``python-hwpx`` package. It lets agents start from a form HWPX plus an
idea/brief, apply a built-in quality profile, generate a candidate document,
inspect quality, and return revision evidence without requiring a per-run
quality-sample file.
"""

from __future__ import annotations

import copy
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any, Mapping

try:  # python-hwpx >= 2.10.3
    from hwpx.tools.package_validator import validate_package
except Exception as exc:  # pragma: no cover - depends on installed python-hwpx
    validate_package = None
    _PACKAGE_VALIDATOR_IMPORT_ERROR: Exception | None = exc
else:
    _PACKAGE_VALIDATOR_IMPORT_ERROR = None

from .core.document import open_doc
from .storage import build_hwpx_open_safety_report
from .upstream import new_document, validate_document_path
from .utils.helpers import resolve_path

try:  # python-hwpx >= proposal preset feature
    from .office.authoring.presets import (
        create_proposal_document,
        inspect_proposal_quality,
    )
except Exception:  # pragma: no cover - optional dependency compatibility
    create_proposal_document = None
    inspect_proposal_quality = None

_QUALITY_GENERATION_SCHEMA_VERSION = "hwpx.quality-generation.v1"
_DEFAULT_PROFILE_NAME = "korean_ai_school_application_v1"
_QUALITY_PLANS: dict[str, dict[str, Any]] = {}

_DEFAULT_SECTION_TITLES = (
    "추진 배경 및 필요성",
    "운영 목표",
    "세부 운영 계획",
    "AI 교육과정 편성 및 운영",
    "교원 역량 강화 계획",
    "성과 관리 및 확산 계획",
)
# HWPX table sizes are stored in HWP units.  The upstream default is compact
# for generated form fragments, so use a near-page-width table for readable
# front-matter and budget tables in the quality-generation fallback path.
_READABLE_TABLE_WIDTH = 95_000

_BUILT_IN_PROFILE: dict[str, Any] = {
    "name": _DEFAULT_PROFILE_NAME,
    "ordinary_input_contract": ["form_filename", "idea_brief"],
    "quality_sample_required": False,
    "target_document_traits": {
        "front_matter": "readable document information block near the beginning",
        "heading_hierarchy": "clear numbered sections with short headings",
        "table_usage": "use tables for budget/resource or other structured plans when they improve readability",
        "paragraph_rhythm": "short Korean business-document paragraphs plus bullets",
        "style_tokens": "bounded reusable semantic run styles instead of many one-off styles",
        "validation": "output must reopen and pass package/document validation",
    },
    "minimum_quality": {
        "rubric_average": 4.0,
        "sample_match_average": 4.0,
        "validation_pass": True,
    },
    "revision_policy": {
        "max_default_revision_rounds": 1,
        "deterministic_fixes": [
            "ensure executive summary",
            "ensure required section outline",
            "ensure budget/resource table",
            "ensure expected outcomes",
            "ensure closing/declaration block",
        ],
    },
    "non_goals": [
        "binary .hwp conversion/editing",
        "complex layout reproduction",
        "pixel-perfect rendered parity",
        "per-run target-quality sample requirement",
    ],
}


def analyze_quality_generation_workflow(
    *,
    form_filename: str,
    idea_brief: str | Mapping[str, Any],
    destination_filename: str | None = None,
    quality_profile: str = _DEFAULT_PROFILE_NAME,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a non-mutating generation plan from a form and idea/brief."""

    form_path = resolve_path(form_filename)
    destination_path = resolve_path(destination_filename) if destination_filename else None
    doc = open_doc(form_path)
    outline = _document_outline(doc)
    tables = _table_summaries(doc)
    styles = _style_summary(doc)
    content_spec = _normalize_content_spec(idea_brief, outline=outline)
    plan_id = f"qg_{uuid.uuid4().hex[:16]}"
    profile = _quality_profile(quality_profile)
    analysis: dict[str, Any] = {
        "plan_id": plan_id,
        "schemaVersion": _QUALITY_GENERATION_SCHEMA_VERSION,
        "quality_profile": profile,
        "quality_sample_required": False,
        "inputs": {
            "form": {"filename": form_filename, "path": form_path},
            "idea_brief_kind": "mapping" if isinstance(idea_brief, Mapping) else "text",
            "destination": {
                "filename": destination_filename,
                "path": destination_path,
                "required_for_apply": bool(destination_filename),
            },
        },
        "form_analysis": {
            "paragraph_count": len(getattr(doc, "paragraphs", [])),
            "table_count": len(tables),
            "outline": outline,
            "tables": tables,
            "styles": styles,
            "unsupported": _unsupported_form_traits(doc),
        },
        "content_spec": content_spec,
        "generation_plan": _generation_plan(content_spec, profile=profile),
        "quality_gates": _quality_gates(profile),
        "mutated": False,
        "next_tool": "apply_quality_generation",
        "options": options or {},
    }
    _QUALITY_PLANS[plan_id] = copy.deepcopy(analysis)
    return analysis


def apply_quality_generation_workflow(
    *,
    plan_id: str | None = None,
    analysis: dict[str, Any] | None = None,
    form_filename: str | None = None,
    destination_filename: str | None = None,
    idea_brief: str | Mapping[str, Any] | None = None,
    max_revision_rounds: int = 1,
    confirm: bool = True,
) -> dict[str, Any]:
    """Generate an HWPX output, inspect quality, and run deterministic revisions."""

    if not confirm:
        raise ValueError("confirm must be true to apply quality generation")
    plan = _resolve_plan(plan_id=plan_id, analysis=analysis)
    if idea_brief is not None:
        plan["content_spec"] = _normalize_content_spec(
            idea_brief,
            outline=plan.get("form_analysis", {}).get("outline", []),
        )
        plan["generation_plan"] = _generation_plan(
            plan["content_spec"],
            profile=plan.get("quality_profile") or _quality_profile(_DEFAULT_PROFILE_NAME),
        )
    source_filename = form_filename or plan.get("inputs", {}).get("form", {}).get("path")
    if not source_filename:
        raise ValueError("form_filename is required")
    destination = _destination_from_plan(plan, destination_filename)
    Path(destination).parent.mkdir(parents=True, exist_ok=True)

    rounds: list[dict[str, Any]] = []
    content_spec = copy.deepcopy(plan["content_spec"])
    rounds.append(_write_and_inspect(destination, content_spec, revision_round=0))
    remaining = max(0, int(max_revision_rounds))
    while remaining and not rounds[-1]["quality"]["pass"]:
        content_spec = _revise_content_spec(content_spec, rounds[-1]["quality"]["gaps"])
        rounds.append(_write_and_inspect(destination, content_spec, revision_round=len(rounds)))
        remaining -= 1

    final = rounds[-1]
    return {
        "handoff_status": "ready" if final["quality"]["pass"] else "needs_revision",
        "schemaVersion": _QUALITY_GENERATION_SCHEMA_VERSION,
        "plan_id": plan.get("plan_id"),
        "quality_sample_required": False,
        "source": {
            "form_filename": form_filename,
            "form_path": str(resolve_path(str(source_filename))),
        },
        "destination": {
            "path": destination,
            "created": Path(destination).exists(),
        },
        "quality_profile": plan.get("quality_profile") or _quality_profile(_DEFAULT_PROFILE_NAME),
        "content_spec": content_spec,
        "revision_history": rounds,
        "quality": final["quality"],
        "validation": final["validation"],
        "next_action": (
            "use generated file"
            if final["quality"]["pass"]
            else "review quality.gaps and rerun with a richer idea_brief/content_spec"
        ),
    }


def _resolve_plan(*, plan_id: str | None, analysis: dict[str, Any] | None) -> dict[str, Any]:
    if analysis is not None:
        return copy.deepcopy(analysis)
    if plan_id is None:
        raise ValueError("provide plan_id or analysis")
    try:
        return copy.deepcopy(_QUALITY_PLANS[plan_id])
    except KeyError as exc:
        raise ValueError(f"unknown quality-generation plan_id: {plan_id}") from exc


def _destination_from_plan(plan: Mapping[str, Any], override: str | None) -> str:
    if override:
        return resolve_path(override)
    destination = (plan.get("inputs") or {}).get("destination") or {}
    path = destination.get("path") or destination.get("filename")
    if not path:
        raise ValueError("destination_filename is required")
    return resolve_path(str(path))


def _quality_profile(name: str) -> dict[str, Any]:
    if name != _DEFAULT_PROFILE_NAME:
        profile = copy.deepcopy(_BUILT_IN_PROFILE)
        profile["name"] = str(name)
        profile["base_profile"] = _DEFAULT_PROFILE_NAME
        return profile
    return copy.deepcopy(_BUILT_IN_PROFILE)


def _normalize_content_spec(
    idea_brief: str | Mapping[str, Any],
    *,
    outline: list[dict[str, Any]],
) -> dict[str, Any]:
    if isinstance(idea_brief, Mapping):
        payload = copy.deepcopy(dict(idea_brief))
    else:
        payload = {"idea_brief": str(idea_brief or "").strip()}

    raw_brief = str(payload.get("idea_brief") or payload.get("brief") or "").strip()
    title = str(payload.get("title") or "").strip()
    if not title:
        title = _derive_title(raw_brief, outline)
    organization = str(payload.get("organization") or payload.get("school") or "신청 기관").strip()
    author = str(payload.get("author") or payload.get("team") or "AI 중점학교 운영팀").strip()
    date = str(payload.get("date") or "2026").strip()
    sections = _normalize_sections(payload.get("sections"), raw_brief=raw_brief, outline=outline)
    executive_summary = str(payload.get("executive_summary") or payload.get("summary") or "").strip()
    if not executive_summary:
        executive_summary = _derive_summary(raw_brief, title=title)
    budget_items = _normalize_budget_items(payload.get("budget_items"))
    expected_outcomes = _string_list(payload.get("expected_outcomes") or payload.get("outcomes") or [])
    if not expected_outcomes:
        expected_outcomes = [
            "학생의 AI 기초 소양과 문제 해결 역량을 체계적으로 강화한다.",
            "교원의 AI 활용 수업 설계 역량을 높이고 학교 내 실행 사례를 확산한다.",
        ]
    closing = str(payload.get("closing") or "").strip() or "본 계획을 바탕으로 AI 중점학교 운영을 성실히 추진하고 성과를 공유하겠습니다."

    return {
        "title": title,
        "subtitle": str(payload.get("subtitle") or "양식 기반 AI 중점학교 운영계획서").strip(),
        "organization": organization,
        "author": author,
        "date": date,
        "metadata": {
            **{str(k): str(v) for k, v in dict(payload.get("metadata") or {}).items()},
            "문서유형": str(payload.get("document_type") or "신청서 및 운영계획서"),
            "생성방식": "MCP 품질 파이프라인",
        },
        "executive_summary": executive_summary,
        "sections": sections,
        "budget_items": budget_items,
        "expected_outcomes": expected_outcomes,
        "closing": closing,
        "source_brief": raw_brief,
    }


def _bullet_shape(doc: Any) -> str:
    """Hancom's own bullet (a ``hh:bullet`` definition) for a list item, not a typed ``•``."""

    from .office.authoring import bullet_paragraph_shape

    return bullet_paragraph_shape(doc)


def _derive_title(raw_brief: str, outline: list[dict[str, Any]]) -> str:
    for item in outline:
        text = str(item.get("text") or "").strip()
        if "AI" in text and len(text) <= 80:
            return text
    if raw_brief:
        first = re.split(r"[.\n]", raw_brief, maxsplit=1)[0].strip()
        if 8 <= len(first) <= 80:
            return first
    return "2026년 AI 중점학교 신청서 및 운영계획서"


def _derive_summary(raw_brief: str, *, title: str) -> str:
    if raw_brief:
        compact = " ".join(raw_brief.split())
        return compact[:220]
    return f"{title}의 운영 목표, 교육과정 편성, 교원 역량 강화, 성과 확산 계획을 구조화해 제시합니다."


def _normalize_sections(value: Any, *, raw_brief: str, outline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(value, list) and value:
        sections: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, Mapping):
                title = str(item.get("title") or "").strip()
                if title:
                    sections.append(
                        {
                            "title": title,
                            "paragraphs": _string_list(item.get("paragraphs") or item.get("body") or []),
                            "bullets": _string_list(item.get("bullets") or []),
                        }
                    )
        if sections:
            return sections

    hints = [str(item.get("text") or "").strip() for item in outline if str(item.get("text") or "").strip()]
    selected_titles = _DEFAULT_SECTION_TITLES
    if hints:
        plausible = [text for text in hints if 5 <= len(text) <= 60 and not text.startswith("[")]
        if len(plausible) >= 3:
            selected_titles = tuple(plausible[:6])
    brief_sentence = _derive_summary(raw_brief, title="운영계획")
    return [
        {
            "title": title,
            "paragraphs": [f"{title}은(는) 학교 여건과 신청 양식의 요구 항목을 반영해 {brief_sentence}"],
            "bullets": [
                "담당자와 추진 일정을 명확히 지정한다.",
                "운영 결과를 점검하고 다음 단계 개선에 반영한다.",
            ],
        }
        for title in selected_titles
    ]


def _normalize_budget_items(value: Any) -> list[dict[str, str]]:
    if isinstance(value, list) and value:
        items = []
        for item in value:
            if isinstance(item, Mapping):
                items.append({str(k): str(v) for k, v in item.items()})
        if items:
            return items
    return [
        {"item": "AI 교육 운영비", "amount": "계획 수립 후 확정", "note": "수업 운영 및 산출물 제작"},
        {"item": "교원 역량 강화", "amount": "계획 수립 후 확정", "note": "연수 및 컨설팅"},
    ]


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _document_outline(doc: Any) -> list[dict[str, Any]]:
    outline = []
    for index, para in enumerate(getattr(doc, "paragraphs", [])):
        text = (getattr(para, "text", None) or "").strip()
        if not text:
            continue
        if len(text) <= 90 or _looks_like_heading(text):
            outline.append({"paragraph_index": index, "text": text, "level": 1 if _looks_like_heading(text) else 2})
    return outline[:40]


def _looks_like_heading(text: str) -> bool:
    return bool(re.match(r"^([0-9]+[.)]|[ⅠⅡⅢⅣⅤ]+[.]?|[가-하][.)]|[□■○●])\\s*", text)) or len(text) < 35


def _table_summaries(doc: Any) -> list[dict[str, Any]]:
    tables = []
    for paragraph in getattr(doc, "paragraphs", []):
        for table in getattr(paragraph, "tables", []):
            rows = getattr(table, "rows", [])
            sample_rows = []
            for row in rows[:3]:
                cells = [str(getattr(cell, "text", "") or "").strip() for cell in getattr(row, "cells", [])[:4]]
                sample_rows.append(cells)
            tables.append(
                {
                    "index": len(tables),
                    "rows": len(rows),
                    "cols": max((len(getattr(row, "cells", [])) for row in rows), default=0),
                    "sample_rows": sample_rows,
                }
            )
    return tables


def _style_summary(doc: Any) -> dict[str, Any]:
    used_ids: set[str] = set()
    # iter_runs/char_properties moved under doc.text/doc.styles (design
    # §2.4/§2.6) — drill through the namespace defensively, same as the
    # surrounding getattr(doc, ...) calls in this module, in case doc is a
    # duck-typed stand-in without the full namespace surface.
    text_ns = getattr(doc, "text", None)
    for run in getattr(text_ns, "runs", lambda: [])():
        style_id = getattr(run, "char_pr_id_ref", None)
        if style_id:
            used_ids.add(str(style_id))
    styles_ns = getattr(doc, "styles", {})
    return {
        "available_char_style_count": len(getattr(styles_ns, "char_properties", {})),
        "available_paragraph_style_count": len(styles_ns),
        "used_run_style_ids": sorted(used_ids),
        "used_run_style_count": len(used_ids),
    }


def _unsupported_form_traits(doc: Any) -> list[dict[str, Any]]:
    unsupported = []
    for table in _table_summaries(doc):
        if table["cols"] > 8:
            unsupported.append(
                {
                    "kind": "wide-table",
                    "table_index": table["index"],
                    "reason": "v1 does not attempt complex layout reproduction",
                }
            )
    return unsupported


def _generation_plan(content_spec: Mapping[str, Any], *, profile: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "strategy": "proposal-preset-backed-quality-generation",
        "profile": profile.get("name"),
        "builder": "hwpx.presets.create_proposal_document",
        "inspector": "hwpx.presets.inspect_proposal_quality",
        "required_sections": [section.get("title") for section in content_spec.get("sections", [])],
        "revision_policy": profile.get("revision_policy", {}),
    }


def _quality_gates(profile: Mapping[str, Any]) -> dict[str, Any]:
    minimum = profile.get("minimum_quality") or {}
    return {
        "rubric_average_min": minimum.get("rubric_average", 4.0),
        "sample_match_average_min": minimum.get("sample_match_average", 4.0),
        "validation_required": bool(minimum.get("validation_pass", True)),
    }


def _write_and_inspect(destination: str, content_spec: Mapping[str, Any], *, revision_round: int) -> dict[str, Any]:
    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{destination_path.stem}.",
        suffix=destination_path.suffix or ".hwpx",
        dir=str(destination_path.parent),
    )
    tmp_path = Path(tmp_name)
    os.close(fd)
    doc = None
    try:
        doc = (
            create_proposal_document(content_spec)
            if create_proposal_document is not None
            else _create_quality_document_fallback(content_spec)
        )
        # Phase F: this user-file commit funnels through the one SavePipeline gate.
        from . import quality as quality_contract

        quality_contract.assert_write_capability()
        quality_contract.save_through_pipeline(doc, tmp_path)
        report = (
            inspect_proposal_quality(str(tmp_path))
            if inspect_proposal_quality is not None
            else _inspect_quality_fallback(str(tmp_path))
        )
        validation = _runtime_validation(str(tmp_path))
        if not validation.get("openSafety", {}).get("ok"):
            raise RuntimeError(
                "quality-generation output failed open-safety verification: "
                + str(validation.get("openSafety", {}).get("summary", "unknown failure"))
            )
        os.replace(tmp_path, destination_path)
    finally:
        tmp_path.unlink(missing_ok=True)
        if doc is not None:
            doc.close()
    quality = _quality_result(report, validation)
    return {
        "round": revision_round,
        "destination": destination,
        "quality": quality,
        "validation": validation,
        "report": report,
    }


def _create_quality_document_fallback(content_spec: Mapping[str, Any]) -> Any:
    """Create a presentable document when proposal presets are unavailable."""

    doc = new_document()
    title_style = doc.styles.ensure_run(bold=True)
    heading_style = doc.styles.ensure_run(bold=True, underline=True)
    body_style = doc.styles.ensure_run()
    table_header_style = doc.styles.ensure_run(bold=True)
    callout_style = doc.styles.ensure_run(bold=True)

    doc.add_paragraph(str(content_spec.get("title") or "운영계획서"), char_pr_id_ref=title_style)
    subtitle = str(content_spec.get("subtitle") or "")
    if subtitle:
        doc.add_paragraph(subtitle, char_pr_id_ref=callout_style)

    metadata = dict(content_spec.get("metadata") or {})
    for key in ("organization", "author", "date"):
        if content_spec.get(key):
            metadata.setdefault({"organization": "기관", "author": "작성", "date": "연도"}[key], str(content_spec[key]))
    if metadata:
        doc.add_paragraph("문서 정보", char_pr_id_ref=heading_style)
        for key, value in metadata.items():
            doc.add_paragraph(f"{key}: {value}", char_pr_id_ref=body_style)

    summary = str(content_spec.get("executive_summary") or "")
    if summary:
        doc.add_paragraph("핵심 요약", char_pr_id_ref=heading_style)
        doc.add_paragraph(summary, char_pr_id_ref=callout_style)

    for index, section in enumerate(content_spec.get("sections") or [], start=1):
        if not isinstance(section, Mapping):
            continue
        title = str(section.get("title") or f"섹션 {index}")
        doc.add_paragraph(f"{index}. {title}", char_pr_id_ref=heading_style)
        for paragraph in _string_list(section.get("paragraphs") or []):
            doc.add_paragraph(paragraph, char_pr_id_ref=body_style)
        for bullet in _string_list(section.get("bullets") or []):
            doc.add_paragraph(bullet, char_pr_id_ref=body_style, para_pr_id_ref=_bullet_shape(doc))

    budget_items = [item for item in content_spec.get("budget_items") or [] if isinstance(item, Mapping)]
    if budget_items:
        doc.add_paragraph("예산 및 자원 계획", char_pr_id_ref=heading_style)
        from .markdown._import import document_font_writer, draw_table

        rows = [["항목", "금액", "비고"]] + [
            [str(item.get("item", "")), str(item.get("amount", "")), str(item.get("note", ""))]
            for item in budget_items
        ]
        table = doc.add_table(len(rows), 3, width=_READABLE_TABLE_WIDTH)
        # The shared table look (8.0), in the document's own type.
        draw_table(doc, table, rows, header=True, style="report", write=document_font_writer(doc))

    outcomes = _string_list(content_spec.get("expected_outcomes") or [])
    if outcomes:
        doc.add_paragraph("기대 효과", char_pr_id_ref=heading_style)
        for outcome in outcomes:
            doc.add_paragraph(outcome, char_pr_id_ref=body_style, para_pr_id_ref=_bullet_shape(doc))

    closing = str(content_spec.get("closing") or "")
    if closing:
        doc.add_paragraph("마무리", char_pr_id_ref=heading_style)
        doc.add_paragraph(closing, char_pr_id_ref=body_style)

    # Keep an otherwise-unused style token visible in the package for quality
    # reports that expect a bounded semantic style vocabulary.
    del table_header_style
    return doc


def _inspect_quality_fallback(path: str) -> dict[str, Any]:
    doc = open_doc(path)
    try:
        texts = [(getattr(paragraph, "text", "") or "").strip() for paragraph in getattr(doc, "paragraphs", [])]
        joined = "\n".join(text for text in texts if text)
        tables = len(_table_summaries(doc))
        validation = validate_document_path(path)
        style_usage = _style_summary(doc)
    finally:
        close = getattr(doc, "close", None)
        if callable(close):
            close()

    required = {
        "title": bool(joined.strip()),
        "metadata": "문서 정보" in joined or tables >= 1,
        "executive_summary": "요약" in joined,
        "body_sections": sum(1 for text in texts if _looks_like_heading(text)) >= 4,
        "budget": "예산" in joined or "자원" in joined,
        "expected_outcomes": "기대 효과" in joined or "성과" in joined,
        "closing": "마무리" in joined or "추진" in joined,
    }
    style_count = int(style_usage.get("used_run_style_count", 0))
    scores = {
        "outline": 5.0 if required["body_sections"] else 2.5,
        "tables": 5.0 if tables >= 2 else (4.0 if tables == 1 else 2.0),
        "content": 5.0 * sum(required.values()) / len(required),
        "style_tokens": 5.0 if style_count >= 4 else (4.0 if style_count >= 3 else 3.0),
        "validation": 5.0 if validation.ok else 2.0,
    }
    average = round(sum(scores.values()) / len(scores), 2)
    failed = [name for name, present in required.items() if not present]
    return {
        "pass": average >= 4.0 and validation.ok and not failed,
        "report_version": "quality-generation-fallback-v1",
        "outline": {"required_sections_present": not failed, "required": required},
        "table_checks": {"table_count": tables, "has_structured_tables": tables >= 1},
        "style_token_usage": style_usage,
        "sample_match": {
            "average": average,
            "pass": average >= 4.0 and not failed,
            "visual_review_required": True,
            "dimensions": {},
        },
        "rubric_scores": scores,
        "rubric_average": average,
        "gaps": [f"missing required quality trait: {name}" for name in failed],
    }


def _runtime_validation(path: str) -> dict[str, Any]:
    if validate_package is None:
        package_payload = _dependency_unavailable_validation(
            "python-hwpx>=2.10.3 is required for HWPX package validation",
            _PACKAGE_VALIDATOR_IMPORT_ERROR,
        )
    else:
        package = validate_package(path)
        package_payload = {"ok": bool(package.ok), "errors": _report_errors(package)}
    document = validate_document_path(path)
    open_safety = build_hwpx_open_safety_report(Path(path))
    reopened = False
    try:
        doc = open_doc(path)
        reopened = bool(doc.paragraphs is not None)
        close = getattr(doc, "close", None)
        if callable(close):
            close()
    except Exception:
        reopened = False
    return {
        "reopened": reopened,
        "validate_package": package_payload,
        "validate_document": {"ok": bool(document.ok), "errors": _report_errors(document)},
        "openSafety": open_safety,
    }


def _dependency_unavailable_validation(message: str, error: Exception | None) -> dict[str, Any]:
    detail = f"{message}: {error}" if error is not None else message
    return {"ok": False, "errors": [detail]}


def _report_errors(report: Any) -> list[Any]:
    for attr in ("errors", "issues", "messages"):
        value = getattr(report, attr, None)
        if value is not None:
            try:
                return list(value)
            except TypeError:
                return [value]
    return []


def _quality_result(report: Mapping[str, Any], validation: Mapping[str, Any]) -> dict[str, Any]:
    sample_match = report.get("sample_match") or {}
    gaps = list(report.get("gaps") or [])
    if not validation.get("reopened"):
        gaps.append("generated document could not be reopened")
    if not validation.get("validate_package", {}).get("ok"):
        gaps.append("package validation failed")
    if not validation.get("validate_document", {}).get("ok"):
        gaps.append("document validation failed")
    if not validation.get("openSafety", {}).get("ok"):
        gaps.append("editor-open safety validation failed")
    passed = bool(
        report.get("pass")
        and validation.get("reopened")
        and validation.get("validate_package", {}).get("ok")
        and validation.get("validate_document", {}).get("ok")
        and validation.get("openSafety", {}).get("ok")
    )
    return {
        "pass": passed,
        "rubric_average": report.get("rubric_average"),
        "sample_match_average": sample_match.get("average"),
        "sample_match_pass": sample_match.get("pass"),
        "visual_review_required": sample_match.get("visual_review_required", True),
        "gaps": gaps,
        "revision_recommended": not passed,
    }


def _revise_content_spec(content_spec: Mapping[str, Any], gaps: list[str]) -> dict[str, Any]:
    revised = copy.deepcopy(dict(content_spec))
    sections = list(revised.get("sections") or [])
    existing_titles = {str(section.get("title")) for section in sections if isinstance(section, Mapping)}
    for title in _DEFAULT_SECTION_TITLES:
        if title not in existing_titles:
            sections.append(
                {
                    "title": title,
                    "paragraphs": [f"{title}을(를) 보강해 운영 계획의 완성도를 높입니다."],
                    "bullets": ["세부 실행 과제를 정리한다.", "성과 확인 방법을 포함한다."],
                }
            )
    revised["sections"] = sections
    if not revised.get("executive_summary"):
        revised["executive_summary"] = _derive_summary(str(revised.get("source_brief") or ""), title=str(revised.get("title") or "운영계획"))
    if not revised.get("budget_items"):
        revised["budget_items"] = _normalize_budget_items([])
    if not revised.get("expected_outcomes"):
        revised["expected_outcomes"] = [
            "AI 기반 수업 혁신 사례를 축적한다.",
            "학생 맞춤형 학습 지원 체계를 강화한다.",
        ]
    revised.setdefault("revision_notes", []).append({"reason": "quality gaps", "gaps": list(gaps)})
    return revised


# Compatibility helpers for MCP tools whose installed python-hwpx build may
# not yet include proposal presets.  Keep the actual implementation private so
# the quality-generation workflow remains the owner of this fallback behavior.
create_quality_document_fallback = _create_quality_document_fallback
inspect_quality_fallback = _inspect_quality_fallback
