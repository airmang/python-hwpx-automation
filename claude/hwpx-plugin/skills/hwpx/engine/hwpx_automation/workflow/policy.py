# SPDX-License-Identifier: Apache-2.0
"""Fail-closed policy decisions for durable HWPX workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from hwpx_automation.document_state import document_revision

from .models import WorkFamily, WorkflowEvent, WorkflowRecord, WorkflowState, content_hash, utc_now


MUTATING_FAMILIES = frozenset(
    {
        WorkFamily.TRANSACTIONAL_EDIT,
        WorkFamily.KNOWN_TEMPLATE_FILL,
        WorkFamily.UNKNOWN_FORM_FILL,
        WorkFamily.STRUCTURAL_TABLE_EDIT,
        WorkFamily.TYPED_AUTHORING,
    }
)


class PolicyViolation(RuntimeError):
    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        self.code = code
        self.details = dict(details or {})
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": False, "code": self.code, "message": str(self), "details": self.details}


@dataclass(frozen=True, slots=True)
class ActionRequest:
    tool_name: str
    arguments: Mapping[str, Any]
    destructive: bool = False

    @property
    def action_hash(self) -> str:
        return content_hash(
            {"tool": self.tool_name, "arguments": self.arguments, "destructive": self.destructive}
        )


class WorkflowPolicyEngine:
    """Evaluate invariants using durable record/event evidence only."""

    def validate_intake(self, record: WorkflowRecord) -> None:
        order = record.work_order
        if order.family not in MUTATING_FAMILIES:
            return
        if order.source_path and order.output_path and order.source_path == order.output_path:
            raise PolicyViolation(
                "ORIGINAL_OVERWRITE_FORBIDDEN",
                "workflow output must be a distinct copy; the original cannot be overwritten",
            )
        if order.family != WorkFamily.TYPED_AUTHORING and not order.source_path:
            raise PolicyViolation("SOURCE_REQUIRED", "this workflow family requires a source document")
        if not order.output_path:
            raise PolicyViolation("OUTPUT_COPY_REQUIRED", "mutating workflows require a distinct output path")
        if order.policy.require_expected_revision and order.source_path and not order.expected_revision:
            raise PolicyViolation("EXPECTED_REVISION_REQUIRED", "expected_revision is required before mutation")

    def authorize_action(
        self,
        record: WorkflowRecord,
        action: ActionRequest,
        events: Iterable[WorkflowEvent],
        *,
        capability_ok: bool,
    ) -> None:
        self.validate_intake(record)
        if not capability_ok:
            raise PolicyViolation("CAPABILITY_SKEW", "workflow dispatch is disabled by capability/version skew")
        if record.terminal:
            raise PolicyViolation("WORKFLOW_TERMINAL", "terminal workflows cannot dispatch more tools")

        event_list = list(events)
        elapsed = (utc_now() - record.created_at).total_seconds()
        if elapsed >= record.work_order.budget.max_elapsed_seconds:
            raise PolicyViolation(
                "ELAPSED_TIME_BUDGET_EXCEEDED",
                "workflow elapsed-time budget is exhausted",
                details={"elapsedSeconds": int(elapsed), "maximum": record.work_order.budget.max_elapsed_seconds},
            )
        calls = sum(event.event_type == "dispatch.started" for event in event_list)
        if calls >= record.work_order.budget.max_tool_calls:
            raise PolicyViolation(
                "TOOL_CALL_BUDGET_EXCEEDED",
                "workflow tool-call budget is exhausted",
                details={"used": calls, "maximum": record.work_order.budget.max_tool_calls},
            )
        attempts = sum(
            event.event_type == "dispatch.started" and event.payload.get("actionHash") == action.action_hash
            for event in event_list
        )
        if attempts >= record.work_order.budget.max_attempts:
            raise PolicyViolation(
                "ACTION_ATTEMPT_BUDGET_EXCEEDED",
                "action attempt budget is exhausted",
                details={"used": attempts, "maximum": record.work_order.budget.max_attempts},
            )
        repair_rounds = sum(
            event.from_state != WorkflowState.REPAIR and event.to_state == WorkflowState.REPAIR
            for event in event_list
        )
        if repair_rounds > record.work_order.budget.max_repair_rounds:
            raise PolicyViolation(
                "REPAIR_BUDGET_EXCEEDED",
                "workflow repair-round budget is exhausted",
                details={"used": repair_rounds, "maximum": record.work_order.budget.max_repair_rounds},
            )

        order = record.work_order
        if order.source_path and order.expected_revision:
            actual = document_revision(order.source_path)
            if actual != order.expected_revision:
                raise PolicyViolation(
                    "STALE_DOCUMENT_REVISION",
                    "source document changed after workflow intake",
                    details={"expected": order.expected_revision, "actual": actual},
                )

        if action.destructive and order.policy.require_decision_for_destructive:
            approved = any(
                event.event_type == "decision.approved"
                and event.from_state == WorkflowState.DECISION
                and event.to_state == WorkflowState.DECISION
                and event.payload.get("actionHash") == action.action_hash
                for event in event_list
            )
            if not approved:
                raise PolicyViolation(
                    "DECISION_REQUIRED",
                    "this action requires an explicit matching decision receipt",
                    details={"actionHash": action.action_hash},
                )

    def authorize_completion(self, record: WorkflowRecord, verification: Mapping[str, Any]) -> None:
        if record.state != WorkflowState.VERIFY:
            raise PolicyViolation("VERIFY_STATE_REQUIRED", "completion is only allowed from verify state")
        if record.work_order.policy.require_open_safety and verification.get("openSafetyOk") is not True:
            raise PolicyViolation("OPEN_SAFETY_REQUIRED", "openSafety evidence is required for completion")
        if record.work_order.policy.require_verified_completion and verification.get("verified") is not True:
            raise PolicyViolation("VERIFIED_COMPLETION_REQUIRED", "unverified work cannot be marked completed")
        if verification.get("domainVerified") is not True:
            raise PolicyViolation(
                "DOMAIN_VERIFICATION_REQUIRED",
                "family-specific result and quality verification are required for completion",
            )

    def record_decision(
        self,
        store: Any,
        record: WorkflowRecord,
        action: ActionRequest,
        *,
        approved: bool,
    ) -> WorkflowRecord:
        if record.state != WorkflowState.DECISION:
            raise PolicyViolation("DECISION_STATE_REQUIRED", "decision receipts are only valid in decision state")
        event_type = "decision.approved" if approved else "decision.rejected"
        updated, _, _ = store.append_event(
            record.workflow_id,
            event_type,
            expected_state=record.state,
            expected_version=record.state_version,
            payload={"actionHash": action.action_hash, "approved": approved},
            event_key=f"decision:{action.action_hash}",
        )
        return updated

    def complete(
        self,
        store: Any,
        record: WorkflowRecord,
        verification: Mapping[str, Any],
        *,
        output_content_hash: str | None = None,
    ) -> WorkflowRecord:
        """Policy-gated only path from VERIFY to COMPLETED."""

        self.authorize_completion(record, verification)
        return store.transition(
            record.workflow_id,
            WorkflowState.COMPLETED,
            expected_state=record.state,
            expected_version=record.state_version,
            event_type="workflow.completed",
            payload={"verification": dict(verification)},
            output_content_hash=output_content_hash,
        )


__all__ = ["ActionRequest", "MUTATING_FAMILIES", "PolicyViolation", "WorkflowPolicyEngine"]
