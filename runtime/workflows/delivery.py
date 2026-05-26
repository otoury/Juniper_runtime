from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.workflows.declarations import (
    WorkflowDeclaration,
    WorkflowDeclarationError,
    WorkflowStepDeclaration,
    resolve_workflow_declaration,
)
from runtime.workflows.instances import (
    APPROVAL_STATE_APPROVED,
    DEFAULT_WORKFLOW_INSTANCE_STORE_PATH,
    STATUS_APPROVED_PENDING_RESUME,
    STATUS_RESUMED_PENDING_EXECUTION,
    get_workflow_instance_by_continuation_id,
    get_workflow_instance_by_instance_id,
)


DELIVERY_ACTION_DESCRIPTOR_TYPE = "delivery_action"
DELIVERY_GOVERNANCE_ENABLED = "enabled"
DELIVERY_PREPARATION_STATUSES = {
    STATUS_APPROVED_PENDING_RESUME,
    STATUS_RESUMED_PENDING_EXECUTION,
}


@dataclass(frozen=True)
class WorkflowDeliveryMaterialization:
    continuation_id: str | None
    workflow_instance_id: str | None
    workflow_id: str | None
    delivery_action: dict[str, Any] | None
    materialized: bool
    delivery_prepared: bool
    delivery_performed: bool
    execution_allowed: bool
    skipped_reasons: tuple[str, ...]
    audit_summary: dict[str, Any]

    def to_audit_record(self) -> dict[str, Any]:
        return {
            "continuation_id": self.continuation_id,
            "workflow_instance_id": self.workflow_instance_id,
            "workflow_id": self.workflow_id,
            "materialized": self.materialized,
            "delivery_prepared": self.delivery_prepared,
            "delivery_performed": self.delivery_performed,
            "execution_allowed": self.execution_allowed,
            "skipped_reasons": list(self.skipped_reasons),
            "audit_summary": dict(self.audit_summary),
        }


def materialize_delivery_action(
    *,
    continuation_id: str | None = None,
    workflow_instance_id: str | None = None,
    store_path: str | Path = DEFAULT_WORKFLOW_INSTANCE_STORE_PATH,
    root: str | Path = ".",
    prepared_at: datetime | None = None,
    delivery_governance_state: str = DELIVERY_GOVERNANCE_ENABLED,
) -> WorkflowDeliveryMaterialization:
    instance = _load_instance(
        continuation_id=continuation_id,
        workflow_instance_id=workflow_instance_id,
        store_path=store_path,
    )
    if instance is None:
        return _closed(
            continuation_id=continuation_id,
            workflow_instance_id=workflow_instance_id,
            workflow_id=None,
            skipped_reasons=("workflow_instance_not_found",),
        )

    base = _base(instance)
    if instance.get("approval_state") != APPROVAL_STATE_APPROVED:
        return _closed(
            **base,
            skipped_reasons=("workflow_not_approved",),
        )

    if instance.get("status") not in DELIVERY_PREPARATION_STATUSES:
        return _closed(
            **base,
            skipped_reasons=("workflow_status_not_delivery_preparable",),
        )

    if delivery_governance_state != DELIVERY_GOVERNANCE_ENABLED:
        return _closed(
            **base,
            skipped_reasons=(
                f"delivery_governance_{delivery_governance_state}",
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

    if workflow.governance_state != DELIVERY_GOVERNANCE_ENABLED:
        return _closed(
            **base,
            skipped_reasons=(
                f"workflow_governance_{workflow.governance_state}",
            ),
        )

    delivery_step = _delivery_step(workflow, after_step_id=instance["step_id"])
    if delivery_step is None:
        return _closed(
            **base,
            skipped_reasons=("delivery_step_not_declared",),
        )

    if delivery_step.governance_state != DELIVERY_GOVERNANCE_ENABLED:
        return _closed(
            **base,
            skipped_reasons=(
                f"delivery_governance_{delivery_step.governance_state}",
            ),
            step=delivery_step,
        )

    if delivery_step.delivery_performed:
        return _closed(
            **base,
            skipped_reasons=("delivery_already_performed",),
            step=delivery_step,
        )

    artifact_refs = _safe_refs(instance.get("artifact_refs"), "artifact")
    action_refs = _safe_refs(instance.get("action_refs"), "action")
    if artifact_refs is None or action_refs is None:
        return _closed(
            **base,
            skipped_reasons=("unsafe_workflow_references",),
            step=delivery_step,
        )

    if not artifact_refs and not action_refs:
        return _closed(
            **base,
            skipped_reasons=("missing_workflow_references",),
            step=delivery_step,
        )

    prepared_timestamp = _timestamp(prepared_at)
    descriptor = {
        "descriptor_type": DELIVERY_ACTION_DESCRIPTOR_TYPE,
        "action_type": delivery_step.action_type,
        "workflow_id": workflow.workflow_id,
        "workflow_instance_id": instance["workflow_instance_id"],
        "continuation_id": instance["continuation_id"],
        "step_id": delivery_step.step_id,
        "semantic_operation": delivery_step.semantic_operation,
        "delivery_capability": delivery_step.capability,
        "delivery_channel": _optional_constraint(
            delivery_step,
            "delivery_channel",
        ),
        "artifact_refs": list(artifact_refs),
        "action_refs": list(action_refs),
        "requires_approval": delivery_step.requires_approval,
        "approval_state": instance["approval_state"],
        "delivery_prepared": True,
        "delivery_performed": False,
        "execution_allowed": _preparation_execution_allowed(delivery_step),
        "governance_state": delivery_step.governance_state,
        "provenance": {
            "workflow_id": workflow.workflow_id,
            "workflow_instance_id": instance["workflow_instance_id"],
            "continuation_id": instance["continuation_id"],
            "prepared_at": prepared_timestamp,
            "approval_state": instance["approval_state"],
            "status": instance["status"],
            "delivery_governance_state": delivery_step.governance_state,
            "delivery_prepared": True,
            "delivery_performed": False,
            "execution_allowed": _preparation_execution_allowed(
                delivery_step
            ),
        },
    }
    return WorkflowDeliveryMaterialization(
        continuation_id=instance["continuation_id"],
        workflow_instance_id=instance["workflow_instance_id"],
        workflow_id=workflow.workflow_id,
        delivery_action=descriptor,
        materialized=True,
        delivery_prepared=True,
        delivery_performed=False,
        execution_allowed=bool(descriptor["execution_allowed"]),
        skipped_reasons=(),
        audit_summary=_audit_summary(
            workflow_id=workflow.workflow_id,
            workflow_instance_id=instance["workflow_instance_id"],
            continuation_id=instance["continuation_id"],
            step=delivery_step,
            materialized=True,
            delivery_prepared=True,
            delivery_performed=False,
            execution_allowed=bool(descriptor["execution_allowed"]),
            skipped_reasons=(),
        ),
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


def _delivery_step(
    workflow: WorkflowDeclaration,
    *,
    after_step_id: str,
) -> WorkflowStepDeclaration | None:
    steps = list(workflow.steps)
    for step in steps:
        if (
            step.step_id == after_step_id
            and step.step_kind == "delivery_placeholder"
        ):
            return step

    start = 0
    for index, step in enumerate(steps):
        if step.step_id == after_step_id:
            start = index + 1
            break

    for step in steps[start:]:
        if step.step_kind == "delivery_placeholder":
            return step
    return None


def _safe_refs(value: Any, expected_prefix: str) -> tuple[str, ...] | None:
    if not isinstance(value, (list, tuple)):
        return ()

    safe: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return None
        text = item.strip()
        if not _safe_ref(text, expected_prefix):
            return None
        safe.append(text)
    return tuple(safe)


def _safe_ref(value: str, expected_prefix: str) -> bool:
    if not value or len(value) > 200:
        return False
    if any(character.isspace() for character in value):
        return False
    parts = value.split(":")
    if len(parts) < 3:
        return False
    if parts[0] != expected_prefix:
        return False
    return all(part.strip() for part in parts)


def _preparation_execution_allowed(step: WorkflowStepDeclaration) -> bool:
    return step.constraints.get("delivery_preparation_execution_allowed") is True


def _optional_constraint(
    step: WorkflowStepDeclaration,
    key: str,
) -> str | None:
    value = step.constraints.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _base(instance: dict[str, Any]) -> dict[str, Any]:
    return {
        "continuation_id": instance.get("continuation_id"),
        "workflow_instance_id": instance.get("workflow_instance_id"),
        "workflow_id": instance.get("workflow_id"),
    }


def _closed(
    *,
    continuation_id: str | None,
    workflow_instance_id: str | None,
    workflow_id: str | None,
    skipped_reasons: tuple[str, ...],
    step: WorkflowStepDeclaration | None = None,
) -> WorkflowDeliveryMaterialization:
    return WorkflowDeliveryMaterialization(
        continuation_id=continuation_id,
        workflow_instance_id=workflow_instance_id,
        workflow_id=workflow_id,
        delivery_action=None,
        materialized=False,
        delivery_prepared=False,
        delivery_performed=False,
        execution_allowed=False,
        skipped_reasons=skipped_reasons,
        audit_summary=_audit_summary(
            workflow_id=workflow_id,
            workflow_instance_id=workflow_instance_id,
            continuation_id=continuation_id,
            step=step,
            materialized=False,
            delivery_prepared=False,
            delivery_performed=False,
            execution_allowed=False,
            skipped_reasons=skipped_reasons,
        ),
    )


def _audit_summary(
    *,
    workflow_id: str | None,
    workflow_instance_id: str | None,
    continuation_id: str | None,
    step: WorkflowStepDeclaration | None,
    materialized: bool,
    delivery_prepared: bool,
    delivery_performed: bool,
    execution_allowed: bool,
    skipped_reasons: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "workflow_id": workflow_id,
        "workflow_instance_id": workflow_instance_id,
        "continuation_id": continuation_id,
        "step_id": step.step_id if step else None,
        "action_type": step.action_type if step else None,
        "delivery_capability": step.capability if step else None,
        "materialized": materialized,
        "delivery_prepared": delivery_prepared,
        "delivery_performed": delivery_performed,
        "execution_allowed": execution_allowed,
        "skipped_reasons": list(skipped_reasons),
    }


def _timestamp(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


__all__ = [
    "DELIVERY_ACTION_DESCRIPTOR_TYPE",
    "DELIVERY_GOVERNANCE_ENABLED",
    "WorkflowDeliveryMaterialization",
    "materialize_delivery_action",
]
