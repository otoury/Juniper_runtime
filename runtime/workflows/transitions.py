from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.workflows.declarations import (
    WorkflowDeclaration,
    WorkflowStepDeclaration,
)


OUTCOME_SUCCESS = "success"
OUTCOME_FAILURE = "failure"
OUTCOME_INADEQUATE = "inadequate"
TERMINAL_OPERATION_ID = "__terminate__"
ALLOWED_OUTCOMES = {
    OUTCOME_SUCCESS,
    OUTCOME_FAILURE,
    OUTCOME_INADEQUATE,
}
STATUS_TO_OUTCOME = {
    "success": OUTCOME_SUCCESS,
    "succeeded": OUTCOME_SUCCESS,
    "completed": OUTCOME_SUCCESS,
    "failure": OUTCOME_FAILURE,
    "failed": OUTCOME_FAILURE,
    "error": OUTCOME_FAILURE,
    "inadequate": OUTCOME_INADEQUATE,
    "insufficient": OUTCOME_INADEQUATE,
}


@dataclass(frozen=True)
class WorkflowTransitionResolution:
    workflow_id: str
    current_operation_id: str | None
    outcome: str | None
    next_operation_id: str | None
    resolved: bool
    terminal: bool
    blocking: bool
    suspending: bool
    skipped_reasons: tuple[str, ...]
    audit_summary: dict[str, Any]

    def to_audit_record(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "current_operation_id": self.current_operation_id,
            "outcome": self.outcome,
            "next_operation_id": self.next_operation_id,
            "resolved": self.resolved,
            "terminal": self.terminal,
            "blocking": self.blocking,
            "suspending": self.suspending,
            "skipped_reasons": list(self.skipped_reasons),
            "audit_summary": dict(self.audit_summary),
        }


def resolve_workflow_transition(
    *,
    workflow: WorkflowDeclaration,
    current_operation_id: str,
    result_status: str | None = None,
    outcome: str | None = None,
) -> WorkflowTransitionResolution:
    current = _step_by_operation_id(workflow, current_operation_id)
    if current is None:
        return _closed(
            workflow=workflow,
            current_operation_id=current_operation_id,
            outcome=_normalize_outcome(outcome, result_status),
            skipped_reasons=("operation_not_found",),
        )

    normalized_outcome = _normalize_outcome(outcome, result_status)
    if normalized_outcome not in ALLOWED_OUTCOMES:
        return _closed(
            workflow=workflow,
            current_operation_id=current.semantic_operation,
            outcome=normalized_outcome,
            skipped_reasons=("unsupported_transition_outcome",),
            current=current,
        )

    target = _transition_target(current, normalized_outcome)
    if target is None:
        return _closed(
            workflow=workflow,
            current_operation_id=current.semantic_operation,
            outcome=normalized_outcome,
            skipped_reasons=("transition_not_declared",),
            current=current,
        )

    if target == TERMINAL_OPERATION_ID:
        return _resolved(
            workflow=workflow,
            current=current,
            outcome=normalized_outcome,
            next_step=None,
            terminal=True,
        )

    next_step = _step_by_operation_id(workflow, target)
    if next_step is None:
        return _closed(
            workflow=workflow,
            current_operation_id=current.semantic_operation,
            outcome=normalized_outcome,
            skipped_reasons=("transition_target_not_found",),
            current=current,
        )

    return _resolved(
        workflow=workflow,
        current=current,
        outcome=normalized_outcome,
        next_step=next_step,
        terminal=False,
    )


def _transition_target(
    step: WorkflowStepDeclaration,
    outcome: str,
) -> str | None:
    if outcome == OUTCOME_SUCCESS:
        return step.on_success
    if outcome == OUTCOME_FAILURE:
        return step.on_failure
    if outcome == OUTCOME_INADEQUATE:
        return step.on_inadequate
    return None


def _normalize_outcome(
    outcome: str | None,
    result_status: str | None,
) -> str | None:
    if isinstance(outcome, str) and outcome.strip():
        return outcome.strip()
    if isinstance(result_status, str) and result_status.strip():
        status = result_status.strip()
        return STATUS_TO_OUTCOME.get(status, status)
    return None


def _step_by_operation_id(
    workflow: WorkflowDeclaration,
    operation_id: str,
) -> WorkflowStepDeclaration | None:
    if not isinstance(operation_id, str) or not operation_id.strip():
        return None
    wanted = operation_id.strip()
    for step in workflow.steps:
        if step.semantic_operation == wanted:
            return step
    return None


def _resolved(
    *,
    workflow: WorkflowDeclaration,
    current: WorkflowStepDeclaration,
    outcome: str,
    next_step: WorkflowStepDeclaration | None,
    terminal: bool,
) -> WorkflowTransitionResolution:
    next_operation_id = (
        None if terminal or next_step is None else next_step.semantic_operation
    )
    blocking = False if next_step is None else next_step.blocking
    suspending = False if next_step is None else next_step.suspending
    return WorkflowTransitionResolution(
        workflow_id=workflow.workflow_id,
        current_operation_id=current.semantic_operation,
        outcome=outcome,
        next_operation_id=next_operation_id,
        resolved=True,
        terminal=terminal,
        blocking=blocking,
        suspending=suspending,
        skipped_reasons=(),
        audit_summary=_audit_summary(
            workflow=workflow,
            current=current,
            outcome=outcome,
            next_step=next_step,
            resolved=True,
            terminal=terminal,
            blocking=blocking,
            suspending=suspending,
            skipped_reasons=(),
        ),
    )


def _closed(
    *,
    workflow: WorkflowDeclaration,
    current_operation_id: str | None,
    outcome: str | None,
    skipped_reasons: tuple[str, ...],
    current: WorkflowStepDeclaration | None = None,
) -> WorkflowTransitionResolution:
    return WorkflowTransitionResolution(
        workflow_id=workflow.workflow_id,
        current_operation_id=current_operation_id,
        outcome=outcome,
        next_operation_id=None,
        resolved=False,
        terminal=False,
        blocking=False,
        suspending=False,
        skipped_reasons=skipped_reasons,
        audit_summary=_audit_summary(
            workflow=workflow,
            current=current,
            outcome=outcome,
            next_step=None,
            resolved=False,
            terminal=False,
            blocking=False,
            suspending=False,
            skipped_reasons=skipped_reasons,
        ),
    )


def _audit_summary(
    *,
    workflow: WorkflowDeclaration,
    current: WorkflowStepDeclaration | None,
    outcome: str | None,
    next_step: WorkflowStepDeclaration | None,
    resolved: bool,
    terminal: bool,
    blocking: bool,
    suspending: bool,
    skipped_reasons: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "workflow_id": workflow.workflow_id,
        "current_operation_id": (
            current.semantic_operation if current else None
        ),
        "outcome": outcome,
        "next_operation_id": (
            next_step.semantic_operation if next_step else None
        ),
        "resolved": resolved,
        "terminal": terminal,
        "blocking": blocking,
        "suspending": suspending,
        "skipped_reasons": list(skipped_reasons),
        "execution_performed": False,
    }


__all__ = [
    "OUTCOME_FAILURE",
    "OUTCOME_INADEQUATE",
    "OUTCOME_SUCCESS",
    "TERMINAL_OPERATION_ID",
    "WorkflowTransitionResolution",
    "resolve_workflow_transition",
]
