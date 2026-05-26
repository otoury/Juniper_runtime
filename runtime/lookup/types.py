from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ALLOWED_BOUNDED_LOOKUP_MODES = {
    "declared_fixture",
    "fixed_id",
}
SUPPORTED_LOOKUP_KEYS = {
    "entity_id",
}


@dataclass(frozen=True)
class BoundedLookupValidationError:
    error_code: str
    field: str
    message: str


@dataclass(frozen=True)
class BoundedLookupRequest:
    lookup_id: str
    source_contract_id: str
    lookup_mode: str
    query: str | None
    lookup_key: str | None
    lookup_value: str | None
    max_records: int


@dataclass(frozen=True)
class BoundedLookupResult:
    lookup_id: str
    source_contract_id: str
    records: list[dict[str, Any]]
    retrieval_executed: bool
    skipped_reasons: list[str] = field(default_factory=list)


def _non_empty_string_error(
    value: Any,
    *,
    field_name: str,
) -> BoundedLookupValidationError | None:
    if isinstance(value, str) and value.strip():
        return None

    return BoundedLookupValidationError(
        error_code="invalid_bounded_lookup_contract",
        field=field_name,
        message=f"{field_name} must be a non-empty string.",
    )


def validate_bounded_lookup_request(
    request: BoundedLookupRequest,
) -> list[BoundedLookupValidationError]:
    errors: list[BoundedLookupValidationError] = []

    for field_name in ("lookup_id", "source_contract_id"):
        error = _non_empty_string_error(
            getattr(request, field_name),
            field_name=field_name,
        )
        if error is not None:
            errors.append(error)

    if request.lookup_mode not in ALLOWED_BOUNDED_LOOKUP_MODES:
        errors.append(
            BoundedLookupValidationError(
                error_code="invalid_bounded_lookup_contract",
                field="lookup_mode",
                message=(
                    "lookup_mode must be one of: "
                    f"{sorted(ALLOWED_BOUNDED_LOOKUP_MODES)}"
                ),
            )
        )

    if (
        not isinstance(request.max_records, int)
        or isinstance(request.max_records, bool)
        or request.max_records != 1
    ):
        errors.append(
            BoundedLookupValidationError(
                error_code="invalid_bounded_lookup_contract",
                field="max_records",
                message="max_records must be the integer 1.",
            )
        )

    if request.query is not None and not isinstance(request.query, str):
        errors.append(
            BoundedLookupValidationError(
                error_code="invalid_bounded_lookup_contract",
                field="query",
                message="query must be a string or None.",
            )
        )

    if (
        request.lookup_key is not None
        and request.lookup_key not in SUPPORTED_LOOKUP_KEYS
    ):
        errors.append(
            BoundedLookupValidationError(
                error_code="invalid_bounded_lookup_contract",
                field="lookup_key",
                message=(
                    "lookup_key must be one of: "
                    f"{sorted(SUPPORTED_LOOKUP_KEYS)}"
                ),
            )
        )

    if request.lookup_value is not None and not isinstance(
        request.lookup_value,
        str,
    ):
        errors.append(
            BoundedLookupValidationError(
                error_code="invalid_bounded_lookup_contract",
                field="lookup_value",
                message="lookup_value must be a string or None.",
            )
        )

    if request.lookup_mode == "fixed_id":
        if request.lookup_key != "entity_id":
            errors.append(
                BoundedLookupValidationError(
                    error_code="invalid_bounded_lookup_contract",
                    field="lookup_key",
                    message="fixed_id lookup requires lookup_key='entity_id'.",
                )
            )

        if (
            not isinstance(request.lookup_value, str)
            or not request.lookup_value.strip()
        ):
            errors.append(
                BoundedLookupValidationError(
                    error_code="invalid_bounded_lookup_contract",
                    field="lookup_value",
                    message="fixed_id lookup requires a non-empty lookup_value.",
                )
            )

    return errors


def validate_bounded_lookup_result(
    result: BoundedLookupResult,
) -> list[BoundedLookupValidationError]:
    errors: list[BoundedLookupValidationError] = []

    for field_name in ("lookup_id", "source_contract_id"):
        error = _non_empty_string_error(
            getattr(result, field_name),
            field_name=field_name,
        )
        if error is not None:
            errors.append(error)

    if not isinstance(result.records, list):
        errors.append(
            BoundedLookupValidationError(
                error_code="invalid_bounded_lookup_contract",
                field="records",
                message="records must be a list.",
            )
        )

    if not isinstance(result.retrieval_executed, bool):
        errors.append(
            BoundedLookupValidationError(
                error_code="invalid_bounded_lookup_contract",
                field="retrieval_executed",
                message="retrieval_executed must be a boolean.",
            )
        )

    if (
        not isinstance(result.skipped_reasons, list)
        or any(
            not isinstance(reason, str)
            for reason in result.skipped_reasons
        )
    ):
        errors.append(
            BoundedLookupValidationError(
                error_code="invalid_bounded_lookup_contract",
                field="skipped_reasons",
                message="skipped_reasons must be a list of strings.",
            )
        )

    return errors


__all__ = [
    "ALLOWED_BOUNDED_LOOKUP_MODES",
    "BoundedLookupRequest",
    "BoundedLookupResult",
    "BoundedLookupValidationError",
    "SUPPORTED_LOOKUP_KEYS",
    "validate_bounded_lookup_request",
    "validate_bounded_lookup_result",
]
