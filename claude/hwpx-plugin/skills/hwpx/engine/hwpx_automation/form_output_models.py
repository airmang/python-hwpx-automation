# SPDX-License-Identifier: Apache-2.0
"""Typed public outputs for canonical and compatibility form tools.

The server keeps returning ordinary dictionaries.  These models are bound as
return annotations so FastMCP validates those dictionaries and publishes the
same closed output contract that callers actually receive.  Legacy form-fill
responses intentionally keep an open payload because their long-standing
compatibility fields vary by route; their identifying compatibility envelope
remains typed so they cannot silently accept a malformed canonical response.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

from .mixed_form import (
    FormVerificationReceipt,
    MixedFormCompiledPlanInput,
    MixedFormResolution,
)


_REVISION_PATTERN = r"^sha256:[0-9a-f]{64}$"


class _StrictOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class _LegacyOutput(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class _AnalysisSource(_StrictOutput):
    filename: str
    revision: str = Field(pattern=_REVISION_PATTERN)
    unchanged_after_analysis: Literal[True] = Field(alias="unchangedAfterAnalysis")


class _AnalysisOutputRef(_StrictOutput):
    filename: str
    unchanged_after_analysis: Literal[True] = Field(alias="unchangedAfterAnalysis")


class CanonicalMixedFormAnalysisOutput(_StrictOutput):
    schema_version: Literal["hwpx.mixed-form-analysis/v1"] = Field(
        alias="schemaVersion"
    )
    mutated: Literal[False]
    source: _AnalysisSource
    output: _AnalysisOutputRef
    compiled_plan: MixedFormCompiledPlanInput = Field(alias="compiledPlan")
    plan_hash: str = Field(alias="planHash", pattern=_REVISION_PATTERN)
    request_hash: str = Field(alias="requestHash", pattern=_REVISION_PATTERN)
    resolutions: list[MixedFormResolution]
    open_safety: dict[str, Any] = Field(alias="openSafety")
    next_tool: Literal["apply_form_fill"] = Field(alias="nextTool")


class _LegacyFormFillCompatibility(_StrictOutput):
    schema_version: Literal["hwpx.formfill.v1"] = Field(alias="schemaVersion")
    status: Literal["retained"]
    canonical_input: str = Field(alias="canonicalInput", min_length=1)


class LegacyFormFillAnalysisOutput(_LegacyOutput):
    schema_version: Literal["hwpx.formfill.v1"] = Field(alias="schemaVersion")
    plan_id: str = Field(min_length=1)
    mutated: Literal[False]
    compatibility: _LegacyFormFillCompatibility


class AnalyzeFormFillOutput(
    RootModel[CanonicalMixedFormAnalysisOutput | LegacyFormFillAnalysisOutput]
):
    """Canonical analysis or the retained ``hwpx.formfill.v1`` response."""


class _AgentOutputRef(_StrictOutput):
    filename: str


class _PublicCommandResult(_StrictOutput):
    command_id: str = Field(alias="commandId", min_length=1)
    op: str = Field(min_length=1)
    ok: bool
    path: str | None = None
    parent_path: str | None = Field(default=None, alias="parentPath")
    warning_count: int = Field(alias="warningCount", ge=0)
    changed_property_names: list[str] = Field(alias="changedPropertyNames")
    generated_identity_count: int = Field(alias="generatedIdentityCount", ge=0)


class CanonicalMixedFormApplyOutput(_StrictOutput):
    schema_version: Literal["hwpx.agent-batch-result/v1"] = Field(
        alias="schemaVersion"
    )
    ok: bool
    rolled_back: bool = Field(alias="rolledBack")
    dry_run: bool = Field(alias="dryRun")
    input_revision: str = Field(alias="inputRevision", pattern=_REVISION_PATTERN)
    document_revision: str | None = Field(
        alias="documentRevision",
        pattern=_REVISION_PATTERN,
    )
    output: _AgentOutputRef
    command_results: list[_PublicCommandResult] = Field(alias="commandResults")
    semantic_diff: dict[str, Any] = Field(alias="semanticDiff")
    verification_report: dict[str, Any] = Field(alias="verificationReport")
    error: dict[str, Any] | None = None
    plan_hash: str = Field(alias="planHash", pattern=_REVISION_PATTERN)
    request_hash: str = Field(alias="requestHash", pattern=_REVISION_PATTERN)
    resolutions: list[MixedFormResolution]
    verification_receipt: FormVerificationReceipt = Field(
        alias="verificationReceipt"
    )
    open_safety: dict[str, Any] = Field(alias="openSafety")


class LegacyFormFillApplyOutput(_LegacyOutput):
    handoff_status: Literal["ready", "blocked"]
    compatibility: _LegacyFormFillCompatibility


class ApplyFormFillOutput(
    RootModel[CanonicalMixedFormApplyOutput | LegacyFormFillApplyOutput]
):
    """Canonical atomic apply or the retained ``hwpx.formfill.v1`` response."""


class _LegacyRenderCompatibility(_StrictOutput):
    status: Literal["retained-render-verifier"]
    canonical_input: Literal["plan: hwpx.mixed-form-compiled-plan/v1"] = Field(
        alias="canonicalInput"
    )


class LegacyFormFillVerifyOutput(_LegacyOutput):
    render_checked: bool = Field(alias="renderChecked")
    ok: bool
    compatibility: _LegacyRenderCompatibility


class VerifyFormFillOutput(
    RootModel[FormVerificationReceipt | LegacyFormFillVerifyOutput]
):
    """Canonical receipt or the retained two-file render verifier response."""


class _SpecializedCompatibility(_StrictOutput):
    status: Literal[
        "specialized-semantics-preserved",
        "specialized-verification-failed",
        "rolled-back",
    ]
    canonical_receipt: Literal["hwpx.form-verification-receipt/v1"] = Field(
        alias="canonicalReceipt"
    )


class _SpecializedFormOutput(_StrictOutput):
    ok: bool
    dry_run: bool = Field(alias="dryRun")
    output_path: str | None = Field(alias="outputPath")
    changed_parts: list[str] = Field(alias="changedParts")
    byte_identical: bool = Field(alias="byteIdentical")
    skipped: list[Any]
    rolled_back: bool = Field(alias="rolledBack")
    verification_receipt: FormVerificationReceipt = Field(
        alias="verificationReceipt"
    )
    compatibility: _SpecializedCompatibility
    open_safety: dict[str, Any] | None = Field(default=None, alias="openSafety")
    verification_report: dict[str, Any] | None = Field(
        default=None,
        alias="verificationReport",
    )
    render_verdict: dict[str, Any] | None = Field(
        default=None,
        alias="renderVerdict",
    )
    document_revision: str | None = Field(
        default=None,
        alias="documentRevision",
        pattern=_REVISION_PATTERN,
    )
    error: dict[str, Any] | None = None


class ApplyTableOpsOutput(_SpecializedFormOutput):
    applied: list[dict[str, Any]]
    zip_method: str = Field(alias="zipMethod")
    transcript: list[Any] | None = None


class ApplyBodyOpsOutput(_SpecializedFormOutput):
    transcript: list[Any]


class ApplyEvalplanFillOutput(_SpecializedFormOutput):
    transcript: list[Any]
    expected_skeleton: Any = Field(alias="expectedSkeleton")
    content_report: dict[str, Any] = Field(alias="contentReport")
    rubric_needs_review: int = Field(alias="rubricNeedsReview", ge=0)
    needs_review_notes: list[str] = Field(alias="needsReviewNotes")
    scorecard: dict[str, Any] | None = None


__all__ = [
    "AnalyzeFormFillOutput",
    "ApplyBodyOpsOutput",
    "ApplyEvalplanFillOutput",
    "ApplyFormFillOutput",
    "ApplyTableOpsOutput",
    "CanonicalMixedFormAnalysisOutput",
    "CanonicalMixedFormApplyOutput",
    "LegacyFormFillAnalysisOutput",
    "LegacyFormFillApplyOutput",
    "LegacyFormFillVerifyOutput",
    "VerifyFormFillOutput",
]
