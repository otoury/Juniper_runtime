from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


SEARCH_API_RESULT_SET_ARTIFACT = "search_api_result_set"
FORBIDDEN_DERIVED_FIELDS = (
    "briefing",
    "candidate_count",
    "candidates",
    "delivery_payload",
    "final_answer",
    "guest_candidate_list",
    "guest_candidates",
    "news_briefing",
    "normalized_results",
    "ranking",
    "selected_candidate",
    "sourced_summary",
    "summary",
    "telegram_prose",
    "telegram_text",
)
SEMANTIC_AUTHORITY_BOUNDARY = {
    "planner_semantic_grounding": False,
    "runtime_semantic_grounding": False,
    "operation_selection": False,
    "artifact_type_selection": False,
    "capability_selection": False,
}


@dataclass(frozen=True)
class SearchAPIResultValidationError:
    error_code: str
    field: str
    message: str


def build_search_api_result_set(
    *,
    provider_id: str,
    provider_type: str,
    query: str,
    results: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    source_refs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    citations: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    raw_provider_payload: Any = None,
    external_call_performed: bool = False,
    dry_run: bool = True,
    cost_incurred: bool = False,
    rejected_results: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safe_provenance = {
        "provider_id": _safe_string(provider_id),
        "provider_type": _safe_string(provider_type),
        "query": _safe_string(query),
        "raw_search_api_result": True,
        "external_call_performed": bool(external_call_performed),
        "dry_run": bool(dry_run),
        "cost_incurred": bool(cost_incurred),
        "source_normalization_performed": True,
        "summary_generated": False,
        "newsroom_normalization_performed": False,
        "ranking_performed": False,
        "selection_performed": False,
        "delivery_performed": False,
    }
    if isinstance(provenance, dict):
        safe_provenance.update(deepcopy(provenance))

    return {
        "artifact_type": SEARCH_API_RESULT_SET_ARTIFACT,
        "result_type": SEARCH_API_RESULT_SET_ARTIFACT,
        "provider_id": _safe_string(provider_id),
        "provider_type": _safe_string(provider_type),
        "query": _safe_string(query),
        "results": [deepcopy(item) for item in results],
        "source_refs": [deepcopy(item) for item in source_refs],
        "citations": [deepcopy(item) for item in citations],
        "raw_provider_payload": deepcopy(raw_provider_payload),
        "external_call_performed": bool(external_call_performed),
        "dry_run": bool(dry_run),
        "cost_incurred": bool(cost_incurred),
        "rejected_results": [deepcopy(item) for item in rejected_results],
        "provenance": safe_provenance,
        "semantic_authority": deepcopy(SEMANTIC_AUTHORITY_BOUNDARY),
    }


def validate_search_api_result_set(
    artifact: Any,
) -> tuple[SearchAPIResultValidationError, ...]:
    if not isinstance(artifact, dict):
        return (
            SearchAPIResultValidationError(
                "invalid_search_api_result_artifact",
                "artifact",
                "search_api result artifact must be an object.",
            ),
        )

    errors: list[SearchAPIResultValidationError] = []
    if artifact.get("artifact_type") != SEARCH_API_RESULT_SET_ARTIFACT:
        errors.append(
            SearchAPIResultValidationError(
                "invalid_artifact_type",
                "artifact_type",
                "artifact_type must be search_api_result_set.",
            )
        )

    if artifact.get("result_type") != SEARCH_API_RESULT_SET_ARTIFACT:
        errors.append(
            SearchAPIResultValidationError(
                "invalid_result_type",
                "result_type",
                "result_type must be search_api_result_set.",
            )
        )

    for field in ("provider_id", "provider_type", "query"):
        if not _safe_string(artifact.get(field)):
            errors.append(
                SearchAPIResultValidationError(
                    "missing_required_field",
                    field,
                    f"{field} must be a non-empty string.",
                )
            )

    for field in ("external_call_performed", "dry_run", "cost_incurred"):
        if not isinstance(artifact.get(field), bool):
            errors.append(
                SearchAPIResultValidationError(
                    "invalid_boolean_field",
                    field,
                    f"{field} must be a boolean.",
                )
            )

    for field in FORBIDDEN_DERIVED_FIELDS:
        if field in artifact:
            errors.append(
                SearchAPIResultValidationError(
                    "derived_field_not_allowed",
                    field,
                    "raw search_api result artifacts must not include derived summary or domain-normalized fields.",
                )
            )

    result_payload_required = _requires_result_payload(artifact)
    _validate_object_list(
        artifact.get("results"),
        field="results",
        required=result_payload_required,
        errors=errors,
    )
    _validate_object_list(
        artifact.get("source_refs"),
        field="source_refs",
        required=result_payload_required,
        errors=errors,
    )
    _validate_object_list(
        artifact.get("citations"),
        field="citations",
        required=False,
        errors=errors,
    )
    _validate_object_list(
        artifact.get("rejected_results"),
        field="rejected_results",
        required=False,
        errors=errors,
    )
    _validate_accepted_result_sources(artifact, errors=errors)
    _validate_provenance(artifact, errors=errors)

    return tuple(errors)


def normalize_search_api_result_set_to_summary_source_items(
    artifact: Any,
) -> tuple[dict[str, Any], ...]:
    if validate_search_api_result_set(artifact):
        return ()
    if not isinstance(artifact, dict):
        return ()

    source_refs_by_id, source_refs_by_result_id = _indexed_source_refs(
        artifact.get("source_refs")
    )
    normalized: list[dict[str, Any]] = []
    results = artifact.get("results")
    if not isinstance(results, list):
        return ()

    for result in results:
        if not isinstance(result, dict):
            continue
        provider_result_id = _safe_string(result.get("provider_result_id"))
        source_ref_id = _safe_string(result.get("source_ref_id"))
        source_ref = (
            source_refs_by_id.get(source_ref_id or "")
            or source_refs_by_result_id.get(provider_result_id or "")
        )
        if not provider_result_id or not isinstance(source_ref, dict):
            continue

        source_ref_id = _safe_string(source_ref.get("source_ref_id")) or source_ref_id
        url = _result_url(result) or _source_url(source_ref)
        title = _safe_string(result.get("title")) or _safe_string(
            source_ref.get("title")
        )
        if not source_ref_id or not url or not title:
            continue

        source_metadata = _safe_mapping(result.get("source_metadata"))
        provider_metadata = _merged_provider_metadata(
            artifact=artifact,
            result=result,
        )
        item = {
            "item_id": provider_result_id,
            "provider_result_id": provider_result_id,
            "source_ref_id": source_ref_id,
            "source_id": f"{artifact['provider_id']}:{provider_result_id}",
            "source_type": (
                _safe_string(source_ref.get("source_type"))
                or source_metadata.get("source_type")
                or "web_page"
            ),
            "title": title,
            "link": url,
            "url": url,
            "snippet": _safe_string(result.get("snippet"))
            or _safe_string(result.get("raw_snippet"))
            or "",
            "published": _safe_string(result.get("published"))
            or _safe_string(result.get("published_at"))
            or source_metadata.get("published_date", "")
            or _safe_string(source_ref.get("published"))
            or _safe_string(source_ref.get("published_date"))
            or "",
            "fetched_at": _safe_string(result.get("fetched_at"))
            or _safe_string(source_ref.get("fetched_at"))
            or "",
            "provenance": {
                "kind": "search_api_source_item",
                "provider_id": artifact["provider_id"],
                "provider_type": artifact["provider_type"],
                "query": artifact["query"],
                "source_ref_id": source_ref_id,
            },
            "provider_metadata": provider_metadata,
            "source_metadata": source_metadata,
            "source_ref": deepcopy(source_ref),
        }
        normalized.append(item)

    return tuple(normalized)


def _requires_result_payload(artifact: dict[str, Any]) -> bool:
    return (
        artifact.get("external_call_performed") is True
        and artifact.get("dry_run") is False
    )


def _validate_object_list(
    value: Any,
    *,
    field: str,
    required: bool,
    errors: list[SearchAPIResultValidationError],
) -> None:
    if value is None and not required:
        return
    if (
        not isinstance(value, list)
        or (required and not value)
        or any(not isinstance(item, dict) for item in value)
    ):
        errors.append(
            SearchAPIResultValidationError(
                "invalid_object_list",
                field,
                f"{field} must be a list of objects.",
            )
        )


def _validate_accepted_result_sources(
    artifact: dict[str, Any],
    *,
    errors: list[SearchAPIResultValidationError],
) -> None:
    results = artifact.get("results")
    source_refs = artifact.get("source_refs")
    if not isinstance(results, list) or not isinstance(source_refs, list):
        return

    source_ref_ids = _source_ref_ids(source_refs)
    source_result_ids = _provider_result_ids(source_refs)
    for index, result in enumerate(results):
        if not isinstance(result, dict):
            continue
        provider_result_id = _safe_string(result.get("provider_result_id"))
        source_ref_id = _safe_string(result.get("source_ref_id"))
        if not provider_result_id:
            errors.append(
                SearchAPIResultValidationError(
                    "missing_provider_result_id",
                    f"results[{index}].provider_result_id",
                    "accepted search_api results must include provider_result_id.",
                )
            )
        if not _result_url(result):
            errors.append(
                SearchAPIResultValidationError(
                    "accepted_result_missing_url",
                    f"results[{index}].url",
                    "accepted search_api results must include a URL.",
                )
            )
        if provider_result_id and provider_result_id in source_result_ids:
            continue
        if source_ref_id and source_ref_id in source_ref_ids:
            continue
        errors.append(
            SearchAPIResultValidationError(
                "accepted_result_missing_source_ref",
                f"results[{index}].source_refs",
                "accepted search_api results must have matching source refs.",
            )
        )

    for index, source_ref in enumerate(source_refs):
        if not isinstance(source_ref, dict):
            continue
        if not _source_url(source_ref):
            errors.append(
                SearchAPIResultValidationError(
                    "source_ref_missing_url",
                    f"source_refs[{index}].source_url",
                    "source refs must include source_url or url.",
                )
            )


def _validate_provenance(
    artifact: dict[str, Any],
    *,
    errors: list[SearchAPIResultValidationError],
) -> None:
    provenance = artifact.get("provenance")
    if not isinstance(provenance, dict):
        errors.append(
            SearchAPIResultValidationError(
                "invalid_provenance",
                "provenance",
                "provenance must be an object.",
            )
        )
        return

    expected = {
        "provider_id": artifact.get("provider_id"),
        "provider_type": artifact.get("provider_type"),
        "query": artifact.get("query"),
        "external_call_performed": artifact.get("external_call_performed"),
        "dry_run": artifact.get("dry_run"),
        "cost_incurred": artifact.get("cost_incurred"),
    }
    for field, value in expected.items():
        if provenance.get(field) != value:
            errors.append(
                SearchAPIResultValidationError(
                    "provenance_mismatch",
                    f"provenance.{field}",
                    f"provenance.{field} must match top-level {field}.",
                )
            )

    required_false = (
        "summary_generated",
        "newsroom_normalization_performed",
        "ranking_performed",
        "selection_performed",
        "delivery_performed",
    )
    if provenance.get("raw_search_api_result") is not True:
        errors.append(
            SearchAPIResultValidationError(
                "missing_raw_search_api_result_provenance",
                "provenance.raw_search_api_result",
                "provenance must mark the artifact as a raw search_api result.",
            )
        )
    for field in required_false:
        if provenance.get(field) is not False:
            errors.append(
                SearchAPIResultValidationError(
                    "derived_operation_not_allowed",
                    f"provenance.{field}",
                    "raw search_api result artifacts must not claim summary, normalization, ranking, selection, or delivery.",
                )
            )


def _provider_result_ids(items: list[Any]) -> set[str]:
    result_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        provider_result_id = _safe_string(item.get("provider_result_id"))
        if provider_result_id:
            result_ids.add(provider_result_id)
    return result_ids


def _source_ref_ids(items: list[Any]) -> set[str]:
    source_ref_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        source_ref_id = _safe_string(item.get("source_ref_id"))
        if source_ref_id:
            source_ref_ids.add(source_ref_id)
    return source_ref_ids


def _indexed_source_refs(
    source_refs: Any,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_source_ref_id: dict[str, dict[str, Any]] = {}
    by_provider_result_id: dict[str, dict[str, Any]] = {}
    if not isinstance(source_refs, list):
        return by_source_ref_id, by_provider_result_id
    for source_ref in source_refs:
        if not isinstance(source_ref, dict):
            continue
        source_ref_id = _safe_string(source_ref.get("source_ref_id"))
        provider_result_id = _safe_string(source_ref.get("provider_result_id"))
        if source_ref_id:
            by_source_ref_id[source_ref_id] = source_ref
        if provider_result_id:
            by_provider_result_id[provider_result_id] = source_ref
    return by_source_ref_id, by_provider_result_id


def _merged_provider_metadata(
    *,
    artifact: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, str]:
    provider_metadata = {
        "provider_id": _safe_string(artifact.get("provider_id")) or "",
        "provider_type": _safe_string(artifact.get("provider_type")) or "",
        "query": _safe_string(artifact.get("query")) or "",
    }
    provider_metadata.update(_safe_mapping(result.get("provider_metadata")))
    return {
        key: value
        for key, value in provider_metadata.items()
        if isinstance(key, str) and isinstance(value, str) and value
    }


def _safe_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        key: item.strip()
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str) and item.strip()
    }


def _result_url(result: dict[str, Any]) -> str | None:
    return _safe_url(result.get("url")) or _safe_url(result.get("raw_url"))


def _source_url(source_ref: dict[str, Any]) -> str | None:
    return _safe_url(source_ref.get("source_url")) or _safe_url(source_ref.get("url"))


def _safe_url(value: Any) -> str | None:
    text = _safe_string(value)
    if text and text.startswith(("http://", "https://")):
        return text
    return None


def _safe_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "SEARCH_API_RESULT_SET_ARTIFACT",
    "SearchAPIResultValidationError",
    "build_search_api_result_set",
    "normalize_search_api_result_set_to_summary_source_items",
    "validate_search_api_result_set",
]
