from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


EXACT_ENTITY_LOOKUP_CONTRACTS_PATH = Path(
    "agents/shared/semantics/exact_entity_lookup_contracts.json"
)
ALLOWED_LOOKUP_TYPES = {"exact_entity_lookup"}
REQUIRED_INPUTS = {"entity_name"}
OPTIONAL_INPUTS = {"entity_type", "workflow_topic", "source_scope"}
FORBIDDEN_BEHAVIORS = {
    "fuzzy_search",
    "keyword_search",
    "semantic_search",
    "ranking",
    "embeddings",
    "indexing",
    "hidden_rag",
    "heuristic_routing",
    "autonomous_retrieval",
    "writes",
}
FORBIDDEN_TELEMETRY_FIELDS = {
    "entity_name",
    "query",
    "lookup_value",
    "record_contents",
    "rendered_context",
    "raw_source_target",
    "raw_database_path",
}


class ExactEntityLookupRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExactEntityLookupContract:
    id: str
    operation_id: str
    lookup_type: str
    enabled: bool
    required_inputs: tuple[str, ...]
    optional_inputs: tuple[str, ...]
    bounded_source_reference: dict[str, Any]
    result_expectations: dict[str, Any]
    forbidden_behaviors: tuple[str, ...]
    fail_closed: dict[str, bool]
    telemetry_safe_provenance_fields: tuple[str, ...]
    telemetry_forbidden_fields: tuple[str, ...]
    raw_data: dict[str, Any]


@dataclass(frozen=True)
class ExactEntityLookupValidationError:
    error_code: str
    field: str
    message: str


def _registry_path(root: str | Path | None = None) -> Path:
    if root is None:
        return EXACT_ENTITY_LOOKUP_CONTRACTS_PATH

    return Path(root) / EXACT_ENTITY_LOOKUP_CONTRACTS_PATH


def _require_string(
    entry: dict[str, Any],
    key: str,
    *,
    entry_id: str,
) -> str:
    value = entry.get(key)

    if not isinstance(value, str) or not value.strip():
        raise ExactEntityLookupRegistryError(
            f"Exact entity lookup contract '{entry_id}' field '{key}' "
            "must be a non-empty string."
        )

    return value.strip()


def _require_bool(
    entry: dict[str, Any],
    key: str,
    *,
    entry_id: str,
) -> bool:
    value = entry.get(key)

    if not isinstance(value, bool):
        raise ExactEntityLookupRegistryError(
            f"Exact entity lookup contract '{entry_id}' field '{key}' "
            "must be a boolean."
        )

    return value


def _require_string_list(
    entry: dict[str, Any],
    key: str,
    *,
    entry_id: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    value = entry.get(key)

    if not isinstance(value, list) or (
        not allow_empty and not value
    ) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ExactEntityLookupRegistryError(
            f"Exact entity lookup contract '{entry_id}' field '{key}' "
            "must be a list of non-empty strings."
        )

    return tuple(item.strip() for item in value)


def _require_object(
    entry: dict[str, Any],
    key: str,
    *,
    entry_id: str,
) -> dict[str, Any]:
    value = entry.get(key)

    if not isinstance(value, dict):
        raise ExactEntityLookupRegistryError(
            f"Exact entity lookup contract '{entry_id}' field '{key}' "
            "must be an object."
        )

    return dict(value)


def _contract_from_entry(entry: Any) -> ExactEntityLookupContract:
    if not isinstance(entry, dict):
        raise ExactEntityLookupRegistryError(
            "Exact entity lookup contract entries must be objects."
        )

    entry_id = _require_string(entry, "id", entry_id="<unknown>")
    operation_id = _require_string(entry, "operation_id", entry_id=entry_id)
    lookup_type = _require_string(entry, "lookup_type", entry_id=entry_id)

    if operation_id != "exact_entity_lookup":
        raise ExactEntityLookupRegistryError(
            f"Exact entity lookup contract '{entry_id}' uses unsupported "
            f"operation_id '{operation_id}'."
        )

    if lookup_type not in ALLOWED_LOOKUP_TYPES:
        raise ExactEntityLookupRegistryError(
            f"Exact entity lookup contract '{entry_id}' uses unsupported "
            f"lookup_type '{lookup_type}'."
        )

    inputs = _require_object(entry, "inputs", entry_id=entry_id)
    required_inputs = _require_string_list(
        inputs,
        "required",
        entry_id=entry_id,
    )
    optional_inputs = _require_string_list(
        inputs,
        "optional",
        entry_id=entry_id,
        allow_empty=True,
    )

    if set(required_inputs) != REQUIRED_INPUTS:
        raise ExactEntityLookupRegistryError(
            f"Exact entity lookup contract '{entry_id}' must require "
            f"{sorted(REQUIRED_INPUTS)}."
        )

    if not set(optional_inputs).issubset(OPTIONAL_INPUTS):
        raise ExactEntityLookupRegistryError(
            f"Exact entity lookup contract '{entry_id}' has unsupported "
            "optional inputs."
        )

    source_reference = _require_object(
        entry,
        "bounded_source_reference",
        entry_id=entry_id,
    )
    if source_reference.get("raw_target_allowed") is not False:
        raise ExactEntityLookupRegistryError(
            f"Exact entity lookup contract '{entry_id}' must disallow raw "
            "source targets."
        )

    result_expectations = _require_object(
        entry,
        "result_expectations",
        entry_id=entry_id,
    )
    if result_expectations.get("max_records") != 1:
        raise ExactEntityLookupRegistryError(
            f"Exact entity lookup contract '{entry_id}' must be bounded to "
            "max_records=1."
        )
    if result_expectations.get("match_mode") != "exact_name_only":
        raise ExactEntityLookupRegistryError(
            f"Exact entity lookup contract '{entry_id}' must use "
            "match_mode='exact_name_only'."
        )

    forbidden_behaviors = _require_string_list(
        entry,
        "forbidden_behaviors",
        entry_id=entry_id,
    )
    if not FORBIDDEN_BEHAVIORS.issubset(set(forbidden_behaviors)):
        raise ExactEntityLookupRegistryError(
            f"Exact entity lookup contract '{entry_id}' does not forbid all "
            "unsupported lookup behaviors."
        )

    fail_closed = _require_object(entry, "fail_closed", entry_id=entry_id)
    if any(value is not True for value in fail_closed.values()):
        raise ExactEntityLookupRegistryError(
            f"Exact entity lookup contract '{entry_id}' fail_closed values "
            "must all be true."
        )

    safe_fields = _require_string_list(
        entry,
        "telemetry_safe_provenance_fields",
        entry_id=entry_id,
    )
    forbidden_fields = _require_string_list(
        entry,
        "telemetry_forbidden_fields",
        entry_id=entry_id,
    )
    if FORBIDDEN_TELEMETRY_FIELDS & set(safe_fields):
        raise ExactEntityLookupRegistryError(
            f"Exact entity lookup contract '{entry_id}' exposes forbidden "
            "telemetry fields as safe."
        )
    if not FORBIDDEN_TELEMETRY_FIELDS.issubset(set(forbidden_fields)):
        raise ExactEntityLookupRegistryError(
            f"Exact entity lookup contract '{entry_id}' must explicitly "
            "forbid private telemetry fields."
        )

    return ExactEntityLookupContract(
        id=entry_id,
        operation_id=operation_id,
        lookup_type=lookup_type,
        enabled=_require_bool(entry, "enabled", entry_id=entry_id),
        required_inputs=required_inputs,
        optional_inputs=optional_inputs,
        bounded_source_reference=source_reference,
        result_expectations=result_expectations,
        forbidden_behaviors=forbidden_behaviors,
        fail_closed={key: bool(value) for key, value in fail_closed.items()},
        telemetry_safe_provenance_fields=safe_fields,
        telemetry_forbidden_fields=forbidden_fields,
        raw_data=dict(entry),
    )


def _load_registry_strict(
    root: str | Path | None = None,
) -> tuple[ExactEntityLookupContract, ...]:
    data = json.loads(_registry_path(root).read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        raise ExactEntityLookupRegistryError(
            "Exact entity lookup registry must be an object."
        )

    if data.get("version") != 1:
        raise ExactEntityLookupRegistryError(
            "Exact entity lookup registry version must be 1."
        )

    contracts = data.get("contracts")
    if not isinstance(contracts, list):
        raise ExactEntityLookupRegistryError(
            "Exact entity lookup registry 'contracts' must be a list."
        )

    loaded = tuple(_contract_from_entry(entry) for entry in contracts)
    ids = [contract.id for contract in loaded]
    if len(ids) != len(set(ids)):
        raise ExactEntityLookupRegistryError(
            "Exact entity lookup registry contains duplicate contract IDs."
        )

    return loaded


@lru_cache(maxsize=None)
def load_exact_entity_lookup_contracts(
    root: str | Path | None = None,
) -> tuple[ExactEntityLookupContract, ...]:
    try:
        return _load_registry_strict(root)
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        ExactEntityLookupRegistryError,
    ):
        return ()


def get_exact_entity_lookup_contract(
    lookup_type: str,
    *,
    root: str | Path | None = None,
) -> ExactEntityLookupContract | None:
    normalized = str(lookup_type or "").strip()
    if not normalized:
        return None

    for contract in load_exact_entity_lookup_contracts(root):
        if contract.lookup_type == normalized:
            return contract

    return None


def validate_exact_entity_lookup_request(
    request: dict[str, Any],
    *,
    root: str | Path | None = None,
) -> list[ExactEntityLookupValidationError]:
    errors: list[ExactEntityLookupValidationError] = []

    if not isinstance(request, dict):
        return [
            ExactEntityLookupValidationError(
                error_code="invalid_exact_entity_lookup_request",
                field="request",
                message="request must be an object.",
            )
        ]

    lookup_type = request.get("lookup_type")
    if not isinstance(lookup_type, str) or not lookup_type.strip():
        errors.append(
            ExactEntityLookupValidationError(
                error_code="invalid_exact_entity_lookup_request",
                field="lookup_type",
                message="lookup_type must be a non-empty string.",
            )
        )
        return errors

    contract = get_exact_entity_lookup_contract(lookup_type, root=root)
    if contract is None:
        return [
            ExactEntityLookupValidationError(
                error_code="unknown_exact_entity_lookup_type",
                field="lookup_type",
                message="lookup_type is not registered.",
            )
        ]

    entity_name = request.get("entity_name")
    if not isinstance(entity_name, str) or not entity_name.strip():
        errors.append(
            ExactEntityLookupValidationError(
                error_code="invalid_exact_entity_lookup_request",
                field="entity_name",
                message="entity_name must be a non-empty string.",
            )
        )

    allowed_inputs = set(contract.required_inputs) | set(
        contract.optional_inputs
    ) | {
        "lookup_type",
        "lookup_id",
        "lookup_lineage_id",
        "lookup_request_id",
        "lookup_execution_id",
        "lookup_packet_id",
        "lookup_render_id",
        "lookup_injection_id",
    }
    for key in request:
        if key not in allowed_inputs:
            errors.append(
                ExactEntityLookupValidationError(
                    error_code="invalid_exact_entity_lookup_request",
                    field=key,
                    message="field is not allowed by the lookup contract.",
                )
            )

    for optional_key in contract.optional_inputs:
        value = request.get(optional_key)
        if value is not None and not isinstance(value, str):
            errors.append(
                ExactEntityLookupValidationError(
                    error_code="invalid_exact_entity_lookup_request",
                    field=optional_key,
                    message=f"{optional_key} must be a string when present.",
                )
            )

    return errors


__all__ = [
    "ALLOWED_LOOKUP_TYPES",
    "EXACT_ENTITY_LOOKUP_CONTRACTS_PATH",
    "ExactEntityLookupContract",
    "ExactEntityLookupRegistryError",
    "ExactEntityLookupValidationError",
    "FORBIDDEN_BEHAVIORS",
    "FORBIDDEN_TELEMETRY_FIELDS",
    "OPTIONAL_INPUTS",
    "REQUIRED_INPUTS",
    "get_exact_entity_lookup_contract",
    "load_exact_entity_lookup_contracts",
    "validate_exact_entity_lookup_request",
]
