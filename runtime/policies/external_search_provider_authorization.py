from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from runtime.governance.operational_controls import (
    OperationalControlDecision,
    evaluate_provider_authorization_control,
    evaluate_tavily_execution_control,
)


EXTERNAL_SEARCH_PROVIDER_AUTHORIZATION_CONTRACTS_PATH = Path(
    "agents/shared/contracts/external_search_provider_authorization_contracts.json"
)
EXTERNAL_SEARCH_PROVIDER_AUTHORIZATION_GOVERNANCE_PATH = Path(
    "agents/shared/governance/external_search_provider_authorization.json"
)
EXTERNAL_SEARCH_PROVIDER_AUTHORIZATION_POLICY_PATH = Path(
    "agents/shared/policies/external_search_provider_authorization_policy.json"
)
EXTERNAL_SEARCH_PROVIDER_BINDINGS_PATH = Path(
    "agents/shared/bindings/external_search_providers.json"
)

AUTHORIZATION_STATE_BLOCKED = "blocked"
AUTHORIZATION_STATE_AUDIT_ONLY = "audit_only"
AUTHORIZATION_STATE_ALLOWED = "allowed"
AUTHORIZATION_STATUS_ALLOWED = "allowed"
AUTHORIZATION_STATUS_BLOCKED = "blocked"
AUTHORIZATION_STATUS_AUDIT_ONLY = "audit_only"
PROVIDER_CONFIGURATION_STATE_CONFIGURED = "configured"
PROVIDER_CONFIGURATION_STATE_MISSING = "missing"
PROVIDER_CONFIGURATION_STATE_NOT_APPLICABLE = "not_applicable"
TAVILY_PROVIDER_ID = "tavily"
TAVILY_API_KEY_ENV_VAR = "TAVILY_API_KEY"
ALLOWED_AUTHORIZATION_STATES = frozenset(
    {
        AUTHORIZATION_STATE_BLOCKED,
        AUTHORIZATION_STATE_AUDIT_ONLY,
        AUTHORIZATION_STATE_ALLOWED,
    }
)
FORBIDDEN_BINDING_FIELDS = {
    "adapter_id",
    "api_key",
    "browser_callable",
    "credential_env_var",
    "executor",
    "fallback_provider_id",
    "model",
    "normalizer",
    "provider_options",
    "ranking",
    "summarizer",
}
FORBIDDEN_AUDIT_FIELDS = {
    "api_key",
    "citations",
    "credential",
    "provider_payload",
    "query",
    "raw_provider_payload",
    "raw_results",
    "rendered_context",
    "search_intent",
    "source_refs",
}


class ExternalSearchProviderAuthorizationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExternalSearchProviderAuthorizationContract:
    id: str
    semantic_type: str
    authorization_states: tuple[str, ...]
    required_decision_fields: tuple[str, ...]
    content_safe_audit_fields: tuple[str, ...]
    forbidden_audit_fields: tuple[str, ...]
    fail_closed: dict[str, bool]
    semantic_authority: dict[str, bool]


@dataclass(frozen=True)
class ExternalSearchProviderAuthorizationGovernance:
    id: str
    default_authorization_state: str
    authorization_states: tuple[str, ...]
    provider_authorizations: dict[tuple[str, str], str]


@dataclass(frozen=True)
class ExternalSearchProviderAuthorizationPolicy:
    id: str
    semantic_type: str
    state_policy: dict[str, dict[str, bool]]
    runtime_bounds: dict[str, bool]


@dataclass(frozen=True)
class ExternalSearchProviderBinding:
    binding_id: str
    semantic_type: str
    provider_id: str
    provider_type: str
    resource_id: str
    contract_id: str
    governance_id: str
    policy_id: str


@dataclass(frozen=True)
class ExternalSearchProviderConfigurationDiagnostic:
    provider_id: str | None
    provider_type: str | None
    credential_state: str
    credential_configured: bool
    canonical_env_var: str | None

    def to_audit_record(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_type": self.provider_type,
            "credential_state": self.credential_state,
            "credential_configured": self.credential_configured,
            "canonical_env_var": self.canonical_env_var,
        }


@dataclass(frozen=True)
class ExternalSearchProviderAuthorizationInput:
    provider_id: str | None
    resource_id: str | None = None
    semantic_type: str = "external_search"


@dataclass(frozen=True)
class ExternalSearchProviderAuthorizationDecision:
    provider_id: str | None
    resource_id: str | None
    semantic_type: str
    authorization_state: str
    authorization_status: str
    live_provider_execution_authorized: bool
    external_call_allowed: bool
    cost_allowed: bool
    audit_required: bool
    fail_closed: bool
    skipped_reasons: tuple[str, ...]
    policy_id: str | None = None
    governance_id: str | None = None
    binding_id: str | None = None
    contract_id: str | None = None
    provider_configuration: ExternalSearchProviderConfigurationDiagnostic | None = None
    operational_controls: tuple[OperationalControlDecision, ...] = ()

    def to_audit_record(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "resource_id": self.resource_id,
            "semantic_type": self.semantic_type,
            "authorization_state": self.authorization_state,
            "authorization_status": self.authorization_status,
            "live_provider_execution_authorized": (
                self.live_provider_execution_authorized
            ),
            "external_call_allowed": self.external_call_allowed,
            "cost_allowed": self.cost_allowed,
            "audit_required": self.audit_required,
            "fail_closed": self.fail_closed,
            "policy_id": self.policy_id,
            "governance_id": self.governance_id,
            "binding_id": self.binding_id,
            "contract_id": self.contract_id,
            "provider_configuration": (
                self.provider_configuration.to_audit_record()
                if self.provider_configuration is not None
                else None
            ),
            "operational_controls": [
                control.to_diagnostics() for control in self.operational_controls
            ],
            "skipped_reasons": list(self.skipped_reasons),
        }


def evaluate_external_search_provider_authorization(
    request: ExternalSearchProviderAuthorizationInput,
    *,
    root: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> ExternalSearchProviderAuthorizationDecision:
    contract = load_external_search_provider_authorization_contract(root)
    governance = load_external_search_provider_authorization_governance(root)
    policy = load_external_search_provider_authorization_policy(root)
    bindings = load_external_search_provider_bindings(root)

    provider_id = _safe_optional_string(request.provider_id)
    resource_id = _safe_optional_string(request.resource_id)
    semantic_type = _safe_optional_string(request.semantic_type) or "external_search"
    skipped_reasons: list[str] = []

    if contract is None:
        skipped_reasons.append("malformed_contract")
    if governance is None:
        skipped_reasons.append("malformed_governance")
    if policy is None:
        skipped_reasons.append("malformed_policy")
    if bindings is None:
        skipped_reasons.append("malformed_binding")
    if provider_id is None:
        skipped_reasons.append("missing_provider_id")

    binding = None
    if provider_id and bindings:
        binding = _matching_binding(
            bindings,
            provider_id=provider_id,
            resource_id=resource_id,
            semantic_type=semantic_type,
        )
        if binding is None:
            skipped_reasons.append("missing_provider_binding")
        else:
            resource_id = resource_id or binding.resource_id

    provider_configuration = evaluate_external_search_provider_configuration(
        provider_id=provider_id,
        provider_type=binding.provider_type if binding else None,
        environ=environ,
    )
    operational_controls = _evaluate_operational_provider_controls(
        provider_id,
        root=root,
        environ=environ,
    )

    state = AUTHORIZATION_STATE_BLOCKED
    if governance and provider_id and resource_id:
        state = governance.provider_authorizations.get(
            (provider_id, resource_id),
            governance.default_authorization_state,
        )
        if (provider_id, resource_id) not in governance.provider_authorizations:
            skipped_reasons.append("missing_provider_authorization")
    elif provider_id:
        skipped_reasons.append("missing_provider_authorization")

    if state not in ALLOWED_AUTHORIZATION_STATES:
        state = AUTHORIZATION_STATE_BLOCKED
        skipped_reasons.append("unknown_authorization_state")

    if state == AUTHORIZATION_STATE_ALLOWED:
        for control in operational_controls:
            if not control.allowed:
                skipped_reasons.extend(control.reason_codes)

    state_policy = policy.state_policy.get(state, {}) if policy else {}
    live_authorized = bool(state_policy.get("live_provider_execution_authorized"))
    external_call_allowed = bool(state_policy.get("external_call_allowed"))
    cost_allowed = bool(state_policy.get("cost_allowed"))
    audit_required = bool(state_policy.get("audit_required", True))

    if state != AUTHORIZATION_STATE_ALLOWED:
        skipped_reasons.append("state_not_allowed")
    if not live_authorized:
        skipped_reasons.append("policy_disallows_live_execution")

    fail_closed = bool(skipped_reasons)
    if fail_closed:
        status = (
            AUTHORIZATION_STATUS_AUDIT_ONLY
            if state == AUTHORIZATION_STATE_AUDIT_ONLY
            and skipped_reasons
            == ["state_not_allowed", "policy_disallows_live_execution"]
            else AUTHORIZATION_STATUS_BLOCKED
        )
        live_authorized = False
        external_call_allowed = False
        cost_allowed = False
    else:
        status = AUTHORIZATION_STATUS_ALLOWED

    return ExternalSearchProviderAuthorizationDecision(
        provider_id=provider_id,
        resource_id=resource_id,
        semantic_type=semantic_type,
        authorization_state=state,
        authorization_status=status,
        live_provider_execution_authorized=live_authorized,
        external_call_allowed=external_call_allowed,
        cost_allowed=cost_allowed,
        audit_required=audit_required,
        fail_closed=fail_closed,
        skipped_reasons=tuple(dict.fromkeys(skipped_reasons)),
        policy_id=policy.id if policy else None,
        governance_id=governance.id if governance else None,
        binding_id=binding.binding_id if binding else None,
        contract_id=contract.id if contract else None,
        provider_configuration=provider_configuration,
        operational_controls=operational_controls,
    )


def _evaluate_operational_provider_controls(
    provider_id: str | None,
    *,
    root: str | Path | None,
    environ: Mapping[str, str] | None = None,
) -> tuple[OperationalControlDecision, ...]:
    controls = [
        evaluate_provider_authorization_control(provider_id, root=root, environ=environ),
    ]
    if provider_id == TAVILY_PROVIDER_ID:
        controls.append(evaluate_tavily_execution_control(root=root, environ=environ))
    return tuple(controls)


def resolve_tavily_api_key(
    environ: Mapping[str, str] | None = None,
) -> tuple[str | None, ExternalSearchProviderConfigurationDiagnostic]:
    env = os.environ if environ is None else environ
    canonical = _safe_optional_string(env.get(TAVILY_API_KEY_ENV_VAR))

    if canonical is not None:
        return canonical, ExternalSearchProviderConfigurationDiagnostic(
            provider_id=TAVILY_PROVIDER_ID,
            provider_type=TAVILY_PROVIDER_ID,
            credential_state=PROVIDER_CONFIGURATION_STATE_CONFIGURED,
            credential_configured=True,
            canonical_env_var=TAVILY_API_KEY_ENV_VAR,
        )

    return None, ExternalSearchProviderConfigurationDiagnostic(
        provider_id=TAVILY_PROVIDER_ID,
        provider_type=TAVILY_PROVIDER_ID,
        credential_state=PROVIDER_CONFIGURATION_STATE_MISSING,
        credential_configured=False,
        canonical_env_var=TAVILY_API_KEY_ENV_VAR,
    )


def evaluate_external_search_provider_configuration(
    *,
    provider_id: str | None,
    provider_type: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> ExternalSearchProviderConfigurationDiagnostic:
    normalized_provider_id = _safe_optional_string(provider_id)
    normalized_provider_type = _safe_optional_string(provider_type)
    if normalized_provider_id == TAVILY_PROVIDER_ID:
        _, diagnostic = resolve_tavily_api_key(environ=environ)
        return diagnostic
    return ExternalSearchProviderConfigurationDiagnostic(
        provider_id=normalized_provider_id,
        provider_type=normalized_provider_type,
        credential_state=PROVIDER_CONFIGURATION_STATE_NOT_APPLICABLE,
        credential_configured=False,
        canonical_env_var=None,
    )


def validate_external_search_live_provider_execution_authorization(
    decision: ExternalSearchProviderAuthorizationDecision | None,
) -> tuple[str, ...]:
    if decision is None:
        return ("missing_provider_authorization",)
    reasons: list[str] = []
    if decision.authorization_state != AUTHORIZATION_STATE_ALLOWED:
        reasons.append("state_not_allowed")
    if decision.live_provider_execution_authorized is not True:
        reasons.append("live_provider_execution_not_authorized")
    if decision.external_call_allowed is not True:
        reasons.append("external_call_not_allowed")
    if decision.cost_allowed is not True:
        reasons.append("cost_not_allowed")
    if decision.fail_closed:
        reasons.append("authorization_failed_closed")
    return tuple(dict.fromkeys(reasons))


def validate_authorization_audit_record(record: Any) -> tuple[str, ...]:
    if not isinstance(record, dict):
        return ("audit_record_not_object",)
    forbidden = sorted(FORBIDDEN_AUDIT_FIELDS & set(record))
    return tuple(f"forbidden_audit_field:{field}" for field in forbidden)


@lru_cache(maxsize=None)
def load_external_search_provider_authorization_contract(
    root: str | Path | None = None,
) -> ExternalSearchProviderAuthorizationContract | None:
    try:
        data = _read_json(EXTERNAL_SEARCH_PROVIDER_AUTHORIZATION_CONTRACTS_PATH, root)
        contracts = data.get("contracts")
        if not isinstance(contracts, list) or len(contracts) != 1:
            raise ExternalSearchProviderAuthorizationError("contract list invalid")
        return _contract_from_entry(contracts[0])
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        ExternalSearchProviderAuthorizationError,
    ):
        return None


@lru_cache(maxsize=None)
def load_external_search_provider_authorization_governance(
    root: str | Path | None = None,
) -> ExternalSearchProviderAuthorizationGovernance | None:
    try:
        data = _read_json(EXTERNAL_SEARCH_PROVIDER_AUTHORIZATION_GOVERNANCE_PATH, root)
        if data.get("version") != 1:
            raise ExternalSearchProviderAuthorizationError("governance version invalid")
        states = _string_tuple(data.get("authorization_states"))
        _require_exact_states(states)
        default_state = _required_state(data.get("default_authorization_state"))
        entries = data.get("provider_authorizations")
        if not isinstance(entries, list):
            raise ExternalSearchProviderAuthorizationError("authorization list invalid")
        authorizations: dict[tuple[str, str], str] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise ExternalSearchProviderAuthorizationError(
                    "authorization entries must be objects"
                )
            provider_id = _required_string(entry.get("provider_id"))
            resource_id = _required_string(entry.get("resource_id"))
            state = _required_state(entry.get("authorization_state"))
            authorizations[(provider_id, resource_id)] = state
        return ExternalSearchProviderAuthorizationGovernance(
            id=_required_string(data.get("id")),
            default_authorization_state=default_state,
            authorization_states=states,
            provider_authorizations=authorizations,
        )
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        ExternalSearchProviderAuthorizationError,
    ):
        return None


@lru_cache(maxsize=None)
def load_external_search_provider_authorization_policy(
    root: str | Path | None = None,
) -> ExternalSearchProviderAuthorizationPolicy | None:
    try:
        data = _read_json(EXTERNAL_SEARCH_PROVIDER_AUTHORIZATION_POLICY_PATH, root)
        if data.get("version") != 1:
            raise ExternalSearchProviderAuthorizationError("policy version invalid")
        if data.get("semantic_type") != "external_search":
            raise ExternalSearchProviderAuthorizationError("policy semantic type invalid")
        state_policy = data.get("state_policy")
        if not isinstance(state_policy, dict):
            raise ExternalSearchProviderAuthorizationError("state policy invalid")
        if set(state_policy) != ALLOWED_AUTHORIZATION_STATES:
            raise ExternalSearchProviderAuthorizationError("state policy states invalid")
        parsed_state_policy: dict[str, dict[str, bool]] = {}
        for state, behavior in state_policy.items():
            parsed_state_policy[state] = _bool_object(behavior)
        if parsed_state_policy[AUTHORIZATION_STATE_BLOCKED].get(
            "live_provider_execution_authorized"
        ) is not False:
            raise ExternalSearchProviderAuthorizationError("blocked state can execute")
        if parsed_state_policy[AUTHORIZATION_STATE_AUDIT_ONLY].get(
            "live_provider_execution_authorized"
        ) is not False:
            raise ExternalSearchProviderAuthorizationError("audit_only state can execute")
        if parsed_state_policy[AUTHORIZATION_STATE_ALLOWED].get(
            "live_provider_execution_authorized"
        ) is not True:
            raise ExternalSearchProviderAuthorizationError("allowed state cannot execute")
        runtime_bounds = _bool_object(data.get("runtime_bounds"))
        for required_false in (
            "authorization_must_not_select_provider",
            "authorization_must_not_select_semantic_intent",
            "content_safe_audit_required",
        ):
            if runtime_bounds.get(required_false) is not True:
                raise ExternalSearchProviderAuthorizationError(
                    "required runtime bound missing"
                )
        for required_false in (
            "fallback_execution_allowed",
            "silent_retrieval_escalation_allowed",
            "memory_writes_allowed",
        ):
            if runtime_bounds.get(required_false) is not False:
                raise ExternalSearchProviderAuthorizationError(
                    "forbidden runtime bound enabled"
                )
        return ExternalSearchProviderAuthorizationPolicy(
            id=_required_string(data.get("id")),
            semantic_type="external_search",
            state_policy=parsed_state_policy,
            runtime_bounds=runtime_bounds,
        )
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        ExternalSearchProviderAuthorizationError,
    ):
        return None


@lru_cache(maxsize=None)
def load_external_search_provider_bindings(
    root: str | Path | None = None,
) -> tuple[ExternalSearchProviderBinding, ...] | None:
    try:
        data = _read_json(EXTERNAL_SEARCH_PROVIDER_BINDINGS_PATH, root)
        if data.get("version") != 1:
            raise ExternalSearchProviderAuthorizationError("binding version invalid")
        entries = data.get("bindings")
        if not isinstance(entries, list):
            raise ExternalSearchProviderAuthorizationError("binding list invalid")
        bindings = tuple(_binding_from_entry(entry) for entry in entries)
        if len({binding.binding_id for binding in bindings}) != len(bindings):
            raise ExternalSearchProviderAuthorizationError("duplicate binding id")
        return bindings
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        ExternalSearchProviderAuthorizationError,
    ):
        return None


def _contract_from_entry(
    entry: Any,
) -> ExternalSearchProviderAuthorizationContract:
    if not isinstance(entry, dict):
        raise ExternalSearchProviderAuthorizationError("contract entry invalid")
    states = _string_tuple(entry.get("authorization_states"))
    _require_exact_states(states)
    safe_fields = _string_tuple(entry.get("content_safe_audit_fields"))
    forbidden_fields = _string_tuple(entry.get("forbidden_audit_fields"))
    if FORBIDDEN_AUDIT_FIELDS & set(safe_fields):
        raise ExternalSearchProviderAuthorizationError("unsafe audit field exposed")
    if not FORBIDDEN_AUDIT_FIELDS.issubset(set(forbidden_fields)):
        raise ExternalSearchProviderAuthorizationError("forbidden audit fields missing")
    fail_closed = _bool_object(entry.get("fail_closed"))
    if any(value is not True for value in fail_closed.values()):
        raise ExternalSearchProviderAuthorizationError("fail closed contract invalid")
    semantic_authority = _bool_object(entry.get("semantic_authority"))
    if any(value is not False for value in semantic_authority.values()):
        raise ExternalSearchProviderAuthorizationError(
            "authorization contract grants semantic authority"
        )
    return ExternalSearchProviderAuthorizationContract(
        id=_required_string(entry.get("id")),
        semantic_type=_required_string(entry.get("semantic_type")),
        authorization_states=states,
        required_decision_fields=_string_tuple(entry.get("required_decision_fields")),
        content_safe_audit_fields=safe_fields,
        forbidden_audit_fields=forbidden_fields,
        fail_closed=fail_closed,
        semantic_authority=semantic_authority,
    )


def _binding_from_entry(entry: Any) -> ExternalSearchProviderBinding:
    if not isinstance(entry, dict):
        raise ExternalSearchProviderAuthorizationError("binding entry invalid")
    forbidden_paths = _forbidden_field_paths(entry)
    if forbidden_paths:
        raise ExternalSearchProviderAuthorizationError(
            "binding contains forbidden fields"
        )
    allowed_fields = {
        "binding_id",
        "contract_id",
        "governance_id",
        "policy_id",
        "provider_id",
        "provider_type",
        "resource_id",
        "semantic_type",
    }
    if set(entry) != allowed_fields:
        raise ExternalSearchProviderAuthorizationError(
            "binding must contain only provider/resource/policy references"
        )
    if entry.get("semantic_type") != "external_search":
        raise ExternalSearchProviderAuthorizationError("binding semantic type invalid")
    return ExternalSearchProviderBinding(
        binding_id=_required_string(entry.get("binding_id")),
        semantic_type="external_search",
        provider_id=_required_string(entry.get("provider_id")),
        provider_type=_required_string(entry.get("provider_type")),
        resource_id=_required_string(entry.get("resource_id")),
        contract_id=_required_string(entry.get("contract_id")),
        governance_id=_required_string(entry.get("governance_id")),
        policy_id=_required_string(entry.get("policy_id")),
    )


def _matching_binding(
    bindings: tuple[ExternalSearchProviderBinding, ...],
    *,
    provider_id: str,
    resource_id: str | None,
    semantic_type: str,
) -> ExternalSearchProviderBinding | None:
    for binding in bindings:
        if binding.provider_id != provider_id or binding.semantic_type != semantic_type:
            continue
        if resource_id is not None and binding.resource_id != resource_id:
            continue
        return binding
    return None


def _read_json(path: Path, root: str | Path | None) -> dict[str, Any]:
    full_path = path if root is None else Path(root) / path
    data = json.loads(full_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ExternalSearchProviderAuthorizationError("json root must be object")
    return data


def _require_exact_states(states: tuple[str, ...]) -> None:
    if set(states) != ALLOWED_AUTHORIZATION_STATES:
        raise ExternalSearchProviderAuthorizationError("authorization states invalid")


def _required_state(value: Any) -> str:
    state = _required_string(value)
    if state not in ALLOWED_AUTHORIZATION_STATES:
        raise ExternalSearchProviderAuthorizationError("authorization state invalid")
    return state


def _required_string(value: Any) -> str:
    normalized = _safe_optional_string(value)
    if normalized is None:
        raise ExternalSearchProviderAuthorizationError("string required")
    return normalized


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        _safe_optional_string(item) is None for item in value
    ):
        raise ExternalSearchProviderAuthorizationError("string list required")
    return tuple(str(item).strip() for item in value)


def _bool_object(value: Any) -> dict[str, bool]:
    if (
        not isinstance(value, dict)
        or not value
        or any(not isinstance(item, bool) for item in value.values())
    ):
        raise ExternalSearchProviderAuthorizationError("boolean object required")
    return dict(value)


def _forbidden_field_paths(value: Any, *, prefix: str = "") -> tuple[str, ...]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, item in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if key_text in FORBIDDEN_BINDING_FIELDS:
                paths.append(path)
            paths.extend(_forbidden_field_paths(item, prefix=path))
        return tuple(paths)
    if isinstance(value, list):
        paths = []
        for index, item in enumerate(value):
            paths.extend(_forbidden_field_paths(item, prefix=f"{prefix}[{index}]"))
        return tuple(paths)
    return ()


def _safe_optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "AUTHORIZATION_STATE_ALLOWED",
    "AUTHORIZATION_STATE_AUDIT_ONLY",
    "AUTHORIZATION_STATE_BLOCKED",
    "AUTHORIZATION_STATUS_ALLOWED",
    "AUTHORIZATION_STATUS_AUDIT_ONLY",
    "AUTHORIZATION_STATUS_BLOCKED",
    "ALLOWED_AUTHORIZATION_STATES",
    "EXTERNAL_SEARCH_PROVIDER_AUTHORIZATION_CONTRACTS_PATH",
    "EXTERNAL_SEARCH_PROVIDER_AUTHORIZATION_GOVERNANCE_PATH",
    "EXTERNAL_SEARCH_PROVIDER_AUTHORIZATION_POLICY_PATH",
    "EXTERNAL_SEARCH_PROVIDER_BINDINGS_PATH",
    "PROVIDER_CONFIGURATION_STATE_CONFIGURED",
    "PROVIDER_CONFIGURATION_STATE_MISSING",
    "PROVIDER_CONFIGURATION_STATE_NOT_APPLICABLE",
    "TAVILY_API_KEY_ENV_VAR",
    "TAVILY_PROVIDER_ID",
    "ExternalSearchProviderAuthorizationDecision",
    "ExternalSearchProviderAuthorizationError",
    "ExternalSearchProviderAuthorizationInput",
    "ExternalSearchProviderConfigurationDiagnostic",
    "evaluate_external_search_provider_authorization",
    "evaluate_external_search_provider_configuration",
    "load_external_search_provider_authorization_contract",
    "load_external_search_provider_authorization_governance",
    "load_external_search_provider_authorization_policy",
    "load_external_search_provider_bindings",
    "resolve_tavily_api_key",
    "validate_authorization_audit_record",
    "validate_external_search_live_provider_execution_authorization",
]
