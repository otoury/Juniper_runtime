from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from agents.alexis.workflows.guest_contact_retrieval_diagnostics import (
    build_guest_contact_retrieval_diagnostics,
    validate_guest_contact_retrieval_diagnostics,
)
from agents.alexis.workflows.guest_external_discovery_handoff import (
    build_guest_external_discovery_handoff,
    validate_guest_external_discovery_handoff,
)
from runtime.workflows.adequacy import (
    materialize_guest_db_adequacy,
    validate_guest_db_adequacy,
)


DEFAULT_EXTERNAL_DISCOVERY_GOVERNANCE = {
    "external_discovery_allowed": True,
    "governance_state": "audit_only",
}


def build_alexis_guest_workflow_telemetry(
    *,
    candidate_artifact: Mapping[str, Any] | None,
    lookup_intent: Mapping[str, Any] | None,
    merge_artifact: Mapping[str, Any] | None = None,
    provider_id: str | None = None,
    root: str | None = None,
    generated_at: datetime | None = None,
    require_current_freshness: bool = False,
) -> dict[str, Any]:
    safe_candidate_artifact = (
        dict(candidate_artifact) if isinstance(candidate_artifact, Mapping) else None
    )
    safe_lookup_intent = (
        dict(lookup_intent) if isinstance(lookup_intent, Mapping) else None
    )
    adequacy = materialize_guest_db_adequacy(
        candidate_artifact=safe_candidate_artifact,
        lookup_intent=safe_lookup_intent,
        require_current_freshness=require_current_freshness,
        generated_at=generated_at,
    ).artifact
    handoff = build_guest_external_discovery_handoff(
        adequacy_artifact=adequacy,
        lookup_intent=safe_lookup_intent,
        external_discovery_governance=DEFAULT_EXTERNAL_DISCOVERY_GOVERNANCE,
        generated_at=generated_at,
    )
    diagnostics = build_guest_contact_retrieval_diagnostics(
        guest_db_adequacy_artifact=adequacy,
        handoff_artifact=handoff,
        merge_artifact=merge_artifact,
        provider_id=provider_id,
        root=root,
    )
    return {
        "telemetry_type": "alexis_guest_workflow_observability",
        "observational_only": True,
        "live_external_discovery_executed": False,
        "external_call_performed": False,
        "provider_adapter_called": False,
        "db_write_performed": False,
        "memory_write_performed": False,
        "automatic_workflow_escalation_performed": False,
        "guest_db_adequacy": adequacy,
        "guest_external_discovery_handoff": handoff,
        "contact_retrieval_diagnostics": diagnostics,
        "validity": {
            "guest_db_adequacy": validate_guest_db_adequacy(adequacy),
            "guest_external_discovery_handoff": (
                validate_guest_external_discovery_handoff(handoff)
            ),
            "contact_retrieval_diagnostics": (
                validate_guest_contact_retrieval_diagnostics(diagnostics)
            ),
        },
    }


def summarize_alexis_guest_workflow_telemetry(
    telemetry: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(telemetry, Mapping):
        return {}
    adequacy = _mapping(telemetry.get("guest_db_adequacy"))
    handoff = _mapping(telemetry.get("guest_external_discovery_handoff"))
    diagnostics = _mapping(telemetry.get("contact_retrieval_diagnostics"))
    contact_safety = _mapping(diagnostics.get("contact_safety_governance"))
    candidate_merge = _mapping(diagnostics.get("candidate_merge"))
    return {
        "telemetry_type": _text(telemetry.get("telemetry_type")),
        "observational_only": telemetry.get("observational_only") is True,
        "live_external_discovery_executed": (
            telemetry.get("live_external_discovery_executed") is True
        ),
        "external_call_performed": telemetry.get("external_call_performed") is True,
        "provider_adapter_called": telemetry.get("provider_adapter_called") is True,
        "db_write_performed": telemetry.get("db_write_performed") is True,
        "memory_write_performed": telemetry.get("memory_write_performed") is True,
        "automatic_workflow_escalation_performed": (
            telemetry.get("automatic_workflow_escalation_performed") is True
        ),
        "guest_db_adequacy": {
            "artifact_type": _text(adequacy.get("artifact_type")),
            "outcome": _text(adequacy.get("outcome")),
            "adequate": _optional_bool(adequacy.get("adequate")),
            "candidate_count": _int(adequacy.get("candidate_count")),
            "inadequacy_reason_codes": _text_list(
                adequacy.get("inadequacy_reason_codes")
            ),
            "reason_codes": _text_list(adequacy.get("reason_codes")),
        },
        "guest_external_discovery_handoff": {
            "artifact_type": _text(handoff.get("artifact_type")),
            "status": _text(handoff.get("status")),
            "handoff_eligible": _optional_bool(handoff.get("handoff_eligible")),
            "prepared_request_present": isinstance(
                handoff.get("prepared_request"),
                Mapping,
            ),
            "external_call_performed": (
                handoff.get("external_call_performed") is True
            ),
            "provider_execution_allowed": (
                handoff.get("provider_execution_allowed") is True
            ),
            "contact_scraping_allowed": (
                handoff.get("contact_scraping_allowed") is True
            ),
            "reason_codes": _text_list(handoff.get("reason_codes")),
            "discovery_reason_codes": _text_list(
                handoff.get("discovery_reason_codes")
            ),
        },
        "contact_safety_governance": {
            "governance_state": _text(contact_safety.get("governance_state")),
            "live_contact_search_enabled": (
                contact_safety.get("live_contact_search_enabled") is True
            ),
            "public_professional_sources_only": (
                contact_safety.get("public_professional_sources_only") is True
            ),
            "contact_value_generation_allowed": (
                contact_safety.get("contact_value_generation_allowed") is True
            ),
            "automatic_db_update_allowed": (
                contact_safety.get("automatic_db_update_allowed") is True
            ),
            "memory_writes_allowed": (
                contact_safety.get("memory_writes_allowed") is True
            ),
        },
        "merge_receipt": {
            "merge_receipt_count": _int(candidate_merge.get("merge_receipt_count")),
            "receipt_refs": _text_list(diagnostics.get("receipt_refs")),
            "automatic_contact_promotion_performed": _optional_bool(
                candidate_merge.get("automatic_contact_promotion_performed")
            ),
            "external_overwrite_performed": _optional_bool(
                candidate_merge.get("external_overwrite_performed")
            ),
        },
        "validity": dict(telemetry.get("validity", {}))
        if isinstance(telemetry.get("validity"), Mapping)
        else {},
    }


def candidate_artifact_from_lookup_planning(planning: Any) -> dict[str, Any]:
    lookup_results = getattr(planning, "lookup_results", [])
    candidates: list[dict[str, Any]] = []
    retrieval_executed = False
    source_scope = "db"
    for result in lookup_results if isinstance(lookup_results, list) else []:
        if not isinstance(result, Mapping):
            continue
        retrieval_executed = retrieval_executed or result.get("retrieval_executed") is True
        if isinstance(result.get("source_scope"), str) and result["source_scope"].strip():
            source_scope = result["source_scope"].strip()
        payloads = result.get("payloads")
        if not isinstance(payloads, list):
            continue
        for payload in payloads:
            if isinstance(payload, Mapping):
                candidates.append(dict(payload))
    return {
        "artifact_type": "guest_candidate_list",
        "source_scope": source_scope,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "provenance": {
            "source_scope": source_scope,
            "retrieval_executed": retrieval_executed,
            "external_call_performed": False,
        },
    }


def lookup_intent_from_planning(planning: Any) -> dict[str, Any]:
    lookup_requests = getattr(planning, "lookup_requests", [])
    for request in lookup_requests if isinstance(lookup_requests, list) else []:
        if not isinstance(request, Mapping):
            continue
        return {
            "entity_name": _text(request.get("entity_name")),
            "query_text": _text(request.get("workflow_topic")),
            "topic": _text(request.get("workflow_topic")),
        }
    return {}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return " ".join(value.split())[:240]
    return None


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    result: list[str] = []
    for item in value:
        text = _text(item)
        if text and text not in result:
            result.append(text)
    return result


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


__all__ = [
    "build_alexis_guest_workflow_telemetry",
    "candidate_artifact_from_lookup_planning",
    "lookup_intent_from_planning",
    "summarize_alexis_guest_workflow_telemetry",
]
