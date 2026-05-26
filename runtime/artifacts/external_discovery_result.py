from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from runtime.artifacts.external_discovery_execution_receipt import (
    validate_external_discovery_execution_receipt,
)


EXTERNAL_DISCOVERY_RESULT_SET_ARTIFACT = "external_discovery_result_set"
FORBIDDEN_NORMALIZED_TOP_LEVEL_FIELDS = (
    "candidate_count",
    "candidates",
    "guest_candidate_list",
    "guest_candidates",
    "normalized_candidates",
    "normalized_results",
    "ranking",
    "selected_candidate",
)
FORBIDDEN_EXECUTION_FIELDS = (
    "browser_api_called",
    "cloud_model_called",
    "delivery_performed",
    "discovery_executed",
    "external_adapter_called",
    "external_call_performed",
    "normalization_performed",
    "provider_executed",
    "provider_execution_performed",
    "ranking_performed",
    "search_api_called",
    "selection_performed",
    "web_search_executed",
)
SEMANTIC_AUTHORITY_BOUNDARY = {
    "planner_semantic_grounding": False,
    "runtime_semantic_grounding": False,
    "operation_selection": False,
    "artifact_type_selection": False,
    "capability_selection": False,
}


@dataclass(frozen=True)
class ExternalDiscoveryResultValidationError:
    error_code: str
    field: str
    message: str


def build_external_discovery_result_set(
    *,
    provider_metadata: dict[str, Any],
    raw_provider_payload: Any,
    raw_results: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    source_refs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    citations: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    rejected_raw_results: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safe_provider_metadata = deepcopy(provider_metadata)
    safe_provenance = _base_provenance(safe_provider_metadata)
    if isinstance(provenance, dict):
        safe_provenance.update(deepcopy(provenance))

    return {
        "artifact_type": EXTERNAL_DISCOVERY_RESULT_SET_ARTIFACT,
        "provider_metadata": safe_provider_metadata,
        "raw_provider_payload": deepcopy(raw_provider_payload),
        "raw_results": [deepcopy(item) for item in raw_results],
        "source_refs": [deepcopy(item) for item in source_refs],
        "citations": [deepcopy(item) for item in citations],
        "rejected_raw_results": [deepcopy(item) for item in rejected_raw_results],
        "provenance": safe_provenance,
        "semantic_authority": deepcopy(SEMANTIC_AUTHORITY_BOUNDARY),
    }


def validate_external_discovery_result_set(
    artifact: Any,
) -> tuple[ExternalDiscoveryResultValidationError, ...]:
    if not isinstance(artifact, dict):
        return (
            ExternalDiscoveryResultValidationError(
                "invalid_external_discovery_result_artifact",
                "artifact",
                "external discovery result artifact must be an object.",
            ),
        )

    errors: list[ExternalDiscoveryResultValidationError] = []

    if artifact.get("artifact_type") != EXTERNAL_DISCOVERY_RESULT_SET_ARTIFACT:
        errors.append(
            ExternalDiscoveryResultValidationError(
                "invalid_artifact_type",
                "artifact_type",
                "artifact_type must be external_discovery_result_set.",
            )
        )

    _validate_no_top_level_normalized_fields(artifact, errors=errors)
    _validate_provider_metadata(artifact.get("provider_metadata"), errors=errors)
    empty_result_payload_allowed = (
        _is_non_executed_artifact(artifact)
        and not _external_call_performed(artifact)
    )
    _validate_object_list(
        artifact.get("raw_results"),
        field="raw_results",
        required=not empty_result_payload_allowed,
        errors=errors,
    )
    _validate_object_list(
        artifact.get("source_refs"),
        field="source_refs",
        required=not empty_result_payload_allowed,
        errors=errors,
    )
    _validate_object_list(
        artifact.get("citations"),
        field="citations",
        required=not empty_result_payload_allowed,
        errors=errors,
    )
    _validate_object_list(
        artifact.get("rejected_raw_results"),
        field="rejected_raw_results",
        required=False,
        errors=errors,
    )
    _validate_live_accepted_result_sources(artifact, errors=errors)
    if "raw_provider_payload" not in artifact:
        errors.append(
            ExternalDiscoveryResultValidationError(
                "missing_raw_provider_payload",
                "raw_provider_payload",
                "raw_provider_payload must be present to preserve raw output.",
            )
        )
    _validate_provenance(artifact.get("provenance"), errors=errors)
    _validate_embedded_execution_receipt(
        artifact.get("provider_metadata"),
        errors=errors,
    )

    return tuple(errors)


def _base_provenance(provider_metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider_id": _safe_string(provider_metadata.get("provider_id")),
        "provider_type": _safe_string(provider_metadata.get("provider_type")),
        "raw_external_result": True,
        "provider_execution_performed": False,
        "provider_executed": False,
        "web_search_executed": False,
        "search_api_called": False,
        "browser_api_called": False,
        "cloud_model_called": False,
        "external_adapter_called": False,
        "external_call_performed": False,
        "cost_incurred": False,
        "discovery_executed": False,
        "normalization_performed": False,
        "ranking_performed": False,
        "selection_performed": False,
        "delivery_performed": False,
    }


def _validate_no_top_level_normalized_fields(
    artifact: dict[str, Any],
    *,
    errors: list[ExternalDiscoveryResultValidationError],
) -> None:
    for field in FORBIDDEN_NORMALIZED_TOP_LEVEL_FIELDS:
        if field in artifact:
            errors.append(
                ExternalDiscoveryResultValidationError(
                    "normalized_field_not_allowed",
                    field,
                    "raw external discovery results must not include normalized candidate fields.",
                )
            )


def _validate_provider_metadata(
    value: Any,
    *,
    errors: list[ExternalDiscoveryResultValidationError],
) -> None:
    if not isinstance(value, dict):
        errors.append(
            ExternalDiscoveryResultValidationError(
                "invalid_provider_metadata",
                "provider_metadata",
                "provider_metadata must be an object.",
            )
        )
        return

    for field in ("provider_id", "provider_type"):
        if not _safe_string(value.get(field)):
            errors.append(
                ExternalDiscoveryResultValidationError(
                    "missing_provider_metadata_field",
                    f"provider_metadata.{field}",
                    f"provider_metadata.{field} must be a non-empty string.",
                )
            )


def _validate_object_list(
    value: Any,
    *,
    field: str,
    required: bool,
    errors: list[ExternalDiscoveryResultValidationError],
) -> None:
    if value is None and not required:
        return
    if (
        not isinstance(value, list)
        or (required and not value)
        or any(not isinstance(item, dict) for item in value)
    ):
        errors.append(
            ExternalDiscoveryResultValidationError(
                "invalid_object_list",
                field,
                f"{field} must be a non-empty list of objects.",
            )
        )


def _validate_live_accepted_result_sources(
    artifact: dict[str, Any],
    *,
    errors: list[ExternalDiscoveryResultValidationError],
) -> None:
    if not _external_call_performed(artifact):
        return

    raw_results = artifact.get("raw_results")
    source_refs = artifact.get("source_refs")
    citations = artifact.get("citations")
    if not (
        isinstance(raw_results, list)
        and isinstance(source_refs, list)
        and isinstance(citations, list)
    ):
        return

    source_result_ids = _provider_result_ids(source_refs)
    citation_result_ids = _provider_result_ids(citations)
    for index, raw_result in enumerate(raw_results):
        if not isinstance(raw_result, dict):
            continue
        provider_result_id = _safe_string(raw_result.get("provider_result_id"))
        if provider_result_id is None:
            errors.append(
                ExternalDiscoveryResultValidationError(
                    "missing_provider_result_id",
                    f"raw_results[{index}].provider_result_id",
                    "live accepted raw results must include provider_result_id.",
                )
            )
            continue
        if provider_result_id not in source_result_ids:
            errors.append(
                ExternalDiscoveryResultValidationError(
                    "accepted_result_missing_source_ref",
                    f"raw_results[{index}].source_refs",
                    "live accepted raw results must have matching source_refs.",
                )
            )
        if provider_result_id not in citation_result_ids:
            errors.append(
                ExternalDiscoveryResultValidationError(
                    "accepted_result_missing_citation",
                    f"raw_results[{index}].citations",
                    "live accepted raw results must have matching citations.",
                )
            )


def _validate_provenance(
    value: Any,
    *,
    errors: list[ExternalDiscoveryResultValidationError],
) -> None:
    if not isinstance(value, dict):
        errors.append(
            ExternalDiscoveryResultValidationError(
                "invalid_provenance",
                "provenance",
                "provenance must be an object.",
            )
        )
        return

    if value.get("raw_external_result") is not True:
        errors.append(
            ExternalDiscoveryResultValidationError(
                "missing_raw_external_result_provenance",
                "provenance.raw_external_result",
                "provenance must mark the artifact as a raw external result.",
            )
        )

    live_raw_execution = _is_live_raw_execution_provenance(value)
    allowed_live_fields = (
        "external_call_performed",
        "discovery_executed",
        "provider_call_implemented",
    )

    for field in FORBIDDEN_EXECUTION_FIELDS:
        if live_raw_execution and field in allowed_live_fields:
            continue
        if value.get(field) is not False:
            errors.append(
                ExternalDiscoveryResultValidationError(
                    "external_discovery_execution_not_allowed",
                    f"provenance.{field}",
                    "raw external discovery result artifacts must not claim runtime execution, normalization, or delivery.",
                )
            )

    if value.get("cost_incurred") is not False and not live_raw_execution:
        errors.append(
            ExternalDiscoveryResultValidationError(
                "external_discovery_cost_not_allowed",
                "provenance.cost_incurred",
                "raw external discovery result artifacts must not record incurred cost.",
            )
        )


def _validate_embedded_execution_receipt(
    provider_metadata: Any,
    *,
    errors: list[ExternalDiscoveryResultValidationError],
) -> None:
    if not isinstance(provider_metadata, dict):
        return
    if "execution_receipt" not in provider_metadata:
        return

    receipt_errors = validate_external_discovery_execution_receipt(
        provider_metadata.get("execution_receipt")
    )
    for receipt_error in receipt_errors:
        errors.append(
            ExternalDiscoveryResultValidationError(
                receipt_error.error_code,
                f"provider_metadata.execution_receipt.{receipt_error.field}",
                receipt_error.message,
            )
        )


def _is_non_executed_artifact(artifact: dict[str, Any]) -> bool:
    provider_metadata = artifact.get("provider_metadata")
    provenance = artifact.get("provenance")
    live_adapter_failed = (
        isinstance(provider_metadata, dict)
        and isinstance(provenance, dict)
        and provider_metadata.get("execution_state") == "live_adapter_failed"
        and provenance.get("execution_state") == "live_adapter_failed"
    )
    return (
        isinstance(provider_metadata, dict)
        and (
            provider_metadata.get("dry_run") is True
            or provider_metadata.get("provider_call_implemented") is False
            or live_adapter_failed
        )
        and isinstance(provenance, dict)
        and (
            provenance.get("dry_run") is True
            or provenance.get("provider_call_implemented") is False
            or live_adapter_failed
        )
        and (live_adapter_failed or provenance.get("cost_incurred") is False)
    )


def _is_live_raw_execution_provenance(provenance: dict[str, Any]) -> bool:
    return (
        provenance.get("dry_run") is False
        and provenance.get("live_authorized") is True
        and provenance.get("provider_call_implemented") is True
        and provenance.get("execution_state")
        in {"live_adapter_executed", "live_adapter_failed"}
        and provenance.get("normalization_performed") is False
        and provenance.get("ranking_performed") is False
        and provenance.get("selection_performed") is False
        and provenance.get("delivery_performed") is False
    )


def _external_call_performed(artifact: dict[str, Any]) -> bool:
    provider_metadata = artifact.get("provider_metadata")
    provenance = artifact.get("provenance")
    return (
        isinstance(provider_metadata, dict)
        and provider_metadata.get("external_call_performed") is True
    ) or (
        isinstance(provenance, dict)
        and provenance.get("external_call_performed") is True
    )


def _provider_result_ids(items: list[Any]) -> set[str]:
    result_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        provider_result_id = _safe_string(item.get("provider_result_id"))
        if provider_result_id is not None:
            result_ids.add(provider_result_id)
    return result_ids


def _safe_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "EXTERNAL_DISCOVERY_RESULT_SET_ARTIFACT",
    "ExternalDiscoveryResultValidationError",
    "build_external_discovery_result_set",
    "validate_external_discovery_result_set",
]
