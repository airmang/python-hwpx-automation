# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence
from uuid import uuid4

from ..core.plan import (
    ApplyEditInput,
    GetContextInput,
    PipelineError,
    PlanEditInput,
    PlanManager,
    PreviewEditInput,
    SearchHitModel,
    SearchInput,
    SearchOutput,
)
from ..metadata import tools_meta
from ..upstream import (
    create_text_extractor,
)

from .context import DocumentContext

logger = logging.getLogger("hwpx_automation.hwpx_ops")


class PlanningService:
    def __init__(self, context: DocumentContext) -> None:
        self._context = context
        self._manager = PlanManager()

    @property
    def plan_manager(self) -> PlanManager:
        return self._manager

    def _ensure_planner_document(self, doc_id: str, path: str) -> None:
        resolved = self._context._resolve_path(path)
        paragraphs: List[str] = []
        with create_text_extractor(self._context._text_source(resolved)) as extractor:
            for paragraph in extractor.iter_document_paragraphs():
                paragraphs.append(paragraph.text(preserve_breaks=True))
        self._manager.register_document(doc_id, "\n".join(paragraphs))

    def plan_edit(
        self,
        *,
        path: str,
        operations: Sequence[Dict[str, Any]],
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = PlanEditInput.model_validate(
            {"path": path, "operations": operations, "traceId": trace_id}
        )
        doc_path = payload.path_or_none()
        if doc_path is not None:
            self._ensure_planner_document(payload.doc_id, doc_path)
        trace = payload.trace_id or f"plan-{uuid4().hex}"
        try:
            record = self._manager.create_plan_record(
                payload.doc_id, payload.operations, trace_id=trace
            )
        except PipelineError as error:
            return self._manager.error_response(payload.doc_id, trace, error)
        return self._manager.plan_response(record)

    def preview_edit(
        self,
        *,
        plan_id: str,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = PreviewEditInput.model_validate(
            {"planId": plan_id, "traceId": trace_id}
        )
        trace = payload.trace_id or payload.plan_id
        try:
            preview = self._manager.preview_plan_record(payload.plan_id)
        except PipelineError as error:
            plan = self._manager.get_plan_record(payload.plan_id)
            doc_id = plan.doc_id if plan is not None else payload.plan_id
            return self._manager.error_response(
                doc_id, trace, error, plan_id=payload.plan_id
            )
        return self._manager.preview_response(preview)

    def apply_edit(
        self,
        *,
        plan_id: str,
        confirm: bool,
        idempotency_key: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = ApplyEditInput.model_validate(
            {
                "planId": plan_id,
                "confirm": confirm,
                "idempotencyKey": idempotency_key,
                "traceId": trace_id,
            }
        )
        trace = payload.trace_id or payload.plan_id
        try:
            result = self._manager.apply_plan_record(
                payload.plan_id,
                confirm=payload.confirm,
                idempotency_key=payload.idempotency_key,
            )
        except PipelineError as error:
            plan = self._manager.get_plan_record(payload.plan_id)
            doc_id = plan.doc_id if plan is not None else payload.plan_id
            template = (
                tools_meta.ERROR_PREVIEW_REQUIRED
                if error.error_code == "PREVIEW_REQUIRED"
                else None
            )
            return self._manager.error_response(
                doc_id,
                trace,
                error,
                plan_id=payload.plan_id,
                next_action=template,
            )
        plan_record = self._manager.get_plan_record(payload.plan_id)
        if plan_record is None:  # pragma: no cover - defensive
            raise self._context._new_error(
                "PLAN_RECORD_MISSING",
                "plan record missing after apply",
                details={"planId": payload.plan_id},
            )
        return self._manager.apply_response(plan_record, result, trace)

    def search(
        self,
        *,
        path: str,
        pattern: str,
        scope: Optional[str] = None,
        is_regex: bool = False,
        limit: int = 20,
    ) -> Dict[str, Any]:
        payload = SearchInput.model_validate(
            {
                "path": path,
                "pattern": pattern,
                "scope": scope,
                "is_regex": is_regex,
                "limit": limit,
            }
        )
        doc_path = payload.path_or_none()
        if doc_path is not None:
            self._ensure_planner_document(payload.doc_id, doc_path)
        try:
            hits = self._manager.search_document(payload.doc_id, payload)
        except PipelineError as error:
            raise self._context._new_error(
                "PIPELINE_ERROR",
                error.message,
                details={"pipelineCode": error.error_code},
                hint=error.hint,
            ) from error
        models = [
            SearchHitModel(
                nodeId=hit.node_id,
                paragraphIndex=hit.paragraph_index,
                match=hit.match,
                context=hit.context,
            )
            for hit in hits
        ]
        return SearchOutput(matches=models).model_dump(by_alias=True)

    def get_context(
        self,
        *,
        path: str,
        target: Dict[str, Any],
        window: int = 1,
    ) -> Dict[str, Any]:
        payload = GetContextInput.model_validate(
            {"path": path, "target": target, "window": window}
        )
        doc_path = payload.path_or_none()
        if doc_path is not None:
            self._ensure_planner_document(payload.doc_id, doc_path)
        try:
            view = self._manager.context_window(
                payload.doc_id, payload.target, window=payload.window
            )
        except PipelineError as error:
            raise self._context._new_error(
                "PIPELINE_ERROR",
                error.message,
                details={"pipelineCode": error.error_code},
                hint=error.hint,
            ) from error
        return view.model_dump(by_alias=True)
