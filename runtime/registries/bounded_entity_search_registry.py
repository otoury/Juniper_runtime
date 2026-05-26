from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


BOUNDED_ENTITY_SEARCH_CONTRACTS_PATH = Path(
    "agents/shared/semantics/bounded_entity_search_contracts.json"
)
ALLOWED_SEARCH_TYPES = {"bounded_entity_search"}
REQUIRED_ANY_INPUTS = {"search_topic", "query_intent"}
OPTIONAL_INPUTS = {"entity_type", "constraints", "max_results"}
FORBIDDEN_PLANNER_FIELDS = {
    "source_scope",
    "raw_source_target",
    "adapter_id",
    "datasource_path",
}
FORBIDDEN_BEHAVIORS = {
    "fuzzy_matching",
    "semantic_search_execution",
    "ranking",
    "scoring",
    "embeddings",
    "indexing",
    "hidden_rag",
    "heuristic_routing",
    "autonomous_retrieval",
    "prompt_injection",
    "writes",
}
FORBIDDEN_TELEMETRY_FIELDS = {
    "search_topic",
    "query_intent",
    "constraints",
    "record_contents",
    "rendered_context",
    "raw_source_target",
    "raw_database_path",
    "datasource_path",
}


class BoundedEntitySearchRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class BoundedEntitySearchContract:
    id: str
    operation_id: str
    lookup_type: str
    enabled: bool
    required_any_inputs: tuple[str, ...]
    optional_inputs: tuple[str, ...]
    agent_policy_fields_forbidden: tuple[str, ...]
    bounded_source_reference: dict[str, Any]
    result_expectations: dict[str, Any]
    forbidden_behaviors: tuple[str, ...]
    fail_closed: dict[str, bool]
    telemetry_safe_provenance_fields: tuple[str, ...]
    telemetry_forbidden_fields: tuple[str, ...]
    raw_data: dict[str, Any]


@dataclass(frozen=True)
class BoundedEntitySearchValidationError:
    error_code: str
    field: str
    message: str


def _registry_path(root: str | Path | None = None) -> Path:
    if root is None:
        return BOUNDED_ENTITY_SEARCH_CONTRACTS_PATH

    return Path(root) / BOUNDED_ENTITY_SEARCH_CONTRACTS_PATH


def _require_string(
    entry: dict[str, Any],
    key: str,
    *,
    entry_id: str,
) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BoundedEntitySearchRegistryError(
            f"Bounded entity search contract '{entry_id}' field '{key}' "
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
        raise BoundedEntitySearchRegistryError(
            f"Bounded entity search contract '{entry_id}' field '{key}' "
            "must be a boolean."
        )
    return value


def _require_object(
    entry: dict[str, Any],
    key: str,
    *,
    entry_id: str,
) -> dict[str, Any]:
    value = entry.get(key)
    if not isinstance(value, dict):
        raise BoundedEntitySearchRegistryError(
            f"Bounded entity search contract '{entry_id}' field '{key}' "
            "must be an object."
        )
    return dict(value)


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
        raise BoundedEntitySearchRegistryError(
            f"Bounded entity search contract '{entry_id}' field '{key}' "
            "must be a list of non-empty strings."
        )
    return tuple(item.strip() for item in value)


def _contract_from_entry(entry: Any) -> BoundedEntitySearchContract:
    if not isinstance(entry, dict):
        raise BoundedEntitySearchRegistryError(
            "Bounded entity search contract entries must be objects."
        )

    entry_id = _require_string(entry, "id", entry_id="<unknown>")
    operation_id = _require_string(entry, "operation_id", entry_id=entry_id)
    lookup_type = _require_string(entry, "lookup_type", entry_id=entry_id)
    if operation_id != "bounded_entity_search":
        raise BoundedEntitySearchRegistryError(
            f"Bounded entity search contract '{entry_id}' uses "
            f"unsupported operation_id '{operation_id}'."
        )
    if lookup_type not in ALLOWED_SEARCH_TYPES:
        raise BoundedEntitySearchRegistryError(
            f"Bounded entity search contract '{entry_id}' uses "
            f"unsupported lookup_type '{lookup_type}'."
        )

    inputs = _require_object(entry, "inputs", entry_id=entry_id)
    required_any = _require_string_list(
        inputs,
        "required_any",
        entry_id=entry_id,
    )
    optional = _require_string_list(
        inputs,
        "optional",
        entry_id=entry_id,
        allow_empty=True,
    )
    forbidden_planner_fields = _require_string_list(
        inputs,
        "agent_policy_fields_forbidden",
        entry_id=entry_id,
    )
    if set(required_any) != REQUIRED_ANY_INPUTS:
        raise BoundedEntitySearchRegistryError(
            f"Bounded entity search contract '{entry_id}' must require "
            "one of search_topic or query_intent."
        )
    if not set(optional).issubset(OPTIONAL_INPUTS):
        raise BoundedEntitySearchRegistryError(
            f"Bounded entity search contract '{entry_id}' has unsupported "
            "optional inputs."
        )
    if not FORBIDDEN_PLANNER_FIELDS.issubset(set(forbidden_planner_fields)):
        raise BoundedEntitySearchRegistryError(
            f"Bounded entity search contract '{entry_id}' must forbid "
            "planner-owned source policy fields."
        )

    source_reference = _require_object(
        entry,
        "bounded_source_reference",
        entry_id=entry_id,
    )
    if source_reference.get("raw_target_allowed") is not False:
        raise BoundedEntitySearchRegistryError(
            f"Bounded entity search contract '{entry_id}' must disallow "
            "raw source targets."
        )
    if source_reference.get("owner") != "agent_capability_policy":
        raise BoundedEntitySearchRegistryError(
            f"Bounded entity search contract '{entry_id}' must leave "
            "source ownership to agent capability policy."
        )

    result_expectations = _require_object(
        entry,
        "result_expectations",
        entry_id=entry_id,
    )
    max_results = result_expectations.get("max_results")
    if (
        not isinstance(max_results, int)
        or isinstance(max_results, bool)
        or max_results < 1
        or max_results > 10
    ):
        raise BoundedEntitySearchRegistryError(
            f"Bounded entity search contract '{entry_id}' must declare a "
            "bounded max_results value from 1 to 10."
        )
    if result_expectations.get("final_answer") is not False:
        raise BoundedEntitySearchRegistryError(
            f"Bounded entity search contract '{entry_id}' must not return "
            "a final answer."
        )

    forbidden_behaviors = _require_string_list(
        entry,
        "forbidden_behaviors",
        entry_id=entry_id,
    )
    if not FORBIDDEN_BEHAVIORS.issubset(set(forbidden_behaviors)):
        raise BoundedEntitySearchRegistryError(
            f"Bounded entity search contract '{entry_id}' does not forbid "
            "all unsupported retrieval behaviors."
        )

    fail_closed = _require_object(entry, "fail_closed", entry_id=entry_id)
    if any(value is not True for value in fail_closed.values()):
        raise BoundedEntitySearchRegistryError(
            f"Bounded entity search contract '{entry_id}' fail_closed "
            "values must all be true."
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
        raise BoundedEntitySearchRegistryError(
            f"Bounded entity search contract '{entry_id}' exposes "
            "forbidden telemetry fields as safe."
        )
    if not FORBIDDEN_TELEMETRY_FIELDS.issubset(set(forbidden_fields)):
        raise BoundedEntitySearchRegistryError(
            f"Bounded entity search contract '{entry_id}' must explicitly "
            "forbid private telemetry fields."
        )

    return BoundedEntitySearchContract(
        id=entry_id,
        operation_id=operation_id,
        lookup_type=lookup_type,
        enabled=_require_bool(entry, "enabled", entry_id=entry_id),
        required_any_inputs=required_any,
        optional_inputs=optional,
        agent_policy_fields_forbidden=forbidden_planner_fields,
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
) -> tuple[BoundedEntitySearchContract, ...]:
    data = json.loads(_registry_path(root).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise BoundedEntitySearchRegistryError(
            "Bounded entity search registry must be an object."
        )
    if data.get("version") != 1:
        raise BoundedEntitySearchRegistryError(
            "Bounded entity search registry version must be 1."
        )

    contracts = data.get("contracts")
    if not isinstance(contracts, list):
        raise BoundedEntitySearchRegistryError(
            "Bounded entity search registry 'contracts' must be a list."
        )

    loaded = tuple(_contract_from_entry(entry) for entry in contracts)
    ids = [contract.id for contract in loaded]
    if len(ids) != len(set(ids)):
        raise BoundedEntitySearchRegistryError(
            "Bounded entity search registry contains duplicate contract IDs."
        )
    return loaded


@lru_cache(maxsize=None)
def load_bounded_entity_search_contracts(
    root: str | Path | None = None,
) -> tuple[BoundedEntitySearchContract, ...]:
    try:
        return _load_registry_strict(root)
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        BoundedEntitySearchRegistryError,
    ):
        return ()


def get_bounded_entity_search_contract(
    lookup_type: str,
    *,
    root: str | Path | None = None,
) -> BoundedEntitySearchContract | None:
    normalized = str(lookup_type or "").strip()
    if not normalized:
        return None

    for contract in load_bounded_entity_search_contracts(root):
        if contract.lookup_type == normalized:
            return contract
    return None


def validate_bounded_entity_search_request(
    request: dict[str, Any],
    *,
    root: str | Path | None = None,
    allow_policy_fields: bool = False,
) -> list[BoundedEntitySearchValidationError]:
    if not isinstance(request, dict):
        return [
            BoundedEntitySearchValidationError(
                error_code="invalid_bounded_entity_search_request",
                field="request",
                message="request must be an object.",
            )
        ]

    lookup_type = request.get("lookup_type")
    if not isinstance(lookup_type, str) or not lookup_type.strip():
        return [
            BoundedEntitySearchValidationError(
                error_code="invalid_bounded_entity_search_request",
                field="lookup_type",
                message="lookup_type must be a non-empty string.",
            )
        ]

    contract = get_bounded_entity_search_contract(lookup_type, root=root)
    if contract is None:
        return [
            BoundedEntitySearchValidationError(
                error_code="unknown_bounded_entity_search_type",
                field="lookup_type",
                message="lookup_type is not registered.",
            )
        ]

    errors: list[BoundedEntitySearchValidationError] = []
    has_required = any(
        isinstance(request.get(field), str) and request.get(field).strip()
        for field in contract.required_any_inputs
    )
    if not has_required:
        errors.append(
            BoundedEntitySearchValidationError(
                error_code="invalid_bounded_entity_search_request",
                field="search_topic",
                message="search_topic or query_intent must be present.",
            )
        )

    allowed_inputs = set(contract.required_any_inputs) | set(
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
    if allow_policy_fields:
        allowed_inputs = allowed_inputs | {"source_scope"}

    for key in request:
        if (
            key in contract.agent_policy_fields_forbidden
            and not allow_policy_fields
        ):
            errors.append(
                BoundedEntitySearchValidationError(
                    error_code="invalid_bounded_entity_search_request",
                    field=key,
                    message="field belongs to capability policy.",
                )
            )
        elif key not in allowed_inputs:
            errors.append(
                BoundedEntitySearchValidationError(
                    error_code="invalid_bounded_entity_search_request",
                    field=key,
                    message="field is not allowed by the search contract.",
                )
            )

    for field in ("search_topic", "query_intent", "entity_type"):
        value = request.get(field)
        if value is not None and not isinstance(value, str):
            errors.append(
                BoundedEntitySearchValidationError(
                    error_code="invalid_bounded_entity_search_request",
                    field=field,
                    message=f"{field} must be a string when present.",
                )
            )

    source_scope = request.get("source_scope")
    if allow_policy_fields and source_scope is not None and (
        not isinstance(source_scope, str) or not source_scope.strip()
    ):
        errors.append(
            BoundedEntitySearchValidationError(
                error_code="invalid_bounded_entity_search_request",
                field="source_scope",
                message="source_scope must be a non-empty string when present.",
            )
        )

    constraints = request.get("constraints")
    if constraints is not None and not isinstance(constraints, dict):
        errors.append(
            BoundedEntitySearchValidationError(
                error_code="invalid_bounded_entity_search_request",
                field="constraints",
                message="constraints must be an object when present.",
            )
        )

    max_results = request.get("max_results")
    if max_results is not None and (
        not isinstance(max_results, int)
        or isinstance(max_results, bool)
        or max_results < 1
        or max_results > contract.result_expectations["max_results"]
    ):
        errors.append(
            BoundedEntitySearchValidationError(
                error_code="invalid_bounded_entity_search_request",
                field="max_results",
                message="max_results exceeds the bounded contract.",
            )
        )

    return errors


__all__ = [
    "ALLOWED_SEARCH_TYPES",
    "BOUNDED_ENTITY_SEARCH_CONTRACTS_PATH",
    "BoundedEntitySearchContract",
    "BoundedEntitySearchRegistryError",
    "BoundedEntitySearchValidationError",
    "FORBIDDEN_BEHAVIORS",
    "FORBIDDEN_PLANNER_FIELDS",
    "FORBIDDEN_TELEMETRY_FIELDS",
    "OPTIONAL_INPUTS",
    "REQUIRED_ANY_INPUTS",
    "get_bounded_entity_search_contract",
    "load_bounded_entity_search_contracts",
    "validate_bounded_entity_search_request",
]
