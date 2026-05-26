from __future__ import annotations

from typing import Any, Mapping, Sequence

from runtime.governance.boundary_terms import (
    AUTONOMY_FIELDS,
    MEMORY_FIELDS,
    MUTATION_FIELDS,
    SEMANTIC_MUTATION_FIELDS,
    SUBSTRATE_STATE_FIELDS,
    SUBSTRATES,
)
from runtime.governance.substrate_boundary import (
    CROSS_SUBSTRATE_CONTRACT_ID,
    validate_cross_substrate_interaction,
    validate_substrate_boundary_payload,
)
from runtime.governance.validator_support import (
    matching_paths,
    safe_string,
    unique_values,
    validator_lineage,
)


HELPER_PURITY_CONTRACT_ID = "helper_semantic_purity_v1"
HELPER_PURITY_DIAGNOSTIC_TYPE = "helper_semantic_purity_diagnostic"

HELPER_FORBIDDEN_CONTROL_FIELDS = frozenset(
    {
        "helper_derived_planner_mutation",
        "helper_derived_planner_mutation_performed",
        "helper_routing_decision",
        "hidden_governance_injection",
        "hidden_governance_injection_performed",
        "hidden_helper_route",
        "hidden_helper_routing",
        "hidden_helper_routing_performed",
        "hidden_visibility_attachment",
        "hidden_visibility_attachment_performed",
    }
)

VISIBILITY_ATTACHMENT_FIELDS = frozenset(
    {
        "diagnostic_attachment_target",
        "hidden_context_injection_performed",
        "planner_prompt",
        "visibility_attachment_target",
    }
)


class HelperPurityError(ValueError):
    def __init__(self, diagnostic: Mapping[str, Any]):
        self.diagnostic = dict(diagnostic)
        super().__init__(self.diagnostic.get("reason", "helper purity violation"))


def helper_purity_policy() -> dict[str, Any]:
    return {
        "contract_id": HELPER_PURITY_CONTRACT_ID,
        "helpers_may_assist_execution": True,
        "helpers_semantic_orchestration_allowed": False,
        "helper_derived_planner_mutation_allowed": False,
        "hidden_helper_routing_allowed": False,
        "hidden_visibility_attachment_allowed": False,
        "hidden_governance_injection_allowed": False,
        "memory_writes_allowed": False,
        "fail_closed_validation_required": True,
        "explicit_cross_substrate_contract_required": True,
        "allowed_substrates": sorted(SUBSTRATES),
    }


def validate_helper_purity(
    *,
    helper_name: str,
    input_substrate: str,
    output_substrate: str,
    input_payload: Mapping[str, Any] | None = None,
    output_payload: Mapping[str, Any] | None = None,
    interaction_type: str | None = None,
    explicit_contract_id: str | None = None,
    source: str = "helper_purity",
) -> dict[str, Any]:
    helper_id = _safe_string(helper_name)
    input_id = _safe_string(input_substrate)
    output_id = _safe_string(output_substrate)
    blocked: list[str] = []

    if helper_id is None:
        blocked.append("helper_name")
    if input_id not in SUBSTRATES:
        blocked.append("input_substrate")
    if output_id not in SUBSTRATES:
        blocked.append("output_substrate")

    blocked.extend(
        f"input.{field}" for field in _helper_payload_violations(input_payload)
    )
    blocked.extend(
        f"output.{field}" for field in _helper_payload_violations(output_payload)
    )

    cross_substrate = (
        input_id in SUBSTRATES and output_id in SUBSTRATES and input_id != output_id
    )
    cross_diagnostic: dict[str, Any] | None = None
    if cross_substrate:
        if explicit_contract_id != CROSS_SUBSTRATE_CONTRACT_ID:
            blocked.append("explicit_cross_substrate_contract_id")
        if not _safe_string(interaction_type):
            blocked.append("interaction_type")

        cross_diagnostic = validate_cross_substrate_interaction(
            source_substrate=input_id or "",
            target_substrate=output_id or "",
            interaction_type=interaction_type or "",
            payload=output_payload,
            explicit_contract_id=explicit_contract_id,
            source=f"{source}:cross_substrate",
        )
        blocked.extend(
            f"cross_substrate.{field}"
            for field in cross_diagnostic.get("blocked_fields", [])
        )
    elif output_id in SUBSTRATES:
        owned = validate_substrate_boundary_payload(
            output_payload,
            owning_substrate=output_id,
        )
        blocked.extend(
            f"output_boundary.{field}" for field in owned.get("blocked_fields", [])
        )

    blocked = _unique(blocked)
    allowed = not blocked
    diagnostic = _diagnostic(
        source=source,
        helper_name=helper_id,
        input_substrate=input_id,
        output_substrate=output_id,
        interaction_type=_safe_string(interaction_type),
        allowed=allowed,
        blocked_fields=blocked,
        cross_substrate=bool(cross_substrate),
        cross_substrate_diagnostic=cross_diagnostic,
    )
    return diagnostic


def assert_helper_pure(
    *,
    helper_name: str,
    input_substrate: str,
    output_substrate: str,
    input_payload: Mapping[str, Any] | None = None,
    output_payload: Mapping[str, Any] | None = None,
    interaction_type: str | None = None,
    explicit_contract_id: str | None = None,
    source: str = "helper_purity",
) -> dict[str, Any]:
    diagnostic = validate_helper_purity(
        helper_name=helper_name,
        input_substrate=input_substrate,
        output_substrate=output_substrate,
        input_payload=input_payload,
        output_payload=output_payload,
        interaction_type=interaction_type,
        explicit_contract_id=explicit_contract_id,
        source=source,
    )
    if diagnostic["allowed"] is not True:
        raise HelperPurityError(diagnostic)
    return diagnostic


def build_helper_purity_diagnostic(
    *,
    helper_name: str,
    allowed: bool,
    source: str = "helper_purity",
    blocked_fields: Sequence[str] | None = None,
) -> dict[str, Any]:
    return _diagnostic(
        source=source,
        helper_name=_safe_string(helper_name),
        input_substrate=None,
        output_substrate=None,
        interaction_type=None,
        allowed=bool(allowed),
        blocked_fields=_unique(list(blocked_fields or [])),
        cross_substrate=False,
        cross_substrate_diagnostic=None,
    )


def _helper_payload_violations(payload: Mapping[str, Any] | None) -> list[str]:
    if payload is None:
        return []
    if not isinstance(payload, Mapping):
        return ["payload"]

    blocked: list[str] = []
    blocked.extend(_matching_paths(payload, HELPER_FORBIDDEN_CONTROL_FIELDS))
    blocked.extend(_matching_paths(payload, MEMORY_FIELDS, allow_false=True))
    blocked.extend(_matching_paths(payload, AUTONOMY_FIELDS, allow_false=True))
    blocked.extend(_matching_paths(payload, MUTATION_FIELDS, allow_false=True))
    blocked.extend(
        _matching_paths(
            payload,
            SEMANTIC_MUTATION_FIELDS,
            false_allowed_fields=frozenset({"planner_semantic_authority"}),
        )
    )

    if payload.get("hidden_context_injection_performed") is True:
        blocked.append("hidden_context_injection_performed")
    if payload.get("hidden_helper_routing_performed") is True:
        blocked.append("hidden_helper_routing_performed")
    if payload.get("helper_derived_planner_mutation_performed") is True:
        blocked.append("helper_derived_planner_mutation_performed")
    if payload.get("hidden_visibility_attachment_performed") is True:
        blocked.append("hidden_visibility_attachment_performed")
    if payload.get("hidden_governance_injection_performed") is True:
        blocked.append("hidden_governance_injection_performed")

    blocked.extend(
        _matching_paths(
            payload,
            VISIBILITY_ATTACHMENT_FIELDS,
            false_allowed_fields=frozenset({"hidden_context_injection_performed"}),
        )
    )
    for fields in SUBSTRATE_STATE_FIELDS.values():
        blocked.extend(
            _matching_paths(
                payload,
                fields,
                false_allowed_fields=frozenset({"hidden_context_injection_performed"}),
            )
        )

    return _unique(blocked)


def _diagnostic(
    *,
    source: str,
    helper_name: str | None,
    input_substrate: str | None,
    output_substrate: str | None,
    interaction_type: str | None,
    allowed: bool,
    blocked_fields: list[str],
    cross_substrate: bool,
    cross_substrate_diagnostic: Mapping[str, Any] | None,
) -> dict[str, Any]:
    diagnostic: dict[str, Any] = {
        "contract_id": HELPER_PURITY_CONTRACT_ID,
        "diagnostic_type": HELPER_PURITY_DIAGNOSTIC_TYPE,
        "source": _safe_string(source) or "helper_purity",
        "helper_name": helper_name,
        "input_substrate": input_substrate,
        "output_substrate": output_substrate,
        "interaction_type": interaction_type,
        "allowed": bool(allowed),
        "content_safe": True,
        "observational_only": True,
        "helper_semantic_authority": False,
        "planner_semantic_authority": False,
        "helpers_may_assist_execution": True,
        "semantic_purity_preserved": bool(allowed),
        "helper_layer_cross_substrate_leakage_detected": bool(
            cross_substrate and not allowed
        ),
        "hidden_helper_routing_performed": False,
        "helper_derived_planner_mutation_performed": False,
        "hidden_visibility_attachment_performed": False,
        "hidden_governance_injection_performed": False,
        "hidden_context_injection_performed": False,
        "memory_write_performed": False,
        "fail_closed": not allowed,
        "blocked_fields": blocked_fields,
        "skipped_reasons": ([] if allowed else ["helper_purity_violation"]),
        "validator_lineage": validator_lineage(
            owner="runtime.governance.helper_purity",
            validator="validate_helper_purity",
            contract_id=HELPER_PURITY_CONTRACT_ID,
            source=source,
            child_validators=(
                ["runtime.governance.substrate_boundary"]
                if cross_substrate_diagnostic is not None
                else []
            ),
        ),
        "reason": (
            "Helper preserved semantic substrate purity."
            if allowed
            else "Helper payload failed semantic purity validation."
        ),
    }
    if isinstance(cross_substrate_diagnostic, Mapping):
        diagnostic["cross_substrate_diagnostic"] = dict(cross_substrate_diagnostic)
    return diagnostic


def _matching_paths(
    value: Any,
    fields: frozenset[str],
    *,
    prefix: str = "",
    allow_false: bool = False,
    false_allowed_fields: frozenset[str] = frozenset(),
) -> list[str]:
    return matching_paths(
        value,
        fields,
        prefix=prefix,
        allow_false=allow_false,
        false_allowed_fields=false_allowed_fields,
    )


def _unique(values: Sequence[str]) -> list[str]:
    return unique_values(values)


def _safe_string(value: Any) -> str | None:
    return safe_string(value)


__all__ = [
    "HELPER_PURITY_CONTRACT_ID",
    "HELPER_PURITY_DIAGNOSTIC_TYPE",
    "HelperPurityError",
    "assert_helper_pure",
    "build_helper_purity_diagnostic",
    "helper_purity_policy",
    "validate_helper_purity",
]
