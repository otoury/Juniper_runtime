from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agents.alexis.adapters.guest_db.schema_registry import (
    GuestDbSchema,
    load_guest_db_schema,
)


@dataclass(frozen=True)
class GuestDbRecordValidationError:
    error_code: str
    field_name: str | None
    message: str


@dataclass(frozen=True)
class GuestDbRecordValidationResult:
    ok: bool
    errors: tuple[GuestDbRecordValidationError, ...] = ()


def _error(
    error_code: str,
    message: str,
    *,
    field_name: str | None = None,
) -> GuestDbRecordValidationError:
    return GuestDbRecordValidationError(
        error_code=error_code,
        field_name=field_name,
        message=message,
    )


def validate_guest_record(
    record: Any,
    schema: GuestDbSchema | None = None,
) -> GuestDbRecordValidationResult:
    active_schema = schema if schema is not None else load_guest_db_schema()

    if active_schema is None or not active_schema.fields:
        return GuestDbRecordValidationResult(
            ok=False,
            errors=(
                _error(
                    "schema_unavailable",
                    "Guest DB schema is unavailable or invalid.",
                ),
            ),
        )

    if not isinstance(record, dict):
        return GuestDbRecordValidationResult(
            ok=False,
            errors=(
                _error(
                    "record_not_object",
                    "Guest DB record must be an object.",
                ),
            ),
        )

    errors: list[GuestDbRecordValidationError] = []

    for field in active_schema.fields:
        if field.name not in record:
            if field.required:
                errors.append(
                    _error(
                        "required_field_missing",
                        "Required guest DB field is missing.",
                        field_name=field.name,
                    )
                )
            continue

        value = record[field.name]

        if field.type == "string":
            if not isinstance(value, str):
                errors.append(
                    _error(
                        "field_type_invalid",
                        "Guest DB field must be a string.",
                        field_name=field.name,
                    )
                )
                continue

            if field.required and not value.strip():
                errors.append(
                    _error(
                        "required_string_empty",
                        "Required guest DB string field must be non-empty.",
                        field_name=field.name,
                    )
                )

    return GuestDbRecordValidationResult(
        ok=not errors,
        errors=tuple(errors),
    )


__all__ = [
    "GuestDbRecordValidationError",
    "GuestDbRecordValidationResult",
    "validate_guest_record",
]
