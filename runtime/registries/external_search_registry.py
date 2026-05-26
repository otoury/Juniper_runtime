from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


EXTERNAL_SEARCH_CONTRACTS_PATH = Path(
    "agents/shared/semantics/external_search_contracts.json"
)
ALLOWED_EXTERNAL_SEARCH_TYPES = {"external_search"}
REQUIRED_INPUTS = {"query"}
OPTIONAL_INPUTS = {
    "search_intent",
    "max_results",
    "freshness_policy",
    "source_policy",
    "result_bounds",
}
FORBIDDEN_PLANNER_FIELDS = {
    "adapter_id",
    "api_key",
    "browser_callable",
    "credential_env_var",
    "datasource_path",
    "delivery_target",
    "domain_output_type",
    "executor",
    "model",
    "normalizer",
    "provider_id",
    "provider_name",
    "provider_type",
    "ranking",
    "summarizer",
}
FORBIDDEN_BEHAVIORS = {
    "provider_selection",
    "provider_adapter_invocation",
    "network_call",
    "browser_automation",
    "cloud_model_web_search",
    "credential_access",
    "summarization",
    "domain_normalization",
    "ranking",
    "scoring",
    "selection",
    "delivery",
    "writes",
    "hidden_rag",
    "heuristic_routing",
    "prompt_injection",
}
FORBIDDEN_TELEMETRY_FIELDS = {
    "query",
    "search_intent",
    "raw_results",
    "source_refs",
    "citations",
    "raw_provider_payload",
    "provider_payload",
    "credential",
    "api_key",
    "rendered_context",
}
EXECUTION_REQUEST_FIELDS = {
    "allow_live_call",
    "execute",
    "execution_allowed",
    "external_call_performed",
    "live_execution_allowed",
    "network_calls_allowed",
    "provider_integration_allowed",
    "provider_selection_allowed",
}


class ExternalSearchRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExternalSearchContract:
    id: str
    operation_id: str
    semantic_type: str
    enabled: bool
    required_inputs: tuple[str, ...]
    optional_inputs: tuple[str, ...]
    planner_fields_forbidden: tuple[str, ...]
    governance: dict[str, Any]
    result_contract: dict[str, Any]
    bounds: dict[str, Any]
    forbidden_behaviors: tuple[str, ...]
    fail_closed: dict[str, bool]
    telemetry_safe_provenance_fields: tuple[str, ...]
    telemetry_forbidden_fields: tuple[str, ...]
    raw_data: dict[str, Any]

    @property
    def execution_allowed(self) -> bool:
        return False


@dataclass(frozen=True)
class ExternalSearchValidationError:
    error_code: str
    field: str
    message: str


def _registry_path(root: str | Path | None = None) -> Path:
    if root is None:
        return EXTERNAL_SEARCH_CONTRACTS_PATH
    return Path(root) / EXTERNAL_SEARCH_CONTRACTS_PATH


def _require_string(entry: dict[str, Any], key: str, *, entry_id: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ExternalSearchRegistryError(
            f"External search contract '{entry_id}' field '{key}' must be a non-empty string."
        )
    return value.strip()


def _require_bool(entry: dict[str, Any], key: str, *, entry_id: str) -> bool:
    value = entry.get(key)
    if not isinstance(value, bool):
        raise ExternalSearchRegistryError(
            f"External search contract '{entry_id}' field '{key}' must be a boolean."
        )
    return value


def _require_object(entry: dict[str, Any], key: str, *, entry_id: str) -> dict[str, Any]:
    value = entry.get(key)
    if not isinstance(value, dict):
        raise ExternalSearchRegistryError(
            f"External search contract '{entry_id}' field '{key}' must be an object."
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
        raise ExternalSearchRegistryError(
            f"External search contract '{entry_id}' field '{key}' must be a list of non-empty strings."
        )
    return tuple(item.strip() for item in value)


def _contract_from_entry(entry: Any) -> ExternalSearchContract:
    if not isinstance(entry, dict):
        raise ExternalSearchRegistryError("External search contract entries must be objects.")

    entry_id = _require_string(entry, "id", entry_id="<unknown>")
    operation_id = _require_string(entry, "operation_id", entry_id=entry_id)
    semantic_type = _require_string(entry, "semantic_type", entry_id=entry_id)
    if operation_id != "external_search" or semantic_type not in ALLOWED_EXTERNAL_SEARCH_TYPES:
        raise ExternalSearchRegistryError(
            f"External search contract '{entry_id}' uses unsupported semantic identity."
        )

    inputs = _require_object(entry, "inputs", entry_id=entry_id)
    required = _require_string_list(inputs, "required", entry_id=entry_id)
    optional = _require_string_list(
        inputs,
        "optional",
        entry_id=entry_id,
        allow_empty=True,
    )
    forbidden_planner_fields = _require_string_list(
        inputs,
        "planner_fields_forbidden",
        entry_id=entry_id,
    )
    if set(required) != REQUIRED_INPUTS:
        raise ExternalSearchRegistryError(
            f"External search contract '{entry_id}' must require query."
        )
    if not set(optional).issubset(OPTIONAL_INPUTS):
        raise ExternalSearchRegistryError(
            f"External search contract '{entry_id}' has unsupported optional inputs."
        )
    if not FORBIDDEN_PLANNER_FIELDS.issubset(set(forbidden_planner_fields)):
        raise ExternalSearchRegistryError(
            f"External search contract '{entry_id}' must forbid provider and execution planner fields."
        )

    governance = _require_object(entry, "governance", entry_id=entry_id)
    _validate_governance(governance, entry_id=entry_id)
    result_contract = _require_object(entry, "result_contract", entry_id=entry_id)
    _validate_result_contract(result_contract, entry_id=entry_id)
    bounds = _require_object(entry, "bounds", entry_id=entry_id)
    _validate_bounds(bounds, entry_id=entry_id)

    forbidden_behaviors = _require_string_list(
        entry,
        "forbidden_behaviors",
        entry_id=entry_id,
    )
    if not FORBIDDEN_BEHAVIORS.issubset(set(forbidden_behaviors)):
        raise ExternalSearchRegistryError(
            f"External search contract '{entry_id}' does not forbid all provider-stage behavior."
        )

    fail_closed = _require_object(entry, "fail_closed", entry_id=entry_id)
    if any(value is not True for value in fail_closed.values()):
        raise ExternalSearchRegistryError(
            f"External search contract '{entry_id}' fail_closed values must all be true."
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
        raise ExternalSearchRegistryError(
            f"External search contract '{entry_id}' exposes forbidden telemetry fields as safe."
        )
    if not FORBIDDEN_TELEMETRY_FIELDS.issubset(set(forbidden_fields)):
        raise ExternalSearchRegistryError(
            f"External search contract '{entry_id}' must explicitly forbid content telemetry fields."
        )

    return ExternalSearchContract(
        id=entry_id,
        operation_id=operation_id,
        semantic_type=semantic_type,
        enabled=_require_bool(entry, "enabled", entry_id=entry_id),
        required_inputs=required,
        optional_inputs=optional,
        planner_fields_forbidden=forbidden_planner_fields,
        governance=governance,
        result_contract=result_contract,
        bounds=bounds,
        forbidden_behaviors=forbidden_behaviors,
        fail_closed={key: bool(value) for key, value in fail_closed.items()},
        telemetry_safe_provenance_fields=safe_fields,
        telemetry_forbidden_fields=forbidden_fields,
        raw_data=dict(entry),
    )


def _validate_governance(governance: dict[str, Any], *, entry_id: str) -> None:
    required_true = (
        "external",
        "governed",
        "cost_bearing",
        "dry_run_or_mock_required",
    )
    required_false = (
        "provider_integration_allowed",
        "provider_selection_allowed",
        "network_calls_allowed",
        "browser_calls_allowed",
        "cloud_model_calls_allowed",
        "credential_access_allowed",
        "execution_allowed",
        "delivery_allowed",
    )
    for field in required_true:
        if governance.get(field) is not True:
            raise ExternalSearchRegistryError(
                f"External search contract '{entry_id}' governance.{field} must be true."
            )
    for field in required_false:
        if governance.get(field) is not False:
            raise ExternalSearchRegistryError(
                f"External search contract '{entry_id}' governance.{field} must be false."
            )
    if governance.get("contract_stage") != "pre_provider_integration":
        raise ExternalSearchRegistryError(
            f"External search contract '{entry_id}' must remain pre_provider_integration."
        )


def _validate_result_contract(result_contract: dict[str, Any], *, entry_id: str) -> None:
    if result_contract.get("artifact_type") != "external_search_result_set":
        raise ExternalSearchRegistryError(
            f"External search contract '{entry_id}' must return external_search_result_set."
        )
    required_true = (
        "raw_results_required",
        "source_refs_required",
        "citations_required",
        "result_lineage_required_for_normalized_results",
        "empty_result_allowed_when_not_executed",
        "requires_operator_auditable_provenance",
    )
    required_false = (
        "provider_metadata_allowed",
        "final_answer",
        "summarization_allowed",
        "domain_normalization_allowed",
        "ranking_allowed",
        "selection_allowed",
        "delivery_allowed",
    )
    for field in required_true:
        if result_contract.get(field) is not True:
            raise ExternalSearchRegistryError(
                f"External search contract '{entry_id}' result_contract.{field} must be true."
            )
    for field in required_false:
        if result_contract.get(field) is not False:
            raise ExternalSearchRegistryError(
                f"External search contract '{entry_id}' result_contract.{field} must be false."
            )


def _validate_bounds(bounds: dict[str, Any], *, entry_id: str) -> None:
    max_queries = bounds.get("max_queries")
    max_results = bounds.get("max_results")
    timeout_ms = bounds.get("timeout_ms")
    if max_queries != 1:
        raise ExternalSearchRegistryError(
            f"External search contract '{entry_id}' bounds.max_queries must be 1."
        )
    if not isinstance(max_results, int) or isinstance(max_results, bool) or max_results < 1 or max_results > 10:
        raise ExternalSearchRegistryError(
            f"External search contract '{entry_id}' bounds.max_results must be between 1 and 10."
        )
    if timeout_ms != 0:
        raise ExternalSearchRegistryError(
            f"External search contract '{entry_id}' bounds.timeout_ms must be 0 before provider integration."
        )
    max_cost = bounds.get("max_cost")
    if not isinstance(max_cost, dict) or max_cost.get("currency") != "USD" or max_cost.get("amount") != 0:
        raise ExternalSearchRegistryError(
            f"External search contract '{entry_id}' bounds.max_cost must be zero USD."
        )


def _load_registry_strict(root: str | Path | None = None) -> tuple[ExternalSearchContract, ...]:
    data = json.loads(_registry_path(root).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ExternalSearchRegistryError("External search registry version must be 1.")
    raw_contracts = data.get("contracts")
    if not isinstance(raw_contracts, list):
        raise ExternalSearchRegistryError("External search registry contracts must be a list.")
    contracts = tuple(_contract_from_entry(entry) for entry in raw_contracts)
    semantic_types = [contract.semantic_type for contract in contracts]
    if len(semantic_types) != len(set(semantic_types)):
        raise ExternalSearchRegistryError("External search registry contains duplicate semantic types.")
    return contracts


@lru_cache(maxsize=None)
def load_external_search_contracts(
    root: str | Path | None = None,
) -> tuple[ExternalSearchContract, ...]:
    try:
        return _load_registry_strict(root)
    except (FileNotFoundError, json.JSONDecodeError, ExternalSearchRegistryError):
        return ()


def get_external_search_contract(
    semantic_type: str,
    *,
    root: str | Path | None = None,
) -> ExternalSearchContract | None:
    normalized = str(semantic_type or "").strip()
    if not normalized:
        return None
    for contract in load_external_search_contracts(root):
        if contract.semantic_type == normalized:
            return contract
    return None


def validate_external_search_request(
    request: Any,
    *,
    root: str | Path | None = None,
) -> list[ExternalSearchValidationError]:
    if not isinstance(request, dict):
        return [
            ExternalSearchValidationError(
                "invalid_external_search_request",
                "request",
                "external search request must be an object.",
            )
        ]

    semantic_type = _safe_string(request.get("semantic_type")) or _safe_string(
        request.get("operation_id")
    )
    contract = get_external_search_contract(semantic_type or "", root=root)
    if contract is None:
        return [
            ExternalSearchValidationError(
                "unknown_external_search_type",
                "semantic_type",
                "external search request must use canonical semantic_type external_search.",
            )
        ]

    errors: list[ExternalSearchValidationError] = []
    if not _safe_string(request.get("query")):
        errors.append(
            ExternalSearchValidationError(
                "missing_required_input",
                "query",
                "external search request must include a non-empty query.",
            )
        )

    for field in contract.planner_fields_forbidden:
        if field in request:
            errors.append(
                ExternalSearchValidationError(
                    "provider_field_not_allowed",
                    field,
                    "external search contracts must not include provider, credential, delivery, or execution planner fields.",
                )
            )

    for field in EXECUTION_REQUEST_FIELDS:
        if request.get(field) is True:
            errors.append(
                ExternalSearchValidationError(
                    "execution_not_allowed",
                    field,
                    "external search Stage 124 contracts do not authorize execution or provider integration.",
                )
            )

    max_results = request.get("max_results")
    if max_results is not None:
        contract_max = contract.bounds.get("max_results")
        if (
            not isinstance(max_results, int)
            or isinstance(max_results, bool)
            or max_results < 1
            or max_results > contract_max
        ):
            errors.append(
                ExternalSearchValidationError(
                    "invalid_result_bound",
                    "max_results",
                    f"max_results must be an integer from 1 to {contract_max}.",
                )
            )

    return errors


def _safe_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "ALLOWED_EXTERNAL_SEARCH_TYPES",
    "EXECUTION_REQUEST_FIELDS",
    "EXTERNAL_SEARCH_CONTRACTS_PATH",
    "FORBIDDEN_BEHAVIORS",
    "FORBIDDEN_PLANNER_FIELDS",
    "FORBIDDEN_TELEMETRY_FIELDS",
    "OPTIONAL_INPUTS",
    "REQUIRED_INPUTS",
    "ExternalSearchContract",
    "ExternalSearchRegistryError",
    "ExternalSearchValidationError",
    "get_external_search_contract",
    "load_external_search_contracts",
    "validate_external_search_request",
]
