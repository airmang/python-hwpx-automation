# SPDX-License-Identifier: Apache-2.0
"""Curated, MCP-independent task API for :mod:`hwpx_automation`.

Deep modules remain available for advanced users, but this facade is the
stable entry point promised by the ``python-hwpx-automation`` distribution.
"""

from __future__ import annotations

from typing import Any, Mapping

from .form_fill import (
    CanonicalFormFillInput,
    FormFillAnalyzeOptions,
    FormFillPlanInput,
    analyze_form_fill_workflow,
    apply_form_fill_workflow,
)
from .office.authoring import (
    DocumentPlan,
    DocumentStylePreset,
    create_document_from_plan,
    normalize_document_plan,
    validate_document_plan,
)
from .office.evalplan import (
    EvalPlanContent,
    Rubric,
    fill_evalplan,
    finalize_evalplan,
    parse_review_file,
    parse_review_md,
)
from .office.exam import ComposeResult, compose_exam_into_form, parse_exam_markdown


def analyze_form_fill(
    *,
    source_filename: str,
    input_json: CanonicalFormFillInput | dict[str, Any] | str | None = None,
    input_json_path: str | None = None,
    input_docx: str | None = None,
    destination_filename: str | None = None,
    options: FormFillAnalyzeOptions | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Analyze form fill without mutation and return a serializable plan.

    Paths are resolved through the configured workspace boundary. Invalid or
    ambiguous input raises the same typed/structured errors as the underlying
    automation service; callers should not treat a partial plan as applied.
    """

    return analyze_form_fill_workflow(
        source_filename=source_filename,
        input_json=input_json,
        input_json_path=input_json_path,
        input_docx=input_docx,
        destination_filename=destination_filename,
        options=options,
    )


def apply_form_fill(
    *,
    plan_id: str | None = None,
    analysis: FormFillPlanInput | dict[str, Any] | None = None,
    source_filename: str | None = None,
    destination_filename: str | None = None,
    canonical_input: CanonicalFormFillInput | dict[str, Any] | str | None = None,
    confirm: bool = True,
    mask: bool = True,
) -> dict[str, Any]:
    """Apply a reviewed plan to a distinct destination and validate it.

    Source-in-place writes and ``confirm=False`` fail before publication.
    Unresolved mappings return a blocked handoff instead of a partial write.
    """

    return apply_form_fill_workflow(
        plan_id=plan_id,
        analysis=analysis,
        source_filename=source_filename,
        destination_filename=destination_filename,
        canonical_input=canonical_input,
        confirm=confirm,
        mask=mask,
    )


def compose_exam(
    form_path: str,
    exam_markdown: str,
    output_path: str,
    *,
    oracle: Any = None,
    max_rounds: int = 2,
    role_style_names: Mapping[str, str] | None = None,
) -> ComposeResult:
    """Compose exam Markdown into a destination form with honest render state."""

    return compose_exam_into_form(
        form_path,
        exam_markdown,
        output_path,
        oracle=oracle,
        max_rounds=max_rounds,
        role_style_names=role_style_names,
    )


def parse_evalplan_review(source: str, *, from_file: bool = False) -> EvalPlanContent:
    """Parse evaluation-plan review Markdown from text or a file path."""

    return parse_review_file(source) if from_file else parse_review_md(source)


__all__ = [
    "CanonicalFormFillInput",
    "ComposeResult",
    "DocumentPlan",
    "DocumentStylePreset",
    "EvalPlanContent",
    "FormFillAnalyzeOptions",
    "FormFillPlanInput",
    "Rubric",
    "analyze_form_fill",
    "apply_form_fill",
    "compose_exam",
    "create_document_from_plan",
    "fill_evalplan",
    "finalize_evalplan",
    "normalize_document_plan",
    "parse_evalplan_review",
    "parse_exam_markdown",
    "validate_document_plan",
]
