from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from runtime.semantic_index import LocalSemanticIndex
from runtime.semantic_retrieval import retrieve_semantic_index_matches


GUEST_CANDIDATE_LIST_ARTIFACT = "guest_candidate_list"
DB_SOURCE_SCOPE = "db"


@dataclass(frozen=True)
class SemanticGuestRetrievalMaterialization:
    artifact: dict[str, Any]
    materialized: bool
    transition_outcome: str | None
    skipped_reasons: tuple[str, ...]
    audit_summary: dict[str, Any]

    def to_audit_record(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact.get("artifact_type"),
            "materialized": self.materialized,
            "transition_outcome": self.transition_outcome,
            "skipped_reasons": list(self.skipped_reasons),
            "audit_summary": dict(self.audit_summary),
        }


def materialize_semantic_guest_db_retrieval(
    *,
    semantic_query: Mapping[str, Any] | None,
    guest_semantic_index: LocalSemanticIndex | None,
    provider_binding_metadata: Mapping[str, Any] | None = None,
    workflow_id: str | None = None,
    step_id: str | None = None,
    artifact_ref: str | None = None,
) -> SemanticGuestRetrievalMaterialization:
    retrieval = retrieve_semantic_index_matches(
        semantic_query=semantic_query,
        semantic_index=guest_semantic_index,
    )
    artifact = _artifact(
        retrieval=retrieval,
        provider_binding_metadata=provider_binding_metadata,
        workflow_id=workflow_id,
        step_id=step_id,
        artifact_ref=artifact_ref,
    )
    materialized = retrieval.ok
    return SemanticGuestRetrievalMaterialization(
        artifact=artifact,
        materialized=materialized,
        transition_outcome="success" if materialized else "failure",
        skipped_reasons=retrieval.skipped_reasons,
        audit_summary=_audit_summary(
            artifact=artifact,
            materialized=materialized,
            skipped_reasons=retrieval.skipped_reasons,
        ),
    )


def _artifact(
    *,
    retrieval: Any,
    provider_binding_metadata: Mapping[str, Any] | None,
    workflow_id: str | None,
    step_id: str | None,
    artifact_ref: str | None,
) -> dict[str, Any]:
    candidates = [
        _candidate(match)
        for match in retrieval.matches
    ]
    provider_metadata = _provider_metadata(provider_binding_metadata)
    return {
        "artifact_type": GUEST_CANDIDATE_LIST_ARTIFACT,
        "workflow_id": _optional_string(workflow_id),
        "step_id": _optional_string(step_id),
        "artifact_ref": _optional_string(artifact_ref),
        "source_scope": DB_SOURCE_SCOPE,
        "provider": provider_metadata,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "semantic_query_terms": list(retrieval.query_terms),
        "provenance": {
            **dict(retrieval.provenance),
            "artifact_type": GUEST_CANDIDATE_LIST_ARTIFACT,
            "materialization_boundary": (
                "runtime.workflows.semantic_guest_retrieval"
            ),
            "source_scope": DB_SOURCE_SCOPE,
            "provider": provider_metadata,
            "provider_id": provider_metadata.get("provider_id"),
            "provider_contract_id": provider_metadata.get("provider_contract_id"),
            "resource_binding_id": provider_metadata.get("resource_binding_id"),
            "resource_id": provider_metadata.get("resource_id"),
            "semantic_owner": provider_metadata.get("semantic_owner"),
            "retrieval_executed": retrieval.ok,
            "ranking_performed": False,
            "selection_performed": False,
            "web_search_executed": False,
            "browser_api_called": False,
            "search_api_called": False,
            "external_adapter_called": False,
            "draft_generated": False,
            "delivery_performed": False,
        },
    }


def _provider_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}

    metadata = dict(value)
    execution_policy = metadata.get("execution_policy")
    if isinstance(execution_policy, Mapping):
        metadata["execution_policy"] = dict(execution_policy)
    return metadata


def _candidate(match: Any) -> dict[str, Any]:
    entry = match.entry
    entry_provenance = (
        dict(entry.provenance)
        if isinstance(entry.provenance, dict)
        else {}
    )
    return {
        "candidate_id": match.candidate_id,
        "semantic_match_score": match.semantic_match_score,
        "semantic_match_reasons": list(match.semantic_match_reasons),
        "matched_terms": list(match.matched_terms),
        "metadata": {
            "semantic_match_score": match.semantic_match_score,
            "semantic_match_reasons": list(match.semantic_match_reasons),
            "matched_terms": list(match.matched_terms),
            "source_scope": DB_SOURCE_SCOPE,
        },
        "provenance": {
            **entry_provenance,
            "source_scope": DB_SOURCE_SCOPE,
            "source_index_scope": entry_provenance.get("source_scope"),
            "source_record_id": entry_provenance.get(
                "source_record_id",
                match.candidate_id,
            ),
            "semantic_retrieval_executed": True,
            "semantic_match_score": match.semantic_match_score,
            "semantic_match_reasons": list(match.semantic_match_reasons),
            "matched_terms": list(match.matched_terms),
        },
    }


def _audit_summary(
    *,
    artifact: dict[str, Any],
    materialized: bool,
    skipped_reasons: tuple[str, ...],
) -> dict[str, Any]:
    provenance = artifact.get("provenance")
    return {
        "artifact_type": artifact.get("artifact_type"),
        "candidate_count": artifact.get("candidate_count"),
        "source_scope": artifact.get("source_scope"),
        "materialized": materialized,
        "retrieval_executed": bool(
            isinstance(provenance, dict)
            and provenance.get("retrieval_executed") is True
        ),
        "deterministic": bool(
            isinstance(provenance, dict)
            and provenance.get("deterministic") is True
        ),
        "skipped_reasons": list(skipped_reasons),
    }


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "DB_SOURCE_SCOPE",
    "GUEST_CANDIDATE_LIST_ARTIFACT",
    "SemanticGuestRetrievalMaterialization",
    "materialize_semantic_guest_db_retrieval",
]
