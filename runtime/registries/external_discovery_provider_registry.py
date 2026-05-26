from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


EXTERNAL_DISCOVERY_PROVIDER_CONTRACTS_PATH = Path(
    "agents/shared/semantics/external_discovery_provider_contracts.json"
)
ALLOWED_PROVIDER_TYPES = {"cloud_ai", "search_api"}
ALLOWED_EXECUTION_MODES = {"declaration_only"}
ALLOWED_GOVERNANCE_STATES = {"enabled", "audit_only", "disabled"}
ALLOWED_OUTPUT_TYPES = {
    "external_discovery_result_set",
    "external_discovery_source_reference",
}
REQUIRED_DECLARATION_FIELDS = {
    "provider_id",
    "provider_type",
    "execution_mode",
    "governance_state",
    "external",
    "cost_bearing",
    "governed",
    "non_executing",
    "governance",
    "cost_policy",
    "supported_output_types",
    "max_queries",
    "max_results",
    "max_cost",
    "execution_bounds",
    "source_requirements",
    "citation_requirements",
}
SHARED_PROVIDER_IDS = {"cloud_web_ai", "search_api", "cloud_web_deep_premium"}
FORBIDDEN_DECLARATION_FIELDS = {
    "adapter_callable",
    "agent_id",
    "browser_callable",
    "datasource_path",
    "delivery_target",
    "domain",
    "domain_output_type",
    "execute",
    "executor",
    "gateway",
    "model",
    "normalizer",
    "outreach_template",
    "prompt",
    "ranking",
    "summarizer",
    "summary_prompt",
    "telegram",
}


class ExternalDiscoveryProviderRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExternalDiscoveryProviderContract:
    id: str
    contract_version: int
    required_declaration_fields: tuple[str, ...]
    allowed_provider_types: tuple[str, ...]
    allowed_execution_modes: tuple[str, ...]
    allowed_governance_states: tuple[str, ...]
    allowed_output_types: tuple[str, ...]
    execution_policy: dict[str, bool]
    forbidden_declaration_fields: tuple[str, ...]
    raw_data: dict[str, Any]


@dataclass(frozen=True)
class ExternalDiscoveryProviderDeclaration:
    provider_id: str
    provider_type: str
    execution_mode: str
    governance_state: str
    external: bool
    cost_bearing: bool
    governed: bool
    non_executing: bool
    governance: dict[str, Any]
    cost_policy: dict[str, Any]
    supported_output_types: tuple[str, ...]
    max_queries: int
    max_results: int
    max_cost: dict[str, Any]
    execution_bounds: dict[str, Any]
    source_requirements: dict[str, Any]
    citation_requirements: dict[str, Any]
    raw_data: dict[str, Any]

    @property
    def execution_allowed(self) -> bool:
        return False

    def to_metadata(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_type": self.provider_type,
            "execution_mode": self.execution_mode,
            "governance_state": self.governance_state,
            "external": self.external,
            "cost_bearing": self.cost_bearing,
            "governed": self.governed,
            "non_executing": self.non_executing,
            "governance": dict(self.governance),
            "cost_policy": dict(self.cost_policy),
            "supported_output_types": list(self.supported_output_types),
            "max_queries": self.max_queries,
            "max_results": self.max_results,
            "max_cost": dict(self.max_cost),
            "execution_bounds": dict(self.execution_bounds),
            "source_requirements": dict(self.source_requirements),
            "citation_requirements": dict(self.citation_requirements),
            "execution_allowed": False,
        }


def _registry_path(root: str | Path | None = None) -> Path:
    if root is None:
        return EXTERNAL_DISCOVERY_PROVIDER_CONTRACTS_PATH
    return Path(root) / EXTERNAL_DISCOVERY_PROVIDER_CONTRACTS_PATH


def _require_string(entry: dict[str, Any], key: str, *, entry_id: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider entry '{entry_id}' field '{key}' "
            "must be a non-empty string."
        )
    return value.strip()


def _require_bool(entry: dict[str, Any], key: str, *, entry_id: str) -> bool:
    value = entry.get(key)
    if not isinstance(value, bool):
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider entry '{entry_id}' field '{key}' "
            "must be a boolean."
        )
    return value


def _require_int(
    entry: dict[str, Any],
    key: str,
    *,
    entry_id: str,
    minimum: int = 1,
) -> int:
    value = entry.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider entry '{entry_id}' field '{key}' "
            f"must be an integer greater than or equal to {minimum}."
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
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider entry '{entry_id}' field '{key}' "
            "must be an object."
        )
    return dict(value)


def _require_optional_number(
    entry: dict[str, Any],
    key: str,
    *,
    entry_id: str,
) -> int | float | None:
    value = entry.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider entry '{entry_id}' field '{key}' "
            "must be null or a number."
        )
    if value < 0:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider entry '{entry_id}' field '{key}' "
            "must not be negative."
        )
    return value


def _require_string_list(
    entry: dict[str, Any],
    key: str,
    *,
    entry_id: str,
) -> tuple[str, ...]:
    value = entry.get(key)
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider entry '{entry_id}' field '{key}' "
            "must be a list of non-empty strings."
        )
    return tuple(item.strip() for item in value)


def _forbidden_field_paths(value: Any, *, prefix: str = "") -> tuple[str, ...]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, item in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if key_text in FORBIDDEN_DECLARATION_FIELDS:
                paths.append(path)
            paths.extend(_forbidden_field_paths(item, prefix=path))
        return tuple(paths)
    if isinstance(value, list):
        paths = []
        for index, item in enumerate(value):
            paths.extend(_forbidden_field_paths(item, prefix=f"{prefix}[{index}]"))
        return tuple(paths)
    return ()


def _validate_governance_metadata(
    governance: dict[str, Any],
    *,
    provider_id: str,
) -> None:
    required_false_fields = (
        "live_execution_allowed",
        "network_calls_allowed",
        "delivery_allowed",
    )
    for field in required_false_fields:
        if governance.get(field) is not False:
            raise ExternalDiscoveryProviderRegistryError(
                f"External discovery provider declaration '{provider_id}' "
                f"governance.{field} must be false."
            )
    if governance.get("dry_run_or_mock_required") is not True:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' "
            "governance.dry_run_or_mock_required must be true."
        )


def _validate_cost_policy(
    cost_policy: dict[str, Any],
    *,
    max_cost: dict[str, Any],
    provider_id: str,
) -> None:
    if cost_policy.get("cost_bearing") is not True:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' "
            "cost_policy.cost_bearing must be true."
        )
    if not isinstance(cost_policy.get("free_tier_available"), bool):
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' "
            "cost_policy.free_tier_available must be a boolean."
        )
    if not isinstance(cost_policy.get("free_tier"), dict):
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' "
            "cost_policy.free_tier must be an object."
        )
    if not isinstance(cost_policy.get("cost_tracking_required"), bool):
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' "
            "cost_policy.cost_tracking_required must be a boolean."
        )
    if _require_string(max_cost, "currency", entry_id=provider_id) != "USD":
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' "
            "max_cost.currency must be USD."
        )
    _require_optional_number(max_cost, "amount", entry_id=provider_id)
    _require_string(max_cost, "period", entry_id=provider_id)


def _validate_execution_bounds(
    execution_bounds: dict[str, Any],
    *,
    max_queries: int,
    max_results: int,
    provider_id: str,
) -> None:
    timeout_ms = _require_int(
        execution_bounds,
        "timeout_ms",
        entry_id=provider_id,
        minimum=1,
    )
    _require_int(
        execution_bounds,
        "connect_timeout_ms",
        entry_id=provider_id,
        minimum=1,
    )
    _require_int(
        execution_bounds,
        "read_timeout_ms",
        entry_id=provider_id,
        minimum=1,
    )
    _require_int(
        execution_bounds,
        "max_retries",
        entry_id=provider_id,
        minimum=0,
    )
    if execution_bounds.get("max_queries") != max_queries:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' "
            "execution_bounds.max_queries must match max_queries."
        )
    if execution_bounds.get("max_results") != max_results:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' "
            "execution_bounds.max_results must match max_results."
        )
    if execution_bounds.get("connect_timeout_ms") > timeout_ms:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' "
            "connect timeout must not exceed timeout_ms."
        )
    if execution_bounds.get("read_timeout_ms") > timeout_ms:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' "
            "read timeout must not exceed timeout_ms."
        )


def _validate_source_requirements(
    source_requirements: dict[str, Any],
    citation_requirements: dict[str, Any],
    *,
    provider_id: str,
) -> None:
    required_true_source_fields = (
        "source_refs_required",
        "provider_result_id_required",
        "source_url_required",
        "raw_results_required",
    )
    for field in required_true_source_fields:
        if source_requirements.get(field) is not True:
            raise ExternalDiscoveryProviderRegistryError(
                f"External discovery provider declaration '{provider_id}' "
                f"source_requirements.{field} must be true."
            )
    if not isinstance(source_requirements.get("allowed_source_types"), list):
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' "
            "source_requirements.allowed_source_types must be a list."
        )
    if citation_requirements.get("citations_required") is not True:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' "
            "citation_requirements.citations_required must be true."
        )
    if citation_requirements.get("source_url_required") is not True:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' "
            "citation_requirements.source_url_required must be true."
        )


def _contract_from_entry(entry: Any) -> ExternalDiscoveryProviderContract:
    if not isinstance(entry, dict):
        raise ExternalDiscoveryProviderRegistryError(
            "External discovery provider contract entries must be objects."
        )

    entry_id = _require_string(entry, "id", entry_id="<unknown>")
    contract_version = _require_int(entry, "contract_version", entry_id=entry_id)
    if contract_version != 1:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider contract '{entry_id}' has "
            "unsupported version."
        )

    required_fields = _require_string_list(
        entry,
        "required_declaration_fields",
        entry_id=entry_id,
    )
    if set(required_fields) != REQUIRED_DECLARATION_FIELDS:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider contract '{entry_id}' has "
            "unsupported declaration fields."
        )

    provider_types = _require_string_list(
        entry,
        "allowed_provider_types",
        entry_id=entry_id,
    )
    if set(provider_types) != ALLOWED_PROVIDER_TYPES:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider contract '{entry_id}' has "
            "unsupported provider types."
        )

    execution_modes = _require_string_list(
        entry,
        "allowed_execution_modes",
        entry_id=entry_id,
    )
    if set(execution_modes) != ALLOWED_EXECUTION_MODES:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider contract '{entry_id}' has "
            "unsupported execution modes."
        )

    governance_states = _require_string_list(
        entry,
        "allowed_governance_states",
        entry_id=entry_id,
    )
    if set(governance_states) != ALLOWED_GOVERNANCE_STATES:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider contract '{entry_id}' has "
            "unsupported governance states."
        )

    output_types = _require_string_list(
        entry,
        "allowed_output_types",
        entry_id=entry_id,
    )
    if set(output_types) != ALLOWED_OUTPUT_TYPES:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider contract '{entry_id}' has "
            "unsupported output types."
        )

    execution_policy = _require_object(
        entry,
        "execution_policy",
        entry_id=entry_id,
    )
    if any(value is not False for value in execution_policy.values()):
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider contract '{entry_id}' must be "
            "non-executing."
        )

    forbidden_fields = _require_string_list(
        entry,
        "forbidden_declaration_fields",
        entry_id=entry_id,
    )
    if not FORBIDDEN_DECLARATION_FIELDS.issubset(set(forbidden_fields)):
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider contract '{entry_id}' does not "
            "forbid all execution and domain-routing fields."
        )

    return ExternalDiscoveryProviderContract(
        id=entry_id,
        contract_version=contract_version,
        required_declaration_fields=required_fields,
        allowed_provider_types=provider_types,
        allowed_execution_modes=execution_modes,
        allowed_governance_states=governance_states,
        allowed_output_types=output_types,
        execution_policy={
            key: bool(value)
            for key, value in execution_policy.items()
        },
        forbidden_declaration_fields=forbidden_fields,
        raw_data=dict(entry),
    )


def _declaration_from_entry(
    entry: Any,
    *,
    contracts: tuple[ExternalDiscoveryProviderContract, ...],
) -> ExternalDiscoveryProviderDeclaration:
    if not isinstance(entry, dict):
        raise ExternalDiscoveryProviderRegistryError(
            "External discovery provider declarations must be objects."
        )

    provider_id = _require_string(entry, "provider_id", entry_id="<unknown>")
    if not contracts:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' has "
            "no contract."
        )
    contract = contracts[0]

    missing_fields = sorted(
        field for field in contract.required_declaration_fields if field not in entry
    )
    if missing_fields:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' is "
            "missing required fields: "
            + ", ".join(missing_fields)
        )

    forbidden_paths = _forbidden_field_paths(entry)
    if forbidden_paths:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' contains "
            "forbidden fields: "
            + ", ".join(forbidden_paths)
        )

    if provider_id not in SHARED_PROVIDER_IDS:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' is "
            "not an approved shared provider."
        )

    provider_type = _require_string(entry, "provider_type", entry_id=provider_id)
    if provider_type not in contract.allowed_provider_types:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' has "
            "unsupported provider_type."
        )

    execution_mode = _require_string(entry, "execution_mode", entry_id=provider_id)
    if execution_mode not in contract.allowed_execution_modes:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' has "
            "unsupported execution_mode."
        )

    governance_state = _require_string(
        entry,
        "governance_state",
        entry_id=provider_id,
    )
    if governance_state not in contract.allowed_governance_states:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' has "
            "unsupported governance_state."
        )
    if governance_state == "enabled":
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' must "
            "default to disabled or audit_only."
        )

    external = _require_bool(entry, "external", entry_id=provider_id)
    cost_bearing = _require_bool(entry, "cost_bearing", entry_id=provider_id)
    governed = _require_bool(entry, "governed", entry_id=provider_id)
    non_executing = _require_bool(entry, "non_executing", entry_id=provider_id)
    if not external:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' must "
            "declare external=true."
        )
    if not cost_bearing:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' must "
            "declare cost_bearing=true."
        )
    if not governed:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' must "
            "declare governed=true."
        )
    if not non_executing:
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' must "
            "declare non_executing=true."
        )

    output_types = _require_string_list(
        entry,
        "supported_output_types",
        entry_id=provider_id,
    )
    if not set(output_types).issubset(set(contract.allowed_output_types)):
        raise ExternalDiscoveryProviderRegistryError(
            f"External discovery provider declaration '{provider_id}' has "
            "unsupported output types."
        )

    max_queries = _require_int(entry, "max_queries", entry_id=provider_id)
    max_results = _require_int(entry, "max_results", entry_id=provider_id)
    max_cost = _require_object(entry, "max_cost", entry_id=provider_id)
    governance = _require_object(entry, "governance", entry_id=provider_id)
    cost_policy = _require_object(entry, "cost_policy", entry_id=provider_id)
    execution_bounds = _require_object(
        entry,
        "execution_bounds",
        entry_id=provider_id,
    )
    source_requirements = _require_object(
        entry,
        "source_requirements",
        entry_id=provider_id,
    )
    citation_requirements = _require_object(
        entry,
        "citation_requirements",
        entry_id=provider_id,
    )
    _validate_governance_metadata(governance, provider_id=provider_id)
    _validate_cost_policy(
        cost_policy,
        max_cost=max_cost,
        provider_id=provider_id,
    )
    _validate_execution_bounds(
        execution_bounds,
        max_queries=max_queries,
        max_results=max_results,
        provider_id=provider_id,
    )
    _validate_source_requirements(
        source_requirements,
        citation_requirements,
        provider_id=provider_id,
    )

    return ExternalDiscoveryProviderDeclaration(
        provider_id=provider_id,
        provider_type=provider_type,
        execution_mode=execution_mode,
        governance_state=governance_state,
        external=external,
        cost_bearing=cost_bearing,
        governed=governed,
        non_executing=non_executing,
        governance=governance,
        cost_policy=cost_policy,
        supported_output_types=output_types,
        max_queries=max_queries,
        max_results=max_results,
        max_cost=max_cost,
        execution_bounds=execution_bounds,
        source_requirements=source_requirements,
        citation_requirements=citation_requirements,
        raw_data=dict(entry),
    )


def _load_registry_strict(
    root: str | Path | None = None,
) -> tuple[
    tuple[ExternalDiscoveryProviderContract, ...],
    tuple[ExternalDiscoveryProviderDeclaration, ...],
]:
    data = json.loads(_registry_path(root).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ExternalDiscoveryProviderRegistryError(
            "External discovery provider registry version must be 1."
        )

    raw_contracts = data.get("contracts")
    if not isinstance(raw_contracts, list):
        raise ExternalDiscoveryProviderRegistryError(
            "External discovery provider registry 'contracts' must be a list."
        )
    contracts = tuple(_contract_from_entry(entry) for entry in raw_contracts)
    if len(contracts) != 1:
        raise ExternalDiscoveryProviderRegistryError(
            "External discovery provider registry must declare exactly one contract."
        )

    raw_declarations = data.get("provider_declarations")
    if not isinstance(raw_declarations, list):
        raise ExternalDiscoveryProviderRegistryError(
            "External discovery provider registry 'provider_declarations' "
            "must be a list."
        )
    declarations = tuple(
        _declaration_from_entry(entry, contracts=contracts)
        for entry in raw_declarations
    )

    provider_ids = [declaration.provider_id for declaration in declarations]
    if len(provider_ids) != len(set(provider_ids)):
        raise ExternalDiscoveryProviderRegistryError(
            "External discovery provider registry contains duplicate provider IDs."
        )

    return contracts, declarations


@lru_cache(maxsize=None)
def load_external_discovery_provider_contracts(
    root: str | Path | None = None,
) -> tuple[ExternalDiscoveryProviderContract, ...]:
    try:
        contracts, _declarations = _load_registry_strict(root)
        return contracts
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        ExternalDiscoveryProviderRegistryError,
    ):
        return ()


@lru_cache(maxsize=None)
def load_external_discovery_provider_declarations(
    root: str | Path | None = None,
) -> tuple[ExternalDiscoveryProviderDeclaration, ...]:
    try:
        _contracts, declarations = _load_registry_strict(root)
        return declarations
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        ExternalDiscoveryProviderRegistryError,
    ):
        return ()


def get_external_discovery_provider_declaration(
    provider_id: str,
    *,
    root: str | Path | None = None,
) -> ExternalDiscoveryProviderDeclaration | None:
    normalized = str(provider_id or "").strip()
    if not normalized:
        return None

    for declaration in load_external_discovery_provider_declarations(root):
        if declaration.provider_id == normalized:
            return declaration
    return None


__all__ = [
    "ALLOWED_EXECUTION_MODES",
    "ALLOWED_GOVERNANCE_STATES",
    "ALLOWED_OUTPUT_TYPES",
    "ALLOWED_PROVIDER_TYPES",
    "EXTERNAL_DISCOVERY_PROVIDER_CONTRACTS_PATH",
    "ExternalDiscoveryProviderContract",
    "ExternalDiscoveryProviderDeclaration",
    "ExternalDiscoveryProviderRegistryError",
    "FORBIDDEN_DECLARATION_FIELDS",
    "REQUIRED_DECLARATION_FIELDS",
    "SHARED_PROVIDER_IDS",
    "get_external_discovery_provider_declaration",
    "load_external_discovery_provider_contracts",
    "load_external_discovery_provider_declarations",
]
