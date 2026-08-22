# SPDX-License-Identifier: Apache-2.0
"""Typed, deterministic contract for the installed FastMCP tool surface.

``BASELINE_TOOL_SPECS`` records the current classification baseline, including
the fixture-QA tools that became internal in 4.0.0 (the 3.0.0 census minus the
practice tools removed in 4.0.0 and the transition stubs removed at the 5.0.0
major boundary).  ``TOOL_SPECS`` is the only installed/public surface.
Registration, capability reporting, generated documentation, health checks, and
the versioned contract delta all consume these objects instead of maintaining
parallel name lists.
"""

from __future__ import annotations

import functools
import hashlib
import inspect
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping

MIN_PYTHON_HWPX = "6.3.0"
# The 5.0 train: core drops the workflow surfaces and the `hwpx` console name,
# this package picks the name up, and the plugin pins both. The three move
# together — a mixed set is what "no valid install has two declarers" rules out.
MIN_AUTOMATION_VERSION = "7.0.1"
# Compatibility alias retained in the 6.x contract payload for existing health
# and plugin consumers. New code and documentation use the automation name.
MIN_MCP_VERSION = MIN_AUTOMATION_VERSION
MIN_SKILL_VERSION = "2.0.0"
# Frozen release receipt for non-runtime services. Runtime construction still
# recomputes and verifies the bound callable/schema contract through
# ``contract_hash()``; this constant prevents those services from importing the
# runtime composer merely to stamp the approved release receipt.
RELEASED_CONTRACT_HASH = "8c278ebd5becba08"


def describe_callables(entries: Any) -> Any:
    """Load the optional FastMCP schema adapter only for explicit binding."""

    from .fastmcp_adapter import describe_callables as implementation

    return implementation(entries)


def register_canonical_tool(*args: Any, **kwargs: Any) -> Any:
    """Load the optional FastMCP registrar only for explicit registration."""

    from .fastmcp_adapter import register_canonical_tool as implementation

    return implementation(*args, **kwargs)


def snapshot_runtime_tools(mcp: Any) -> Any:
    """Load the optional FastMCP snapshot adapter only for runtime validation."""

    from .fastmcp_adapter import snapshot_runtime_tools as implementation

    return implementation(mcp)


class ToolClassification(str, Enum):
    """Product decision for one name in the 131-tool classification baseline."""

    PUBLIC = "public"
    COMPATIBILITY = "compatibility"
    ADVANCED = "advanced"
    DEPRECATED = "deprecated"
    INTERNAL = "internal"


class ToolProfile(str, Enum):
    DEFAULT = "default"
    ADVANCED = "advanced"


class ToolAvailability(str, Enum):
    """Declared registration state of a tool in the selected profile."""

    AVAILABLE = "available"
    PROFILE_GATED = "profile-gated"
    INTERNAL_ONLY = "internal-only"
    UNAVAILABLE = "unavailable"


class AvailabilityReasonCode(str, Enum):
    CALLABLE_MISSING = "CALLABLE_MISSING"
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    DEPENDENCY_VERSION_SKEW = "DEPENDENCY_VERSION_SKEW"
    PROFILE_DISABLED = "PROFILE_DISABLED"
    INTERNAL_ONLY = "INTERNAL_ONLY"


@dataclass(frozen=True, slots=True)
class AvailabilityRequirement:
    dependency: str
    minimum_version: str
    optional: bool = False
    extra: str | None = None


@dataclass(frozen=True, slots=True)
class AvailabilityReason:
    code: AvailabilityReasonCode
    message: str
    dependency: str | None = None
    required_version: str | None = None
    installed_version: str | None = None
    install_hint: str | None = None


class SchemaBinding(str, Enum):
    """Authoritative source from which FastMCP builds the input schema."""

    PYTHON_SIGNATURE = "python-signature"
    INTERNAL_LIBRARY = "internal-library"


@dataclass(frozen=True, slots=True)
class DomainSpec:
    key: str
    title: str
    intent: str
    when_to_use: str
    tools: tuple[str, ...]
    public: bool = True


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Static release decision plus explicit callable/schema binding."""

    name: str
    domain: str
    profile: ToolProfile
    classification: ToolClassification
    availability_requirement: AvailabilityRequirement
    availability: ToolAvailability
    availability_reason: AvailabilityReason | None
    reason: str
    replacement_tools: tuple[str, ...] = ()
    skill_required: bool = False
    callable_name: str | None = None
    schema_binding: SchemaBinding = SchemaBinding.PYTHON_SIGNATURE
    mutates: bool = False
    tags: tuple[str, ...] = ()

    @property
    def installed(self) -> bool:
        return self.classification is not ToolClassification.INTERNAL


@dataclass(frozen=True, slots=True)
class SchemaParameter:
    name: str
    annotation: str
    required: bool


@dataclass(frozen=True, slots=True)
class BoundToolSpec:
    """A ToolSpec resolved to one concrete callable before registration."""

    spec: ToolSpec
    function: Callable[..., Any]
    signature: str
    parameters: tuple[SchemaParameter, ...]
    description: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    availability: ToolAvailability = ToolAvailability.AVAILABLE
    availability_reason: AvailabilityReason | None = None


@dataclass(frozen=True, slots=True)
class RegisteredToolRegistry:
    """Immutable record of the exact callables handed to FastMCP."""

    tools: tuple[BoundToolSpec, ...]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(item.spec.name for item in self.tools)

    def callable_map(self) -> Mapping[str, Callable[..., Any]]:
        return {item.spec.name: item.function for item in self.tools}

    def by_name(self) -> Mapping[str, BoundToolSpec]:
        return {item.spec.name: item for item in self.tools}

    def payload(self) -> dict[str, Any]:
        return {
            "schemaVersion": "hwpx.bound-tool-registry.v1",
            "contractHash": contract_hash(),
            "tools": [
                {
                    "name": item.spec.name,
                    "callableName": item.spec.callable_name,
                    "signature": item.signature,
                    "description": item.description,
                    "inputSchema": item.input_schema,
                    "outputSchema": item.output_schema,
                    "availability": item.availability.value,
                    "availabilityReason": _availability_reason_payload(
                        item.availability_reason
                    ),
                    "parameters": [
                        {
                            "name": parameter.name,
                            "annotation": parameter.annotation,
                            "required": parameter.required,
                        }
                        for parameter in item.parameters
                    ],
                }
                for item in self.tools
            ],
        }

    def binding_hash(self) -> str:
        raw = json.dumps(self.payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


_ADVANCED_CLASSIFICATION = {
    "package_parts",
    "package_get_xml",
    "package_get_text",
    "object_find_by_tag",
    "object_find_by_attr",
    "validate_structure",
    "lint_text_conventions",
    "score_form_fill",
}

_ADVANCED_PROFILE = _ADVANCED_CLASSIFICATION

_COMPATIBILITY_REPLACEMENTS: dict[str, tuple[str, ...]] = {
    "apply_edits": ("apply_document_commands",),
    "apply_evalplan_fill": ("analyze_form_fill", "apply_form_fill", "verify_form_fill"),
    "create_comparison_table_document": ("create_document_from_plan",),
    "create_government_report_document": ("create_document_from_plan",),
    "create_proposal_document": ("create_document_from_plan",),
    "fill_by_path": ("analyze_form_fill", "apply_form_fill", "verify_form_fill"),
}

# At the 5.0.0 major boundary, the three template-formfit facades demote from
# COMPATIBILITY to DEPRECATED. Their handlers and behaviour are unchanged; they
# now carry the one-transition deprecation guidance toward the canonical
# analyze/apply/verify_form_fill trio, exactly like the former stub group.
_DEPRECATED_REPLACEMENTS: dict[str, tuple[str, ...]] = {
    "analyze_template_formfit": ("analyze_form_fill", "apply_form_fill", "verify_form_fill"),
    "apply_template_formfit": ("analyze_form_fill", "apply_form_fill", "verify_form_fill"),
    "fill_form_field": ("analyze_form_fill", "apply_form_fill", "verify_form_fill"),
}

_INTERNAL_QA_TOOLS = {
    "export_fixture_benchmark",
    "run_fixture_benchmark",
    "visual_repair_fixture",
    "visual_review_fixture",
}

_SKILL_REQUIRED_TOOLS = {
    "get_document_node",
    "run_edit_plan",
    "query_document_nodes",
    "apply_document_commands",
    "dump_document_blueprint",
    "replay_document_blueprint",
    "create_document_from_plan",
    "create_government_report_document",
    "mail_merge",
    "table_compute",
    "extract_style_profile",
    "list_templates",
    "get_document_map",
    "repair_hwpx",
    "replace_by_anchor",
    "add_memo_by_anchor",
    "byte_preserving_patch",
    "render_preview",
    "apply_edits",
    "add_tracked_edit",
    "undo_last_edit",
    "compose_exam",
    "scan_form_guidance",
    "apply_table_ops",
    "apply_body_ops",
    "inspect_fill_residue",
    "verify_form_fill",
    "apply_evalplan_fill",
    "score_form_fill",
}


_MUTATING_TOOLS = {
    "apply_document_commands", "replay_document_blueprint",
    # These render tools can materialize queue or preview artifacts when their
    # optional output arguments are supplied, so classify them conservatively
    # as writers for process-wide serialization.
    "render_preview", "render_submit", "render_status", "render_cancel",
    "start_workflow", "continue_workflow", "approve_workflow_decision",
    "cancel_workflow", "resume_workflow",
    "apply_table_ops", "apply_body_ops", "run_edit_plan", "add_form_field", "fill_form_field", "fill_by_path",
    "apply_form_fill", "apply_template_formfit",
    "apply_evalplan_fill",
    "create_document", "create_document_from_plan", "copy_document",
    "create_government_report_document", "create_proposal_document",
    "create_comparison_table_document", "register_template",
    "add_heading", "add_paragraph", "insert_paragraph", "delete_paragraph",
    "add_page_break", "add_equation", "add_chart", "apply_edits", "undo_last_edit",
    "replace_by_anchor", "replace_in_paragraph", "search_and_replace", "batch_replace",
    "byte_preserving_patch", "insert_picture", "replace_picture",
    "add_table", "set_table_cell_text", "merge_table_cells", "split_table_cell",
    "format_table", "table_compute",
    "create_custom_style", "set_paragraph_format", "set_list_format", "format_text",
    "apply_style_profile_to_plan", "set_page_setup", "set_header_footer",
    "set_page_number", "add_toc", "add_cross_reference", "add_tracked_edit",
    "compose_exam", "place_seal", "mail_merge", "build_image_grid",
    "build_meeting_nameplates", "build_organization_chart", "add_memo",
    "add_memo_by_anchor", "remove_memo", "repair_hwpx",
    "add_boxed_org_chart",
}


BASELINE_DOMAIN_SPECS: tuple[DomainSpec, ...] = (
    DomainSpec(
        "agent_document",
        "에이전트 문서 인터페이스",
        "공유 semantic node/path/query/command 계약으로 낯선 HWPX를 탐색하고 이종 편집을 한 번에 원자 적용.",
        "get_document_node/query_document_nodes로 revision-bound canonical path를 찾은 뒤 "
        "apply_document_commands 한 배치로 적용한다. 도메인 증거가 필요한 작업은 전문 도구를 사용한다.",
        (
            "get_document_node",
            "query_document_nodes",
            "apply_document_commands",
            "dump_document_blueprint",
            "replay_document_blueprint",
        ),
    ),
    DomainSpec(
        "real_hancom_render",
        "실한컴 비동기 렌더",
        "인증된 private queue로 HWPX를 제출하고 실한컴 PDF·페이지 영수증을 비동기로 조회.",
        "render_submit 후 job id를 받고 render_status로 폴링한다. unavailable/degraded이면 unverified로 보류한다.",
        ("render_submit", "render_status", "render_cancel", "render_health"),
    ),
    DomainSpec(
        "workflow",
        "자율 문서 워크플로",
        "서버가 상태·정책·결정·예산·검증을 강제하는 재시작 가능한 고수준 문서 작업.",
        "호스트별 스킬 지식 없이 HWPX 작업을 안전하게 시작·진행·승인·재개할 때.",
        (
            "start_workflow",
            "get_workflow",
            "get_workflow_result",
            "continue_workflow",
            "approve_workflow_decision",
            "cancel_workflow",
            "resume_workflow",
        ),
    ),
    DomainSpec(
        "visual_qa",
        "전 페이지 fixture 비전 검수",
        "제품 QA fixture 전용 검수와 제한 수리.",
        "설치형 제품 도구가 아니라 CI 라이브러리로만 실행한다.",
        ("visual_review_fixture", "visual_repair_fixture"),
        public=False,
    ),
    DomainSpec(
        "blind_eval",
        "블라인드 fixture 실무 평가",
        "동결 fixture 실행·판정 증거와 익명 심사용 번들.",
        "설치형 제품 도구가 아니라 CI 라이브러리로만 실행한다.",
        ("run_fixture_benchmark", "export_fixture_benchmark"),
        public=False,
    ),
    DomainSpec(
        "read",
        "읽기·추출·변환",
        "HWPX 문서를 읽어 텍스트·구조·서식을 뽑거나 Markdown/HTML/JSON으로 변환.",
        "문서 내용을 이해·인용·재작업하거나 다른 형식으로 내보낼 때.",
        (
            "get_document_text", "get_document_info", "get_document_outline", "get_document_map",
            "get_paragraph_text", "get_paragraphs_text", "get_location_text", "get_table_text",
            "get_table_map", "find_text", "list_available_documents", "hwpx_to_markdown",
            "document_to_markdown", "hwpx_to_html", "hwpx_extract_json", "document_extract_json",
        ),
    ),
    DomainSpec(
        "form_fill",
        "양식 채움 (동적)",
        "처음 보는 실양식을 정찰하고 typed plan을 한 transaction으로 채운 뒤 검증.",
        "analyze_form_fill → 승인 → apply_form_fill → verify_form_fill을 canonical 경로로 사용한다.",
        (
            "scan_form_guidance", "apply_table_ops", "apply_body_ops", "run_edit_plan",
            "inspect_fill_residue",
            "verify_form_fill", "list_form_fields", "add_form_field", "fill_form_field",
            "find_cell_by_label",
            "fill_by_path", "analyze_form_fill", "apply_form_fill", "analyze_template_formfit",
            "apply_template_formfit",
            "apply_evalplan_fill", "score_form_fill",
        ),
    ),
    DomainSpec(
        "author",
        "문서 생성",
        "계획·브리프로 새 HWPX 문서를 생성.",
        "빈 문서에서 공문·보고서·제안서·비교표 등을 저작할 때.",
        (
            "create_document", "create_document_from_plan", "copy_document",
            "create_government_report_document", "create_proposal_document",
            "create_comparison_table_document", "get_document_plan_schema", "validate_document_plan",
            "analyze_document_plan", "markdown_to_document_plan", "parse_government_report_text",
            "compute_report_value", "register_template", "list_templates", "describe_template",
        ),
    ),
    DomainSpec(
        "edit",
        "편집",
        "기존 문서의 문단·그림·텍스트를 안전하게 편집.",
        "기존 문서를 고치거나 byte-preserving 수술을 적용할 때.",
        (
            "add_heading", "add_paragraph", "insert_paragraph", "delete_paragraph", "add_page_break",
            "apply_edits", "undo_last_edit",
            "replace_by_anchor", "replace_in_paragraph", "search_and_replace", "batch_replace",
            "byte_preserving_patch", "insert_picture", "replace_picture", "add_equation", "add_chart",
        ),
    ),
    DomainSpec(
        "tables", "표 조작", "표 생성·셀 편집·병합·계산.", "표를 직접 만들거나 값을 바꿀 때.",
        ("add_table", "set_table_cell_text", "merge_table_cells", "split_table_cell", "format_table", "table_compute"),
    ),
    DomainSpec(
        "styles", "서식·스타일", "문단/런 서식과 스타일 프로파일을 편집.", "글꼴·정렬·목록·서식을 바꿀 때.",
        (
            "list_styles", "create_custom_style", "set_paragraph_format", "set_list_format",
            "format_text", "extract_style_profile", "apply_style_profile_to_plan", "compare_style_profiles",
            "get_genre_grammar",
        ),
    ),
    DomainSpec(
        "layout", "페이지·머리글·쪽번호", "페이지 레이아웃 요소를 설정.", "용지·머리글·쪽번호를 바꿀 때.",
        ("set_page_setup", "set_header_footer", "set_page_number"),
    ),
    DomainSpec(
        "toc_xref", "차례·상호참조", "한컴 네이티브 차례와 쪽 상호참조를 저작·검증.",
        "자동 목차/상호참조가 필요할 때.", ("add_toc", "add_cross_reference", "verify_toc"),
    ),
    DomainSpec("pii", "개인정보", "개인정보를 탐지·마스킹.", "배포 전 PII를 감사할 때.", ("scan_personal_info",)),
    DomainSpec("redline", "변경추적", "수락/거부 가능한 추적 변경을 저작.", "검토용 redline이 필요할 때.", ("add_tracked_edit",)),
    DomainSpec("exam", "시험지 조판", "문항 Markdown을 학교 양식에 조판.", "시험지 원안지에 문항을 앉힐 때.", ("compose_exam", "verify_question_splits")),
    DomainSpec("seal", "직인·관인", "직인을 배치하고 규정을 검사.", "공문 직인 처리에.", ("place_seal", "check_seal_compliance")),
    DomainSpec(
        "generators", "대량생산·특수 산출", "메일머지·사진대지·명패·조직도를 생성.",
        "반복 문서나 특수 레이아웃을 만들 때.",
        ("mail_merge", "inspect_mail_merge_placeholders", "build_image_grid", "build_meeting_nameplates", "build_organization_chart", "add_boxed_org_chart", "compose_section_chip", "compose_official_draft", "compose_simple_draft"),
    ),
    DomainSpec("memo", "메모·주석", "검토 메모를 추가·삭제.", "문서에 코멘트를 달 때.", ("add_memo", "add_memo_by_anchor", "remove_memo")),
    DomainSpec(
        "verify_quality", "검증·품질·복구", "렌더·품질·정합·복구·서버 상태를 검사.",
        "산출물 확언 전 검증하거나 문제를 진단할 때.",
        (
            "render_preview", "repair_hwpx", "mcp_server_health", "describe_capabilities", "doc_diff",
            "validate_structure", "lint_text_conventions", "inspect_document_quality",
            "inspect_document_authoring_quality", "inspect_operating_plan_quality",
            "inspect_official_document_style", "inspect_reference_consistency",
        ),
    ),
    DomainSpec(
        "package_io", "패키지 조회", "고급 OPC 파트와 XML 객체를 조회.", "저수준 진단이 필요할 때.",
        ("package_parts", "package_get_text", "package_get_xml", "object_find_by_attr", "object_find_by_tag"),
    ),
)

DOMAIN_SPECS: tuple[DomainSpec, ...] = tuple(domain for domain in BASELINE_DOMAIN_SPECS if domain.public)


def _classification(name: str) -> ToolClassification:
    if name in _INTERNAL_QA_TOOLS:
        return ToolClassification.INTERNAL
    if name in _DEPRECATED_REPLACEMENTS:
        return ToolClassification.DEPRECATED
    if name in _COMPATIBILITY_REPLACEMENTS:
        return ToolClassification.COMPATIBILITY
    if name in _ADVANCED_CLASSIFICATION:
        return ToolClassification.ADVANCED
    return ToolClassification.PUBLIC


def _reason(classification: ToolClassification) -> str:
    return {
        ToolClassification.PUBLIC: "canonical installed product capability",
        ToolClassification.COMPATIBILITY: "transition facade over a canonical typed engine",
        ToolClassification.ADVANCED: "opt-in diagnostic or expert capability outside ordinary routing",
        ToolClassification.DEPRECATED: "one-transition stub with explicit replacement guidance",
        ToolClassification.INTERNAL: "fixture QA library retained for CI but removed from installed registration",
    }[classification]


def _build_baseline_tool_specs() -> tuple[ToolSpec, ...]:
    seen: set[str] = set()
    specs: list[ToolSpec] = []
    for domain in BASELINE_DOMAIN_SPECS:
        for name in domain.tools:
            if name in seen:
                raise RuntimeError(f"duplicate ToolSpec name: {name}")
            seen.add(name)
            classification = _classification(name)
            internal = classification is ToolClassification.INTERNAL
            profile = ToolProfile.ADVANCED if name in _ADVANCED_PROFILE else ToolProfile.DEFAULT
            availability = (
                ToolAvailability.INTERNAL_ONLY
                if internal
                else ToolAvailability.PROFILE_GATED
                if profile is ToolProfile.ADVANCED
                else ToolAvailability.AVAILABLE
            )
            availability_reason = (
                AvailabilityReason(
                    code=AvailabilityReasonCode.INTERNAL_ONLY,
                    message="fixture QA capability is retained only as an internal library",
                )
                if internal
                else AvailabilityReason(
                    code=AvailabilityReasonCode.PROFILE_DISABLED,
                    message=(
                        "set HWPX_AUTOMATION_ADVANCED=1 before server import "
                        "(HWPX_MCP_ADVANCED remains a 6.x fallback)"
                    ),
                )
                if profile is ToolProfile.ADVANCED
                else None
            )
            tags = tuple(
                tag
                for tag, enabled in (
                    (domain.key, True),
                    (classification.value, True),
                    ("mutation", name in _MUTATING_TOOLS),
                    ("skill-required", name in _SKILL_REQUIRED_TOOLS),
                )
                if enabled
            )
            specs.append(
                ToolSpec(
                    name=name,
                    domain=domain.key,
                    profile=profile,
                    classification=classification,
                    availability_requirement=AvailabilityRequirement(
                        dependency="python-hwpx",
                        minimum_version=MIN_PYTHON_HWPX,
                    ),
                    availability=availability,
                    availability_reason=availability_reason,
                    reason=_reason(classification),
                    replacement_tools=(
                        _COMPATIBILITY_REPLACEMENTS.get(name)
                        or _DEPRECATED_REPLACEMENTS.get(name)
                        or ()
                    ),
                    skill_required=name in _SKILL_REQUIRED_TOOLS,
                    callable_name=None if internal else name,
                    schema_binding=(
                        SchemaBinding.INTERNAL_LIBRARY if internal else SchemaBinding.PYTHON_SIGNATURE
                    ),
                    mutates=name in _MUTATING_TOOLS,
                    tags=tags,
                )
            )

    expected_sets = (
        _ADVANCED_CLASSIFICATION,
        set(_COMPATIBILITY_REPLACEMENTS),
        set(_DEPRECATED_REPLACEMENTS),
        _INTERNAL_QA_TOOLS,
        _SKILL_REQUIRED_TOOLS,
    )
    missing = set().union(*(items - seen for items in expected_sets))
    if missing:
        raise RuntimeError(f"classified tools absent from domains: {sorted(missing)}")
    return tuple(specs)


BASELINE_TOOL_SPECS = _build_baseline_tool_specs()
TOOL_SPECS = tuple(spec for spec in BASELINE_TOOL_SPECS if spec.installed)


def _validate_classification() -> None:
    counts = classification_counts()
    expected = {
        # 6.6: +1 public — run_edit_plan — 선언적 편집 계획 실행기.
        ToolClassification.PUBLIC.value: 119,
        ToolClassification.COMPATIBILITY.value: 6,
        ToolClassification.ADVANCED.value: 8,
        ToolClassification.DEPRECATED.value: 3,
        ToolClassification.INTERNAL.value: 4,
    }
    if len(BASELINE_TOOL_SPECS) != 140 or counts != expected:
        raise RuntimeError(
            f"140-tool classification must be disjoint and exhaustive: {counts!r} != {expected!r}"
        )
    if len(TOOL_SPECS) != 136:
        raise RuntimeError(f"installed advanced surface must contain 136 tools, got {len(TOOL_SPECS)}")
    if sum(spec.skill_required for spec in TOOL_SPECS) != 29:
        raise RuntimeError(
            "installed surface must contain exactly 29 skill-required tools"
        )


def classification_counts() -> dict[str, int]:
    return {
        classification.value: sum(
            spec.classification is classification for spec in BASELINE_TOOL_SPECS
        )
        for classification in ToolClassification
    }


_validate_classification()


def active_tool_specs(*, advanced: bool) -> tuple[ToolSpec, ...]:
    return tuple(
        spec
        for spec in TOOL_SPECS
        if spec.profile is ToolProfile.DEFAULT or advanced
    )


def expected_tool_order(*, advanced: bool) -> tuple[str, ...]:
    return tuple(spec.name for spec in active_tool_specs(advanced=advanced))


def expected_tool_names(*, advanced: bool) -> set[str]:
    return set(expected_tool_order(advanced=advanced))


def skill_required_tool_names() -> set[str]:
    return {spec.name for spec in TOOL_SPECS if spec.skill_required}


def classification_payload() -> dict[str, Any]:
    return {
        "schemaVersion": "hwpx.tool-classification.v1",
        "baselineToolCount": len(BASELINE_TOOL_SPECS),
        "counts": classification_counts(),
        "tools": [_tool_payload(spec) for spec in BASELINE_TOOL_SPECS],
    }


def _availability_reason_payload(reason: AvailabilityReason | None) -> dict[str, Any] | None:
    if reason is None:
        return None
    return {
        "code": reason.code.value,
        "message": reason.message,
        "dependency": reason.dependency,
        "requiredVersion": reason.required_version,
        "installedVersion": reason.installed_version,
        "installHint": reason.install_hint,
    }


def _tool_payload(spec: ToolSpec, bound: BoundToolSpec | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": spec.name,
        "domain": spec.domain,
        "profile": spec.profile.value,
        "classification": spec.classification.value,
        "lifecycle": spec.classification.value,
        "availabilityRequirement": {
            "dependency": spec.availability_requirement.dependency,
            "minimumVersion": spec.availability_requirement.minimum_version,
            "optional": spec.availability_requirement.optional,
            "extra": spec.availability_requirement.extra,
        },
        "declaredAvailability": spec.availability.value,
        "availability": (bound.availability if bound else spec.availability).value,
        "availabilityReason": _availability_reason_payload(
            bound.availability_reason if bound else spec.availability_reason
        ),
        "decisionReason": spec.reason,
        "replacementTools": list(spec.replacement_tools),
        "skillRequired": spec.skill_required,
        "callableName": spec.callable_name,
        "schemaBinding": spec.schema_binding.value,
        "mutates": spec.mutates,
        "tags": list(spec.tags),
    }
    if bound is not None:
        payload.update(
            {
                "description": bound.description,
                "signature": bound.signature,
                "inputSchema": bound.input_schema,
                "outputSchema": bound.output_schema,
            }
        )
    return payload


_BOUND_TOOL_REGISTRY: RegisteredToolRegistry | None = None


def bound_tool_registry() -> RegisteredToolRegistry:
    """Return the complete installed registry after explicit runtime initialization."""

    if _BOUND_TOOL_REGISTRY is None:
        raise RuntimeError(
            "canonical ToolSpec registry is not bound; initialize "
            "hwpx_automation.runtime first"
        )
    return _BOUND_TOOL_REGISTRY


def contract_payload() -> dict[str, Any]:
    registry = bound_tool_registry()
    bound = registry.by_name()
    return {
        "schemaVersion": "hwpx.tool-contract.v2",
        "minPythonHwpx": MIN_PYTHON_HWPX,
        "minAutomationVersion": MIN_AUTOMATION_VERSION,
        "minMcpVersion": MIN_MCP_VERSION,
        "minSkillVersion": MIN_SKILL_VERSION,
        "tools": [_tool_payload(spec, bound[spec.name]) for spec in TOOL_SPECS],
        "baselineClassification": classification_payload(),
    }


def contract_hash() -> str:
    # Non-MCP automation services use the frozen release receipt without
    # importing or constructing FastMCP. Once the optional adapter binds the
    # canonical registry, recompute from live schemas and fail tests on drift.
    if _BOUND_TOOL_REGISTRY is None:
        return RELEASED_CONTRACT_HASH
    raw = json.dumps(contract_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _annotation_name(annotation: Any) -> str:
    if annotation is inspect.Parameter.empty:
        return "untyped"
    if isinstance(annotation, str):
        return annotation
    return getattr(annotation, "__name__", str(annotation).replace("typing.", ""))


def bind_tool_specs(
    namespace: Mapping[str, Any],
    *,
    advanced: bool | None = None,
) -> RegisteredToolRegistry:
    """Resolve callable identity and normalized schemas before registration.

    Every missing/non-callable binding and every schema-signature failure is
    reported together, so import/programming errors cannot produce a silently
    degraded partial registry.
    """

    # Keep the static ToolSpec/classification contract importable in the base
    # automation distribution.  FastMCP is an optional adapter and is loaded
    # only when a caller explicitly binds the MCP schema surface.
    specs = TOOL_SPECS if advanced is None else active_tool_specs(advanced=advanced)
    resolved: list[tuple[ToolSpec, Callable[..., Any], inspect.Signature]] = []
    errors: list[str] = []
    schema_entries: list[tuple[str, Callable[..., Any], str, Mapping[str, Any]]] = []
    for spec in specs:
        callable_name = spec.callable_name
        function = namespace.get(callable_name) if callable_name else None
        if not callable(function):
            errors.append(f"{spec.name}: missing callable {callable_name!r}")
            continue
        try:
            signature = inspect.signature(function)
        except (TypeError, ValueError) as exc:
            errors.append(f"{spec.name}: invalid Python signature: {exc}")
            continue
        description = inspect.getdoc(function) or f"HWPX tool {spec.name}"
        meta = {
            "hwpxLifecycle": spec.classification.value,
            "hwpxProfile": spec.profile.value,
            "hwpxMutates": spec.mutates,
            "hwpxReplacementTools": list(spec.replacement_tools),
        }
        resolved.append((spec, function, signature))
        schema_entries.append((spec.name, function, description, meta))
    if errors:
        raise RuntimeError("ToolSpec binding failed:\n- " + "\n- ".join(errors))

    try:
        snapshots = describe_callables(schema_entries)
    except Exception as exc:
        raise RuntimeError(f"ToolSpec schema binding failed: {exc}") from exc

    bound: list[BoundToolSpec] = []
    for spec, function, signature in resolved:
        parameters = tuple(
            SchemaParameter(
                name=parameter.name,
                annotation=_annotation_name(parameter.annotation),
                required=parameter.default is inspect.Parameter.empty,
            )
            for parameter in signature.parameters.values()
            if parameter.kind
            not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        )
        bound.append(
            BoundToolSpec(
                spec=spec,
                function=function,
                signature=str(signature),
                parameters=parameters,
                description=snapshots[spec.name].description,
                input_schema=snapshots[spec.name].input_schema,
                output_schema=snapshots[spec.name].output_schema,
                availability=ToolAvailability.AVAILABLE,
                availability_reason=None,
            )
        )
    return RegisteredToolRegistry(tuple(bound))


def _deprecated_wrapper(item: BoundToolSpec) -> Callable[..., Any]:
    replacement_tools = item.spec.replacement_tools
    function = item.function

    @functools.wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        result = function(*args, **kwargs)
        if isinstance(result, Mapping):
            payload = dict(result)
            payload.setdefault(
                "deprecation",
                {
                    "status": "deprecated",
                    "tool": item.spec.name,
                    "replacementTools": list(replacement_tools),
                    "message": "This tool is retained for one transition release.",
                },
            )
            return payload
        return result

    setattr(wrapped, "__hwpx_original_callable__", function)
    return wrapped


def register_fastmcp_tools(
    mcp: Any,
    namespace: Mapping[str, Any],
    *,
    advanced: bool,
) -> RegisteredToolRegistry:
    """Bind the full contract, then register the selected deterministic profile."""

    global _BOUND_TOOL_REGISTRY
    canonical = bind_tool_specs(namespace, advanced=None)
    _BOUND_TOOL_REGISTRY = canonical
    canonical_by_name = canonical.by_name()
    active = RegisteredToolRegistry(
        tuple(canonical_by_name[spec.name] for spec in active_tool_specs(advanced=advanced))
    )
    for item in active.tools:
        function = (
            _deprecated_wrapper(item)
            if item.spec.classification is ToolClassification.DEPRECATED
            else item.function
        )
        register_canonical_tool(
            mcp,
            name=item.spec.name,
            func=function,
            description=item.description,
            meta={
                "hwpxLifecycle": item.spec.classification.value,
                "hwpxProfile": item.spec.profile.value,
                "hwpxMutates": item.spec.mutates,
                "hwpxReplacementTools": list(item.spec.replacement_tools),
            },
        )
    report = validate_registered_tools(mcp, active)
    if not report["ok"]:
        raise RuntimeError(f"FastMCP registry validation failed: {report!r}")
    return active


def validate_registered_tools(mcp: Any, registry: RegisteredToolRegistry) -> dict[str, Any]:
    """Compare live names, callable identity, description, and both schemas."""

    actual_by_name = snapshot_runtime_tools(mcp)
    expected_by_name = registry.by_name()
    expected_names = registry.names
    actual_names = tuple(actual_by_name)
    order_mismatch = actual_names != expected_names
    callable_mismatches: list[str] = []
    input_schema_mismatches: list[str] = []
    output_schema_mismatches: list[str] = []
    description_mismatches: list[str] = []
    for item in registry.tools:
        actual = actual_by_name.get(item.spec.name)
        if actual is None:
            continue
        if actual.callable is not item.function:
            callable_mismatches.append(item.spec.name)
        if actual.input_schema != item.input_schema:
            input_schema_mismatches.append(item.spec.name)
        if actual.output_schema != item.output_schema:
            output_schema_mismatches.append(item.spec.name)
        if actual.description != item.description:
            description_mismatches.append(item.spec.name)
    missing = [name for name in expected_names if name not in actual_by_name]
    unexpected = [name for name in actual_names if name not in expected_by_name]
    unavailable = [
        item.spec.name
        for item in registry.tools
        if item.availability is not ToolAvailability.AVAILABLE
    ]
    return {
        "ok": not any(
            (
                missing,
                unexpected,
                callable_mismatches,
                input_schema_mismatches,
                output_schema_mismatches,
                description_mismatches,
                unavailable,
                order_mismatch,
            )
        ),
        "missing": missing,
        "unexpected": unexpected,
        "callableMismatches": callable_mismatches,
        "inputSchemaMismatches": input_schema_mismatches,
        "outputSchemaMismatches": output_schema_mismatches,
        "descriptionMismatches": description_mismatches,
        "unavailable": unavailable,
        "orderMismatch": order_mismatch,
        "expectedOrder": list(expected_names),
        "actualOrder": list(actual_names),
    }


async def validate_fastmcp_tools(mcp: Any, registry: RegisteredToolRegistry) -> dict[str, Any]:
    """Async compatibility wrapper retained for existing diagnostics."""

    return validate_registered_tools(mcp, registry)


__all__ = [
    "AvailabilityReason",
    "AvailabilityReasonCode",
    "AvailabilityRequirement",
    "BASELINE_DOMAIN_SPECS",
    "BASELINE_TOOL_SPECS",
    "BoundToolSpec",
    "DOMAIN_SPECS",
    "MIN_AUTOMATION_VERSION",
    "MIN_MCP_VERSION",
    "MIN_PYTHON_HWPX",
    "MIN_SKILL_VERSION",
    "RegisteredToolRegistry",
    "RELEASED_CONTRACT_HASH",
    "SchemaBinding",
    "TOOL_SPECS",
    "ToolAvailability",
    "ToolClassification",
    "ToolProfile",
    "ToolSpec",
    "active_tool_specs",
    "bind_tool_specs",
    "bound_tool_registry",
    "classification_counts",
    "classification_payload",
    "contract_hash",
    "contract_payload",
    "expected_tool_names",
    "expected_tool_order",
    "register_fastmcp_tools",
    "skill_required_tool_names",
    "validate_fastmcp_tools",
    "validate_registered_tools",
]
