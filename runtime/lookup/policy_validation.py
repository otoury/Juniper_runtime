from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from runtime.lookup.capability_compatibility import (
    LOOKUP_CAPABILITY_CONTRACT_VERSION,
    LOOKUP_RUNTIME_COMPATIBILITY_VERSION,
    normalize_lookup_capability_compatibility,
)
from runtime.lookup.governance import normalize_lookup_governance_policy
from runtime.lookup.execution_policy import normalize_lookup_execution_policy


ROOT = Path(__file__).resolve().parents[2]
LOOKUP_CAPABILITY_CONTRACTS_PATH = Path(
    "agents/shared/contracts/lookup_capability_contracts.json"
)
LOOKUP_RUNTIME_COMPATIBILITY_CONTRACTS_PATH = Path(
    "agents/shared/contracts/lookup_runtime_compatibility.json"
)
LOOKUP_RENDER_CONTRACTS_PATH = Path(
    "agents/shared/contracts/lookup_render_contracts.json"
)
LOOKUP_GOVERNANCE_STATES_PATH = Path(
    "agents/shared/governance/lookup_governance_states.json"
)
LOOKUP_EXECUTION_POLICY_PATH = Path(
    "agents/shared/policies/lookup_execution.json"
)
LOOKUP_REQUEST_CONTRACTS_PATH = Path(
    "planner/contracts/lookup_request_contracts.json"
)
LOOKUP_CONTRACT_SECTION_PATHS = (
    LOOKUP_CAPABILITY_CONTRACTS_PATH,
    LOOKUP_RUNTIME_COMPATIBILITY_CONTRACTS_PATH,
    LOOKUP_RENDER_CONTRACTS_PATH,
    LOOKUP_GOVERNANCE_STATES_PATH,
    LOOKUP_EXECUTION_POLICY_PATH,
    LOOKUP_REQUEST_CONTRACTS_PATH,
)


@dataclass(frozen=True)
class LookupPolicyValidationError:
    field: str
    message: str


@dataclass(frozen=True)
class LookupCapabilityContract:
    id: str
    capability_type: str
    retrieval_concept: str
    retrieval_specialization: str
    retrieval_scope: str
    contract_version: int
    runtime_compatibility_version: int
    lookup_types: tuple[str, ...]
    supported_features: tuple[str, ...]
    required_policy_sections: tuple[str, ...]
    agent_owned_values: tuple[str, ...]
    render_modes: tuple[str, ...]
    context_types: tuple[str, ...]
    content_types: tuple[str, ...]
    truncation_modes: tuple[str, ...]
    governance_states: tuple[str, ...]
    cancellation_behaviors: tuple[str, ...]
    required_planner_fields: tuple[str, ...]
    optional_planner_fields: tuple[str, ...]
    agent_policy_fields_forbidden: tuple[str, ...]
    fail_closed: dict[str, bool]


def load_lookup_capability_contracts(
    root: Path | str = ROOT,
) -> tuple[LookupCapabilityContract, ...]:
    return _load_lookup_capability_contracts(str(Path(root)))


def get_lookup_capability_contract(
    contract_id: str = "bounded_lookup_context_capability",
    *,
    root: Path | str = ROOT,
) -> LookupCapabilityContract | None:
    for contract in load_lookup_capability_contracts(root):
        if contract.id == contract_id:
            return contract

    return None


def validate_lookup_request_policy(
    policy: dict[str, Any] | None,
    *,
    contract: LookupCapabilityContract | None = None,
) -> list[LookupPolicyValidationError]:
    contract = contract or get_lookup_capability_contract()
    errors: list[LookupPolicyValidationError] = []
    if contract is None:
        return [_error("lookup_capability_contract", "contract unavailable.")]

    if not isinstance(policy, dict):
        return [_error("lookup_request_policy", "policy must be an object.")]

    if policy.get("enabled") is not True:
        errors.append(_error("enabled", "enabled must be true."))

    lookup_type = policy.get("lookup_type")
    if lookup_type not in contract.lookup_types:
        errors.append(_error("lookup_type", "lookup_type is unsupported."))

    _require_non_empty_string(policy, "source_scope", errors)
    _require_string_list(policy, "allowed_source_scopes", errors)

    allowed_scopes = policy.get("allowed_source_scopes")
    source_scope = policy.get("source_scope")
    if (
        isinstance(source_scope, str)
        and isinstance(allowed_scopes, list)
        and source_scope not in allowed_scopes
    ):
        errors.append(
            _error("source_scope", "source_scope must be explicitly allowed.")
        )

    entity_type = policy.get("entity_type")
    if entity_type is not None and not _non_empty_string(entity_type):
        errors.append(
            _error("entity_type", "entity_type must be a non-empty string.")
        )

    if lookup_type == "bounded_entity_search":
        required_any = policy.get("required_any_planner_fields")
        if required_any != ["search_topic", "query_intent"]:
            errors.append(
                _error(
                    "required_any_planner_fields",
                    "required_any_planner_fields do not match the shared contract.",
                )
            )
    elif tuple(policy.get("required_planner_fields", ())) != (
        contract.required_planner_fields
    ):
        errors.append(
            _error(
                "required_planner_fields",
                "required_planner_fields do not match the shared contract.",
            )
        )

    optional_fields = policy.get("optional_planner_fields", [])
    allowed_optional = (
        {"constraints", "max_results"}
        if lookup_type == "bounded_entity_search"
        else set(contract.optional_planner_fields)
    )
    if not isinstance(optional_fields, list) or any(
        field not in allowed_optional
        for field in optional_fields
    ):
        errors.append(
            _error(
                "optional_planner_fields",
                "optional_planner_fields contains unsupported fields.",
            )
        )

    return errors


def validate_lookup_context_materialization_policy(
    policy: dict[str, Any] | None,
    *,
    contract: LookupCapabilityContract | None = None,
) -> list[LookupPolicyValidationError]:
    contract = contract or get_lookup_capability_contract()
    errors: list[LookupPolicyValidationError] = []
    if contract is None:
        return [_error("lookup_capability_contract", "contract unavailable.")]

    if not isinstance(policy, dict):
        return [_error("materialization_policy", "policy must be an object.")]

    if policy.get("enabled") is not True:
        errors.append(_error("enabled", "enabled must be true."))

    _require_non_empty_string(policy, "context_type", errors)
    if (
        isinstance(policy.get("context_type"), str)
        and policy.get("context_type") not in contract.context_types
    ):
        errors.append(_error("context_type", "context_type unsupported."))

    _require_string_list(policy, "allowed_fields", errors)

    allowed_fields = policy.get("allowed_fields")
    max_fields = policy.get("max_fields")
    if not _positive_int(max_fields):
        errors.append(_error("max_fields", "max_fields must be positive."))
    elif isinstance(allowed_fields, list) and max_fields > len(allowed_fields):
        errors.append(
            _error("max_fields", "max_fields must not exceed allowed_fields.")
        )

    return errors


def validate_lookup_context_render_policy(
    policy: dict[str, Any] | None,
    *,
    contract: LookupCapabilityContract | None = None,
) -> list[LookupPolicyValidationError]:
    contract = contract or get_lookup_capability_contract()
    errors: list[LookupPolicyValidationError] = []
    if contract is None:
        return [_error("lookup_capability_contract", "contract unavailable.")]

    if not isinstance(policy, dict):
        return [_error("render_policy", "policy must be an object.")]

    if policy.get("allowed") is not True:
        errors.append(_error("allowed", "allowed must be true."))

    render_modes = _require_string_list(policy, "render_modes", errors)
    for mode in render_modes:
        if mode not in contract.render_modes:
            errors.append(_error("render_modes", "render mode unsupported."))

    _require_positive_int(policy, "max_packets", errors)
    if not isinstance(policy.get("require_successful_retrieval"), bool):
        errors.append(
            _error(
                "require_successful_retrieval",
                "require_successful_retrieval must be boolean.",
            )
        )

    allowed_context_types = _require_string_list(
        policy,
        "allowed_context_types",
        errors,
    )
    for context_type in allowed_context_types:
        if context_type not in contract.context_types:
            errors.append(
                _error("allowed_context_types", "context_type unsupported.")
            )

    allowed_lookup_types = _optional_string_list(
        policy,
        "allowed_lookup_types",
        errors,
    )
    for lookup_type in allowed_lookup_types:
        if lookup_type not in contract.lookup_types:
            errors.append(
                _error("allowed_lookup_types", "lookup_type unsupported.")
            )

    _optional_string_list(policy, "allowed_source_scopes", errors)
    _optional_string_list(policy, "allowed_entity_types", errors)

    field_order = _require_string_list(policy, "field_order", errors)
    field_labels = policy.get("field_labels")
    if not isinstance(field_labels, dict):
        errors.append(_error("field_labels", "field_labels must be an object."))
    else:
        for field in field_order:
            label = field_labels.get(field, field)
            if not _non_empty_string(label):
                errors.append(
                    _error(
                        "field_labels",
                        "field labels must be non-empty strings.",
                    )
                )

    return errors


def validate_lookup_context_injection_policy(
    policy: dict[str, Any] | None,
    *,
    contract: LookupCapabilityContract | None = None,
) -> list[LookupPolicyValidationError]:
    contract = contract or get_lookup_capability_contract()
    errors: list[LookupPolicyValidationError] = []
    if contract is None:
        return [_error("lookup_capability_contract", "contract unavailable.")]

    if not isinstance(policy, dict):
        return [_error("injection_policy", "policy must be an object.")]

    if policy.get("allowed") is not True:
        errors.append(_error("allowed", "allowed must be true."))

    if policy.get("require_render_decision") is not True:
        errors.append(
            _error(
                "require_render_decision",
                "require_render_decision must be true.",
            )
        )

    if policy.get("require_rendered_context") is not True:
        errors.append(
            _error(
                "require_rendered_context",
                "require_rendered_context must be true.",
            )
        )

    content_types = _require_string_list(
        policy,
        "allowed_content_types",
        errors,
    )
    for content_type in content_types:
        if content_type not in contract.content_types:
            errors.append(
                _error("allowed_content_types", "content_type unsupported.")
            )

    render_modes = _require_string_list(policy, "allowed_render_modes", errors)
    for mode in render_modes:
        if mode not in contract.render_modes:
            errors.append(
                _error("allowed_render_modes", "render mode unsupported.")
            )

    errors.extend(validate_lookup_context_budget_policy(
        policy,
        contract=contract,
    ))
    return errors


def validate_lookup_context_budget_policy(
    policy: dict[str, Any] | None,
    *,
    contract: LookupCapabilityContract | None = None,
) -> list[LookupPolicyValidationError]:
    contract = contract or get_lookup_capability_contract()
    errors: list[LookupPolicyValidationError] = []
    if contract is None:
        return [_error("lookup_capability_contract", "contract unavailable.")]

    if not isinstance(policy, dict):
        return [_error("budget_policy", "policy must be an object.")]

    _require_positive_int(policy, "max_blocks", errors)
    _require_positive_int(policy, "max_facts_per_block", errors)
    _require_positive_int(policy, "max_total_characters", errors)

    if policy.get("truncation_mode") not in contract.truncation_modes:
        errors.append(
            _error("truncation_mode", "truncation_mode is unsupported.")
        )

    return errors


def validate_lookup_execution_policy(
    policy: dict[str, Any] | None,
    *,
    contract: LookupCapabilityContract | None = None,
) -> list[LookupPolicyValidationError]:
    contract = contract or get_lookup_capability_contract()
    errors: list[LookupPolicyValidationError] = []
    if contract is None:
        return [_error("lookup_capability_contract", "contract unavailable.")]

    normalized = normalize_lookup_execution_policy(policy)
    if normalized is None:
        return [_error("policy", "policy is malformed.")]

    if normalized.cancellation_behavior not in contract.cancellation_behaviors:
        errors.append(
            _error(
                "cancellation_behavior",
                "cancellation_behavior is unsupported.",
            )
        )

    return errors


def validate_lookup_capability_compatibility(
    policy: dict[str, Any] | None,
    *,
    contract: LookupCapabilityContract | None = None,
) -> list[LookupPolicyValidationError]:
    contract = contract or get_lookup_capability_contract()
    if contract is None:
        return [_error("lookup_capability_contract", "contract unavailable.")]

    if contract.contract_version != LOOKUP_CAPABILITY_CONTRACT_VERSION:
        return [_error("contract_version", "contract version is unsupported.")]

    if (
        contract.runtime_compatibility_version
        != LOOKUP_RUNTIME_COMPATIBILITY_VERSION
    ):
        return [
            _error(
                "runtime_compatibility_version",
                "runtime compatibility version is unsupported.",
            )
        ]

    normalized = normalize_lookup_capability_compatibility(
        policy,
        supported_features=contract.supported_features,
    )
    if normalized is None:
        return [_error("policy", "compatibility policy is incompatible.")]

    return []


def validate_lookup_capability_policies(
    binding_policy: dict[str, Any] | None,
    *,
    contract: LookupCapabilityContract | None = None,
) -> list[LookupPolicyValidationError]:
    contract = contract or get_lookup_capability_contract()
    if contract is None:
        return [_error("lookup_capability_contract", "contract unavailable.")]

    if not isinstance(binding_policy, dict):
        return [_error("binding_policy", "binding policy must be an object.")]

    errors: list[LookupPolicyValidationError] = []
    errors.extend(
        _error(f"lookup_capability_compatibility.{error.field}", error.message)
        for error in validate_lookup_capability_compatibility(
            binding_policy.get("lookup_capability_compatibility"),
            contract=contract,
        )
    )

    governance = normalize_lookup_governance_policy(
        binding_policy.get("lookup_capability_governance")
    )
    if governance is None:
        errors.append(
            _error(
                "lookup_capability_governance",
                "lookup capability governance is malformed.",
            )
        )
    elif governance.state not in contract.governance_states:
        errors.append(
            _error(
                "lookup_capability_governance.state",
                "lookup capability governance state is unsupported.",
            )
        )

    errors.extend(
        _error(f"lookup_execution_policy.{error.field}", error.message)
        for error in validate_lookup_execution_policy(
            binding_policy.get("lookup_execution_policy"),
            contract=contract,
        )
    )

    validators = {
        "lookup_request_policy": validate_lookup_request_policy,
        "lookup_context_materialization_policy": (
            validate_lookup_context_materialization_policy
        ),
        "lookup_context_render_policy": validate_lookup_context_render_policy,
        "lookup_context_injection_policy": (
            validate_lookup_context_injection_policy
        ),
    }
    for section in contract.required_policy_sections:
        if section not in binding_policy:
            errors.append(_error(section, "required policy section missing."))

    for field, validator in validators.items():
        for error in validator(binding_policy.get(field), contract=contract):
            errors.append(_error(f"{field}.{error.field}", error.message))

    return errors


@lru_cache(maxsize=None)
def _load_lookup_capability_contracts(
    root: str,
) -> tuple[LookupCapabilityContract, ...]:
    entries = _compose_lookup_capability_contract_entries(Path(root))
    if entries is None:
        return ()

    loaded: list[LookupCapabilityContract] = []
    for entry in entries:
        contract = _contract_from_entry(entry)
        if contract is not None:
            loaded.append(contract)

    ids = [contract.id for contract in loaded]
    if len(ids) != len(set(ids)):
        return ()

    return tuple(loaded)


def _compose_lookup_capability_contract_entries(
    root: Path,
) -> list[dict[str, Any]] | None:
    merged: dict[str, dict[str, Any]] = {}

    for relative_path in LOOKUP_CONTRACT_SECTION_PATHS:
        entries = _load_contract_section_entries(root / relative_path)
        if entries is None:
            return None

        for entry in entries:
            if not isinstance(entry, dict):
                return None

            contract_id = entry.get("id")
            if not _non_empty_string(contract_id):
                return None

            target = merged.setdefault(contract_id.strip(), {})
            overlap = set(target).intersection(entry) - {"id"}
            if overlap:
                return None

            target.update(entry)

    return list(merged.values())


def _load_contract_section_entries(path: Path) -> list[Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict) or data.get("version") != 1:
        return None

    contracts = data.get("contracts")
    if not isinstance(contracts, list):
        return None

    return contracts


def _contract_from_entry(entry: Any) -> LookupCapabilityContract | None:
    if not isinstance(entry, dict):
        return None

    policy_sections = entry.get("policy_sections")
    planner_contract = entry.get("planner_contract")
    fail_closed = entry.get("fail_closed")
    if (
        not isinstance(policy_sections, dict)
        or not isinstance(planner_contract, dict)
        or not isinstance(fail_closed, dict)
        or any(value is not True for value in fail_closed.values())
    ):
        return None

    contract_id = entry.get("id")
    capability_type = entry.get("capability_type")
    retrieval_concept = entry.get("retrieval_concept")
    retrieval_specialization = entry.get("retrieval_specialization")
    retrieval_scope = entry.get("retrieval_scope")
    if not _non_empty_string(contract_id) or not _non_empty_string(
        capability_type
    ):
        return None
    if (
        retrieval_concept != "retrieval"
        or retrieval_specialization != "lookup"
        or retrieval_scope != "bounded"
    ):
        return None

    contract_version = entry.get("contract_version")
    runtime_compatibility_version = entry.get(
        "runtime_compatibility_version"
    )
    if not _positive_int(contract_version) or not _positive_int(
        runtime_compatibility_version
    ):
        return None

    supported_features = _string_tuple(entry.get("supported_features"))
    if not supported_features:
        return None

    required_sections = _string_tuple(policy_sections.get("required"))
    if not required_sections:
        return None

    governance_states = _string_tuple(entry.get("governance_states"))
    if not governance_states:
        return None

    cancellation_behaviors = _string_tuple(entry.get("cancellation_behaviors"))
    if not cancellation_behaviors:
        return None

    return LookupCapabilityContract(
        id=contract_id.strip(),
        capability_type=capability_type.strip(),
        retrieval_concept=retrieval_concept.strip(),
        retrieval_specialization=retrieval_specialization.strip(),
        retrieval_scope=retrieval_scope.strip(),
        contract_version=contract_version,
        runtime_compatibility_version=runtime_compatibility_version,
        lookup_types=_string_tuple(entry.get("lookup_types")),
        supported_features=supported_features,
        required_policy_sections=required_sections,
        agent_owned_values=_string_tuple(
            policy_sections.get("agent_owned_values"),
            allow_empty=True,
        ),
        render_modes=_string_tuple(entry.get("render_modes")),
        context_types=_string_tuple(entry.get("context_types")),
        content_types=_string_tuple(entry.get("content_types")),
        truncation_modes=_string_tuple(entry.get("truncation_modes")),
        governance_states=governance_states,
        cancellation_behaviors=cancellation_behaviors,
        required_planner_fields=_string_tuple(
            planner_contract.get("required_fields")
        ),
        optional_planner_fields=_string_tuple(
            planner_contract.get("optional_fields"),
            allow_empty=True,
        ),
        agent_policy_fields_forbidden=_string_tuple(
            planner_contract.get("agent_policy_fields_forbidden"),
            allow_empty=True,
        ),
        fail_closed=dict(fail_closed),
    )


def _require_non_empty_string(
    policy: dict[str, Any],
    field: str,
    errors: list[LookupPolicyValidationError],
) -> None:
    if not _non_empty_string(policy.get(field)):
        errors.append(_error(field, f"{field} must be a non-empty string."))


def _require_string_list(
    policy: dict[str, Any],
    field: str,
    errors: list[LookupPolicyValidationError],
) -> tuple[str, ...]:
    value = policy.get(field)
    if (
        not isinstance(value, list)
        or not value
        or any(not _non_empty_string(item) for item in value)
    ):
        errors.append(_error(field, f"{field} must be a string list."))
        return ()

    return tuple(item.strip() for item in value)


def _optional_string_list(
    policy: dict[str, Any],
    field: str,
    errors: list[LookupPolicyValidationError],
) -> tuple[str, ...]:
    if field not in policy or policy.get(field) is None:
        return ()

    return _require_string_list(policy, field, errors)


def _require_positive_int(
    policy: dict[str, Any],
    field: str,
    errors: list[LookupPolicyValidationError],
) -> None:
    if not _positive_int(policy.get(field)):
        errors.append(_error(field, f"{field} must be a positive integer."))


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_tuple(value: Any, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()

    if not value and allow_empty:
        return ()

    if not value or any(not _non_empty_string(item) for item in value):
        return ()

    return tuple(item.strip() for item in value)


def _error(field: str, message: str) -> LookupPolicyValidationError:
    return LookupPolicyValidationError(field=field, message=message)


__all__ = [
    "LOOKUP_CAPABILITY_CONTRACTS_PATH",
    "LOOKUP_EXECUTION_POLICY_PATH",
    "LOOKUP_GOVERNANCE_STATES_PATH",
    "LOOKUP_RENDER_CONTRACTS_PATH",
    "LOOKUP_REQUEST_CONTRACTS_PATH",
    "LOOKUP_RUNTIME_COMPATIBILITY_CONTRACTS_PATH",
    "LookupCapabilityContract",
    "LookupPolicyValidationError",
    "get_lookup_capability_contract",
    "load_lookup_capability_contracts",
    "validate_lookup_capability_policies",
    "validate_lookup_capability_compatibility",
    "validate_lookup_context_budget_policy",
    "validate_lookup_context_injection_policy",
    "validate_lookup_context_materialization_policy",
    "validate_lookup_context_render_policy",
    "validate_lookup_execution_policy",
    "validate_lookup_request_policy",
]
