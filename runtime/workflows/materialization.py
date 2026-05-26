from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.lookup.governance import GOVERNANCE_DISABLED
from runtime.lookup.request_planner import create_explicit_lookup_request
from runtime.registries.lookup_capability_registry import (
    LookupCapabilityRegistrationError,
    resolve_lookup_capability,
)
from runtime.workflows.declarations import (
    WorkflowDeclaration,
    WorkflowStepDeclaration,
)


GUEST_CANDIDATE_LIST_ARTIFACT = "guest_candidate_list"
RETRIEVAL_ACTION_TYPE = "bounded_guest_retrieval"


@dataclass(frozen=True)
class WorkflowActionMaterialization:
    workflow_id: str
    step_id: str
    action: dict[str, Any] | None
    output_artifact: dict[str, Any] | None
    materialized: bool
    execution_allowed: bool
    skipped_reasons: tuple[str, ...]
    audit_summary: dict[str, Any]


def materialize_retrieval_action(
    *,
    workflow: WorkflowDeclaration,
    planner_lookup: dict[str, Any],
    root: str | Path = ".",
) -> WorkflowActionMaterialization:
    step = _retrieval_step(workflow)
    if step is None:
        return _closed(
            workflow=workflow,
            step_id="",
            skipped_reasons=("retrieval_step_not_declared",),
        )

    if workflow.governance_state == GOVERNANCE_DISABLED:
        return _closed(
            workflow=workflow,
            step_id=step.step_id,
            skipped_reasons=("workflow_disabled",),
            step=step,
        )

    if step.governance_state == GOVERNANCE_DISABLED:
        return _closed(
            workflow=workflow,
            step_id=step.step_id,
            skipped_reasons=("retrieval_step_disabled",),
            step=step,
        )

    lookup_intent = _bounded_planner_lookup(
        planner_lookup=planner_lookup,
        max_results=_max_results(step),
    )
    shared_capability = step.capability
    resolved = resolve_lookup_capability(
        agent=workflow.owning_agent,
        shared_capability=shared_capability,
        root=Path(root),
    )
    if isinstance(resolved, LookupCapabilityRegistrationError):
        return _closed(
            workflow=workflow,
            step_id=step.step_id,
            skipped_reasons=("lookup_capability_resolution_failed",),
            step=step,
            validation_errors=(resolved.field,),
        )

    planned_lookup = create_explicit_lookup_request(
        agent_name=workflow.owning_agent,
        shared_capability=shared_capability,
        planner_lookup=lookup_intent,
        root=Path(root),
        resolved_capability=resolved,
    )
    if planned_lookup.request is None:
        return _closed(
            workflow=workflow,
            step_id=step.step_id,
            skipped_reasons=planned_lookup.skipped_reasons,
            step=step,
            validation_errors=planned_lookup.validation_errors,
            lookup_trace=planned_lookup.trace,
        )

    request = dict(planned_lookup.request)
    action = {
        "action_type": RETRIEVAL_ACTION_TYPE,
        "workflow_id": workflow.workflow_id,
        "owning_agent": workflow.owning_agent,
        "step_id": step.step_id,
        "semantic_operation": step.semantic_operation,
        "capability": shared_capability,
        "requires_approval": step.requires_approval,
        "governance_state": step.governance_state,
        "lookup_request": request,
        "source_binding": {
            "resource_binding_id": step.constraints.get(
                "resource_binding_id"
            ),
            "source_scope": request.get("source_scope"),
            "governance_ref": step.constraints.get("governance_ref"),
            "execution_policy_ref": step.constraints.get(
                "execution_policy_ref"
            ),
        },
        "output_artifact_type": GUEST_CANDIDATE_LIST_ARTIFACT,
        "execution_allowed": (
            step.governance_state == "enabled"
            and resolved.governance.execution_allowed
        ),
    }
    output_artifact = {
        "artifact_type": GUEST_CANDIDATE_LIST_ARTIFACT,
        "workflow_id": workflow.workflow_id,
        "step_id": step.step_id,
        "candidate_count": 0,
        "max_results": request.get("max_results"),
        "candidates": [],
        "provenance": {
            "lookup_type": request.get("lookup_type"),
            "source_scope": request.get("source_scope"),
            "resource_binding_id": step.constraints.get(
                "resource_binding_id"
            ),
            "retrieval_executed": False,
            "governance_state": step.governance_state,
        },
    }

    return WorkflowActionMaterialization(
        workflow_id=workflow.workflow_id,
        step_id=step.step_id,
        action=action,
        output_artifact=output_artifact,
        materialized=True,
        execution_allowed=bool(action["execution_allowed"]),
        skipped_reasons=(),
        audit_summary=_audit_summary(
            workflow=workflow,
            step=step,
            action_type=RETRIEVAL_ACTION_TYPE,
            materialized=True,
            execution_allowed=bool(action["execution_allowed"]),
            skipped_reasons=(),
            lookup_trace=planned_lookup.trace,
        ),
    )


def _retrieval_step(
    workflow: WorkflowDeclaration,
) -> WorkflowStepDeclaration | None:
    for step in workflow.steps:
        if step.step_kind == "retrieval":
            return step
    return None


def _bounded_planner_lookup(
    *,
    planner_lookup: dict[str, Any],
    max_results: int,
) -> dict[str, Any]:
    lookup = dict(planner_lookup if isinstance(planner_lookup, dict) else {})
    requested_max = lookup.get("max_results", max_results)
    if not isinstance(requested_max, int) or isinstance(requested_max, bool):
        requested_max = max_results
    lookup["max_results"] = min(max(1, requested_max), max_results)
    return lookup


def _max_results(step: WorkflowStepDeclaration) -> int:
    value = step.constraints.get("max_results", 5)
    if not isinstance(value, int) or isinstance(value, bool):
        return 5
    return min(max(1, value), 5)


def _closed(
    *,
    workflow: WorkflowDeclaration,
    step_id: str,
    skipped_reasons: tuple[str, ...],
    step: WorkflowStepDeclaration | None = None,
    validation_errors: tuple[str, ...] = (),
    lookup_trace: dict[str, Any] | None = None,
) -> WorkflowActionMaterialization:
    return WorkflowActionMaterialization(
        workflow_id=workflow.workflow_id,
        step_id=step_id,
        action=None,
        output_artifact=None,
        materialized=False,
        execution_allowed=False,
        skipped_reasons=skipped_reasons,
        audit_summary=_audit_summary(
            workflow=workflow,
            step=step,
            action_type=RETRIEVAL_ACTION_TYPE,
            materialized=False,
            execution_allowed=False,
            skipped_reasons=skipped_reasons,
            validation_errors=validation_errors,
            lookup_trace=lookup_trace,
        ),
    )


def _audit_summary(
    *,
    workflow: WorkflowDeclaration,
    step: WorkflowStepDeclaration | None,
    action_type: str,
    materialized: bool,
    execution_allowed: bool,
    skipped_reasons: tuple[str, ...],
    validation_errors: tuple[str, ...] = (),
    lookup_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "workflow_id": workflow.workflow_id,
        "owning_agent": workflow.owning_agent,
        "step_id": step.step_id if step else None,
        "semantic_operation": step.semantic_operation if step else None,
        "action_type": action_type,
        "materialized": materialized,
        "execution_allowed": execution_allowed,
        "retrieval_executed": False,
        "skipped_reasons": list(skipped_reasons),
        "validation_errors": list(validation_errors),
        "lookup_trace": lookup_trace or None,
    }


__all__ = [
    "GUEST_CANDIDATE_LIST_ARTIFACT",
    "RETRIEVAL_ACTION_TYPE",
    "WorkflowActionMaterialization",
    "materialize_retrieval_action",
]
