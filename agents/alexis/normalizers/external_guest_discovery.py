from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from runtime.artifacts.external_discovery_result import (
    EXTERNAL_DISCOVERY_RESULT_SET_ARTIFACT,
    validate_external_discovery_result_set,
)
from runtime.workflows.candidate_merge import (
    ENRICHMENT_METADATA_FIELDS,
    GUEST_CANDIDATE_LIST_ARTIFACT,
    validate_guest_candidate_enrichment_metadata,
)


ALEXIS_EXTERNAL_GUEST_NORMALIZATION = "alexis_external_guest_normalization"
SOURCE_SCOPE = "web"
PASSTHROUGH_CANDIDATE_FIELDS = (
    "candidate_id",
    "display_name",
    "canonical_name",
    "title",
    "affiliation",
    "bio",
    "expertise",
    "email",
    "email_refs",
    "source_url",
    "source_title",
    "source_ref_ids",
    "citation_ids",
    "provider_result_id",
    "candidate_origin",
    "contact_verification_state",
    "verification_state",
    *ENRICHMENT_METADATA_FIELDS,
)
DISPLAY_NAME_FIELDS = (
    "display_name",
    "name",
    "candidate_name",
    "person_name",
    "raw_display_name",
)
SOURCE_URL_FIELDS = ("source_url", "url", "raw_url")
SOURCE_TITLE_FIELDS = ("source_title", "title", "raw_title")
RAW_PROVENANCE_PASSTHROUGH_FIELDS = (
    "provider_id",
    "provider_type",
    "dry_run",
    "dry_run_executed",
    "cloud_dry_run",
    "external_call_performed",
    "cost_incurred",
    "discovery_executed",
    "blocked_reason",
)


@dataclass(frozen=True)
class AlexisExternalGuestNormalization:
    artifact: dict[str, Any]
    materialized: bool
    transition_outcome: str
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


def normalize_external_discovery_to_guest_candidate_list(
    raw_artifact: Any,
    *,
    artifact_ref: str | None = None,
) -> AlexisExternalGuestNormalization:
    errors = validate_external_discovery_result_set(raw_artifact)
    if errors:
        return _closed(
            skipped_reasons=tuple(error.error_code for error in errors),
            raw_artifact_ref=artifact_ref,
        )

    assert isinstance(raw_artifact, dict)
    source_refs = _source_refs_by_provider_result_id(raw_artifact.get("source_refs"))
    citations = _citations_by_provider_result_id(raw_artifact.get("citations"))
    skipped: list[str] = []
    candidates: list[dict[str, Any]] = []

    for index, raw_result in enumerate(raw_artifact.get("raw_results", [])):
        skip_reason = _raw_result_skip_reason(
            raw_result,
            source_refs=source_refs,
            citations=citations,
        )
        if skip_reason is not None:
            skipped.append(skip_reason)
            continue
        candidate = _normalize_raw_result(
            raw_result,
            raw_artifact=raw_artifact,
            source_refs=source_refs,
            citations=citations,
            raw_result_index=index,
            raw_artifact_ref=artifact_ref,
        )
        if candidate is None:
            skipped.append("raw_result_missing_display_name")
            continue
        enrichment_errors = validate_guest_candidate_enrichment_metadata(candidate)
        if enrichment_errors:
            skipped.append("candidate_enrichment_metadata_invalid")
            continue
        candidates.append(candidate)

    artifact = _artifact(
        candidates=candidates,
        raw_artifact=raw_artifact,
        raw_artifact_ref=artifact_ref,
        skipped_reasons=tuple(skipped),
    )
    return AlexisExternalGuestNormalization(
        artifact=artifact,
        materialized=True,
        transition_outcome="success",
        skipped_reasons=tuple(skipped),
        audit_summary=_audit_summary(
            artifact=artifact,
            materialized=True,
            skipped_reasons=tuple(skipped),
        ),
    )


def _normalize_raw_result(
    raw_result: dict[str, Any],
    *,
    raw_artifact: dict[str, Any],
    source_refs: dict[str, list[dict[str, Any]]],
    citations: dict[str, list[dict[str, Any]]],
    raw_result_index: int,
    raw_artifact_ref: str | None,
) -> dict[str, Any] | None:
    display_name = _first_string(raw_result, DISPLAY_NAME_FIELDS)
    if display_name is None:
        return None

    provider_result_id = _optional_string(raw_result.get("provider_result_id"))
    matched_source_refs = source_refs.get(provider_result_id, [])
    matched_citations = citations.get(provider_result_id, [])
    candidate = {
        "display_name": display_name,
        "source_scope": SOURCE_SCOPE,
        "provenance": _candidate_provenance(
            raw_artifact=raw_artifact,
            raw_artifact_ref=raw_artifact_ref,
            raw_result=raw_result,
            raw_result_index=raw_result_index,
            matched_source_refs=matched_source_refs,
            matched_citations=matched_citations,
        ),
    }

    for field in PASSTHROUGH_CANDIDATE_FIELDS:
        if field in raw_result and field not in candidate:
            candidate[field] = deepcopy(raw_result[field])

    if "source_url" not in candidate:
        candidate["source_url"] = _first_string(raw_result, SOURCE_URL_FIELDS)
    if "source_title" not in candidate:
        candidate["source_title"] = _first_string(raw_result, SOURCE_TITLE_FIELDS)
    if provider_result_id is not None:
        candidate["provider_result_id"] = provider_result_id
    if matched_source_refs:
        candidate["source_refs"] = deepcopy(matched_source_refs)
        candidate["source_ref_ids"] = _string_list(
            ref.get("source_ref_id") for ref in matched_source_refs
        )
    if matched_citations:
        candidate["citations"] = deepcopy(matched_citations)
        candidate["citation_ids"] = _string_list(
            citation.get("citation_id") for citation in matched_citations
        )

    return {key: value for key, value in candidate.items() if value is not None}


def _raw_result_skip_reason(
    raw_result: dict[str, Any],
    *,
    source_refs: dict[str, list[dict[str, Any]]],
    citations: dict[str, list[dict[str, Any]]],
) -> str | None:
    display_name = _first_string(raw_result, DISPLAY_NAME_FIELDS)
    if display_name is None:
        return "raw_result_missing_display_name"

    provider_result_id = _optional_string(raw_result.get("provider_result_id"))
    if provider_result_id is None:
        return "raw_result_missing_provider_result_id"
    if not source_refs.get(provider_result_id):
        return "raw_result_missing_source_ref"
    if not citations.get(provider_result_id):
        return "raw_result_missing_citation"
    return None


def _artifact(
    *,
    candidates: list[dict[str, Any]],
    raw_artifact: dict[str, Any],
    raw_artifact_ref: str | None,
    skipped_reasons: tuple[str, ...],
) -> dict[str, Any]:
    provenance = raw_artifact.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    provider_metadata = raw_artifact.get("provider_metadata")
    if not isinstance(provider_metadata, dict):
        provider_metadata = {}

    return {
        "artifact_type": GUEST_CANDIDATE_LIST_ARTIFACT,
        "source_scope": SOURCE_SCOPE,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "raw_external_discovery_artifact_ref": raw_artifact_ref,
        "source_refs": deepcopy(raw_artifact.get("source_refs", [])),
        "citations": deepcopy(raw_artifact.get("citations", [])),
        "provider_metadata": deepcopy(provider_metadata),
        "normalization": {
            "normalizer": ALEXIS_EXTERNAL_GUEST_NORMALIZATION,
            "input_artifact_type": EXTERNAL_DISCOVERY_RESULT_SET_ARTIFACT,
            "output_artifact_type": GUEST_CANDIDATE_LIST_ARTIFACT,
        },
        "provenance": {
            "normalizer": ALEXIS_EXTERNAL_GUEST_NORMALIZATION,
            "normalization_performed": True,
            "input_artifact_type": EXTERNAL_DISCOVERY_RESULT_SET_ARTIFACT,
            "source_scope": SOURCE_SCOPE,
            "raw_external_discovery_artifact_ref": raw_artifact_ref,
            **_raw_provenance_passthrough_fields(
                provenance=provenance,
                provider_metadata=provider_metadata,
            ),
            "raw_external_result_provenance": deepcopy(provenance),
            "provider_metadata": deepcopy(provider_metadata),
            "source_ref_count": len(raw_artifact.get("source_refs", [])),
            "citation_count": len(raw_artifact.get("citations", [])),
            "skipped_reasons": list(skipped_reasons),
            "provider_execution_performed": False,
            "provider_executed": False,
            "web_search_executed": False,
            "browser_api_called": False,
            "search_api_called": False,
            "cloud_model_called": False,
            "external_adapter_called": False,
            "db_write_performed": False,
            "memory_write_performed": False,
            "automatic_contact_promotion_performed": False,
            "external_overwrite_performed": False,
            "ranking_performed": False,
            "scoring_performed": False,
            "selection_performed": False,
            "draft_generated": False,
            "notification_performed": False,
            "delivery_performed": False,
        },
    }


def _closed(
    *,
    skipped_reasons: tuple[str, ...],
    raw_artifact_ref: str | None,
) -> AlexisExternalGuestNormalization:
    artifact = {
        "artifact_type": GUEST_CANDIDATE_LIST_ARTIFACT,
        "source_scope": SOURCE_SCOPE,
        "candidate_count": 0,
        "candidates": [],
        "raw_external_discovery_artifact_ref": raw_artifact_ref,
        "provenance": {
            "normalizer": ALEXIS_EXTERNAL_GUEST_NORMALIZATION,
            "normalization_performed": False,
            "provider_execution_performed": False,
            "provider_executed": False,
            "web_search_executed": False,
            "browser_api_called": False,
            "search_api_called": False,
            "cloud_model_called": False,
            "external_adapter_called": False,
            "db_write_performed": False,
            "memory_write_performed": False,
            "automatic_contact_promotion_performed": False,
            "external_overwrite_performed": False,
            "ranking_performed": False,
            "scoring_performed": False,
            "selection_performed": False,
            "draft_generated": False,
            "notification_performed": False,
            "delivery_performed": False,
            "skipped_reasons": list(skipped_reasons),
        },
    }
    return AlexisExternalGuestNormalization(
        artifact=artifact,
        materialized=False,
        transition_outcome="failure",
        skipped_reasons=skipped_reasons,
        audit_summary=_audit_summary(
            artifact=artifact,
            materialized=False,
            skipped_reasons=skipped_reasons,
        ),
    )


def _candidate_provenance(
    *,
    raw_artifact: dict[str, Any],
    raw_artifact_ref: str | None,
    raw_result: dict[str, Any],
    raw_result_index: int,
    matched_source_refs: list[dict[str, Any]],
    matched_citations: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "normalizer": ALEXIS_EXTERNAL_GUEST_NORMALIZATION,
        "raw_external_discovery_artifact_ref": raw_artifact_ref,
        "raw_result_index": raw_result_index,
        "provider_result_id": _optional_string(raw_result.get("provider_result_id")),
        "provider_metadata": deepcopy(raw_artifact.get("provider_metadata", {})),
        "raw_external_result_provenance": deepcopy(raw_artifact.get("provenance", {})),
        "raw_result": deepcopy(raw_result),
        "source_refs": deepcopy(matched_source_refs),
        "citations": deepcopy(matched_citations),
        **_raw_provenance_passthrough_fields(
            provenance=raw_artifact.get("provenance", {}),
            provider_metadata=raw_artifact.get("provider_metadata", {}),
        ),
        "normalization_performed": True,
        "provider_execution_performed": False,
        "provider_executed": False,
        "web_search_executed": False,
        "browser_api_called": False,
        "search_api_called": False,
        "cloud_model_called": False,
        "external_adapter_called": False,
        "db_write_performed": False,
        "memory_write_performed": False,
        "automatic_contact_promotion_performed": False,
        "external_overwrite_performed": False,
        "ranking_performed": False,
        "scoring_performed": False,
        "selection_performed": False,
        "draft_generated": False,
        "notification_performed": False,
        "delivery_performed": False,
    }


def _source_refs_by_provider_result_id(value: Any) -> dict[str, list[dict[str, Any]]]:
    return _objects_by_provider_result_id(value)


def _citations_by_provider_result_id(value: Any) -> dict[str, list[dict[str, Any]]]:
    return _objects_by_provider_result_id(value)


def _objects_by_provider_result_id(value: Any) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(value, list):
        return grouped
    for item in value:
        if not isinstance(item, dict):
            continue
        provider_result_id = _optional_string(item.get("provider_result_id"))
        if provider_result_id is None:
            continue
        grouped.setdefault(provider_result_id, []).append(item)
    return grouped


def _raw_provenance_passthrough_fields(
    *,
    provenance: dict[str, Any],
    provider_metadata: dict[str, Any],
) -> dict[str, Any]:
    preserved: dict[str, Any] = {}
    for field in RAW_PROVENANCE_PASSTHROUGH_FIELDS:
        if field in provenance:
            preserved[field] = deepcopy(provenance[field])
        elif field in provider_metadata:
            preserved[field] = deepcopy(provider_metadata[field])
    return preserved


def _first_string(source: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    for field in fields:
        value = _optional_string(source.get(field))
        if value is not None:
            return value
    return None


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _string_list(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _optional_string(value)
        if clean is None or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def _audit_summary(
    *,
    artifact: dict[str, Any],
    materialized: bool,
    skipped_reasons: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "artifact_type": artifact.get("artifact_type"),
        "candidate_count": artifact.get("candidate_count"),
        "source_scope": artifact.get("source_scope"),
        "materialized": materialized,
        "normalization_performed": (
            artifact.get("provenance", {}).get("normalization_performed") is True
        ),
        "provider_execution_performed": False,
        "ranking_performed": False,
        "scoring_performed": False,
        "selection_performed": False,
        "web_search_executed": False,
        "cloud_model_called": False,
        "delivery_performed": False,
        "skipped_reasons": list(skipped_reasons),
    }


__all__ = [
    "ALEXIS_EXTERNAL_GUEST_NORMALIZATION",
    "AlexisExternalGuestNormalization",
    "normalize_external_discovery_to_guest_candidate_list",
]
