from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.workflows.declarations import (
    WorkflowDeclarationError,
    WorkflowStepDeclaration,
    resolve_workflow_declaration,
)
from runtime.workflows.instances import (
    APPROVAL_STATE_APPROVED,
    APPROVAL_STATE_PENDING,
    DEFAULT_WORKFLOW_INSTANCE_STORE_PATH,
    STATUS_APPROVED_PENDING_RESUME,
    STATUS_RESUMED_PENDING_EXECUTION,
    STATUS_SUSPENDED,
    get_workflow_instance_by_continuation_id,
    get_workflow_instance_by_instance_id,
    update_workflow_instance,
)
from runtime.workflows.resume_integrity import (
    WorkflowResumeIntegrityReceipt,
    validate_workflow_resume_integrity,
)
from runtime.workflows.trust_inheritance import (
    BOUNDARY_DELEGATED_WORKFLOW_STEP,
    build_trust_inheritance_decision,
    build_workflow_step_trust_lineage,
)


CONTINUATION_GOVERNANCE_ENABLED = "enabled"
TRANSITION_CONTINUATION_RESUMED = "continuation_resumed"


@dataclass(frozen=True)
class WorkflowContinuationReceipt:
    continuation_id: str | None
    workflow_instance_id: str | None
    workflow_id: str | None
    resumed: bool
    resumed_by: str | None
    resumed_at: str | None
    previous_status: str | None
    new_status: str | None
    execution_performed: bool
    remaining_actions: tuple[dict[str, Any], ...]
    skipped_reasons: tuple[str, ...]
    resume_integrity_receipt: dict[str, Any] | None
    provenance: dict[str, Any]

    def to_audit_record(self) -> dict[str, Any]:
        return {
            "continuation_id": self.continuation_id,
            "workflow_instance_id": self.workflow_instance_id,
            "workflow_id": self.workflow_id,
            "resumed": self.resumed,
            "resumed_by": self.resumed_by,
            "resumed_at": self.resumed_at,
            "previous_status": self.previous_status,
            "new_status": self.new_status,
            "execution_performed": self.execution_performed,
            "remaining_action_count": len(self.remaining_actions),
            "skipped_reasons": list(self.skipped_reasons),
            "resume_integrity_receipt": (
                dict(self.resume_integrity_receipt)
                if self.resume_integrity_receipt is not None
                else None
            ),
            "provenance": dict(self.provenance),
        }


def resume_workflow_continuation(
    *,
    continuation_id: str | None = None,
    workflow_instance_id: str | None = None,
    approved: bool,
    resumed_by: str,
    store_path: str | Path = DEFAULT_WORKFLOW_INSTANCE_STORE_PATH,
    root: str | Path = ".",
    resumed_at: datetime | None = None,
    continuation_governance_state: str = CONTINUATION_GOVERNANCE_ENABLED,
) -> WorkflowContinuationReceipt:
    instance = _load_instance(
        continuation_id=continuation_id,
        workflow_instance_id=workflow_instance_id,
        store_path=store_path,
    )
    if instance is None:
        return _closed(
            continuation_id=continuation_id,
            workflow_instance_id=workflow_instance_id,
            skipped_reasons=("workflow_instance_not_found",),
        )

    base = _receipt_base(instance)
    if instance.get("status") not in {
        STATUS_SUSPENDED,
        STATUS_APPROVED_PENDING_RESUME,
    }:
        return _closed(
            **base,
            skipped_reasons=("workflow_not_suspended",),
        )

    if instance.get("suspended") is not True:
        return _closed(
            **base,
            skipped_reasons=("workflow_not_suspended",),
        )

    if instance.get("approval_state") not in {
        APPROVAL_STATE_PENDING,
        APPROVAL_STATE_APPROVED,
    }:
        return _closed(
            **base,
            skipped_reasons=("approval_state_not_continuable",),
        )

    if not approved:
        return _closed(
            **base,
            skipped_reasons=("approval_not_granted",),
        )

    if continuation_governance_state != CONTINUATION_GOVERNANCE_ENABLED:
        return _closed(
            **base,
            skipped_reasons=(
                f"continuation_governance_{continuation_governance_state}",
            ),
        )

    try:
        workflow = resolve_workflow_declaration(
            agent_name=instance["owning_agent"],
            workflow_id=instance["workflow_id"],
            root=root,
        )
    except WorkflowDeclarationError:
        return _closed(
            **base,
            skipped_reasons=("workflow_declaration_not_found",),
        )

    suspended_step = _step_by_id(workflow, instance["step_id"])
    if suspended_step is None:
        return _closed(
            **base,
            skipped_reasons=("suspended_step_not_found",),
        )

    integrity = validate_workflow_resume_integrity(
        instance=instance,
        workflow=workflow,
        step=suspended_step,
    )
    if not integrity.validation_passed:
        return _closed(
            **base,
            skipped_reasons=integrity.skipped_reasons,
            resume_integrity_receipt=integrity,
        )

    if workflow.governance_state != CONTINUATION_GOVERNANCE_ENABLED:
        return _closed(
            **base,
            skipped_reasons=(
                f"workflow_governance_{workflow.governance_state}",
            ),
        )

    if suspended_step.governance_state != CONTINUATION_GOVERNANCE_ENABLED:
        return _closed(
            **base,
            skipped_reasons=(
                f"step_governance_{suspended_step.governance_state}",
            ),
        )

    timestamp = _timestamp(resumed_at)
    remaining_actions = _remaining_actions(
        workflow=workflow,
        after_step_id=suspended_step.step_id,
        continuation_id=instance["continuation_id"],
        instance=instance,
    )
    new_status = STATUS_RESUMED_PENDING_EXECUTION
    provenance = {
        "continuation_id": instance["continuation_id"],
        "workflow_instance_id": instance["workflow_instance_id"],
        "workflow_id": instance["workflow_id"],
        "resumed_by": _string(resumed_by),
        "resumed_at": timestamp,
        "previous_status": instance["status"],
        "new_status": new_status,
        "resume_integrity_receipt_ref": integrity.receipt_ref,
        "execution_performed": False,
        "delivery_performed": False,
    }
    updated = update_workflow_instance(
        instance["workflow_instance_id"],
        {
            "status": new_status,
            "approval_state": APPROVAL_STATE_APPROVED,
            "suspended": False,
            "updated_at": timestamp,
            "provenance": {
                **instance.get("provenance", {}),
                "continuation": provenance,
                "resume_integrity": integrity.to_record(),
            },
        },
        store_path=store_path,
        transition_type=TRANSITION_CONTINUATION_RESUMED,
    )
    if updated is None:
        return _closed(
            **base,
            skipped_reasons=("workflow_instance_update_failed",),
        )

    return WorkflowContinuationReceipt(
        continuation_id=instance["continuation_id"],
        workflow_instance_id=instance["workflow_instance_id"],
        workflow_id=instance["workflow_id"],
        resumed=True,
        resumed_by=_string(resumed_by),
        resumed_at=timestamp,
        previous_status=instance["status"],
        new_status=new_status,
        execution_performed=False,
        remaining_actions=remaining_actions,
        skipped_reasons=(),
        resume_integrity_receipt=integrity.to_record(),
        provenance=provenance,
    )


def _load_instance(
    *,
    continuation_id: str | None,
    workflow_instance_id: str | None,
    store_path: str | Path,
) -> dict[str, Any] | None:
    if continuation_id:
        return get_workflow_instance_by_continuation_id(
            continuation_id,
            store_path=store_path,
        )
    if workflow_instance_id:
        return get_workflow_instance_by_instance_id(
            workflow_instance_id,
            store_path=store_path,
        )
    return None


def _remaining_actions(
    *,
    workflow: Any,
    after_step_id: str,
    continuation_id: str,
    instance: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    step_ids = [step.step_id for step in workflow.steps]
    try:
        start = step_ids.index(after_step_id) + 1
    except ValueError:
        return ()

    actions: list[dict[str, Any]] = []
    for step in workflow.steps[start:]:
        if not step.action_type:
            continue
        actions.append(
            _action_descriptor(
                step,
                workflow,
                continuation_id,
                instance=instance,
            )
        )
    return tuple(actions)


def _action_descriptor(
    step: WorkflowStepDeclaration,
    workflow: Any,
    continuation_id: str,
    instance: dict[str, Any],
) -> dict[str, Any]:
    provenance = (
        instance.get("provenance")
        if isinstance(instance.get("provenance"), dict)
        else {}
    )
    prior_lineage = (
        provenance.get("trust_lineage")
        if isinstance(provenance.get("trust_lineage"), dict)
        else None
    )
    current_lineage = build_workflow_step_trust_lineage(
        owning_agent=getattr(workflow, "owning_agent", None),
        workflow_id=getattr(workflow, "workflow_id", None),
        workflow_type=getattr(workflow, "workflow_type", None),
        step_id=step.step_id,
        capability=step.capability,
        action_type=step.action_type,
    )
    return {
        "workflow_id": workflow.workflow_id,
        "owning_agent": workflow.owning_agent,
        "step_id": step.step_id,
        "operation_id": step.semantic_operation,
        "action_type": step.action_type,
        "output_type": step.output_type,
        "requires_approval": step.requires_approval,
        "governance_state": step.governance_state,
        "placeholder": step.placeholder,
        "delivery_performed": False,
        "execution_performed": False,
        "continuation_id": continuation_id,
        "trust_inheritance": build_trust_inheritance_decision(
            boundary_type=BOUNDARY_DELEGATED_WORKFLOW_STEP,
            prior_trust_state=_string(provenance.get("trust_state")) or None,
            prior_trust_lineage=prior_lineage,
            current_trust_lineage=current_lineage,
        ).to_record(),
    }


def _step_by_id(
    workflow: Any,
    step_id: str,
) -> WorkflowStepDeclaration | None:
    for step in workflow.steps:
        if step.step_id == step_id:
            return step
    return None


def _receipt_base(instance: dict[str, Any]) -> dict[str, Any]:
    return {
        "continuation_id": instance.get("continuation_id"),
        "workflow_instance_id": instance.get("workflow_instance_id"),
        "workflow_id": instance.get("workflow_id"),
        "previous_status": instance.get("status"),
    }


def _closed(
    *,
    continuation_id: str | None = None,
    workflow_instance_id: str | None = None,
    workflow_id: str | None = None,
    previous_status: str | None = None,
    skipped_reasons: tuple[str, ...],
    resume_integrity_receipt: WorkflowResumeIntegrityReceipt | None = None,
) -> WorkflowContinuationReceipt:
    integrity_record = (
        resume_integrity_receipt.to_record()
        if resume_integrity_receipt is not None
        else None
    )
    provenance = {
        "continuation_id": continuation_id,
        "workflow_instance_id": workflow_instance_id,
        "workflow_id": workflow_id,
        "previous_status": previous_status,
        "new_status": previous_status,
        "resume_integrity_receipt_ref": (
            resume_integrity_receipt.receipt_ref
            if resume_integrity_receipt is not None
            else None
        ),
        "execution_performed": False,
        "delivery_performed": False,
    }
    return WorkflowContinuationReceipt(
        continuation_id=continuation_id,
        workflow_instance_id=workflow_instance_id,
        workflow_id=workflow_id,
        resumed=False,
        resumed_by=None,
        resumed_at=None,
        previous_status=previous_status,
        new_status=previous_status,
        execution_performed=False,
        remaining_actions=(),
        skipped_reasons=skipped_reasons,
        resume_integrity_receipt=integrity_record,
        provenance=provenance,
    )


def _timestamp(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


__all__ = [
    "APPROVAL_STATE_APPROVED",
    "CONTINUATION_GOVERNANCE_ENABLED",
    "TRANSITION_CONTINUATION_RESUMED",
    "WorkflowContinuationReceipt",
    "resume_workflow_continuation",
]
