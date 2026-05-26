from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from runtime.artifacts.external_retrieval_lineage import (
    validate_normalized_external_retrieval_result_lineage,
)


EXTERNAL_SEARCH_RESULT_SET_ARTIFACT = "external_search_result_set"
EXTERNAL_SEARCH_RESULT_SET_MERGE_TYPE = "bounded_external_search_result_set_merge"
DEFAULT_MERGE_MAX_RESULT_SETS = 3
DEFAULT_MERGE_MAX_RESULTS_PER_SET = 5
DEFAULT_MERGE_MAX_TOTAL_RESULTS = 10
FORBIDDEN_TOP_LEVEL_FIELDS = (
    "candidate_count",
    "candidates",
    "delivery_payload",
    "final_answer",
    "guest_candidate_list",
    "normalized_results",
    "provider_metadata",
    "provider_payload",
    "ranking",
    "selected_candidate",
    "sourced_summary",
    "summary",
)
FORBIDDEN_PROVENANCE_FLAGS = (
    "browser_api_called",
    "cloud_model_called",
    "delivery_performed",
    "domain_normalization_performed",
    "provider_adapter_called",
    "provider_integration_performed",
    "provider_selected",
    "ranking_performed",
    "selection_performed",
    "summarization_performed",
)
SEMANTIC_AUTHORITY_BOUNDARY = {
    "planner_semantic_grounding": False,
    "runtime_semantic_grounding": False,
    "operation_selection": False,
    "artifact_type_selection": False,
    "capability_selection": False,
}


@dataclass(frozen=True)
class ExternalSearchResultValidationError:
    error_code: str
    field: str
    message: str


def build_external_search_result_set(
    *,
    search_id: str,
    query: str,
    raw_results: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    source_refs: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    citations: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    external_call_performed: bool = False,
    cost_incurred: bool = False,
    rejected_raw_results: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    execution_receipt_refs: list[str] | tuple[str, ...] = (),
    result_lineage: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    provenance: dict[str, Any] | None = None,
    merge_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safe_receipt_refs = [
        item.strip()
        for item in execution_receipt_refs
        if isinstance(item, str) and item.strip()
    ]
    safe_provenance = {
        "search_id": _safe_string(search_id),
        "semantic_type": "external_search",
        "raw_external_search_result": True,
        "contract_stage": "pre_provider_integration",
        "execution_allowed": False,
        "external_call_performed": bool(external_call_performed),
        "cost_incurred": bool(cost_incurred),
        "provider_integration_performed": False,
        "provider_selected": False,
        "provider_adapter_called": False,
        "browser_api_called": False,
        "cloud_model_called": False,
        "summarization_performed": False,
        "domain_normalization_performed": False,
        "ranking_performed": False,
        "selection_performed": False,
        "delivery_performed": False,
        "execution_receipt_refs": list(safe_receipt_refs),
    }
    if isinstance(provenance, dict):
        safe_provenance.update(deepcopy(provenance))

    artifact = {
        "artifact_type": EXTERNAL_SEARCH_RESULT_SET_ARTIFACT,
        "result_type": EXTERNAL_SEARCH_RESULT_SET_ARTIFACT,
        "search_id": _safe_string(search_id),
        "query": _safe_string(query),
        "raw_results": [deepcopy(item) for item in raw_results],
        "source_refs": [deepcopy(item) for item in source_refs],
        "citations": [deepcopy(item) for item in citations],
        "external_call_performed": bool(external_call_performed),
        "cost_incurred": bool(cost_incurred),
        "rejected_raw_results": [deepcopy(item) for item in rejected_raw_results],
        "execution_receipt_refs": list(safe_receipt_refs),
        "result_lineage": [deepcopy(item) for item in result_lineage],
        "provenance": safe_provenance,
        "semantic_authority": deepcopy(SEMANTIC_AUTHORITY_BOUNDARY),
    }
    if isinstance(merge_metadata, dict):
        artifact["merge_metadata"] = deepcopy(merge_metadata)
    return artifact


def merge_external_search_result_sets(
    *,
    search_id: str,
    result_sets: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    max_result_sets: int = DEFAULT_MERGE_MAX_RESULT_SETS,
    max_results_per_set: int = DEFAULT_MERGE_MAX_RESULTS_PER_SET,
    max_total_results: int = DEFAULT_MERGE_MAX_TOTAL_RESULTS,
) -> dict[str, Any]:
    limits = _bounded_merge_limits(
        max_result_sets=max_result_sets,
        max_results_per_set=max_results_per_set,
        max_total_results=max_total_results,
    )
    if not isinstance(result_sets, (list, tuple)):
        return _empty_merged_external_search_result_set(
            search_id=search_id,
            limits=limits,
            skipped_reasons=("result_sets_missing",),
        )

    raw_results: list[dict[str, Any]] = []
    source_refs: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    result_lineage: list[dict[str, Any]] = []
    execution_receipt_refs: list[str] = []
    input_records: list[dict[str, Any]] = []
    skipped_reasons: list[str] = []

    bounded_sets = list(result_sets[: limits["max_result_sets"]])
    if len(result_sets) > len(bounded_sets):
        skipped_reasons.append("result_set_count_bounded")

    for result_set_index, result_set in enumerate(bounded_sets):
        if validate_external_search_result_set(result_set):
            skipped_reasons.append("invalid_result_set")
            continue

        available_raw_results = result_set.get("raw_results", [])
        if not isinstance(available_raw_results, list):
            skipped_reasons.append("raw_results_missing")
            continue

        remaining = limits["max_total_results"] - len(raw_results)
        if remaining <= 0:
            skipped_reasons.append("total_result_count_bounded")
            break

        take_count = min(
            len(available_raw_results),
            limits["max_results_per_set"],
            remaining,
        )
        if len(available_raw_results) > take_count:
            skipped_reasons.append("result_count_bounded")

        start_index = len(raw_results)
        raw_results.extend(deepcopy(available_raw_results[:take_count]))
        source_refs.extend(
            _deepcopy_object_prefix(result_set.get("source_refs", []), take_count)
        )
        citations.extend(
            _deepcopy_object_prefix(result_set.get("citations", []), take_count)
        )
        result_lineage.extend(
            _deepcopy_object_prefix(result_set.get("result_lineage", []), take_count)
        )
        execution_receipt_refs.extend(
            item
            for item in result_set.get("execution_receipt_refs", [])
            if isinstance(item, str) and item.strip()
        )
        input_records.append(
            {
                "input_index": result_set_index,
                "artifact_type": result_set.get("artifact_type"),
                "search_id": result_set.get("search_id"),
                "query": result_set.get("query"),
                "accepted_result_count": take_count,
                "raw_result_start_index": start_index,
                "raw_result_end_index": len(raw_results),
            }
        )

    return build_external_search_result_set(
        search_id=search_id,
        query="merged external search result sets",
        raw_results=raw_results,
        source_refs=source_refs,
        citations=citations,
        rejected_raw_results=[],
        execution_receipt_refs=execution_receipt_refs,
        result_lineage=result_lineage,
        external_call_performed=False,
        cost_incurred=False,
        provenance=_merge_provenance(search_id, execution_receipt_refs),
        merge_metadata=_merge_metadata(
            limits=limits,
            input_records=input_records,
            raw_result_count=len(raw_results),
            skipped_reasons=tuple(skipped_reasons),
        ),
    )


def validate_external_search_result_set(
    artifact: Any,
) -> tuple[ExternalSearchResultValidationError, ...]:
    if not isinstance(artifact, dict):
        return (
            ExternalSearchResultValidationError(
                "invalid_external_search_result_artifact",
                "artifact",
                "external search result artifact must be an object.",
            ),
        )

    errors: list[ExternalSearchResultValidationError] = []
    if artifact.get("artifact_type") != EXTERNAL_SEARCH_RESULT_SET_ARTIFACT:
        errors.append(
            ExternalSearchResultValidationError(
                "invalid_artifact_type",
                "artifact_type",
                "artifact_type must be external_search_result_set.",
            )
        )
    if artifact.get("result_type") != EXTERNAL_SEARCH_RESULT_SET_ARTIFACT:
        errors.append(
            ExternalSearchResultValidationError(
                "invalid_result_type",
                "result_type",
                "result_type must be external_search_result_set.",
            )
        )

    for field in ("search_id", "query"):
        if not _safe_string(artifact.get(field)):
            errors.append(
                ExternalSearchResultValidationError(
                    "missing_required_field",
                    field,
                    f"{field} must be a non-empty string.",
                )
            )

    for field in ("external_call_performed", "cost_incurred"):
        if not isinstance(artifact.get(field), bool):
            errors.append(
                ExternalSearchResultValidationError(
                    "invalid_boolean_field",
                    field,
                    f"{field} must be a boolean.",
                )
            )

    if artifact.get("external_call_performed") is not False:
        errors.append(
            ExternalSearchResultValidationError(
                "external_call_not_allowed",
                "external_call_performed",
                "external search result contracts do not authorize provider calls.",
            )
        )
    if artifact.get("cost_incurred") is not False:
        errors.append(
            ExternalSearchResultValidationError(
                "cost_not_allowed",
                "cost_incurred",
                "external search result contracts do not authorize incurred cost.",
            )
        )

    for field in FORBIDDEN_TOP_LEVEL_FIELDS:
        if field in artifact:
            errors.append(
                ExternalSearchResultValidationError(
                    "derived_or_provider_field_not_allowed",
                    field,
                    "external search results must not include provider, summary, ranking, delivery, or domain-normalized fields.",
                )
            )

    _validate_object_list(artifact.get("raw_results"), field="raw_results", errors=errors)
    _validate_object_list(artifact.get("source_refs"), field="source_refs", errors=errors)
    _validate_object_list(artifact.get("citations"), field="citations", errors=errors)
    _validate_object_list(
        artifact.get("rejected_raw_results"),
        field="rejected_raw_results",
        errors=errors,
        required=False,
    )
    _validate_receipt_refs(
        artifact.get("execution_receipt_refs"),
        field="execution_receipt_refs",
        errors=errors,
        required=False,
    )
    _validate_result_lineage(
        artifact.get("result_lineage"),
        field="result_lineage",
        errors=errors,
        required=False,
    )
    _validate_result_lineage_coverage(artifact, errors=errors)
    _validate_semantic_authority(artifact.get("semantic_authority"), errors=errors)
    _validate_merge_metadata(
        artifact.get("merge_metadata"),
        artifact=artifact,
        errors=errors,
    )
    _validate_provenance(artifact.get("provenance"), errors=errors)
    return tuple(errors)


def _validate_object_list(
    value: Any,
    *,
    field: str,
    errors: list[ExternalSearchResultValidationError],
    required: bool = True,
) -> None:
    if value is None and not required:
        return
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        errors.append(
            ExternalSearchResultValidationError(
                "invalid_object_list",
                field,
                f"{field} must be a list of objects.",
            )
        )


def _validate_provenance(
    provenance: Any,
    *,
    errors: list[ExternalSearchResultValidationError],
) -> None:
    if not isinstance(provenance, dict):
        errors.append(
            ExternalSearchResultValidationError(
                "invalid_provenance",
                "provenance",
                "provenance must be an object.",
            )
        )
        return

    if provenance.get("contract_stage") != "pre_provider_integration":
        errors.append(
            ExternalSearchResultValidationError(
                "invalid_contract_stage",
                "provenance.contract_stage",
                "external search provenance must remain pre_provider_integration.",
            )
        )
    if provenance.get("execution_allowed") is not False:
        errors.append(
            ExternalSearchResultValidationError(
                "execution_not_allowed",
                "provenance.execution_allowed",
                "external search provenance must record execution_allowed=false.",
            )
        )
    for field in FORBIDDEN_PROVENANCE_FLAGS:
        if provenance.get(field) is not False:
            errors.append(
                ExternalSearchResultValidationError(
                    "provider_stage_flag_not_allowed",
                    f"provenance.{field}",
                    "provider-stage provenance flags must remain false.",
                )
            )
    _validate_receipt_refs(
        provenance.get("execution_receipt_refs"),
        field="provenance.execution_receipt_refs",
        errors=errors,
        required=False,
    )


def _validate_semantic_authority(
    value: Any,
    *,
    errors: list[ExternalSearchResultValidationError],
) -> None:
    if not isinstance(value, dict):
        errors.append(
            ExternalSearchResultValidationError(
                "invalid_semantic_authority",
                "semantic_authority",
                "external search results must explicitly deny semantic authority.",
            )
        )
        return

    for field in SEMANTIC_AUTHORITY_BOUNDARY:
        if value.get(field) is not False:
            errors.append(
                ExternalSearchResultValidationError(
                    "semantic_authority_not_allowed",
                    f"semantic_authority.{field}",
                    "retrieval artifacts must not become planner/runtime semantic authority.",
                )
            )


def _validate_result_lineage(
    value: Any,
    *,
    field: str,
    errors: list[ExternalSearchResultValidationError],
    required: bool,
) -> None:
    for error in validate_normalized_external_retrieval_result_lineage(
        value,
        field=field,
        required=required,
    ):
        errors.append(
            ExternalSearchResultValidationError(
                error.error_code,
                error.field,
                error.message,
            )
        )


def _validate_result_lineage_coverage(
    artifact: dict[str, Any],
    *,
    errors: list[ExternalSearchResultValidationError],
) -> None:
    raw_results = artifact.get("raw_results")
    result_lineage = artifact.get("result_lineage")
    if not isinstance(raw_results, list) or not raw_results:
        return
    if not isinstance(result_lineage, list) or not result_lineage:
        errors.append(
            ExternalSearchResultValidationError(
                "missing_result_lineage",
                "result_lineage",
                "normalized external search results must include explicit result_lineage.",
            )
        )
        return
    if len(result_lineage) != len(raw_results):
        errors.append(
            ExternalSearchResultValidationError(
                "result_lineage_count_mismatch",
                "result_lineage",
                "result_lineage must include one lineage object per raw result.",
            )
        )


def _validate_merge_metadata(
    merge_metadata: Any,
    *,
    artifact: dict[str, Any],
    errors: list[ExternalSearchResultValidationError],
) -> None:
    if merge_metadata is None:
        return
    if not isinstance(merge_metadata, dict):
        errors.append(
            ExternalSearchResultValidationError(
                "invalid_merge_metadata",
                "merge_metadata",
                "merge_metadata must be an object when present.",
            )
        )
        return

    if merge_metadata.get("merge_type") != EXTERNAL_SEARCH_RESULT_SET_MERGE_TYPE:
        errors.append(
            ExternalSearchResultValidationError(
                "invalid_merge_type",
                "merge_metadata.merge_type",
                "merge metadata must identify the bounded external search merge.",
            )
        )
    if merge_metadata.get("bounded") is not True:
        errors.append(
            ExternalSearchResultValidationError(
                "merge_not_bounded",
                "merge_metadata.bounded",
                "merge metadata must record bounded=true.",
            )
        )

    limits = merge_metadata.get("limits")
    if not isinstance(limits, dict):
        errors.append(
            ExternalSearchResultValidationError(
                "invalid_merge_limits",
                "merge_metadata.limits",
                "merge limits must be an object.",
            )
        )
    else:
        for field in (
            "max_result_sets",
            "max_results_per_set",
            "max_total_results",
        ):
            if not _positive_int(limits.get(field)):
                errors.append(
                    ExternalSearchResultValidationError(
                        "invalid_merge_limit",
                        f"merge_metadata.limits.{field}",
                        f"{field} must be a positive integer.",
                    )
                )

    input_sets = merge_metadata.get("input_result_sets")
    if not isinstance(input_sets, list) or any(
        not isinstance(item, dict) for item in input_sets
    ):
        errors.append(
            ExternalSearchResultValidationError(
                "invalid_merge_inputs",
                "merge_metadata.input_result_sets",
                "input_result_sets must be a list of objects.",
            )
        )
    elif merge_metadata.get("input_result_set_count") != len(input_sets):
        errors.append(
            ExternalSearchResultValidationError(
                "merge_input_count_mismatch",
                "merge_metadata.input_result_set_count",
                "input_result_set_count must match input_result_sets.",
            )
        )

    raw_result_count = merge_metadata.get("raw_result_count")
    raw_results = artifact.get("raw_results")
    if (
        not isinstance(raw_result_count, int)
        or isinstance(raw_result_count, bool)
        or not isinstance(raw_results, list)
        or raw_result_count != len(raw_results)
    ):
        errors.append(
            ExternalSearchResultValidationError(
                "merge_raw_result_count_mismatch",
                "merge_metadata.raw_result_count",
                "raw_result_count must match merged raw_results.",
            )
        )

    for field in (
        "dedupe_performed",
        "ranking_performed",
        "selection_performed",
        "summarization_performed",
        "domain_normalization_performed",
        "delivery_performed",
    ):
        if merge_metadata.get(field) is not False:
            errors.append(
                ExternalSearchResultValidationError(
                    "merge_derived_stage_not_allowed",
                    f"merge_metadata.{field}",
                    "bounded result-set merge must not perform derived stages.",
                )
            )

    skipped = merge_metadata.get("skipped_reasons")
    if skipped is not None and (
        not isinstance(skipped, list)
        or any(not isinstance(item, str) or not item.strip() for item in skipped)
    ):
        errors.append(
            ExternalSearchResultValidationError(
                "invalid_merge_skipped_reasons",
                "merge_metadata.skipped_reasons",
                "skipped_reasons must be a list of non-empty strings.",
            )
        )


def _validate_receipt_refs(
    value: Any,
    *,
    field: str,
    errors: list[ExternalSearchResultValidationError],
    required: bool,
) -> None:
    if value is None and not required:
        return
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        errors.append(
            ExternalSearchResultValidationError(
                "invalid_execution_receipt_refs",
                field,
                f"{field} must be a list of non-empty strings.",
            )
        )


def _empty_merged_external_search_result_set(
    *,
    search_id: str,
    limits: dict[str, int],
    skipped_reasons: tuple[str, ...],
) -> dict[str, Any]:
    return build_external_search_result_set(
        search_id=search_id,
        query="merged external search result sets",
        raw_results=[],
        source_refs=[],
        citations=[],
        rejected_raw_results=[],
        execution_receipt_refs=[],
        result_lineage=[],
        external_call_performed=False,
        cost_incurred=False,
        provenance=_merge_provenance(search_id, []),
        merge_metadata=_merge_metadata(
            limits=limits,
            input_records=[],
            raw_result_count=0,
            skipped_reasons=skipped_reasons,
        ),
    )


def _merge_provenance(
    search_id: str,
    execution_receipt_refs: list[str],
) -> dict[str, Any]:
    return {
        "search_id": _safe_string(search_id),
        "merge_performed": True,
        "merge_type": EXTERNAL_SEARCH_RESULT_SET_MERGE_TYPE,
        "merge_boundary": "runtime.artifacts.external_search",
        "bounded": True,
        "execution_receipt_refs": _unique_strings(execution_receipt_refs),
        "provider_integration_performed": False,
        "provider_selected": False,
        "provider_adapter_called": False,
        "browser_api_called": False,
        "cloud_model_called": False,
        "summarization_performed": False,
        "domain_normalization_performed": False,
        "ranking_performed": False,
        "selection_performed": False,
        "delivery_performed": False,
    }


def _merge_metadata(
    *,
    limits: dict[str, int],
    input_records: list[dict[str, Any]],
    raw_result_count: int,
    skipped_reasons: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "merge_type": EXTERNAL_SEARCH_RESULT_SET_MERGE_TYPE,
        "merge_boundary": "runtime.artifacts.external_search",
        "bounded": True,
        "limits": dict(limits),
        "input_result_sets": deepcopy(input_records),
        "input_result_set_count": len(input_records),
        "raw_result_count": raw_result_count,
        "merge_order": "input_order",
        "dedupe_performed": False,
        "ranking_performed": False,
        "selection_performed": False,
        "summarization_performed": False,
        "domain_normalization_performed": False,
        "delivery_performed": False,
        "skipped_reasons": _unique_strings(skipped_reasons),
    }


def _bounded_merge_limits(
    *,
    max_result_sets: int,
    max_results_per_set: int,
    max_total_results: int,
) -> dict[str, int]:
    default_limits = {
        "max_result_sets": DEFAULT_MERGE_MAX_RESULT_SETS,
        "max_results_per_set": DEFAULT_MERGE_MAX_RESULTS_PER_SET,
        "max_total_results": DEFAULT_MERGE_MAX_TOTAL_RESULTS,
    }
    requested_limits = {
        "max_result_sets": max_result_sets,
        "max_results_per_set": max_results_per_set,
        "max_total_results": max_total_results,
    }
    return {
        field: value if _positive_int(value) else default_limits[field]
        for field, value in requested_limits.items()
    }


def _deepcopy_object_prefix(value: Any, count: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [deepcopy(item) for item in value[:count] if isinstance(item, dict)]


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _unique_strings(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        clean = value.strip()
        if clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def _safe_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "DEFAULT_MERGE_MAX_RESULT_SETS",
    "DEFAULT_MERGE_MAX_RESULTS_PER_SET",
    "DEFAULT_MERGE_MAX_TOTAL_RESULTS",
    "EXTERNAL_SEARCH_RESULT_SET_ARTIFACT",
    "EXTERNAL_SEARCH_RESULT_SET_MERGE_TYPE",
    "ExternalSearchResultValidationError",
    "build_external_search_result_set",
    "merge_external_search_result_sets",
    "validate_external_search_result_set",
]
