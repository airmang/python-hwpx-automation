# SPDX-License-Identifier: Apache-2.0
"""Pure state-transition rules for the autonomous document workflow."""

from __future__ import annotations

from .models import TERMINAL_STATES, WorkflowState


ALLOWED_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.INTAKE: frozenset({WorkflowState.RECON, WorkflowState.FAILED, WorkflowState.CANCELLED}),
    WorkflowState.RECON: frozenset(
        {WorkflowState.PLAN, WorkflowState.NEEDS_REVIEW, WorkflowState.FAILED, WorkflowState.CANCELLED}
    ),
    WorkflowState.PLAN: frozenset(
        {
            WorkflowState.DECISION,
            WorkflowState.EXECUTE,
            WorkflowState.NEEDS_REVIEW,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
        }
    ),
    WorkflowState.DECISION: frozenset(
        {WorkflowState.EXECUTE, WorkflowState.NEEDS_REVIEW, WorkflowState.FAILED, WorkflowState.CANCELLED}
    ),
    WorkflowState.EXECUTE: frozenset(
        {
            WorkflowState.VERIFY,
            WorkflowState.REPAIR,
            WorkflowState.NEEDS_REVIEW,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
        }
    ),
    WorkflowState.VERIFY: frozenset(
        {
            WorkflowState.COMPLETED,
            WorkflowState.REPAIR,
            WorkflowState.NEEDS_REVIEW,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
        }
    ),
    WorkflowState.REPAIR: frozenset(
        {WorkflowState.VERIFY, WorkflowState.NEEDS_REVIEW, WorkflowState.FAILED, WorkflowState.CANCELLED}
    ),
    WorkflowState.COMPLETED: frozenset(),
    WorkflowState.NEEDS_REVIEW: frozenset(),
    WorkflowState.FAILED: frozenset(),
    WorkflowState.CANCELLED: frozenset(),
}


class InvalidTransition(ValueError):
    pass


def assert_transition(current: WorkflowState, target: WorkflowState) -> None:
    if current in TERMINAL_STATES:
        raise InvalidTransition(f"terminal workflow cannot transition: {current.value} -> {target.value}")
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransition(f"invalid workflow transition: {current.value} -> {target.value}")


__all__ = ["ALLOWED_TRANSITIONS", "InvalidTransition", "assert_transition"]
