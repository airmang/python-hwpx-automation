# SPDX-License-Identifier: Apache-2.0
"""ToolSpec-bound allow-listed primitive dispatcher."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from hwpx_automation.tool_contract import expected_tool_names

from .models import WorkFamily, WorkflowEvent, content_hash
from .policy import ActionRequest, PolicyViolation, WorkflowPolicyEngine
from .store import WorkflowStore


FAMILY_TOOL_ALLOWLISTS: dict[WorkFamily, frozenset[str]] = {
    WorkFamily.READ_EXTRACT: frozenset(
        {
            "get_document_text",
            "get_document_info",
            "get_document_outline",
            "get_document_map",
            "document_to_markdown",
            "document_extract_json",
        }
    ),
    WorkFamily.TRANSACTIONAL_EDIT: frozenset(
        {
            "get_document_info",
            "apply_edits",
            "undo_last_edit",
            "doc_diff",
        }
    ),
    WorkFamily.KNOWN_TEMPLATE_FILL: frozenset(
        {
            "list_form_fields", "fill_form_field", "analyze_template_formfit",
            "apply_template_formfit", "inspect_fill_residue", "verify_form_fill",
            "scan_form_guidance", "apply_table_ops",
        }
    ),
    WorkFamily.UNKNOWN_FORM_FILL: frozenset(
        {"scan_form_guidance", "apply_table_ops", "apply_body_ops", "inspect_fill_residue", "verify_form_fill"}
    ),
    WorkFamily.STRUCTURAL_TABLE_EDIT: frozenset(
        {"scan_form_guidance", "apply_table_ops", "doc_diff"}
    ),
    WorkFamily.TYPED_AUTHORING: frozenset(
        {
            "get_document_plan_schema",
            "validate_document_plan",
            "analyze_document_plan",
            "create_document_from_plan",
            "inspect_document_authoring_quality",
            "inspect_official_document_style",
        }
    ),
    WorkFamily.MUST_ABSTAIN: frozenset(),
}


@dataclass(frozen=True, slots=True)
class DispatchOutcome:
    result: Any
    replayed: bool
    receipt: WorkflowEvent


def _result_evidence(result: Any) -> dict[str, Any]:
    """Extract only policy booleans; never persist tool result bodies."""

    if not isinstance(result, Mapping):
        return {"ok": True, "openSafetyOk": None}
    ok = result.get("ok")
    if ok is None:
        ok = result.get("created")
    if ok is None and isinstance(result.get("verificationReport"), Mapping):
        ok = result["verificationReport"].get("ok")
    open_safety = result.get("openSafety")
    if not isinstance(open_safety, Mapping) and isinstance(result.get("verificationReport"), Mapping):
        open_safety = result["verificationReport"].get("openSafety")
    if not isinstance(open_safety, Mapping) and isinstance(result.get("verification"), Mapping):
        open_safety = result["verification"].get("openSafety")
    open_safety_ok = open_safety.get("ok") if isinstance(open_safety, Mapping) else None
    return {"ok": ok is not False, "openSafetyOk": open_safety_ok}


class AllowlistedDispatcher:
    def __init__(self, namespace: Mapping[str, Callable[..., Any]]) -> None:
        contract_names = expected_tool_names(advanced=True)
        invalid = set().union(*FAMILY_TOOL_ALLOWLISTS.values()) - contract_names
        if invalid:
            raise RuntimeError(f"workflow allowlist contains tools absent from ToolSpec: {sorted(invalid)}")
        self._namespace = namespace

    def resolve(self, family: WorkFamily, action: ActionRequest) -> Callable[..., Any]:
        if action.tool_name not in FAMILY_TOOL_ALLOWLISTS[family]:
            raise PolicyViolation(
                "TOOL_NOT_ALLOWED",
                f"{action.tool_name} is not allowed for {family.value}",
                details={"family": family.value, "tool": action.tool_name},
            )
        function = self._namespace.get(action.tool_name)
        if not callable(function):
            raise PolicyViolation(
                "TOOL_UNAVAILABLE",
                f"ToolSpec tool is not callable in the active server: {action.tool_name}",
            )
        return function

    def dispatch(self, family: WorkFamily, action: ActionRequest) -> Any:
        return self.resolve(family, action)(**dict(action.arguments))

    def dispatch_durable(
        self,
        store: WorkflowStore,
        workflow_id: str,
        action: ActionRequest,
        *,
        expected_version: int,
        capability_ok: bool,
        policy: WorkflowPolicyEngine | None = None,
    ) -> DispatchOutcome:
        """Execute once behind durable started/completed/failed receipts.

        A recovered completed action is not executed again.  A recovered
        ``started`` action without a terminal receipt fails as in-doubt because
        executing it again could duplicate a mutation.
        """

        engine = policy or WorkflowPolicyEngine()
        record = store.get(workflow_id)
        events = store.events(workflow_id)
        action_events = [event for event in events if event.payload.get("actionHash") == action.action_hash]
        completed = next((event for event in reversed(action_events) if event.event_type == "dispatch.completed"), None)
        if completed is not None:
            # The primitive result is encrypted outside the append-only ledger.
            # Replays must return the exact prior result so workflow planning and
            # verification never depend on an in-memory first execution.
            return DispatchOutcome(
                result=store.get_action_result(workflow_id, action.action_hash),
                replayed=True,
                receipt=completed,
            )
        started_attempts = [event for event in action_events if event.event_type == "dispatch.started"]
        terminal_attempts = {
            int(event.payload["attempt"])
            for event in action_events
            if event.event_type in {"dispatch.completed", "dispatch.failed"} and "attempt" in event.payload
        }
        unresolved = next(
            (event for event in reversed(started_attempts) if int(event.payload["attempt"]) not in terminal_attempts),
            None,
        )
        if unresolved is not None:
            raise PolicyViolation(
                "DISPATCH_IN_DOUBT",
                "action has a durable started receipt but no terminal receipt; automatic re-execution is unsafe",
                details={"actionHash": action.action_hash, "attempt": unresolved.payload["attempt"]},
            )

        if record.state_version != expected_version:
            from .store import WorkflowConflict

            raise WorkflowConflict(
                f"stale workflow state: expected {record.state.value}@{expected_version}, "
                f"actual {record.state.value}@{record.state_version}"
            )

        engine.authorize_action(record, action, events, capability_ok=capability_ok)
        function = self.resolve(record.work_order.family, action)
        attempt = len(started_attempts) + 1
        common = {
            "actionHash": action.action_hash,
            "argumentsHash": content_hash(dict(action.arguments)),
            "attempt": attempt,
            "tool": action.tool_name,
        }
        running, started, _ = store.append_event(
            workflow_id,
            "dispatch.started",
            expected_state=record.state,
            expected_version=record.state_version,
            payload=common,
            event_key=f"dispatch:{action.action_hash}:{attempt}:started",
        )
        try:
            result = function(**dict(action.arguments))
        except Exception as error:
            store.append_event(
                workflow_id,
                "dispatch.failed",
                expected_state=running.state,
                expected_version=running.state_version,
                payload={**common, "errorType": type(error).__name__},
                event_key=f"dispatch:{action.action_hash}:{attempt}:failed",
            )
            raise
        store.put_action_result(workflow_id, action.action_hash, result)
        completed_record, completed_receipt, _ = store.append_event(
            workflow_id,
            "dispatch.completed",
            expected_state=running.state,
            expected_version=running.state_version,
            payload={**common, "resultHash": content_hash(result), **_result_evidence(result)},
            event_key=f"dispatch:{action.action_hash}:{attempt}:completed",
        )
        del completed_record, started
        return DispatchOutcome(result=result, replayed=False, receipt=completed_receipt)


__all__ = ["AllowlistedDispatcher", "DispatchOutcome", "FAMILY_TOOL_ALLOWLISTS"]
