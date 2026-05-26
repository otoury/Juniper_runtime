from __future__ import annotations

from typing import Any, Mapping

from runtime.governance.visibility_schema import (
    GOVERNANCE_VISIBILITY_SCHEMA_VERSION,
    build_governance_visibility_surface,
)
from runtime.workflows.trust_lineage import trust_lineage_scope_key


VISIBILITY_SCHEMA_VERSION = GOVERNANCE_VISIBILITY_SCHEMA_VERSION


def build_workflow_governance_visibility(
    *,
    workflow_id: Any = None,
    workflow_type: Any = None,
    owning_agent: Any = None,
    step_id: Any = None,
    action_type: Any = None,
    capability: Any = None,
    governance_state: Any = None,
    execution_allowed: Any = None,
    execution_performed: Any = None,
    requires_approval: Any = None,
    trust_state: Any = None,
    trust_lineage: Mapping[str, Any] | None = None,
    trust_progression: Mapping[str, Any] | None = None,
    skipped_reasons: Any = None,
) -> dict[str, Any]:
    progression = trust_progression if isinstance(trust_progression, Mapping) else {}
    lineage = trust_lineage if isinstance(trust_lineage, Mapping) else None
    return build_governance_visibility_surface(
        operation_domain="workflow",
        fields=_without_none(
            {
                "execution_performed": _optional_bool(execution_performed),
                "execution_allowed": _optional_bool(execution_allowed),
                "requires_approval": _optional_bool(requires_approval),
                "workflow_id": _optional_string(workflow_id),
                "workflow_type": _optional_string(workflow_type),
                "owning_agent": _optional_string(owning_agent),
                "step_id": _optional_string(step_id),
                "action_type": _optional_string(action_type),
                "capability": _optional_string(capability),
                "governance_state": _optional_string(governance_state),
                "trust_state": _optional_string(trust_state),
                "trust_lineage_type": (
                    _optional_string(lineage.get("lineage_type")) if lineage else None
                ),
                "trust_scope_key": trust_lineage_scope_key(lineage),
                "trust_inheritance_boundary": (
                    _optional_string(lineage.get("trust_inheritance_boundary"))
                    if lineage
                    else None
                ),
                "trust_scope_bleed_prevented": _optional_bool(
                    progression.get("trust_scope_bleed_prevented")
                ),
                "prior_trust_scope_match": _optional_bool(
                    progression.get("prior_trust_scope_match")
                ),
                "skipped_reasons": _safe_string_list(skipped_reasons),
            }
        ),
    )


def build_retrieval_governance_visibility(
    *,
    workflow_id: Any = None,
    step_id: Any = None,
    action_type: Any = None,
    capability: Any = None,
    governance_state: Any = None,
    execution_allowed: Any = None,
    retrieval_executed: Any = None,
    lookup_id: Any = None,
    lookup_type: Any = None,
    source_scope: Any = None,
    source_binding_id: Any = None,
    adapter_id: Any = None,
    lookup_lineage_id: Any = None,
    lookup_request_id: Any = None,
    lookup_execution_id: Any = None,
    records_returned: Any = None,
    render_allowed: Any = None,
    injection_allowed: Any = None,
    skipped_reasons: Any = None,
) -> dict[str, Any]:
    return build_governance_visibility_surface(
        operation_domain="retrieval",
        fields=_without_none(
            {
                "workflow_id": _optional_string(workflow_id),
                "step_id": _optional_string(step_id),
                "action_type": _optional_string(action_type),
                "capability": _optional_string(capability),
                "governance_state": _optional_string(governance_state),
                "execution_allowed": _optional_bool(execution_allowed),
                "retrieval_executed": _optional_bool(retrieval_executed),
                "lookup_id": _optional_string(lookup_id),
                "lookup_type": _optional_string(lookup_type),
                "source_scope": _optional_string(source_scope),
                "source_binding_id": _optional_string(source_binding_id),
                "adapter_id": _optional_string(adapter_id),
                "lookup_lineage_id": _optional_string(lookup_lineage_id),
                "lookup_request_id": _optional_string(lookup_request_id),
                "lookup_execution_id": _optional_string(lookup_execution_id),
                "records_returned": _optional_non_negative_int(records_returned),
                "render_allowed": _optional_bool(render_allowed),
                "injection_allowed": _optional_bool(injection_allowed),
                "skipped_reasons": _safe_string_list(skipped_reasons),
            }
        ),
    )


def _without_none(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if item is not None and item != []
    }


def _optional_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _optional_non_negative_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    found: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip() and item.strip() not in found:
            found.append(item.strip())
    return found


__all__ = [
    "VISIBILITY_SCHEMA_VERSION",
    "build_retrieval_governance_visibility",
    "build_workflow_governance_visibility",
]
