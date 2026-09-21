# SPDX-License-Identifier: Apache-2.0
"""High-level durable orchestration over ToolSpec primitive functions."""

from __future__ import annotations

import hashlib
import os
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Mapping

from hwpx_automation.document_state import document_revision
from hwpx_automation.tool_contract import RELEASED_CONTRACT_HASH

from .adapters import ADAPTERS, AdapterAbstention
from .dispatcher import AllowlistedDispatcher
from .evidence_lineage import render_evidence_manifest
from .models import (
    TERMINAL_STATES,
    WORKFLOW_SCHEMA_VERSION,
    WorkFamily,
    WorkflowEvent,
    WorkflowRecord,
    WorkflowState,
    WorkOrder,
    canonical_json,
)
from .policy import ActionRequest, PolicyViolation, WorkflowPolicyEngine
from .rendering import NullRenderClientV2, RenderClientV2, RenderJobV2, RenderStatus
from .store import WorkflowStore


def default_workflow_store_path() -> Path:
    configured = os.environ.get("HWPX_AUTOMATION_WORKFLOW_STORE")
    if configured:
        return Path(configured).expanduser().resolve()
    configured = os.environ.get("HWPX_WORKFLOW_STORE")
    if configured:
        return Path(configured).expanduser().resolve()
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    # 배포 이름이 python-hwpx-automation으로 바뀌어도 이 경로는 그대로다.
    # 디스크에 이미 있는 사용자의 workflow DB가 여기 있고, 경로를 바꾸면
    # 진행 중이던 workflow가 통째로 사라진 것처럼 보인다.
    return (state_home / "hwpx-mcp-server" / "workflows.sqlite3").resolve()


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "uninstalled"


class WorkflowService:
    def __init__(
        self,
        namespace: Mapping[str, Any],
        *,
        store: WorkflowStore | None = None,
        capability_ok: bool = True,
        render_client: RenderClientV2 | None = None,
        tool_spec_hash: str = RELEASED_CONTRACT_HASH,
    ) -> None:
        self.store = store or WorkflowStore(default_workflow_store_path())
        self.dispatcher = AllowlistedDispatcher(namespace)
        self.policy = WorkflowPolicyEngine()
        self.capability_ok = capability_ok
        self.render_client = render_client or NullRenderClientV2()
        self.tool_spec_hash = tool_spec_hash

    def start(
        self,
        *,
        family: str,
        idempotency_key: str,
        source_path: str | None = None,
        output_path: str | None = None,
        expected_revision: str | None = None,
        parameters: dict[str, Any] | None = None,
        budget: dict[str, Any] | None = None,
        policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            typed_family = WorkFamily(family)
        except ValueError:
            return self._abstention_receipt(family, "UNSUPPORTED_INTENT")
        if expected_revision is None and source_path:
            expected_revision = document_revision(source_path)
        values: dict[str, Any] = {
            "family": typed_family,
            "idempotency_key": idempotency_key,
            "source_path": source_path,
            "output_path": output_path,
            "expected_revision": expected_revision,
            "parameters": parameters or {},
        }
        if budget is not None:
            values["budget"] = budget
        if policy is not None:
            values["policy"] = policy
        order = WorkOrder.model_validate(values)
        record, _ = self.store.create(
            order,
            original_content_hash=document_revision(source_path) if source_path else None,
        )
        if typed_family == WorkFamily.MUST_ABSTAIN and not record.terminal:
            # Persist a real no-mutation workflow identity and a closed,
            # authenticated-by-ledger decision gate. Replays recover the same
            # terminal record instead of returning a synthetic no-ID receipt.
            if record.state == WorkflowState.INTAKE:
                record = self.store.transition(
                    record.workflow_id,
                    WorkflowState.RECON,
                    expected_state=record.state,
                    expected_version=record.state_version,
                    event_type="abstention.recognized",
                    payload={"noMutation": True},
                )
            if record.state == WorkflowState.RECON:
                record = self.store.transition(
                    record.workflow_id,
                    WorkflowState.NEEDS_REVIEW,
                    expected_state=record.state,
                    expected_version=record.state_version,
                    event_type="decision_gate.abstained",
                    payload={"reasonCode": "UNSUPPORTED_INTENT", "noMutation": True},
                    stop_reason="UNSUPPORTED_INTENT",
                )
            return self.receipt(record)
        try:
            self.policy.validate_intake(record)
        except PolicyViolation as error:
            record = self.store.transition(
                record.workflow_id,
                WorkflowState.FAILED,
                expected_state=record.state,
                expected_version=record.state_version,
                event_type="workflow.rejected",
                payload={"code": error.code},
                stop_reason=error.code,
            )
        return self.receipt(record)

    def get(self, workflow_id: str) -> dict[str, Any]:
        return self.receipt(self.store.get(workflow_id))

    def continue_workflow(self, workflow_id: str) -> dict[str, Any]:
        record = self.store.get(workflow_id)
        if record.terminal or record.state == WorkflowState.DECISION:
            return self.receipt(record)
        adapter = ADAPTERS[record.work_order.family]
        try:
            if record.state == WorkflowState.INTAKE:
                self.policy.validate_intake(record)
                record = self.store.transition(
                    workflow_id,
                    WorkflowState.RECON,
                    expected_state=record.state,
                    expected_version=record.state_version,
                )
            elif record.state == WorkflowState.RECON:
                action = adapter.recon_action(record)
                outcome = self.dispatcher.dispatch_durable(
                    self.store,
                    workflow_id,
                    action,
                    expected_version=record.state_version,
                    capability_ok=self.capability_ok,
                    policy=self.policy,
                )
                evidence = outcome.result if outcome.result is not None else outcome.receipt.payload
                target = WorkflowState.PLAN if adapter.recon_ok(evidence) else WorkflowState.NEEDS_REVIEW
                record = self.store.transition(
                    workflow_id,
                    target,
                    expected_state=outcome.receipt.to_state,
                    expected_version=self.store.get(workflow_id).state_version,
                    event_type="recon.completed" if target == WorkflowState.PLAN else "workflow.abstained",
                    payload={"actionHash": action.action_hash, "ok": target == WorkflowState.PLAN},
                    stop_reason=None if target == WorkflowState.PLAN else "RECON_NOT_ACTIONABLE",
                )
            elif record.state == WorkflowState.PLAN:
                action = adapter.execution_action(record)
                if action is None:
                    record = self.store.transition(
                        workflow_id,
                        WorkflowState.EXECUTE,
                        expected_state=record.state,
                        expected_version=record.state_version,
                        event_type="plan.accepted",
                        payload={"readOnly": True},
                    )
                else:
                    planned, _, _ = self.store.append_event(
                        workflow_id,
                        "action.planned",
                        expected_state=record.state,
                        expected_version=record.state_version,
                        payload={
                            "actionHash": action.action_hash,
                            "tool": action.tool_name,
                            "destructive": action.destructive,
                        },
                        event_key=f"plan:{action.action_hash}",
                    )
                    target = WorkflowState.DECISION if action.destructive else WorkflowState.EXECUTE
                    record = self.store.transition(
                        workflow_id,
                        target,
                        expected_state=planned.state,
                        expected_version=planned.state_version,
                        event_type="decision.requested" if action.destructive else "plan.accepted",
                        payload={"actionHash": action.action_hash},
                    )
            elif record.state == WorkflowState.EXECUTE:
                action = adapter.execution_action(record)
                if action is None:
                    record = self.store.transition(
                        workflow_id,
                        WorkflowState.VERIFY,
                        expected_state=record.state,
                        expected_version=record.state_version,
                        event_type="execution.completed",
                        payload={"ok": True, "openSafetyOk": True, "readOnly": True},
                    )
                else:
                    prior = self._action_events(record.workflow_id, action)
                    if not any(event.event_type == "dispatch.started" for event in prior):
                        adapter.prepare_execution(record)
                    outcome = self.dispatcher.dispatch_durable(
                        self.store,
                        workflow_id,
                        action,
                        expected_version=record.state_version,
                        capability_ok=self.capability_ok,
                        policy=self.policy,
                    )
                    evidence = {
                        "actionHash": action.action_hash,
                        "ok": outcome.receipt.payload.get("ok") is True,
                        "openSafetyOk": outcome.receipt.payload.get("openSafetyOk"),
                    }
                    record = self.store.transition(
                        workflow_id,
                        WorkflowState.VERIFY,
                        expected_state=outcome.receipt.to_state,
                        expected_version=self.store.get(workflow_id).state_version,
                        event_type="execution.completed",
                        payload=evidence,
                    )
            elif record.state == WorkflowState.VERIFY:
                evidence = self._execution_evidence(workflow_id)
                read_only = record.work_order.family == WorkFamily.READ_EXTRACT
                verification_actions = adapter.verification_actions(record)
                for action in verification_actions:
                    result = self._stored_action_result(workflow_id, action)
                    if result is None:
                        try:
                            outcome = self.dispatcher.dispatch_durable(
                                self.store,
                                workflow_id,
                                action,
                                expected_version=record.state_version,
                                capability_ok=self.capability_ok,
                                policy=self.policy,
                            )
                        except PolicyViolation:
                            record, _, _ = self.store.append_event(
                                workflow_id,
                                "verification.checked",
                                expected_state=record.state,
                                expected_version=record.state_version,
                                payload={
                                    "actionHash": action.action_hash,
                                    "tool": action.tool_name,
                                    "ok": False,
                                },
                                event_key=f"verification:{action.action_hash}",
                            )
                            raise
                        result = outcome.result
                        record = self.store.get(workflow_id)
                    already_checked = any(
                        event.event_type == "verification.checked"
                        and event.payload.get("actionHash") == action.action_hash
                        for event in self.store.events(workflow_id)
                    )
                    if not already_checked:
                        record, _, _ = self.store.append_event(
                            workflow_id,
                            "verification.checked",
                            expected_state=record.state,
                            expected_version=record.state_version,
                            payload={
                                "actionHash": action.action_hash,
                                "tool": action.tool_name,
                                "ok": isinstance(result, Mapping)
                                and result.get("ok") is not False
                                and result.get("pass") is not False,
                            },
                            event_key=f"verification:{action.action_hash}",
                        )
                    record = self.store.get(workflow_id)
                    if result is None:
                        break
                primary_action_hash = self._primary_action_hash(record)
                try:
                    primary_result = (
                        self.store.get_action_result(workflow_id, primary_action_hash)
                        if primary_action_hash is not None
                        else None
                    )
                except KeyError:
                    primary_result = None
                verifier_results = tuple(
                    result
                    for action in verification_actions
                    if (result := self._stored_action_result(workflow_id, action)) is not None
                )
                domain_verified = (
                    adapter.execution_evidence_ok(record, primary_result)
                    and adapter.verification_ok(record, verifier_results)
                )
                verification = {
                    "verified": evidence.get("ok") is True,
                    "openSafetyOk": True if read_only else evidence.get("openSafetyOk") is True,
                    "domainVerified": domain_verified,
                    "verifierCount": len(verifier_results),
                    "requiredVerifierCount": len(verification_actions),
                    "renderChecked": False,
                }
                if (
                    verification["verified"]
                    and verification["openSafetyOk"]
                    and record.work_order.policy.require_real_hancom_render
                    and not read_only
                ):
                    record = self._advance_render_verification(record)
                elif verification["verified"] and verification["openSafetyOk"] and domain_verified:
                    record = self.policy.complete(
                        self.store,
                        record,
                        verification,
                        output_content_hash=self._output_hash(record),
                    )
                else:
                    record = self.store.transition(
                        workflow_id,
                        WorkflowState.NEEDS_REVIEW,
                        expected_state=record.state,
                        expected_version=record.state_version,
                        event_type="verification.incomplete",
                        payload=verification,
                        stop_reason="VERIFICATION_EVIDENCE_REQUIRED",
                    )
            elif record.state == WorkflowState.REPAIR:
                record = self.store.transition(
                    workflow_id,
                    WorkflowState.NEEDS_REVIEW,
                    expected_state=record.state,
                    expected_version=record.state_version,
                    event_type="workflow.abstained",
                    stop_reason="AUTOMATIC_REPAIR_NOT_AVAILABLE",
                )
        except AdapterAbstention as error:
            record = self._abstain_existing(record, error.code)
        except PolicyViolation as error:
            current = self.store.get(workflow_id)
            if current.state != WorkflowState.VERIFY:
                raise
            record = self._abstain_existing(current, error.code)
        return self.receipt(record)

    def approve_decision(self, workflow_id: str, *, approved: bool, action_hash: str | None = None) -> dict[str, Any]:
        record = self.store.get(workflow_id)
        if record.state != WorkflowState.DECISION:
            raise PolicyViolation("DECISION_STATE_REQUIRED", "workflow is not waiting for a decision")
        action = ADAPTERS[record.work_order.family].execution_action(record)
        if action is None:
            raise PolicyViolation("DECISION_ACTION_MISSING", "workflow has no decision action")
        if action_hash is not None and action_hash != action.action_hash:
            raise PolicyViolation("DECISION_ACTION_MISMATCH", "decision action hash does not match the plan")
        record = self.policy.record_decision(self.store, record, action, approved=approved)
        target = WorkflowState.EXECUTE if approved else WorkflowState.NEEDS_REVIEW
        record = self.store.transition(
            workflow_id,
            target,
            expected_state=record.state,
            expected_version=record.state_version,
            event_type="decision.applied",
            payload={"actionHash": action.action_hash, "approved": approved},
            stop_reason=None if approved else "DECISION_REJECTED",
        )
        return self.receipt(record)

    def cancel(self, workflow_id: str, *, reason: str = "CLIENT_CANCELLED") -> dict[str, Any]:
        record = self.store.get(workflow_id)
        if record.terminal:
            return self.receipt(record)
        render_receipt = self._render_receipt(record)
        if render_receipt and render_receipt.status in {RenderStatus.QUEUED, RenderStatus.RUNNING}:
            self.render_client.cancel(render_receipt.job_id)
        record = self.store.transition(
            workflow_id,
            WorkflowState.CANCELLED,
            expected_state=record.state,
            expected_version=record.state_version,
            event_type="workflow.cancelled",
            payload={"reasonCode": reason},
            stop_reason=reason,
        )
        return self.receipt(record)

    def resume(self, workflow_id: str) -> dict[str, Any]:
        try:
            return self.continue_workflow(workflow_id)
        except PolicyViolation as error:
            record = self.store.get(workflow_id)
            if error.code != "DISPATCH_IN_DOUBT" or record.state not in {
                WorkflowState.EXECUTE,
                WorkflowState.RECON,
            }:
                raise
            record = self._abstain_existing(record, error.code)
            return self.receipt(record)

    def receipt(self, record: WorkflowRecord) -> dict[str, Any]:
        events = self.store.events(record.workflow_id)
        decisions = [
            {
                "status": "approved" if event.event_type == "decision.approved" else "rejected",
                "actionHash": event.payload.get("actionHash"),
            }
            for event in events
            if event.event_type in {"decision.approved", "decision.rejected"}
        ]
        evidence = self._execution_evidence(record.workflow_id)
        render_receipt = self._render_receipt(record)
        try:
            render_job = self._render_job(record) if render_receipt else None
        except PolicyViolation:
            render_job = None
        render_checked = bool(
            render_receipt and render_job
            and render_receipt.status == RenderStatus.SUCCEEDED
            and render_receipt.render_checked and render_receipt.binds(render_job)
        )
        read_only = record.work_order.family == WorkFamily.READ_EXTRACT
        if record.state == WorkflowState.COMPLETED:
            verification_status = (
                "verified_read_only" if read_only else
                ("real_hancom_rendered_review_unverified" if render_checked else "structurally_verified_render_unverified")
            )
        elif record.state == WorkflowState.NEEDS_REVIEW:
            verification_status = "needs_review"
        else:
            verification_status = "pending"
        stop_reason = record.stop_reason
        if record.state == WorkflowState.DECISION:
            stop_reason = "DECISION_REQUIRED"
        elif record.state == WorkflowState.COMPLETED:
            stop_reason = "VERIFIED_COMPLETION"
        result_envelope = self._result_envelope(record)
        return {
            "schemaVersion": WORKFLOW_SCHEMA_VERSION,
            "workflowId": record.workflow_id,
            "family": record.work_order.family.value,
            "state": record.state.value,
            "stateVersion": record.state_version,
            "terminal": record.state in TERMINAL_STATES,
            "artifacts": self._artifacts(record),
            "decisions": decisions,
            "result": result_envelope.get("inline"),
            "resultRef": result_envelope.get("reference"),
            "semanticDiff": self._semantic_diff(record),
            "domainVerification": self._domain_verification(record),
            "openSafety": {
                "ok": True if read_only and record.state == WorkflowState.COMPLETED else evidence.get("openSafetyOk"),
                "renderChecked": render_checked,
            },
            "render": render_receipt.model_dump(mode="json") if render_receipt else None,
            "renderEvidence": (
                render_evidence_manifest(
                    revision=render_job.source_content_hash,
                    source_hash=render_job.source_content_hash,
                    receipt=render_receipt,
                )
                if render_checked and render_job is not None and render_receipt is not None
                else None
            ),
            "verificationStatus": verification_status,
            "unresolvedFindings": [] if record.state == WorkflowState.COMPLETED else self._findings(stop_reason),
            "versions": {
                "workflow": WORKFLOW_SCHEMA_VERSION,
                "automation": _package_version("python-hwpx-automation"),
                # 6.x compatibility alias.
                "mcp": _package_version("python-hwpx-automation"),
                "pythonHwpx": _package_version("python-hwpx"),
            },
            "toolSpecHash": self.tool_spec_hash,
            "stopReason": stop_reason,
        }

    def _action_events(self, workflow_id: str, action: ActionRequest) -> list[WorkflowEvent]:
        return [
            event
            for event in self.store.events(workflow_id)
            if event.payload.get("actionHash") == action.action_hash
        ]

    def _stored_action_result(self, workflow_id: str, action: ActionRequest) -> Any | None:
        try:
            return self.store.get_action_result(workflow_id, action.action_hash)
        except KeyError:
            return None

    def _primary_action_hash(self, record: WorkflowRecord) -> str | None:
        events = self.store.events(record.workflow_id)
        event_type = "recon.completed" if record.work_order.family == WorkFamily.READ_EXTRACT else "execution.completed"
        event = next((item for item in reversed(events) if item.event_type == event_type), None)
        return str(event.payload.get("actionHash")) if event and event.payload.get("actionHash") else None

    def _result_envelope(self, record: WorkflowRecord) -> dict[str, Any]:
        action_hash = self._primary_action_hash(record)
        if action_hash is None:
            return {"inline": None, "reference": None}
        try:
            result = self.store.get_action_result(record.workflow_id, action_hash)
        except KeyError:
            return {"inline": None, "reference": None}
        metadata = self.store.action_result_metadata(record.workflow_id, action_hash)
        encoded_size = len(canonical_json(result).encode("utf-8"))
        if encoded_size <= 32 * 1024:
            return {"inline": result, "reference": None}
        if metadata is None:
            # get_action_result above already proved the row exists and is
            # unexpired; action_result_metadata queries the same row, so this
            # branch is unreachable in practice. Fail closed to the same empty
            # envelope the missing-result paths return instead of subscripting.
            return {"inline": None, "reference": None}
        return {
            "inline": None,
            "reference": {
                "workflowId": record.workflow_id,
                "actionHash": action_hash,
                "contentHash": metadata["contentHash"],
                "sizeBytes": metadata["sizeBytes"],
                "expiresAt": metadata["expiresAt"],
                "retrievalTool": "get_workflow_result",
            },
        }

    def workflow_result(self, workflow_id: str, *, action_hash: str | None = None) -> dict[str, Any]:
        record = self.store.get(workflow_id)
        if action_hash is None:
            action_hash = self._primary_action_hash(record)
            if action_hash is None:
                raise KeyError("workflow has no primary result")
        result = self.store.get_action_result(workflow_id, action_hash)
        metadata = self.store.action_result_metadata(workflow_id, action_hash)
        if metadata is None:
            # Same row as get_action_result above (already unexpired), so this
            # is unreachable in practice; raise the same KeyError the store uses
            # for an unavailable result rather than subscript None.
            raise KeyError((workflow_id, action_hash))
        return {
            "workflowId": workflow_id,
            "actionHash": action_hash,
            "contentHash": metadata["contentHash"],
            "sizeBytes": metadata["sizeBytes"],
            "expiresAt": metadata["expiresAt"],
            "result": result,
        }

    def _semantic_diff(self, record: WorkflowRecord) -> dict[str, Any]:
        if record.work_order.family != WorkFamily.TRANSACTIONAL_EDIT:
            return {"status": "not_applicable", "available": False}
        envelope = self._result_envelope(record)
        result = envelope.get("inline")
        if result is None:
            try:
                action_hash = self._primary_action_hash(record)
                result = self.store.get_action_result(record.workflow_id, action_hash) if action_hash else None
            except KeyError:
                result = None
        semantic_diff = result.get("semanticDiff") if isinstance(result, Mapping) else None
        if isinstance(semantic_diff, Mapping):
            return {**dict(semantic_diff), "status": "computed", "available": True}
        return {"status": "missing", "available": False}

    def _domain_verification(self, record: WorkflowRecord) -> dict[str, Any]:
        rows = []
        for event in self.store.events(record.workflow_id):
            if event.event_type != "verification.checked":
                continue
            action_hash = str(event.payload.get("actionHash"))
            try:
                result = self.store.get_action_result(record.workflow_id, action_hash)
            except KeyError:
                result = None
            metadata = None
            if result is not None:
                metadata = self.store.action_result_metadata(record.workflow_id, action_hash)
            rows.append(
                {
                    "tool": event.payload.get("tool"),
                    "actionHash": action_hash,
                    "ok": isinstance(result, Mapping)
                    and result.get("ok") is not False
                    and result.get("pass") is not False,
                    "contentHash": metadata["contentHash"] if metadata else None,
                }
            )
        return {
            "required": bool(rows),
            "complete": all(row["contentHash"] for row in rows),
            "ok": all(row["ok"] for row in rows),
            "verifiers": rows,
        }

    def _execution_evidence(self, workflow_id: str) -> dict[str, Any]:
        for event in reversed(self.store.events(workflow_id)):
            if event.event_type == "execution.completed":
                return dict(event.payload)
        return {}

    def _advance_render_verification(self, record: WorkflowRecord) -> WorkflowRecord:
        job = self._render_job(record)
        submitted = next(
            (event for event in self.store.events(record.workflow_id) if event.event_type == "render.submitted"),
            None,
        )
        if submitted is None:
            receipt = self.render_client.submit(job, Path(record.work_order.output_path or ""))
            record, _, _ = self.store.append_event(
                record.workflow_id, "render.submitted", expected_state=record.state,
                expected_version=record.state_version,
                payload={"jobId": job.job_id, "inputHash": job.source_content_hash, "status": receipt.status.value},
                event_key=f"render-submit:{job.job_id}",
            )
        else:
            try:
                receipt = self.render_client.get(job.job_id)
            except (KeyError, RuntimeError):
                return self.store.transition(
                    record.workflow_id, WorkflowState.NEEDS_REVIEW,
                    expected_state=record.state, expected_version=record.state_version,
                    event_type="render.unverified", payload={"jobId": job.job_id},
                    stop_reason="RENDER_RECEIPT_UNAVAILABLE",
                )
        if receipt.status in {RenderStatus.QUEUED, RenderStatus.RUNNING}:
            return record
        if receipt.status == RenderStatus.SUCCEEDED and receipt.render_checked and receipt.binds(job):
            record, _, _ = self.store.append_event(
                record.workflow_id, "render.completed", expected_state=record.state,
                expected_version=record.state_version,
                payload={"jobId": job.job_id, "inputHash": job.source_content_hash, "status": receipt.status.value},
                event_key=f"render-complete:{job.job_id}",
            )
            return self.policy.complete(
                self.store, record,
                {
                    "verified": True,
                    "openSafetyOk": True,
                    "domainVerified": self._domain_verification(record)["ok"],
                    "renderChecked": True,
                },
                output_content_hash=job.source_content_hash,
            )
        return self.store.transition(
            record.workflow_id, WorkflowState.NEEDS_REVIEW,
            expected_state=record.state, expected_version=record.state_version,
            event_type="render.unverified",
            payload={"jobId": job.job_id, "status": receipt.status.value},
            stop_reason=receipt.terminal_reason or "REAL_HANCOM_RENDER_UNVERIFIED",
        )

    def _render_job(self, record: WorkflowRecord) -> RenderJobV2:
        output = Path(record.work_order.output_path or "")
        if not output.is_file():
            raise PolicyViolation("RENDER_OUTPUT_MISSING", "workflow output is unavailable for rendering")
        digest = "sha256:" + hashlib.sha256(output.read_bytes()).hexdigest()
        stable = hashlib.sha256(record.workflow_id.encode("utf-8")).hexdigest()[:24]
        return RenderJobV2(
            job_id=f"render-{stable}", workflow_id=record.workflow_id,
            idempotency_key=f"render-{stable}-{digest[7:23]}",
            source_content_hash=digest, source_size_bytes=output.stat().st_size,
            submitted_at=record.created_at,
        )

    def _render_receipt(self, record: WorkflowRecord):
        if not record.work_order.policy.require_real_hancom_render:
            return None
        try:
            job = self._render_job(record)
        except PolicyViolation:
            return None
        if not any(event.event_type == "render.submitted" for event in self.store.events(record.workflow_id)):
            return None
        try:
            return self.render_client.get(job.job_id)
        except (KeyError, RuntimeError):
            return None

    def _abstain_existing(self, record: WorkflowRecord, reason: str) -> WorkflowRecord:
        if record.state == WorkflowState.INTAKE:
            target = WorkflowState.FAILED
        else:
            target = WorkflowState.NEEDS_REVIEW
        return self.store.transition(
            record.workflow_id,
            target,
            expected_state=record.state,
            expected_version=record.state_version,
            event_type="workflow.abstained",
            payload={"reasonCode": reason},
            stop_reason=reason,
        )

    @staticmethod
    def _output_hash(record: WorkflowRecord) -> str | None:
        output = record.work_order.output_path
        return document_revision(output) if output and Path(output).is_file() else None

    def _artifacts(self, record: WorkflowRecord) -> list[dict[str, Any]]:
        artifacts = []
        for role, path in (("source", record.work_order.source_path), ("output", record.work_order.output_path)):
            if path:
                artifacts.append(
                    {
                        "role": role,
                        "path": path,
                        "contentHash": document_revision(path) if Path(path).is_file() else None,
                    }
                )
        return artifacts

    @staticmethod
    def _findings(stop_reason: str | None) -> list[dict[str, str]]:
        return [{"code": stop_reason, "severity": "review"}] if stop_reason else []

    def _abstention_receipt(self, family: str, reason: str) -> dict[str, Any]:
        return {
            "schemaVersion": WORKFLOW_SCHEMA_VERSION,
            "workflowId": None,
            "family": family,
            "state": WorkflowState.NEEDS_REVIEW.value,
            "stateVersion": 0,
            "terminal": True,
            "artifacts": [],
            "decisions": [],
            "semanticDiff": {"status": "not_computed", "available": False},
            "openSafety": {"ok": None, "renderChecked": False},
            "verificationStatus": "needs_review",
            "unresolvedFindings": [{"code": reason, "severity": "review"}],
            "versions": {
                "workflow": WORKFLOW_SCHEMA_VERSION,
                "automation": _package_version("python-hwpx-automation"),
                # 6.x compatibility alias.
                "mcp": _package_version("python-hwpx-automation"),
                "pythonHwpx": _package_version("python-hwpx"),
            },
            "toolSpecHash": self.tool_spec_hash,
            "stopReason": reason,
        }


__all__ = ["WorkflowService", "default_workflow_store_path"]
