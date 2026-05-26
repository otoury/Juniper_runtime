from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Mapping

from runtime.adapters.external_search import (
    ExternalSearchAdapterRequest,
    build_external_search_adapter_request,
)
from runtime.workflows.adequacy import GUEST_DB_ADEQUACY_ARTIFACT


GUEST_EXTERNAL_DISCOVERY_HANDOFF_ARTIFACT = "guest_external_discovery_handoff"
HANDOFF_STATUS_ELIGIBLE = "eligible"
HANDOFF_STATUS_INELIGIBLE = "ineligible"
REASON_HANDOFF_ELIGIBLE = "guest_db_inadequate_governance_allows_external_discovery_handoff"
REASON_GUEST_DB_ADEQUACY_MISSING = "guest_db_adequacy_missing"
REASON_GUEST_DB_ADEQUACY_SUFFICIENT = "guest_db_adequacy_sufficient"
REASON_GUEST_DB_INADEQUACY_REQUIRED = "guest_db_inadequacy_required"
REASON_GOVERNANCE_MISSING = "external_discovery_governance_missing"
REASON_GOVERNANCE_BLOCKED = "external_discovery_governance_blocked"
REASON_QUERY_MATERIALIZATION_EMPTY = "query_materialization_empty"
DISCOVERY_REASON_MISSING_CONTACT_INFO = "missing_contact_info"
DISCOVERY_REASON_NO_LOCAL_CANDIDATE = "no_local_candidate"
DISCOVERY_REASON_CANDIDATE_STALE = "candidate_stale"
DISCOVERY_REASON_AMBIGUOUS_IDENTITY = "ambiguous_identity"
DISCOVERY_REASON_BOOKING_RESTRICTION_UNCLEAR = "booking_restriction_unclear"
DISCOVERY_REASON_EXPLICIT_USER_REQUESTED_WEB = "explicit_user_requested_web"
DEFAULT_MAX_QUERY_CHARS = 160
DEFAULT_MAX_RESULTS = 5


_INADEQUACY_DISCOVERY_REASON_MAP = {
    "missing_email_contact": DISCOVERY_REASON_MISSING_CONTACT_INFO,
    "missing_phone_contact": DISCOVERY_REASON_MISSING_CONTACT_INFO,
    "no_local_candidates": DISCOVERY_REASON_NO_LOCAL_CANDIDATE,
    "freshness_stale": DISCOVERY_REASON_CANDIDATE_STALE,
    "freshness_unknown": DISCOVERY_REASON_CANDIDATE_STALE,
    "ambiguous_local_candidates": DISCOVERY_REASON_AMBIGUOUS_IDENTITY,
    "booking_restricted": DISCOVERY_REASON_BOOKING_RESTRICTION_UNCLEAR,
    "booking_suitability_unknown": DISCOVERY_REASON_BOOKING_RESTRICTION_UNCLEAR,
    "user_requested_web": DISCOVERY_REASON_EXPLICIT_USER_REQUESTED_WEB,
}


def build_guest_external_discovery_handoff(
    *,
    adequacy_artifact: Mapping[str, Any] | None,
    lookup_intent: Mapping[str, Any] | None = None,
    external_discovery_governance: Mapping[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    discovery_reasons = map_guest_db_inadequacy_to_external_discovery_reasons(
        adequacy_artifact
    )
    materialization = materialize_external_search_query_from_guest_context(
        lookup_intent=lookup_intent,
    )
    reasons = _handoff_reason_codes(
        adequacy_artifact=adequacy_artifact,
        external_discovery_governance=external_discovery_governance,
        discovery_reasons=discovery_reasons,
        materialization=materialization,
    )
    eligible = reasons == [REASON_HANDOFF_ELIGIBLE]
    search_id = _search_id(adequacy_artifact, materialization["query"])
    prepared_request = (
        {
            "semantic_type": "external_search",
            "search_id": search_id,
            "query": materialization["query"],
            "search_intent": "guest_external_discovery_handoff",
            "max_results": DEFAULT_MAX_RESULTS,
            "freshness_policy": {
                "basis": "guest_db_inadequacy",
                "source_scope": _source_scope(adequacy_artifact),
            },
            "source_policy": {
                "source_refs_required": True,
                "citations_required": True,
                "contact_scraping_allowed": False,
                "contact_discovery_safety_required": True,
                "contact_discovery_safety_policy_id": (
                    "contact_discovery_safety_policy"
                ),
                "public_professional_sources_only": True,
                "email_pattern_inference_allowed": False,
                "private_phone_harvesting_allowed": False,
                "personal_address_discovery_allowed": False,
                "raw_provider_payload_as_contact_record_allowed": False,
                "automatic_db_update_allowed": False,
                "domain_normalization_allowed": False,
            },
            "result_bounds": {
                "max_queries": 1,
                "max_results": DEFAULT_MAX_RESULTS,
                "timeout_ms": 0,
                "max_cost": {"currency": "USD", "amount": 0},
            },
        }
        if eligible
        else None
    )
    return {
        "artifact_type": GUEST_EXTERNAL_DISCOVERY_HANDOFF_ARTIFACT,
        "status": HANDOFF_STATUS_ELIGIBLE if eligible else HANDOFF_STATUS_INELIGIBLE,
        "handoff_eligible": eligible,
        "reason_codes": reasons,
        "discovery_reason_codes": list(discovery_reasons),
        "source_artifact_type": (
            adequacy_artifact.get("artifact_type")
            if isinstance(adequacy_artifact, Mapping)
            else None
        ),
        "source_scope": _source_scope(adequacy_artifact),
        "guest_db_adequacy_outcome": (
            adequacy_artifact.get("outcome")
            if isinstance(adequacy_artifact, Mapping)
            else None
        ),
        "target_semantic_type": "external_search",
        "handoff_is_execution": False,
        "external_call_performed": False,
        "provider_execution_allowed": False,
        "provider_fields_present": False,
        "contact_scraping_allowed": False,
        "prepared_request": prepared_request,
        "query_materialization": materialization,
        "generated_at": _timestamp(generated_at),
        "provenance": {
            "kind": "guest_external_discovery_handoff",
            "owner": "agents.alexis",
            "source_artifact_type": (
                adequacy_artifact.get("artifact_type")
                if isinstance(adequacy_artifact, Mapping)
                else None
            ),
            "source_scope": _source_scope(adequacy_artifact),
            "target_semantic_type": "external_search",
            "handoff_only": True,
            "external_call_performed": False,
            "provider_adapter_called": False,
            "contact_scraping_performed": False,
            "memory_write_performed": False,
            "hidden_context_injected": False,
        },
    }


def map_guest_db_inadequacy_to_external_discovery_reasons(
    adequacy_artifact: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    if not isinstance(adequacy_artifact, Mapping):
        return ()
    reasons: list[str] = []
    raw_codes = adequacy_artifact.get("inadequacy_reason_codes")
    if not isinstance(raw_codes, list | tuple):
        return ()
    for raw_code in raw_codes:
        code = _safe_text(raw_code, limit=80)
        mapped = _INADEQUACY_DISCOVERY_REASON_MAP.get(code)
        if mapped and mapped not in reasons:
            reasons.append(mapped)
    return tuple(reasons)


def materialize_external_search_query_from_guest_context(
    *,
    lookup_intent: Mapping[str, Any] | None,
    max_query_chars: int = DEFAULT_MAX_QUERY_CHARS,
) -> dict[str, Any]:
    query_parts = _lookup_query_parts(lookup_intent)
    query = " ".join(query_parts)[:max_query_chars].strip()
    return {
        "query": query,
        "source": "explicit_lookup_intent" if query else "empty",
        "rules": {
            "max_queries": 1,
            "max_query_chars": max_query_chars,
            "allowed_sources": [
                "lookup_intent.entity_name",
                "lookup_intent.query_text",
                "lookup_intent.topic",
                "lookup_intent.topic_text",
            ],
            "candidate_fields_allowed": False,
            "contact_fields_allowed": False,
            "provider_fields_allowed": False,
            "execution_fields_allowed": False,
        },
        "selected_terms": query_parts,
        "query_char_count": len(query),
        "bounded": True,
        "auditable": True,
    }


def prepare_external_search_request_from_guest_handoff(
    handoff: Mapping[str, Any],
) -> ExternalSearchAdapterRequest | None:
    if not isinstance(handoff, Mapping):
        return None
    if handoff.get("artifact_type") != GUEST_EXTERNAL_DISCOVERY_HANDOFF_ARTIFACT:
        return None
    if handoff.get("handoff_eligible") is not True:
        return None
    prepared_request = handoff.get("prepared_request")
    if not isinstance(prepared_request, dict):
        return None
    return build_external_search_adapter_request(prepared_request)


def validate_guest_external_discovery_handoff(artifact: Mapping[str, Any]) -> bool:
    if not isinstance(artifact, Mapping):
        return False
    if artifact.get("artifact_type") != GUEST_EXTERNAL_DISCOVERY_HANDOFF_ARTIFACT:
        return False
    if artifact.get("status") not in {HANDOFF_STATUS_ELIGIBLE, HANDOFF_STATUS_INELIGIBLE}:
        return False
    eligible = artifact.get("handoff_eligible")
    if eligible not in {True, False}:
        return False
    if artifact.get("handoff_is_execution") is not False:
        return False
    for key in (
        "external_call_performed",
        "provider_execution_allowed",
        "provider_fields_present",
        "contact_scraping_allowed",
    ):
        if artifact.get(key) is not False:
            return False
    if artifact.get("target_semantic_type") != "external_search":
        return False
    if not _valid_reason_codes(artifact.get("reason_codes"), eligible=eligible):
        return False
    if not _valid_discovery_reasons(artifact.get("discovery_reason_codes")):
        return False
    if not _valid_query_materialization(artifact.get("query_materialization")):
        return False
    prepared_request = artifact.get("prepared_request")
    if eligible:
        if not _valid_prepared_request(prepared_request):
            return False
    elif prepared_request is not None:
        return False
    provenance = artifact.get("provenance")
    if not isinstance(provenance, Mapping):
        return False
    for key in (
        "external_call_performed",
        "provider_adapter_called",
        "contact_scraping_performed",
        "memory_write_performed",
        "hidden_context_injected",
    ):
        if provenance.get(key) is not False:
            return False
    return True


def _handoff_reason_codes(
    *,
    adequacy_artifact: Mapping[str, Any] | None,
    external_discovery_governance: Mapping[str, Any] | None,
    discovery_reasons: tuple[str, ...],
    materialization: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if not isinstance(adequacy_artifact, Mapping):
        return [REASON_GUEST_DB_ADEQUACY_MISSING]
    if adequacy_artifact.get("artifact_type") != GUEST_DB_ADEQUACY_ARTIFACT:
        reasons.append(REASON_GUEST_DB_ADEQUACY_MISSING)
    elif adequacy_artifact.get("adequate") is True or adequacy_artifact.get("outcome") == "adequate":
        reasons.append(REASON_GUEST_DB_ADEQUACY_SUFFICIENT)
    elif not discovery_reasons:
        reasons.append(REASON_GUEST_DB_INADEQUACY_REQUIRED)

    if not isinstance(external_discovery_governance, Mapping):
        reasons.append(REASON_GOVERNANCE_MISSING)
    elif external_discovery_governance.get("external_discovery_allowed") is not True:
        reasons.append(REASON_GOVERNANCE_BLOCKED)

    if not _safe_text(materialization.get("query"), limit=DEFAULT_MAX_QUERY_CHARS):
        reasons.append(REASON_QUERY_MATERIALIZATION_EMPTY)

    return reasons or [REASON_HANDOFF_ELIGIBLE]


def _lookup_query_parts(lookup_intent: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(lookup_intent, Mapping):
        return []
    parts: list[str] = []
    for key in ("entity_name", "query_text", "topic", "topic_text"):
        text = _safe_text(lookup_intent.get(key), limit=80)
        if text and text not in parts:
            parts.append(text)
    return parts


def _valid_reason_codes(value: Any, *, eligible: bool) -> bool:
    if not isinstance(value, list):
        return False
    if not value or any(not isinstance(item, str) or not item for item in value):
        return False
    if eligible:
        return value == [REASON_HANDOFF_ELIGIBLE]
    return REASON_HANDOFF_ELIGIBLE not in value


def _valid_discovery_reasons(value: Any) -> bool:
    allowed = set(_INADEQUACY_DISCOVERY_REASON_MAP.values())
    return (
        isinstance(value, list)
        and all(isinstance(item, str) and item in allowed for item in value)
        and len(value) == len(set(value))
    )


def _valid_query_materialization(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    rules = value.get("rules")
    if not isinstance(rules, Mapping):
        return False
    if value.get("bounded") is not True or value.get("auditable") is not True:
        return False
    if rules.get("max_queries") != 1:
        return False
    if rules.get("max_query_chars") != DEFAULT_MAX_QUERY_CHARS:
        return False
    for key in (
        "candidate_fields_allowed",
        "contact_fields_allowed",
        "provider_fields_allowed",
        "execution_fields_allowed",
    ):
        if rules.get(key) is not False:
            return False
    return True


def _valid_prepared_request(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    forbidden = {
        "adapter_id",
        "allow_live_call",
        "api_key",
        "credential_env_var",
        "execute",
        "execution_allowed",
        "external_call_performed",
        "provider_id",
        "provider_name",
        "provider_type",
    }
    if forbidden & set(value):
        return False
    if value.get("semantic_type") != "external_search":
        return False
    if not _safe_text(value.get("query"), limit=DEFAULT_MAX_QUERY_CHARS):
        return False
    if value.get("max_results") != DEFAULT_MAX_RESULTS:
        return False
    bounds = value.get("result_bounds")
    if not isinstance(bounds, Mapping):
        return False
    if bounds.get("max_queries") != 1 or bounds.get("timeout_ms") != 0:
        return False
    source_policy = value.get("source_policy")
    if not isinstance(source_policy, Mapping):
        return False
    for key in (
        "contact_scraping_allowed",
        "email_pattern_inference_allowed",
        "private_phone_harvesting_allowed",
        "personal_address_discovery_allowed",
        "raw_provider_payload_as_contact_record_allowed",
        "automatic_db_update_allowed",
        "domain_normalization_allowed",
    ):
        if source_policy.get(key) is not False:
            return False
    if source_policy.get("contact_discovery_safety_required") is not True:
        return False
    if source_policy.get("public_professional_sources_only") is not True:
        return False
    if source_policy.get("contact_discovery_safety_policy_id") != (
        "contact_discovery_safety_policy"
    ):
        return False
    return True


def _search_id(
    adequacy_artifact: Mapping[str, Any] | None,
    query: str,
) -> str:
    generated_at = (
        adequacy_artifact.get("generated_at")
        if isinstance(adequacy_artifact, Mapping)
        else ""
    )
    identity = f"{generated_at}|{query}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"guest-external-discovery-handoff-{digest}"


def _source_scope(adequacy_artifact: Mapping[str, Any] | None) -> str | None:
    if not isinstance(adequacy_artifact, Mapping):
        return None
    return _safe_text(adequacy_artifact.get("source_scope"), limit=120) or None


def _timestamp(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def _safe_text(value: Any, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


__all__ = [
    "DISCOVERY_REASON_AMBIGUOUS_IDENTITY",
    "DISCOVERY_REASON_BOOKING_RESTRICTION_UNCLEAR",
    "DISCOVERY_REASON_CANDIDATE_STALE",
    "DISCOVERY_REASON_EXPLICIT_USER_REQUESTED_WEB",
    "DISCOVERY_REASON_MISSING_CONTACT_INFO",
    "DISCOVERY_REASON_NO_LOCAL_CANDIDATE",
    "GUEST_EXTERNAL_DISCOVERY_HANDOFF_ARTIFACT",
    "HANDOFF_STATUS_ELIGIBLE",
    "HANDOFF_STATUS_INELIGIBLE",
    "REASON_GOVERNANCE_BLOCKED",
    "REASON_HANDOFF_ELIGIBLE",
    "REASON_GUEST_DB_ADEQUACY_SUFFICIENT",
    "build_guest_external_discovery_handoff",
    "map_guest_db_inadequacy_to_external_discovery_reasons",
    "materialize_external_search_query_from_guest_context",
    "prepare_external_search_request_from_guest_handoff",
    "validate_guest_external_discovery_handoff",
]
