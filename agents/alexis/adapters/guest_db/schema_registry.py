from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


GUEST_DB_SCHEMA_PATH = Path("agents/alexis/adapters/guest_db/schema.json")
SUPPORTED_FIELD_TYPES = {"string"}
REQUIRED_FIELD_NAMES = {"guest_id", "display_name"}


class GuestDbSchemaRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class GuestDbField:
    name: str
    type: str
    required: bool
    raw_data: dict[str, Any]


@dataclass(frozen=True)
class GuestDbSchema:
    version: int
    fields: tuple[GuestDbField, ...]
    raw_data: dict[str, Any]

    def field_names(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields)

    def required_field_names(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields if field.required)


def _schema_path(root: str | Path | None = None) -> Path:
    if root is None:
        return GUEST_DB_SCHEMA_PATH

    return Path(root) / GUEST_DB_SCHEMA_PATH


def _require_string(
    entry: dict[str, Any],
    key: str,
    *,
    field_name: str,
) -> str:
    value = entry.get(key)

    if not isinstance(value, str) or not value.strip():
        raise GuestDbSchemaRegistryError(
            f"Guest DB schema field '{field_name}' key '{key}' must be "
            "a non-empty string."
        )

    return value.strip()


def _require_bool(
    entry: dict[str, Any],
    key: str,
    *,
    field_name: str,
) -> bool:
    value = entry.get(key)

    if not isinstance(value, bool):
        raise GuestDbSchemaRegistryError(
            f"Guest DB schema field '{field_name}' key '{key}' must be "
            "a boolean."
        )

    return value


def _field_from_entry(entry: Any) -> GuestDbField:
    if not isinstance(entry, dict):
        raise GuestDbSchemaRegistryError(
            "Guest DB schema fields must be objects."
        )

    name = _require_string(entry, "name", field_name="<unknown>")
    field_type = _require_string(entry, "type", field_name=name)

    if field_type not in SUPPORTED_FIELD_TYPES:
        raise GuestDbSchemaRegistryError(
            f"Guest DB schema field '{name}' uses unsupported type "
            f"'{field_type}'."
        )

    return GuestDbField(
        name=name,
        type=field_type,
        required=_require_bool(entry, "required", field_name=name),
        raw_data=dict(entry),
    )


def _validate_fields(fields: tuple[GuestDbField, ...]) -> None:
    names = [field.name for field in fields]
    duplicate_names = sorted({
        name for name in names if names.count(name) > 1
    })

    if duplicate_names:
        raise GuestDbSchemaRegistryError(
            "Guest DB schema field names must be unique: "
            f"{', '.join(duplicate_names)}"
        )

    required_names = {
        field.name for field in fields if field.required
    }
    missing_required = sorted(REQUIRED_FIELD_NAMES - required_names)

    if missing_required:
        raise GuestDbSchemaRegistryError(
            "Guest DB schema missing required fields: "
            f"{', '.join(missing_required)}"
        )


def load_guest_db_schema_strict(
    root: str | Path | None = None,
) -> GuestDbSchema:
    path = _schema_path(root)
    data = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        raise GuestDbSchemaRegistryError(
            "Guest DB schema must be an object."
        )

    if data.get("version") != 1:
        raise GuestDbSchemaRegistryError(
            "Guest DB schema version must be 1."
        )

    raw_fields = data.get("fields")
    if not isinstance(raw_fields, list) or not raw_fields:
        raise GuestDbSchemaRegistryError(
            "Guest DB schema 'fields' must be a non-empty list."
        )

    fields = tuple(_field_from_entry(entry) for entry in raw_fields)
    _validate_fields(fields)

    return GuestDbSchema(
        version=1,
        fields=fields,
        raw_data=dict(data),
    )


@lru_cache(maxsize=None)
def load_guest_db_schema(
    root: str | Path | None = None,
) -> GuestDbSchema | None:
    try:
        return load_guest_db_schema_strict(root)
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        GuestDbSchemaRegistryError,
    ):
        return None


def list_guest_db_schema_fields(
    root: str | Path | None = None,
) -> list[GuestDbField]:
    schema = load_guest_db_schema(root)

    if schema is None:
        return []

    return list(schema.fields)


__all__ = [
    "GUEST_DB_SCHEMA_PATH",
    "GuestDbField",
    "GuestDbSchema",
    "GuestDbSchemaRegistryError",
    "list_guest_db_schema_fields",
    "load_guest_db_schema",
    "load_guest_db_schema_strict",
]
