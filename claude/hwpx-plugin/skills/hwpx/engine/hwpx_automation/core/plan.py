# SPDX-License-Identifier: Apache-2.0
"""Planning pipeline and validation helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, conint, constr, model_validator

from ..metadata import tools_meta
from .context import SearchHit, search_paragraphs, window_for_paragraph
from .diff import ParagraphDiff, ParagraphMatch
from .handles import stable_node_id
from .locator import (
    DocumentLocator,
    document_locator_schema,
    locator_identifier,
    locator_path,
    normalize_locator_payload,
)
from .txn import IdempotentReplayError, TransactionManager


class PlanModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class PlanLocatorModel(PlanModel):
    document: DocumentLocator = Field(alias="document")

    @model_validator(mode="before")
    @classmethod
    def _inflate_document(cls, data: object) -> object:
        if isinstance(data, dict):
            return normalize_locator_payload(dict(data), field_name="document")
        return data

    @property
    def doc_id(self) -> str:
        return locator_identifier(self.document)

    def path_or_none(self) -> Optional[str]:
        return locator_path(self.document)

    def to_hwpx_payload(self, *, require_path: bool = True) -> Dict[str, Any]:
        payload = self.model_dump(exclude={"document"})
        path = self.path_or_none()
        if path is None:
            if require_path:
                raise ValueError("document locator must include path or uri")
            payload["path"] = self.doc_id
        else:
            payload["path"] = path
        return payload

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        schema = super().model_json_schema(*args, **kwargs)
        properties = schema.get("properties")
        if isinstance(properties, dict) and "document" in properties:
            properties["document"] = document_locator_schema()
        return schema


class Target(PlanModel):
    node_id: Optional[constr(pattern=r"^n_[A-Za-z0-9]{8,}$")] = Field(None, alias="nodeId")
    section_index: Optional[conint(ge=0)] = Field(None, alias="sectionIndex")
    para_index: Optional[conint(ge=0)] = Field(None, alias="paraIndex")

    @model_validator(mode="after")
    def check_selector(self) -> "Target":
        has_node = self.node_id is not None
        has_indices = self.section_index is not None and self.para_index is not None
        if has_node == has_indices:
            raise ValueError("target must specify nodeId or sectionIndex+paraIndex")
        return self


class ReplaceTextArgs(PlanModel):
    target: Target
    match: constr(min_length=1)
    replacement: str = ""
    limit: conint(ge=1, le=100) = 1
    dry_run: bool = Field(True, alias="dryRun")
    atomic: bool = True


class PlanEditInput(PlanLocatorModel):
    operations: List[ReplaceTextArgs]
    trace_id: Optional[constr(min_length=1)] = Field(None, alias="traceId")

    @model_validator(mode="after")
    def ensure_operations(self) -> "PlanEditInput":
        if not self.operations:
            raise ValueError("operations must not be empty")
        return self


class PreviewEditInput(PlanModel):
    plan_id: constr(min_length=1) = Field(alias="planId")
    trace_id: Optional[constr(min_length=1)] = Field(None, alias="traceId")


class ApplyEditInput(PlanModel):
    plan_id: constr(min_length=1) = Field(alias="planId")
    confirm: bool
    idempotency_key: Optional[constr(min_length=1)] = Field(None, alias="idempotencyKey")
    trace_id: Optional[constr(min_length=1)] = Field(None, alias="traceId")


class NextAction(PlanModel):
    tool: constr(min_length=1)
    example_json: constr(min_length=2) = Field(alias="exampleJson")


class DiffPreview(PlanModel):
    paragraph_index: conint(ge=0) = Field(alias="paragraphIndex")
    before: str
    after: str


class Candidate(PlanModel):
    node_id: constr(min_length=1) = Field(alias="nodeId")
    paragraph_index: conint(ge=0) = Field(alias="paragraphIndex")
    context: constr(min_length=1)


class PlanSummaryData(PlanModel):
    plan_id: constr(min_length=1) = Field(alias="planId")
    complexity_score: conint(ge=0) = Field(alias="complexityScore")
    safe: bool
    preview_available: bool = Field(alias="previewAvailable")


class PreviewData(PlanModel):
    plan_id: constr(min_length=1) = Field(alias="planId")
    diff: List[DiffPreview]
    complexity_score: conint(ge=0) = Field(alias="complexityScore")
    safe: bool


class ApplyData(PlanModel):
    plan_id: constr(min_length=1) = Field(alias="planId")
    applied: bool


class ResponseData(PlanModel):
    plan: Optional[PlanSummaryData] = None
    preview: Optional[PreviewData] = None
    apply: Optional[ApplyData] = None


ErrorCode = Literal[
    "AMBIGUOUS_TARGET",
    "UNSAFE_WILDCARD",
    "MISSING_NODE",
    "RANGE_OUT_OF_BOUNDS",
    "EMPTY_MATCH",
    "CONFLICTING_TARGETS",
    "PREVIEW_REQUIRED",
    "IDEMPOTENT_REPLAY",
]


class ErrorPayload(PlanModel):
    error_code: ErrorCode = Field(alias="errorCode")
    message: str
    candidates: List[Candidate] = Field(default_factory=list)
    hint: Optional[str] = None


class ServerResponse(PlanModel):
    ok: bool
    data: Optional[ResponseData] = None
    error: Optional[ErrorPayload] = None
    next_actions: List[NextAction] = Field(default_factory=list, alias="nextActions")
    api_version: constr(min_length=1) = Field("1.2.0", alias="apiVersion")
    doc_version: constr(min_length=1) = Field(alias="docVersion")
    trace_id: constr(min_length=1) = Field(alias="traceId")


class SearchInput(PlanLocatorModel):
    pattern: constr(min_length=1)
    scope: Optional[constr(min_length=1)] = None
    is_regex: bool = Field(False, alias="isRegex")
    limit: conint(ge=1, le=50) = 20


class SearchHitModel(PlanModel):
    node_id: constr(min_length=1) = Field(alias="nodeId")
    paragraph_index: conint(ge=0) = Field(alias="paragraphIndex")
    match: str
    context: str


class SearchOutput(PlanModel):
    matches: List[SearchHitModel]


class GetContextInput(PlanLocatorModel):
    target: Target
    window: conint(ge=1, le=3) = 1


class ContextOutput(PlanModel):
    before: List[str]
    focus: str
    after: List[str]


class PipelineError(RuntimeError):
    """Exception used to carry pipeline validation failures."""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        candidates: Optional[List[Candidate]] = None,
        hint: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.candidates = candidates or []
        self.hint = hint


@dataclass
class CandidateInfo:
    node_id: str
    paragraph_index: int
    context: str

    def to_model(self) -> Candidate:
        return Candidate(nodeId=self.node_id, paragraphIndex=self.paragraph_index, context=self.context)


@dataclass
class DocumentState:
    doc_id: str
    content: str
    version: int = 1
    _paragraphs: List[str] = field(init=False, repr=False)
    _node_lookup: Dict[str, int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rebuild()

    def _rebuild(self) -> None:
        self._paragraphs = self.content.splitlines()
        self._node_lookup = {
            stable_node_id((self.doc_id, index)): index for index in range(len(self._paragraphs))
        }

    def paragraphs(self) -> List[str]:
        return list(self._paragraphs)

    def node_for_index(self, index: int) -> str:
        return stable_node_id((self.doc_id, index))

    def index_for_node(self, node_id: str) -> Optional[int]:
        return self._node_lookup.get(node_id)

    def set_content(self, content: str, *, bump_version: bool = True) -> None:
        self.content = content
        if bump_version:
            self.version += 1
        self._rebuild()


@dataclass
class PlanRecord:
    plan_id: str
    doc_id: str
    trace_id: str
    base_version: int
    diffs: List[ParagraphDiff]
    candidates: List[CandidateInfo]
    unsafe: bool
    complexity_score: int
    consumed: bool = False

    @property
    def safe(self) -> bool:
        return not self.candidates and not self.unsafe


@dataclass
class PreviewRecord:
    plan_id: str
    doc_id: str
    diff_preview: List[DiffPreview]
    complexity_score: int
    safe: bool
    trace_id: str


class PlanManager:
    """Manage plan/preview/apply lifecycle."""

    def __init__(self) -> None:
        self._documents: Dict[str, DocumentState] = {}
        self._plans: Dict[str, PlanRecord] = {}
        self._previews: Dict[str, PreviewRecord] = {}
        self._txn = TransactionManager[List[str]]()

    # ------------------------------------------------------------------
    # Document lifecycle helpers
    # ------------------------------------------------------------------
    def register_document(self, doc_id: str, content: str) -> None:
        state = self._documents.get(doc_id)
        if state is None:
            self._documents[doc_id] = DocumentState(doc_id=doc_id, content=content)
        else:
            state.set_content(content)

    def has_document(self, doc_id: str) -> bool:
        return doc_id in self._documents

    def get_document_text(self, doc_id: str) -> str:
        state = self._documents.get(doc_id)
        if state is None:
            raise PipelineError("MISSING_NODE", f"document '{doc_id}' is not registered")
        return state.content

    def replace_document(self, doc_id: str, content: str) -> None:
        state = self._documents.get(doc_id)
        if state is None:
            self._documents[doc_id] = DocumentState(doc_id=doc_id, content=content)
        else:
            state.set_content(content)

    def doc_version(self, doc_id: str) -> str:
        state = self._documents.get(doc_id)
        if state is None:
            return "0"
        return str(state.version)

    # ------------------------------------------------------------------
    # Planning lifecycle
    # ------------------------------------------------------------------
    def create_plan_record(
        self,
        doc_id: str,
        operations: Sequence[ReplaceTextArgs | Dict[str, object]],
        *,
        trace_id: Optional[str] = None,
    ) -> PlanRecord:
        state = self._documents.get(doc_id)
        if state is None:
            raise PipelineError("MISSING_NODE", f"document '{doc_id}' is not registered")

        resolved_ops: List[ReplaceTextArgs] = []
        for op in operations:
            if isinstance(op, ReplaceTextArgs):
                resolved_ops.append(op)
            else:
                try:
                    resolved_ops.append(ReplaceTextArgs.model_validate(op))
                except ValidationError as exc:  # pragma: no cover - defensive
                    raise PipelineError("EMPTY_MATCH", str(exc)) from exc

        plan_id = f"pln_{uuid4().hex}"
        paragraphs = state.paragraphs()

        all_diffs: List[ParagraphDiff] = []
        candidates: List[CandidateInfo] = []
        unsafe = False

        for op in resolved_ops:
            matches = self._find_matches(state, paragraphs, op)
            if not matches:
                raise PipelineError("MISSING_NODE", "target match not found")

            if op.limit < len(matches):
                unsafe = True

            if len(matches) > 1:
                for match in matches[:5]:
                    context = match.context(paragraphs[match.paragraph_index])
                    candidates.append(
                        CandidateInfo(
                            node_id=state.node_for_index(match.paragraph_index),
                            paragraph_index=match.paragraph_index,
                            context=context,
                        )
                    )

            for match in matches[: op.limit]:
                all_diffs.append(
                    ParagraphDiff(
                        paragraph_index=match.paragraph_index,
                        start=match.start,
                        end=match.end,
                        before=match.text,
                        after=op.replacement,
                    )
                )

        trace = trace_id or plan_id
        record = PlanRecord(
            plan_id=plan_id,
            doc_id=doc_id,
            trace_id=trace,
            base_version=state.version,
            diffs=all_diffs,
            candidates=candidates,
            unsafe=unsafe,
            complexity_score=len(all_diffs),
        )
        self._plans[plan_id] = record
        return record

    def get_plan_record(self, plan_id: str) -> Optional[PlanRecord]:
        return self._plans.get(plan_id)

    def preview_plan_record(self, plan_id: str) -> PreviewRecord:
        plan = self._plans.get(plan_id)
        if plan is None:
            raise PipelineError("PREVIEW_REQUIRED", "plan is not registered")
        if plan.consumed:
            raise PipelineError("PREVIEW_REQUIRED", "plan has already been applied")

        state = self._documents.get(plan.doc_id)
        if state is None:
            raise PipelineError("MISSING_NODE", f"document '{plan.doc_id}' is not registered")
        if state.version != plan.base_version:
            raise PipelineError("CONFLICTING_TARGETS", "document has changed since planning")

        if plan.unsafe:
            raise PipelineError("UNSAFE_WILDCARD", "match count exceeds provided limit")
        if plan.candidates:
            raise PipelineError(
                "AMBIGUOUS_TARGET",
                "multiple matches require clarification",
                candidates=[info.to_model() for info in plan.candidates],
            )

        diff_models = [
            DiffPreview(
                paragraphIndex=diff.paragraph_index,
                before=diff.before,
                after=diff.after,
            )
            for diff in plan.diffs
        ]

        preview = PreviewRecord(
            plan_id=plan.plan_id,
            doc_id=plan.doc_id,
            diff_preview=diff_models,
            complexity_score=plan.complexity_score,
            safe=plan.safe,
            trace_id=plan.trace_id,
        )
        self._previews[plan.plan_id] = preview
        return preview

    def apply_plan_record(
        self,
        plan_id: str,
        *,
        confirm: bool,
        idempotency_key: Optional[str] = None,
    ) -> ApplyData:
        plan = self._plans.get(plan_id)
        if plan is None:
            raise PipelineError("PREVIEW_REQUIRED", "plan is not registered")

        if idempotency_key:
            try:
                self._txn.ensure_idempotency(plan.doc_id, idempotency_key)
            except IdempotentReplayError as exc:
                raise PipelineError("IDEMPOTENT_REPLAY", str(exc)) from exc

        if plan.consumed:
            raise PipelineError("PREVIEW_REQUIRED", "plan has already been applied")

        preview = self._previews.get(plan_id)
        if preview is None:
            raise PipelineError("PREVIEW_REQUIRED", "preview must be executed before apply")

        state = self._documents.get(plan.doc_id)
        if state is None:
            raise PipelineError("MISSING_NODE", f"document '{plan.doc_id}' is not registered")
        if state.version != plan.base_version:
            raise PipelineError("CONFLICTING_TARGETS", "document has changed since planning")

        if not confirm:
            raise PipelineError("PREVIEW_REQUIRED", "confirm flag must be true")

        snapshot = state.paragraphs()

        def mutator(paragraphs: List[str]) -> List[str]:
            working = paragraphs
            for diff in plan.diffs:
                working = diff.apply(working)
            return working

        def applier(paragraphs: List[str]) -> None:
            state.set_content("\n".join(paragraphs))

        self._txn.atomic(snapshot, mutator, applier)

        if idempotency_key:
            self._txn.record_idempotency(plan.doc_id, idempotency_key, {"planId": plan_id})

        plan.consumed = True
        self._previews.pop(plan_id, None)

        return ApplyData(planId=plan.plan_id, applied=True)

    # ------------------------------------------------------------------
    # Searching and context helpers
    # ------------------------------------------------------------------
    def search_document(self, doc_id: str, params: SearchInput) -> List[SearchHit]:
        state = self._documents.get(doc_id)
        if state is None:
            raise PipelineError("MISSING_NODE", f"document '{doc_id}' is not registered")
        paragraphs = state.paragraphs()
        hits = search_paragraphs(
            paragraphs,
            pattern=params.pattern,
            limit=params.limit,
            use_regex=params.is_regex,
            node_resolver=state.node_for_index,
        )
        return hits

    def context_window(self, doc_id: str, target: Target, *, window: int) -> ContextOutput:
        state = self._documents.get(doc_id)
        if state is None:
            raise PipelineError("MISSING_NODE", f"document '{doc_id}' is not registered")
        index = self._resolve_target_index(state, target)
        paragraphs = state.paragraphs()
        view = window_for_paragraph(paragraphs, index, radius=window)
        return ContextOutput(**view)

    # ------------------------------------------------------------------
    # Response helpers
    # ------------------------------------------------------------------
    def plan_response(self, record: PlanRecord) -> Dict[str, object]:
        data = ResponseData(
            plan=PlanSummaryData(
                planId=record.plan_id,
                complexityScore=record.complexity_score,
                safe=record.safe,
                previewAvailable=not record.consumed,
            )
        )
        actions = [
            NextAction.model_validate(tools_meta.PLAN_NEXT_ACTION.render(record.plan_id))
        ]
        response = ServerResponse(
            ok=True,
            data=data,
            nextActions=actions,
            docVersion=self.doc_version(record.doc_id),
            traceId=record.trace_id,
        )
        return response.model_dump(by_alias=True, exclude_none=True)

    def preview_response(self, preview: PreviewRecord) -> Dict[str, object]:
        data = ResponseData(
            preview=PreviewData(
                planId=preview.plan_id,
                diff=preview.diff_preview,
                complexityScore=preview.complexity_score,
                safe=preview.safe,
            )
        )
        actions = [
            NextAction.model_validate(tools_meta.PREVIEW_NEXT_ACTION.render(preview.plan_id))
        ]
        response = ServerResponse(
            ok=True,
            data=data,
            nextActions=actions,
            docVersion=self.doc_version(preview.doc_id),
            traceId=preview.trace_id,
        )
        return response.model_dump(by_alias=True, exclude_none=True)

    def apply_response(self, plan: PlanRecord, result: ApplyData, trace_id: str) -> Dict[str, object]:
        data = ResponseData(apply=result)
        response = ServerResponse(
            ok=True,
            data=data,
            nextActions=[],
            docVersion=self.doc_version(plan.doc_id),
            traceId=trace_id,
        )
        return response.model_dump(by_alias=True, exclude_none=True)

    def error_response(
        self,
        doc_id: str,
        trace_id: str,
        error: PipelineError,
        *,
        plan_id: Optional[str] = None,
        next_action: Optional[tools_meta.ExampleTemplate] = None,
    ) -> Dict[str, object]:
        actions: List[NextAction] = []
        if next_action is not None:
            rendered_plan = plan_id or "<plan-id>"
            actions.append(NextAction.model_validate(next_action.render(rendered_plan)))
        payload = ErrorPayload(
            errorCode=error.error_code,
            message=error.message,
            candidates=error.candidates,
            hint=error.hint,
        )
        response = ServerResponse(
            ok=False,
            error=payload,
            nextActions=actions,
            docVersion=self.doc_version(doc_id),
            traceId=trace_id,
        )
        return response.model_dump(by_alias=True, exclude_none=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _find_matches(
        self,
        state: DocumentState,
        paragraphs: Sequence[str],
        op: ReplaceTextArgs,
    ) -> List[ParagraphMatch]:
        indices = self._resolve_scope(state, op.target, len(paragraphs))
        matches: List[ParagraphMatch] = []
        for index in indices:
            paragraph = paragraphs[index]
            start = 0
            while True:
                found = paragraph.find(op.match, start)
                if found == -1:
                    break
                match = ParagraphMatch(
                    paragraph_index=index,
                    start=found,
                    end=found + len(op.match),
                    text=op.match,
                )
                matches.append(match)
                start = found + len(op.match)
        return matches

    def _resolve_scope(
        self,
        state: DocumentState,
        target: Target,
        paragraph_count: int,
    ) -> List[int]:
        if target.node_id is not None:
            index = state.index_for_node(target.node_id)
            if index is None:
                raise PipelineError("MISSING_NODE", f"node '{target.node_id}' not found")
            return [index]
        index = target.para_index or 0
        if index < 0 or index >= paragraph_count:
            raise PipelineError("RANGE_OUT_OF_BOUNDS", "paragraph index out of range")
        return [index]

    def _resolve_target_index(self, state: DocumentState, target: Target) -> int:
        if target.node_id is not None:
            index = state.index_for_node(target.node_id)
            if index is None:
                raise PipelineError("MISSING_NODE", f"node '{target.node_id}' not found")
            return index
        index = target.para_index or 0
        paragraphs = len(state.paragraphs())
        if index < 0 or index >= paragraphs:
            raise PipelineError("RANGE_OUT_OF_BOUNDS", "paragraph index out of range")
        return index
