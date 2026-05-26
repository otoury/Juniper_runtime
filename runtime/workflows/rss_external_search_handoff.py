from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Mapping

from runtime.adapters.external_search import (
    ExternalSearchAdapterRequest,
    build_external_search_adapter_request,
)


RSS_EXTERNAL_SEARCH_HANDOFF_ARTIFACT = "rss_external_search_handoff"
HANDOFF_STATUS_ELIGIBLE = "eligible"
HANDOFF_STATUS_INELIGIBLE = "ineligible"
REASON_HANDOFF_ELIGIBLE = "rss_inadequate_governance_allows_external_search_handoff"
REASON_RSS_ADEQUACY_MISSING = "rss_adequacy_missing"
REASON_RSS_COVERAGE_ADEQUATE = "rss_coverage_adequate"
REASON_RSS_INADEQUACY_REQUIRED = "rss_inadequacy_required"
REASON_GOVERNANCE_MISSING = "external_live_retrieval_governance_missing"
REASON_GOVERNANCE_BLOCKED = "external_live_retrieval_governance_blocked"
REASON_QUERY_MATERIALIZATION_EMPTY = "query_materialization_empty"
DEFAULT_MAX_QUERY_CHARS = 160
DEFAULT_MAX_TERMS_PER_BUCKET = 4
DEFAULT_MAX_RESULTS = 5


def build_rss_external_search_handoff(
    *,
    adequacy_artifact: Mapping[str, Any] | None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    materialization = materialize_external_search_query_from_rss_adequacy(
        adequacy_artifact=adequacy_artifact,
    )
    reasons = _handoff_reason_codes(
        adequacy_artifact=adequacy_artifact,
        materialization=materialization,
    )
    eligible = reasons == [REASON_HANDOFF_ELIGIBLE]
    search_id = _search_id(adequacy_artifact, materialization["query"])
    prepared_request = (
        {
            "semantic_type": "external_search",
            "search_id": search_id,
            "query": materialization["query"],
            "search_intent": "rss_inadequacy_external_search_handoff",
            "max_results": DEFAULT_MAX_RESULTS,
            "freshness_policy": {
                "basis": "rss_coverage_inadequacy",
                "source_scope": _source_scope(adequacy_artifact),
            },
            "source_policy": {
                "source_refs_required": True,
                "citations_required": True,
                "rss_first_preserved": True,
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
        "artifact_type": RSS_EXTERNAL_SEARCH_HANDOFF_ARTIFACT,
        "status": HANDOFF_STATUS_ELIGIBLE if eligible else HANDOFF_STATUS_INELIGIBLE,
        "handoff_eligible": eligible,
        "reason_codes": reasons,
        "source_artifact_type": (
            adequacy_artifact.get("artifact_type")
            if isinstance(adequacy_artifact, Mapping)
            else None
        ),
        "source_scope": _source_scope(adequacy_artifact),
        "rss_adequacy_outcome": (
            adequacy_artifact.get("outcome")
            if isinstance(adequacy_artifact, Mapping)
            else None
        ),
        "target_semantic_type": "external_search",
        "handoff_is_execution": False,
        "external_call_performed": False,
        "provider_execution_allowed": False,
        "provider_fields_present": False,
        "prepared_request": prepared_request,
        "query_materialization": materialization,
        "generated_at": _timestamp(generated_at),
        "provenance": {
            "kind": "rss_external_search_handoff",
            "source_artifact_type": (
                adequacy_artifact.get("artifact_type")
                if isinstance(adequacy_artifact, Mapping)
                else None
            ),
            "source_scope": _source_scope(adequacy_artifact),
            "target_semantic_type": "external_search",
            "rss_first_preserved": True,
            "external_call_performed": False,
            "provider_adapter_called": False,
            "memory_write_performed": False,
        },
    }


def prepare_external_search_request_from_rss_handoff(
    handoff: Mapping[str, Any],
) -> ExternalSearchAdapterRequest | None:
    if not isinstance(handoff, Mapping):
        return None
    if handoff.get("artifact_type") != RSS_EXTERNAL_SEARCH_HANDOFF_ARTIFACT:
        return None
    if handoff.get("handoff_eligible") is not True:
        return None
    prepared_request = handoff.get("prepared_request")
    if not isinstance(prepared_request, dict):
        return None
    return build_external_search_adapter_request(prepared_request)


def validate_rss_external_search_handoff(artifact: Mapping[str, Any]) -> bool:
    if not isinstance(artifact, Mapping):
        return False
    if artifact.get("artifact_type") != RSS_EXTERNAL_SEARCH_HANDOFF_ARTIFACT:
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
    ):
        if artifact.get(key) is not False:
            return False
    if artifact.get("target_semantic_type") != "external_search":
        return False
    if not _valid_reason_codes(artifact.get("reason_codes"), eligible=eligible):
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
    if provenance.get("external_call_performed") is not False:
        return False
    if provenance.get("provider_adapter_called") is not False:
        return False
    if provenance.get("memory_write_performed") is not False:
        return False
    return True


def materialize_external_search_query_from_rss_adequacy(
    *,
    adequacy_artifact: Mapping[str, Any] | None,
    max_query_chars: int = DEFAULT_MAX_QUERY_CHARS,
    max_terms_per_bucket: int = DEFAULT_MAX_TERMS_PER_BUCKET,
) -> dict[str, Any]:
    focus = _topic_focus(adequacy_artifact)
    topics = _bounded_terms(focus.get("topics"), max_terms_per_bucket)
    entities = _bounded_terms(focus.get("entities"), max_terms_per_bucket)
    parts = [*entities["terms"], *topics["terms"]]
    source = "topic_entity_focus" if parts else "rss_latest_news_default"
    query = " ".join(parts) if parts else "latest news"
    query = query[:max_query_chars].strip()
    return {
        "query": query,
        "source": source,
        "rules": {
            "max_queries": 1,
            "max_query_chars": max_query_chars,
            "max_terms_per_bucket": max_terms_per_bucket,
            "allowed_sources": [
                "rss_coverage_adequacy.topic_entity_focus",
                "rss_coverage_adequacy.retrieval_metadata.topic_entity_focus",
            ],
            "fallback_query_when_no_focus": "latest news",
            "provider_fields_allowed": False,
            "execution_fields_allowed": False,
        },
        "selected_terms": {
            "topics": topics["terms"],
            "entities": entities["terms"],
        },
        "dropped_term_count": topics["dropped"] + entities["dropped"],
        "query_char_count": len(query),
        "bounded": True,
        "auditable": True,
    }


def _handoff_reason_codes(
    *,
    adequacy_artifact: Mapping[str, Any] | None,
    materialization: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if not isinstance(adequacy_artifact, Mapping):
        return [REASON_RSS_ADEQUACY_MISSING]
    if adequacy_artifact.get("adequate") is True or adequacy_artifact.get("outcome") == "adequate":
        reasons.append(REASON_RSS_COVERAGE_ADEQUATE)
    elif adequacy_artifact.get("adequate") is not False or adequacy_artifact.get("outcome") != "inadequate":
        reasons.append(REASON_RSS_INADEQUACY_REQUIRED)

    governance = adequacy_artifact.get("external_live_retrieval_governance")
    if not isinstance(governance, Mapping):
        reasons.append(REASON_GOVERNANCE_MISSING)
    elif governance.get("live_allowed") is not True:
        reasons.append(REASON_GOVERNANCE_BLOCKED)

    if not _safe_text(materialization.get("query"), limit=DEFAULT_MAX_QUERY_CHARS):
        reasons.append(REASON_QUERY_MATERIALIZATION_EMPTY)

    return reasons or [REASON_HANDOFF_ELIGIBLE]


def _topic_focus(adequacy_artifact: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(adequacy_artifact, Mapping):
        return {}
    focus = adequacy_artifact.get("topic_entity_focus")
    if isinstance(focus, Mapping):
        return dict(focus)
    retrieval_metadata = adequacy_artifact.get("retrieval_metadata")
    if isinstance(retrieval_metadata, Mapping) and isinstance(
        retrieval_metadata.get("topic_entity_focus"),
        Mapping,
    ):
        return dict(retrieval_metadata["topic_entity_focus"])
    return {}


def _bounded_terms(value: Any, max_terms: int) -> dict[str, Any]:
    raw_terms = value if isinstance(value, list | tuple) else ()
    terms: list[str] = []
    dropped = 0
    for raw in raw_terms:
        text = _safe_text(raw, limit=48).lower()
        if not text:
            dropped += 1
            continue
        if text not in terms and len(terms) < max_terms:
            terms.append(text)
        else:
            dropped += 1
    return {"terms": terms, "dropped": dropped}


def _valid_reason_codes(value: Any, *, eligible: bool) -> bool:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return False
    if eligible:
        return value == [REASON_HANDOFF_ELIGIBLE]
    return REASON_HANDOFF_ELIGIBLE not in value and bool(value)


def _valid_query_materialization(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    if value.get("bounded") is not True or value.get("auditable") is not True:
        return False
    query = _safe_text(value.get("query"), limit=DEFAULT_MAX_QUERY_CHARS + 1)
    if not query or len(query) > DEFAULT_MAX_QUERY_CHARS:
        return False
    rules = value.get("rules")
    if not isinstance(rules, Mapping):
        return False
    if rules.get("max_queries") != 1:
        return False
    if rules.get("max_query_chars") != DEFAULT_MAX_QUERY_CHARS:
        return False
    if rules.get("provider_fields_allowed") is not False:
        return False
    if rules.get("execution_fields_allowed") is not False:
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
    return True


def _search_id(
    adequacy_artifact: Mapping[str, Any] | None,
    query: str,
) -> str:
    workflow_id = (
        adequacy_artifact.get("workflow_id")
        if isinstance(adequacy_artifact, Mapping)
        else ""
    )
    generated_at = (
        adequacy_artifact.get("generated_at")
        if isinstance(adequacy_artifact, Mapping)
        else ""
    )
    identity = f"{workflow_id}|{generated_at}|{query}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"rss-external-search-handoff-{digest}"


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
    "HANDOFF_STATUS_ELIGIBLE",
    "HANDOFF_STATUS_INELIGIBLE",
    "REASON_GOVERNANCE_BLOCKED",
    "REASON_HANDOFF_ELIGIBLE",
    "REASON_RSS_COVERAGE_ADEQUATE",
    "RSS_EXTERNAL_SEARCH_HANDOFF_ARTIFACT",
    "build_rss_external_search_handoff",
    "materialize_external_search_query_from_rss_adequacy",
    "prepare_external_search_request_from_rss_handoff",
    "validate_rss_external_search_handoff",
]
