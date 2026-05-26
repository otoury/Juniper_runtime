from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.workflows.declarations import WorkflowStepDeclaration


EXTERNAL_GUEST_DISCOVERY_ACTION = "external_guest_discovery"
GUEST_CANDIDATE_LIST_ARTIFACT = "guest_candidate_list"
WEB_SOURCE_SCOPE = "web"
GOVERNANCE_ENABLED = "enabled"
GOVERNANCE_AUDIT_ONLY = "audit_only"
GOVERNANCE_DISABLED = "disabled"
DEFAULT_FUTURE_SIGNALS = (
    "has_email_contact",
    "email_refs",
    "has_video_presence",
    "video_presence_refs",
    "contact_confidence",
    "on_air_suitability_signals",
)


@dataclass(frozen=True)
class ExternalDiscoveryMaterialization:
    action: dict[str, Any] | None
    expected_output_artifact: dict[str, Any] | None
    materialized: bool
    transition_outcome: str | None
    skipped_reasons: tuple[str, ...]
    audit_summary: dict[str, Any]

    def to_audit_record(self) -> dict[str, Any]:
        return {
            "action_type": None if self.action is None else self.action.get("action_type"),
            "materialized": self.materialized,
            "transition_outcome": self.transition_outcome,
            "skipped_reasons": list(self.skipped_reasons),
            "audit_summary": dict(self.audit_summary),
        }


def materialize_external_guest_discovery(
    *,
    workflow_id: str,
    step: WorkflowStepDeclaration,
    governance_state: str | None = None,
    artifact_refs: list[str] | tuple[str, ...] = (),
    action_refs: list[str] | tuple[str, ...] = (),
) -> ExternalDiscoveryMaterialization:
    state = _governance_state(governance_state, step.governance_state)
    if state not in {GOVERNANCE_ENABLED, GOVERNANCE_AUDIT_ONLY}:
        return _closed(
            workflow_id=workflow_id,
            step=step,
            governance_state=state,
            skipped_reasons=("web_discovery_governance_closed",),
        )

    source_scope = _source_scope(step)
    if source_scope != WEB_SOURCE_SCOPE:
        return _closed(
            workflow_id=workflow_id,
            step=step,
            governance_state=state,
            skipped_reasons=("source_scope_not_web",),
        )

    if not _is_external_guest_discovery(step):
        return _closed(
            workflow_id=workflow_id,
            step=step,
            governance_state=state,
            skipped_reasons=("operation_not_external_guest_discovery",),
        )

    execution_allowed = False
    expected_output = _expected_output_artifact(step)
    safe_artifact_refs = _string_list(artifact_refs) or list(step.input_refs)
    safe_action_refs = _string_list(action_refs)
    action = {
        "action_type": EXTERNAL_GUEST_DISCOVERY_ACTION,
        "workflow_id": _safe_string(workflow_id),
        "operation_id": step.semantic_operation,
        "step_id": step.step_id,
        "capability": step.capability,
        "source_scope": source_scope,
        "governance_state": state,
        "execution_allowed": execution_allowed,
        "discovery_prepared": True,
        "discovery_executed": False,
        "max_results": _max_results(step),
        "query_refs": _query_refs(step),
        "context_refs": list(step.input_refs),
        "artifact_refs": safe_artifact_refs,
        "action_refs": safe_action_refs,
        "expected_output_artifact": dict(expected_output),
        "future_enrichment_signals": _future_signals(step),
        "metadata": {
            "future_enrichment_signals": _future_signals(step),
            "signal_placeholders_only": True,
            "ranking_performed": False,
            "selection_performed": False,
        },
        "provenance": {
            "workflow_id": _safe_string(workflow_id),
            "operation_id": step.semantic_operation,
            "governance_state": state,
            "declaration_only": bool(step.constraints.get("declaration_only", False)),
            "web_search_executed": False,
            "browser_api_called": False,
            "search_api_called": False,
            "cloud_model_called": False,
            "external_adapter_called": False,
            "ranking_performed": False,
            "selection_performed": False,
            "draft_generated": False,
            "delivery_performed": False,
            "runtime_query_invented": False,
        },
    }
    return ExternalDiscoveryMaterialization(
        action=action,
        expected_output_artifact=expected_output,
        materialized=True,
        transition_outcome="success",
        skipped_reasons=(),
        audit_summary=_audit_summary(
            workflow_id=workflow_id,
            step=step,
            governance_state=state,
            materialized=True,
            skipped_reasons=(),
        ),
    )


def _is_external_guest_discovery(step: WorkflowStepDeclaration) -> bool:
    lookup_type = step.constraints.get("lookup_type")
    return (
        lookup_type in {"external_guest_discovery", "web_guest_discovery"}
        or step.semantic_operation == "web_guest_discovery_placeholder"
    )


def _source_scope(step: WorkflowStepDeclaration) -> str | None:
    raw = step.constraints.get("source_scope")
    if raw == "web_deep":
        return WEB_SOURCE_SCOPE
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _expected_output_artifact(step: WorkflowStepDeclaration) -> dict[str, Any]:
    declared = step.constraints.get("expected_output_artifact")
    if isinstance(declared, dict):
        artifact = dict(declared)
    else:
        artifact = {}
    artifact["artifact_type"] = GUEST_CANDIDATE_LIST_ARTIFACT
    artifact["source_scope"] = WEB_SOURCE_SCOPE
    artifact["candidates"] = []
    artifact["discovery_executed"] = False
    artifact["future_enrichment_signals"] = _future_signals(step)
    artifact["provenance"] = {
        "discovery_executed": False,
        "web_search_executed": False,
        "browser_api_called": False,
        "search_api_called": False,
        "cloud_model_called": False,
        "ranking_performed": False,
        "selection_performed": False,
    }
    return artifact


def _governance_state(
    explicit: str | None,
    declared: str,
) -> str:
    value = explicit if explicit is not None else declared
    if isinstance(value, str) and value.strip():
        return value.strip()
    return GOVERNANCE_DISABLED


def _max_results(step: WorkflowStepDeclaration) -> int | None:
    value = step.constraints.get("max_results")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _query_refs(step: WorkflowStepDeclaration) -> list[str]:
    return _string_list(step.constraints.get("query_refs"))


def _future_signals(step: WorkflowStepDeclaration) -> list[str]:
    values = _string_list(step.constraints.get("future_enrichment_signals"))
    return values or list(DEFAULT_FUTURE_SIGNALS)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    ]


def _safe_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _closed(
    *,
    workflow_id: str,
    step: WorkflowStepDeclaration,
    governance_state: str,
    skipped_reasons: tuple[str, ...],
) -> ExternalDiscoveryMaterialization:
    return ExternalDiscoveryMaterialization(
        action=None,
        expected_output_artifact=None,
        materialized=False,
        transition_outcome="failure",
        skipped_reasons=skipped_reasons,
        audit_summary=_audit_summary(
            workflow_id=workflow_id,
            step=step,
            governance_state=governance_state,
            materialized=False,
            skipped_reasons=skipped_reasons,
        ),
    )


def _audit_summary(
    *,
    workflow_id: str,
    step: WorkflowStepDeclaration,
    governance_state: str,
    materialized: bool,
    skipped_reasons: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "workflow_id": _safe_string(workflow_id),
        "operation_id": step.semantic_operation,
        "action_type": EXTERNAL_GUEST_DISCOVERY_ACTION,
        "source_scope": _source_scope(step),
        "governance_state": governance_state,
        "materialized": materialized,
        "execution_allowed": False,
        "discovery_executed": False,
        "web_search_executed": False,
        "cloud_model_called": False,
        "delivery_performed": False,
        "skipped_reasons": list(skipped_reasons),
    }


__all__ = [
    "EXTERNAL_GUEST_DISCOVERY_ACTION",
    "ExternalDiscoveryMaterialization",
    "GUEST_CANDIDATE_LIST_ARTIFACT",
    "materialize_external_guest_discovery",
]
