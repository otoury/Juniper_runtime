from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


EXTERNAL_RETRIEVAL_RESULT_LINEAGE_TYPE = "normalized_external_retrieval_result"
EXTERNAL_RETRIEVAL_NORMALIZATION_STAGE = "external_search_provider_response_normalization"
REQUIRED_LINEAGE_FLAGS = (
    "summarization_performed",
    "domain_normalization_performed",
    "ranking_performed",
    "selection_performed",
    "delivery_performed",
)


@dataclass(frozen=True)
class ExternalRetrievalLineageValidationError:
    error_code: str
    field: str
    message: str


def build_normalized_external_retrieval_result_lineage(
    *,
    provider_id: str,
    provider_result_id: str,
    raw_result_index: int,
    raw_result_ref: str,
    source_ref: dict[str, Any],
    citation_ref: dict[str, Any],
) -> dict[str, Any]:
    return {
        "lineage_type": EXTERNAL_RETRIEVAL_RESULT_LINEAGE_TYPE,
        "normalization_stage": EXTERNAL_RETRIEVAL_NORMALIZATION_STAGE,
        "provider_id": _safe_string(provider_id),
        "provider_result_id": _safe_string(provider_result_id),
        "raw_result_index": raw_result_index,
        "raw_result_ref": _safe_string(raw_result_ref),
        "source_ref": deepcopy(source_ref),
        "citation_ref": deepcopy(citation_ref),
        "normalization_steps": [
            "required_result_field_validation",
            "provider_field_whitelist_copy",
            "source_ref_materialization",
            "citation_materialization",
        ],
        "summarization_performed": False,
        "domain_normalization_performed": False,
        "ranking_performed": False,
        "selection_performed": False,
        "delivery_performed": False,
    }


def validate_normalized_external_retrieval_result_lineage(
    value: Any,
    *,
    field: str = "result_lineage",
    required: bool = False,
) -> tuple[ExternalRetrievalLineageValidationError, ...]:
    if value is None and not required:
        return ()
    if not isinstance(value, list):
        return (
            ExternalRetrievalLineageValidationError(
                "invalid_result_lineage",
                field,
                f"{field} must be a list of lineage objects.",
            ),
        )

    errors: list[ExternalRetrievalLineageValidationError] = []
    for index, item in enumerate(value):
        item_field = f"{field}[{index}]"
        if not isinstance(item, dict):
            errors.append(
                ExternalRetrievalLineageValidationError(
                    "invalid_lineage_item",
                    item_field,
                    "lineage item must be an object.",
                )
            )
            continue
        if item.get("lineage_type") != EXTERNAL_RETRIEVAL_RESULT_LINEAGE_TYPE:
            errors.append(
                ExternalRetrievalLineageValidationError(
                    "invalid_lineage_type",
                    f"{item_field}.lineage_type",
                    "lineage_type must identify normalized external retrieval results.",
                )
            )
        if item.get("normalization_stage") != EXTERNAL_RETRIEVAL_NORMALIZATION_STAGE:
            errors.append(
                ExternalRetrievalLineageValidationError(
                    "invalid_normalization_stage",
                    f"{item_field}.normalization_stage",
                    "normalization_stage must identify the provider response normalizer.",
                )
            )
        for string_field in (
            "provider_id",
            "provider_result_id",
            "raw_result_ref",
        ):
            if not _safe_string(item.get(string_field)):
                errors.append(
                    ExternalRetrievalLineageValidationError(
                        "missing_lineage_field",
                        f"{item_field}.{string_field}",
                        f"{string_field} must be a non-empty string.",
                    )
                )
        raw_result_index = item.get("raw_result_index")
        if (
            not isinstance(raw_result_index, int)
            or isinstance(raw_result_index, bool)
            or raw_result_index < 0
        ):
            errors.append(
                ExternalRetrievalLineageValidationError(
                    "invalid_raw_result_index",
                    f"{item_field}.raw_result_index",
                    "raw_result_index must be a non-negative integer.",
                )
            )
        for object_field in ("source_ref", "citation_ref"):
            if not isinstance(item.get(object_field), dict):
                errors.append(
                    ExternalRetrievalLineageValidationError(
                        "invalid_lineage_ref",
                        f"{item_field}.{object_field}",
                        f"{object_field} must be an object.",
                    )
                )
        steps = item.get("normalization_steps")
        if (
            not isinstance(steps, list)
            or not steps
            or any(not _safe_string(step) for step in steps)
        ):
            errors.append(
                ExternalRetrievalLineageValidationError(
                    "invalid_normalization_steps",
                    f"{item_field}.normalization_steps",
                    "normalization_steps must be a non-empty list of strings.",
                )
            )
        for flag in REQUIRED_LINEAGE_FLAGS:
            if item.get(flag) is not False:
                errors.append(
                    ExternalRetrievalLineageValidationError(
                        "derived_stage_flag_not_allowed",
                        f"{item_field}.{flag}",
                        "lineage must record derived-stage flags as false.",
                    )
                )
    return tuple(errors)


def _safe_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "EXTERNAL_RETRIEVAL_NORMALIZATION_STAGE",
    "EXTERNAL_RETRIEVAL_RESULT_LINEAGE_TYPE",
    "ExternalRetrievalLineageValidationError",
    "build_normalized_external_retrieval_result_lineage",
    "validate_normalized_external_retrieval_result_lineage",
]
