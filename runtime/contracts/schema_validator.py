# contracts/schema_validator.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SchemaValidationResult:
    ok: bool
    errors: list[str]


def validate_object_schema(
    *,
    payload: Any,
    schema: dict,
) -> SchemaValidationResult:
    errors = []

    if not schema:
        return SchemaValidationResult(ok=True, errors=[])

    if schema.get("type") != "object":
        return SchemaValidationResult(
            ok=False,
            errors=["Only object schemas are supported."],
        )

    if not isinstance(payload, dict):
        return SchemaValidationResult(
            ok=False,
            errors=["Payload is not a JSON object."],
        )

    required = schema.get("required", [])
    properties = schema.get("properties", {})

    for field in required:
        if field not in payload:
            errors.append(f"Missing required field: {field}")

    if schema.get("additionalProperties") is False:
        allowed = set(properties.keys())

        for field in payload:
            if field not in allowed:
                errors.append(f"Unexpected field: {field}")

    for field, field_schema in properties.items():
        if field not in payload:
            continue

        value = payload[field]

        expected_type = field_schema.get("type")

        if expected_type == "string" and not isinstance(value, str):
            errors.append(f"{field} must be a string")
            continue

        if "const" in field_schema and value != field_schema["const"]:
            errors.append(
                f"{field} must equal {field_schema['const']!r}"
            )

        if isinstance(value, str):
            if field_schema.get("single_line") and "\n" in value:
                errors.append(f"{field} must be single line")

            max_words = field_schema.get("max_words")

            if max_words and len(value.split()) > int(max_words):
                errors.append(
                    f"{field} exceeds {max_words} words"
                )

    return SchemaValidationResult(
        ok=not errors,
        errors=errors,
    )
