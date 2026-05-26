from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.lookup.execution import execute_lookup_request
from runtime.registries.adapter_binding_registry import (
    get_context_adapter_for_source,
)
from runtime.registries.lookup_capability_registry import (
    LookupCapabilityRegistrationError,
    ResolvedLookupCapability,
    resolve_lookup_capability,
)
from runtime.governance.operation_visibility import (
    build_retrieval_governance_visibility,
)
from runtime.workflows.materialization import (
    GUEST_CANDIDATE_LIST_ARTIFACT,
    RETRIEVAL_ACTION_TYPE,
)


@dataclass(frozen=True)
class WorkflowActionExecutionReceipt:
    workflow_id: str | None
    step_id: str | None
    action_type: str | None
    execution_status: str
    retrieval_executed: bool
    execution_allowed: bool
    skipped_reasons: tuple[str, ...]
    artifact: dict[str, Any] | None
    provenance: dict[str, Any]

    def to_audit_record(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "action_type": self.action_type,
            "execution_status": self.execution_status,
            "retrieval_executed": self.retrieval_executed,
            "execution_allowed": self.execution_allowed,
            "skipped_reasons": list(self.skipped_reasons),
            "provenance": dict(self.provenance),
        }


def execute_retrieval_action(
    *,
    action: dict[str, Any],
    agent: Any,
    root: str | Path = ".",
    resolved_capability: ResolvedLookupCapability | None = None,
) -> WorkflowActionExecutionReceipt:
    if not isinstance(action, dict):
        return _closed(
            action={},
            skipped_reasons=("malformed_action",),
            governance_state=None,
        )

    if action.get("action_type") != RETRIEVAL_ACTION_TYPE:
        return _closed(
            action=action,
            skipped_reasons=("unsupported_action_type",),
            governance_state=_string(action.get("governance_state")),
        )

    lookup_request = action.get("lookup_request")
    if not isinstance(lookup_request, dict):
        return _closed(
            action=action,
            skipped_reasons=("missing_lookup_request",),
            governance_state=_string(action.get("governance_state")),
        )

    capability = _string(action.get("capability"))
    agent_name = _string(action.get("owning_agent"))
    if resolved_capability is None:
        resolved = resolve_lookup_capability(
            agent=agent_name or "",
            shared_capability=capability,
            root=Path(root),
        )
        if isinstance(resolved, LookupCapabilityRegistrationError):
            return _closed(
                action=action,
                skipped_reasons=("lookup_capability_resolution_failed",),
                validation_errors=(resolved.field,),
                governance_state=_string(action.get("governance_state")),
            )
        resolved_capability = resolved

    governance_state = resolved_capability.governance.state
    source_binding = action.get("source_binding")
    source_binding_id = (
        source_binding.get("resource_binding_id")
        if isinstance(source_binding, dict)
        else None
    )
    adapter_id = _adapter_id_for_source(
        source_binding_id=source_binding_id,
        root=root,
    )

    if not resolved_capability.governance.execution_allowed:
        return _closed(
            action=action,
            skipped_reasons=(
                f"lookup_capability_{governance_state}",
            ),
            governance_state=governance_state,
            source_binding_id=_string(source_binding_id),
            adapter_id=adapter_id,
            resolved_capability=resolved_capability,
        )

    lookup_result = execute_lookup_request(
        agent=agent,
        lookup_request=lookup_request,
        lookup_capability=resolved_capability,
        require_lookup_capability=True,
    )
    artifact = _artifact_from_lookup_result(
        action=action,
        lookup_result=lookup_result,
        governance_state=governance_state,
        source_binding_id=_string(source_binding_id),
        adapter_id=adapter_id,
        resolved_capability=resolved_capability,
    )
    retrieval_executed = lookup_result.retrieval_executed
    skipped_reasons = tuple(lookup_result.skipped_reasons)
    return WorkflowActionExecutionReceipt(
        workflow_id=_string(action.get("workflow_id")),
        step_id=_string(action.get("step_id")),
        action_type=_string(action.get("action_type")),
        execution_status=(
            "executed"
            if retrieval_executed and not skipped_reasons
            else "closed"
        ),
        retrieval_executed=retrieval_executed,
        execution_allowed=True,
        skipped_reasons=skipped_reasons,
        artifact=artifact,
        provenance=dict(artifact["provenance"]),
    )


def _artifact_from_lookup_result(
    *,
    action: dict[str, Any],
    lookup_result: Any,
    governance_state: str,
    source_binding_id: str | None,
    adapter_id: str | None,
    resolved_capability: ResolvedLookupCapability,
) -> dict[str, Any]:
    request = getattr(lookup_result, "request", {}) or {}
    payloads = getattr(lookup_result, "payloads", []) or []
    candidates = [
        dict(payload)
        for payload in payloads
        if isinstance(payload, dict)
    ]
    max_results = request.get("max_results")
    if isinstance(max_results, int) and not isinstance(max_results, bool):
        candidates = candidates[:max_results]

    return {
        "artifact_type": GUEST_CANDIDATE_LIST_ARTIFACT,
        "workflow_id": action.get("workflow_id"),
        "step_id": action.get("step_id"),
        "candidate_count": len(candidates),
        "max_results": max_results,
        "candidates": candidates,
        "provenance": _provenance(
            action=action,
            request=request,
            source_binding_id=source_binding_id,
            adapter_id=adapter_id,
            governance_state=governance_state,
            execution_allowed=True,
            retrieval_executed=bool(
                getattr(lookup_result, "retrieval_executed", False)
            ),
            resolved_capability=resolved_capability,
        ),
    }


def _closed(
    *,
    action: dict[str, Any],
    skipped_reasons: tuple[str, ...],
    governance_state: str | None,
    validation_errors: tuple[str, ...] = (),
    source_binding_id: str | None = None,
    adapter_id: str | None = None,
    resolved_capability: ResolvedLookupCapability | None = None,
) -> WorkflowActionExecutionReceipt:
    provenance = _provenance(
        action=action,
        request=(
            action.get("lookup_request")
            if isinstance(action.get("lookup_request"), dict)
            else {}
        ),
        source_binding_id=source_binding_id,
        adapter_id=adapter_id,
        governance_state=governance_state,
        execution_allowed=False,
        retrieval_executed=False,
        resolved_capability=resolved_capability,
        validation_errors=validation_errors,
    )
    artifact = {
        "artifact_type": GUEST_CANDIDATE_LIST_ARTIFACT,
        "workflow_id": action.get("workflow_id"),
        "step_id": action.get("step_id"),
        "candidate_count": 0,
        "max_results": (
            action.get("lookup_request", {}).get("max_results")
            if isinstance(action.get("lookup_request"), dict)
            else None
        ),
        "candidates": [],
        "provenance": provenance,
    }
    return WorkflowActionExecutionReceipt(
        workflow_id=_string(action.get("workflow_id")),
        step_id=_string(action.get("step_id")),
        action_type=_string(action.get("action_type")),
        execution_status="closed",
        retrieval_executed=False,
        execution_allowed=False,
        skipped_reasons=skipped_reasons,
        artifact=artifact,
        provenance=provenance,
    )


def _provenance(
    *,
    action: dict[str, Any],
    request: dict[str, Any],
    source_binding_id: str | None,
    adapter_id: str | None,
    governance_state: str | None,
    execution_allowed: bool,
    retrieval_executed: bool,
    resolved_capability: ResolvedLookupCapability | None,
    validation_errors: tuple[str, ...] = (),
) -> dict[str, Any]:
    workflow_id = action.get("workflow_id")
    step_id = action.get("step_id")
    action_type = action.get("action_type")
    lookup_id = request.get("lookup_id")
    lookup_type = request.get("lookup_type")
    source_scope = request.get("source_scope")
    capability = action.get("capability")
    return {
        "workflow_id": workflow_id,
        "operation_id": action.get("semantic_operation"),
        "action_type": action_type,
        "source_binding_id": source_binding_id,
        "resource_id": (
            resolved_capability.registration.adapter_owners[0]
            if resolved_capability
            and resolved_capability.registration.adapter_owners
            else None
        ),
        "adapter_id": adapter_id,
        "lookup_id": lookup_id,
        "lookup_type": lookup_type,
        "source_scope": source_scope,
        "retrieval_executed": retrieval_executed,
        "execution_allowed": execution_allowed,
        "governance_state": governance_state,
        "validation_errors": list(validation_errors),
        "governance_visibility": build_retrieval_governance_visibility(
            workflow_id=workflow_id,
            step_id=step_id,
            action_type=action_type,
            capability=capability,
            governance_state=governance_state,
            execution_allowed=execution_allowed,
            retrieval_executed=retrieval_executed,
            lookup_id=lookup_id,
            lookup_type=lookup_type,
            source_scope=source_scope,
            source_binding_id=source_binding_id,
            adapter_id=adapter_id,
            lookup_lineage_id=request.get("lookup_lineage_id"),
            lookup_request_id=request.get("lookup_request_id"),
            lookup_execution_id=request.get("lookup_execution_id"),
        ),
    }


def _adapter_id_for_source(
    *,
    source_binding_id: Any,
    root: str | Path,
) -> str | None:
    if not isinstance(source_binding_id, str) or not source_binding_id:
        return None
    adapter = get_context_adapter_for_source(source_binding_id, root=root)
    return adapter.adapter_id if adapter is not None else None


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


__all__ = [
    "WorkflowActionExecutionReceipt",
    "execute_retrieval_action",
]
