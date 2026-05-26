from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from runtime.workflows.declarations import (
    WorkflowDeclaration,
    WorkflowStepDeclaration,
)


SUSPENSION_ACTION_TYPE = "workflow_suspension"
APPROVAL_STATE_PENDING = "pending_approval"


@dataclass(frozen=True)
class WorkflowSuspensionState:
    workflow_id: str
    owning_agent: str
    step_id: str
    operation_id: str
    action_type: str
    requires_approval: bool
    approval_state: str
    suspended: bool
    continuation_id: str
    delivery_performed: bool
    created_at: str
    artifact_refs: tuple[str, ...]
    action_refs: tuple[str, ...]
    provenance: dict[str, Any]

    def to_record(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "owning_agent": self.owning_agent,
            "step_id": self.step_id,
            "operation_id": self.operation_id,
            "action_type": self.action_type,
            "requires_approval": self.requires_approval,
            "approval_state": self.approval_state,
            "suspended": self.suspended,
            "continuation_id": self.continuation_id,
            "delivery_performed": self.delivery_performed,
            "created_at": self.created_at,
            "artifact_refs": list(self.artifact_refs),
            "action_refs": list(self.action_refs),
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class WorkflowSuspensionMaterialization:
    workflow_id: str
    step_id: str
    action: dict[str, Any] | None
    suspension_state: WorkflowSuspensionState | None
    materialized: bool
    skipped_reasons: tuple[str, ...]
    audit_summary: dict[str, Any]


def materialize_workflow_suspension_action(
    *,
    workflow: WorkflowDeclaration,
    artifact_refs: list[str] | tuple[str, ...] = (),
    action_refs: list[str] | tuple[str, ...] = (),
    step_id: str | None = None,
    created_at: datetime | None = None,
) -> WorkflowSuspensionMaterialization:
    step = _approval_step(workflow, step_id=step_id)
    if step is None:
        return _closed(
            workflow=workflow,
            step_id=step_id or "",
            skipped_reasons=("approval_step_not_declared",),
        )

    if not step.requires_approval:
        return _closed(
            workflow=workflow,
            step_id=step.step_id,
            skipped_reasons=("approval_not_required",),
            step=step,
        )

    if step.delivery_performed:
        return _closed(
            workflow=workflow,
            step_id=step.step_id,
            skipped_reasons=("delivery_already_performed",),
            step=step,
        )

    safe_artifact_refs = _string_tuple(artifact_refs)
    safe_action_refs = _string_tuple(action_refs)
    timestamp = (
        created_at.astimezone(timezone.utc)
        if created_at is not None
        else datetime.now(timezone.utc)
    ).isoformat()
    continuation_id = _continuation_id(
        workflow_id=workflow.workflow_id,
        step_id=step.step_id,
        artifact_refs=safe_artifact_refs,
        action_refs=safe_action_refs,
    )
    provenance = {
        "workflow_id": workflow.workflow_id,
        "operation_id": step.semantic_operation,
        "action_type": SUSPENSION_ACTION_TYPE,
        "requires_approval": True,
        "approval_state": APPROVAL_STATE_PENDING,
        "suspended": True,
        "continuation_id": continuation_id,
        "delivery_performed": False,
        "created_at": timestamp,
    }
    state = WorkflowSuspensionState(
        workflow_id=workflow.workflow_id,
        owning_agent=workflow.owning_agent,
        step_id=step.step_id,
        operation_id=step.semantic_operation,
        action_type=SUSPENSION_ACTION_TYPE,
        requires_approval=True,
        approval_state=APPROVAL_STATE_PENDING,
        suspended=True,
        continuation_id=continuation_id,
        delivery_performed=False,
        created_at=timestamp,
        artifact_refs=safe_artifact_refs,
        action_refs=safe_action_refs,
        provenance=provenance,
    )
    action = {
        "action_type": SUSPENSION_ACTION_TYPE,
        "workflow_id": workflow.workflow_id,
        "owning_agent": workflow.owning_agent,
        "step_id": step.step_id,
        "operation_id": step.semantic_operation,
        "requires_approval": True,
        "approval_state": APPROVAL_STATE_PENDING,
        "suspended": True,
        "continuation_id": continuation_id,
        "delivery_performed": False,
        "artifact_refs": list(safe_artifact_refs),
        "action_refs": list(safe_action_refs),
        "provenance": provenance,
    }
    return WorkflowSuspensionMaterialization(
        workflow_id=workflow.workflow_id,
        step_id=step.step_id,
        action=action,
        suspension_state=state,
        materialized=True,
        skipped_reasons=(),
        audit_summary=_audit_summary(
            workflow=workflow,
            step=step,
            materialized=True,
            skipped_reasons=(),
            continuation_id=continuation_id,
        ),
    )


def _approval_step(
    workflow: WorkflowDeclaration,
    *,
    step_id: str | None,
) -> WorkflowStepDeclaration | None:
    if step_id:
        for step in workflow.steps:
            if step.step_id == step_id:
                return step
        return None

    for kind in ("approval_handoff", "delivery_placeholder"):
        for step in workflow.steps:
            if step.step_kind == kind:
                return step

    return None


def _closed(
    *,
    workflow: WorkflowDeclaration,
    step_id: str,
    skipped_reasons: tuple[str, ...],
    step: WorkflowStepDeclaration | None = None,
) -> WorkflowSuspensionMaterialization:
    return WorkflowSuspensionMaterialization(
        workflow_id=workflow.workflow_id,
        step_id=step_id,
        action=None,
        suspension_state=None,
        materialized=False,
        skipped_reasons=skipped_reasons,
        audit_summary=_audit_summary(
            workflow=workflow,
            step=step,
            materialized=False,
            skipped_reasons=skipped_reasons,
            continuation_id=None,
        ),
    )


def _audit_summary(
    *,
    workflow: WorkflowDeclaration,
    step: WorkflowStepDeclaration | None,
    materialized: bool,
    skipped_reasons: tuple[str, ...],
    continuation_id: str | None,
) -> dict[str, Any]:
    return {
        "workflow_id": workflow.workflow_id,
        "step_id": step.step_id if step else None,
        "operation_id": step.semantic_operation if step else None,
        "action_type": SUSPENSION_ACTION_TYPE,
        "requires_approval": True if step and step.requires_approval else False,
        "approval_state": (
            APPROVAL_STATE_PENDING if materialized else None
        ),
        "suspended": materialized,
        "continuation_id": continuation_id,
        "delivery_performed": False,
        "materialized": materialized,
        "skipped_reasons": list(skipped_reasons),
    }


def _continuation_id(
    *,
    workflow_id: str,
    step_id: str,
    artifact_refs: tuple[str, ...],
    action_refs: tuple[str, ...],
) -> str:
    payload = {
        "workflow_id": workflow_id,
        "step_id": step_id,
        "artifact_refs": list(artifact_refs),
        "action_refs": list(action_refs),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _string_tuple(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        return ()

    return tuple(
        value.strip()
        for value in values
        if isinstance(value, str) and value.strip()
    )


__all__ = [
    "APPROVAL_STATE_PENDING",
    "SUSPENSION_ACTION_TYPE",
    "WorkflowSuspensionMaterialization",
    "WorkflowSuspensionState",
    "materialize_workflow_suspension_action",
]
