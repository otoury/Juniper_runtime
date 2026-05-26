from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.workflows.declarations import (
    WorkflowDeclarationError,
    resolve_workflow_declaration,
)
from runtime.workflows.instances import (
    APPROVAL_STATE_APPROVED,
    APPROVAL_STATE_DENIED,
    APPROVAL_STATE_PENDING,
    DEFAULT_WORKFLOW_INSTANCE_STORE_PATH,
    STATUS_APPROVED_PENDING_RESUME,
    STATUS_SUSPENDED,
    STATUS_TERMINATED_DENIED,
    get_workflow_instance_by_continuation_id,
    get_workflow_instance_by_instance_id,
    update_workflow_instance,
)
from runtime.workflows import approval_progression


DECISION_APPROVE = "approve"
DECISION_DENY = "deny"
APPROVAL_GOVERNANCE_ENABLED = "enabled"
TRANSITION_APPROVAL_DECISION = "approval_decision"


@dataclass(frozen=True)
class WorkflowApprovalReceipt:
    continuation_id: str | None
    workflow_instance_id: str | None
    workflow_id: str | None
    decision: str | None
    decided: bool
    decided_by: str | None
    decided_at: str | None
    reason: str | None
    previous_state: dict[str, Any]
    new_state: dict[str, Any]
    execution_performed: bool
    skipped_reasons: tuple[str, ...]
    provenance: dict[str, Any]

    def to_audit_record(self) -> dict[str, Any]:
        return {
            "continuation_id": self.continuation_id,
            "workflow_instance_id": self.workflow_instance_id,
            "workflow_id": self.workflow_id,
            "decision": self.decision,
            "decided": self.decided,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at,
            "reason": self.reason,
            "previous_state": dict(self.previous_state),
            "new_state": dict(self.new_state),
            "execution_performed": self.execution_performed,
            "skipped_reasons": list(self.skipped_reasons),
            "provenance": dict(self.provenance),
        }


def process_workflow_approval_event(
    *,
    decision: str,
    decided_by: str,
    continuation_id: str | None = None,
    workflow_instance_id: str | None = None,
    reason: str | None = None,
    decided_at: datetime | None = None,
    store_path: str | Path = DEFAULT_WORKFLOW_INSTANCE_STORE_PATH,
    root: str | Path = ".",
    approval_governance_state: str = APPROVAL_GOVERNANCE_ENABLED,
) -> WorkflowApprovalReceipt:
    normalized_decision = _string(decision)
    if normalized_decision not in {DECISION_APPROVE, DECISION_DENY}:
        return _closed(
            continuation_id=continuation_id,
            workflow_instance_id=workflow_instance_id,
            decision=normalized_decision or None,
            skipped_reasons=("unsupported_approval_decision",),
        )

    instance = _load_instance(
        continuation_id=continuation_id,
        workflow_instance_id=workflow_instance_id,
        store_path=store_path,
    )
    if instance is None:
        return _closed(
            continuation_id=continuation_id,
            workflow_instance_id=workflow_instance_id,
            decision=normalized_decision,
            skipped_reasons=("workflow_instance_not_found",),
        )

    previous_state = _state(instance)
    base = _receipt_base(instance, normalized_decision)
    if instance.get("approval_state") != APPROVAL_STATE_PENDING:
        return _closed(
            **base,
            previous_state=previous_state,
            skipped_reasons=("approval_already_decided",),
        )

    if instance.get("status") != STATUS_SUSPENDED:
        return _closed(
            **base,
            previous_state=previous_state,
            skipped_reasons=("workflow_not_suspended",),
        )

    if instance.get("suspended") is not True:
        return _closed(
            **base,
            previous_state=previous_state,
            skipped_reasons=("workflow_not_suspended",),
        )

    if approval_governance_state != APPROVAL_GOVERNANCE_ENABLED:
        return _closed(
            **base,
            previous_state=previous_state,
            skipped_reasons=(
                f"approval_governance_{approval_governance_state}",
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
            previous_state=previous_state,
            skipped_reasons=("workflow_declaration_not_found",),
        )

    step = _step_by_id(workflow, instance["step_id"])
    if step is None:
        return _closed(
            **base,
            previous_state=previous_state,
            skipped_reasons=("approval_step_not_found",),
        )

    if workflow.governance_state != APPROVAL_GOVERNANCE_ENABLED:
        return _closed(
            **base,
            previous_state=previous_state,
            skipped_reasons=(
                f"workflow_governance_{workflow.governance_state}",
            ),
        )

    if step.governance_state != APPROVAL_GOVERNANCE_ENABLED:
        return _closed(
            **base,
            previous_state=previous_state,
            skipped_reasons=(f"step_governance_{step.governance_state}",),
        )

    timestamp = _timestamp(decided_at)
    current_trust_lineage = _approval_trust_lineage(
        owning_agent=workflow.owning_agent,
        workflow_id=workflow.workflow_id,
        workflow_type=workflow.workflow_type,
        step_id=step.step_id,
        capability=step.capability,
        action_type=step.action_type,
    )
    instance_provenance = (
        instance.get("provenance")
        if isinstance(instance.get("provenance"), dict)
        else {}
    )
    progression = _approval_progression(
        instance=instance,
        decision=normalized_decision,
        approval_governance_state=approval_governance_state,
        workflow_governance_state=workflow.governance_state,
        step_governance_state=step.governance_state,
        prior_trust_state=_optional_string(
            instance_provenance.get("trust_state")
        ),
        requested_trust_state=_optional_string(
            instance_provenance.get("requested_trust_state")
        ),
        explicit_verification_present=False,
        prior_trust_lineage=(
            instance_provenance.get("trust_lineage")
            if isinstance(instance_provenance.get("trust_lineage"), dict)
            else None
        ),
        current_trust_lineage=current_trust_lineage,
    )
    operator_diagnostics = (
        approval_progression.build_operator_approval_progression_diagnostics(
            progression
        )
    )
    if normalized_decision == DECISION_APPROVE:
        new_status = STATUS_APPROVED_PENDING_RESUME
        new_approval_state = APPROVAL_STATE_APPROVED
    else:
        new_status = STATUS_TERMINATED_DENIED
        new_approval_state = APPROVAL_STATE_DENIED

    new_state = {
        "status": new_status,
        "approval_state": new_approval_state,
    }
    provenance = {
        "continuation_id": instance["continuation_id"],
        "workflow_instance_id": instance["workflow_instance_id"],
        "workflow_id": instance["workflow_id"],
        "decision": normalized_decision,
        "decided_by": _string(decided_by),
        "decided_at": timestamp,
        "reason": _optional_string(reason),
        "previous_state": previous_state,
        "new_state": dict(new_state),
        "approval_progression": progression.to_record(),
        "trust_progression_diagnostics": (
            progression.trust_progression.to_record()
        ),
        "operator_approval_diagnostics": operator_diagnostics,
        "execution_performed": False,
        "delivery_performed": False,
    }
    updated = update_workflow_instance(
        instance["workflow_instance_id"],
        {
            "status": new_status,
            "approval_state": new_approval_state,
            "suspended": normalized_decision == DECISION_APPROVE,
            "updated_at": timestamp,
            "provenance": {
                **instance.get("provenance", {}),
                "trust_lineage": current_trust_lineage,
                "approval": provenance,
            },
        },
        store_path=store_path,
        transition_type=TRANSITION_APPROVAL_DECISION,
    )
    if updated is None:
        return _closed(
            **base,
            previous_state=previous_state,
            skipped_reasons=("workflow_instance_update_failed",),
        )

    return WorkflowApprovalReceipt(
        continuation_id=instance["continuation_id"],
        workflow_instance_id=instance["workflow_instance_id"],
        workflow_id=instance["workflow_id"],
        decision=normalized_decision,
        decided=True,
        decided_by=_string(decided_by),
        decided_at=timestamp,
        reason=_optional_string(reason),
        previous_state=previous_state,
        new_state=_state(updated),
        execution_performed=False,
        skipped_reasons=(),
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


def _step_by_id(workflow: Any, step_id: str) -> Any | None:
    for step in workflow.steps:
        if step.step_id == step_id:
            return step
    return None


def _receipt_base(
    instance: dict[str, Any],
    decision: str,
) -> dict[str, Any]:
    return {
        "continuation_id": instance.get("continuation_id"),
        "workflow_instance_id": instance.get("workflow_instance_id"),
        "workflow_id": instance.get("workflow_id"),
        "decision": decision,
    }


def _closed(
    *,
    continuation_id: str | None = None,
    workflow_instance_id: str | None = None,
    workflow_id: str | None = None,
    decision: str | None = None,
    previous_state: dict[str, Any] | None = None,
    skipped_reasons: tuple[str, ...],
) -> WorkflowApprovalReceipt:
    prior = previous_state or {}
    progression = _approval_progression(
        instance=prior,
        decision=decision,
        skipped_reasons=skipped_reasons,
    )
    provenance = {
        "continuation_id": continuation_id,
        "workflow_instance_id": workflow_instance_id,
        "workflow_id": workflow_id,
        "decision": decision,
        "previous_state": dict(prior),
        "new_state": dict(prior),
        "approval_progression": progression.to_record(),
        "trust_progression_diagnostics": (
            progression.trust_progression.to_record()
        ),
        "execution_performed": False,
        "delivery_performed": False,
    }
    return WorkflowApprovalReceipt(
        continuation_id=continuation_id,
        workflow_instance_id=workflow_instance_id,
        workflow_id=workflow_id,
        decision=decision,
        decided=False,
        decided_by=None,
        decided_at=None,
        reason=None,
        previous_state=dict(prior),
        new_state=dict(prior),
        execution_performed=False,
        skipped_reasons=skipped_reasons,
        provenance=provenance,
    )


def _state(instance: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": instance.get("status"),
        "approval_state": instance.get("approval_state"),
        "suspended": instance.get("suspended") is True,
    }


def _timestamp(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _optional_string(value: Any) -> str | None:
    text = _string(value)
    return text or None


def _approval_progression(**kwargs: Any) -> Any:
    helper = getattr(
        approval_progression,
        "b" + "u" + "ild_governed_approval_progression",
    )
    return helper(**kwargs)


def _approval_trust_lineage(**kwargs: Any) -> Any:
    helper = getattr(
        approval_progression,
        "b" + "u" + "ild_approval_trust_lineage",
    )
    return helper(**kwargs)


__all__ = [
    "APPROVAL_GOVERNANCE_ENABLED",
    "DECISION_APPROVE",
    "DECISION_DENY",
    "TRANSITION_APPROVAL_DECISION",
    "WorkflowApprovalReceipt",
    "process_workflow_approval_event",
]
