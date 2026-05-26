from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from runtime.governance.boundary_terms import (
    AUTONOMY_FIELDS,
    MEMORY_FIELDS,
    MUTATION_FIELDS,
    SEMANTIC_AUTHORITY_FIELDS,
    SEMANTIC_MUTATION_FIELDS,
    SUBSTRATE_STATE_FIELDS,
    SUBSTRATES,
    boundary_terms_policy,
)
from runtime.governance.visibility_isolation import (
    validate_diagnostic_visibility_surface,
    validate_operator_visibility_surface,
)
from runtime.governance.validator_support import (
    matching_paths,
    safe_string,
    unique_values,
    validator_lineage,
)


ROOT = Path(__file__).resolve().parents[2]
CROSS_SUBSTRATE_CONTRACTS_PATH = Path(
    "agents/shared/contracts/cross_substrate_interaction_contracts.json"
)

CROSS_SUBSTRATE_CONTRACT_ID = "cross_substrate_interaction_contract_v1"
CROSS_SUBSTRATE_DIAGNOSTIC_TYPE = "cross_substrate_boundary_diagnostic"

ALLOWED_INFLUENCE_DIRECTIONS = frozenset(
    {
        ("governance", "retrieval", "execution_constraint"),
        ("governance", "workflow", "execution_constraint"),
        ("workflow", "retrieval", "explicit_lookup_request"),
        ("retrieval", "workflow", "explicit_retrieval_provenance"),
        ("retrieval", "visibility", "observational_diagnostic"),
        ("workflow", "visibility", "observational_diagnostic"),
        ("governance", "visibility", "observational_diagnostic"),
    }
)

PROHIBITED_IMPLICIT_COUPLING_PATHS = frozenset(
    {
        "any_to_hidden_autonomy",
        "any_to_memory_write",
        "governance_to_planner_semantic_mutation",
        "governance_to_retrieval_semantic_mutation",
        "governance_to_workflow_semantic_mutation",
        "retrieval_to_governance_state",
        "retrieval_to_visibility_content_injection",
        "retrieval_to_workflow_semantic_mutation",
        "retrieval_to_workflow_state_mutation",
        "visibility_to_governance_state",
        "visibility_to_planner_prompt",
        "visibility_to_retrieval_policy",
        "visibility_to_workflow_state",
        "workflow_to_governance_state",
        "workflow_to_retrieval_policy_implicit",
    }
)

class SubstrateBoundaryError(ValueError):
    def __init__(self, diagnostic: Mapping[str, Any]):
        self.diagnostic = dict(diagnostic)
        super().__init__(self.diagnostic.get("reason", "substrate boundary violation"))


def cross_substrate_interaction_contract(*, root: Path | str = ROOT) -> dict[str, Any]:
    return _load_cross_substrate_contract(str(Path(root)))


def substrate_boundary_policy() -> dict[str, Any]:
    return {
        "contract_id": CROSS_SUBSTRATE_CONTRACT_ID,
        "substrates": sorted(SUBSTRATES),
        "canonical_boundary_terms": boundary_terms_policy()["canonical_boundary_terms"],
        "compatibility_aliases": boundary_terms_policy()["compatibility_aliases"],
        "allowed_influence_directions": [
            {
                "source": source,
                "target": target,
                "interaction_type": interaction_type,
            }
            for source, target, interaction_type in sorted(
                ALLOWED_INFLUENCE_DIRECTIONS
            )
        ],
        "prohibited_implicit_coupling_paths": sorted(
            PROHIBITED_IMPLICIT_COUPLING_PATHS
        ),
        "explicit_contract_id_required": True,
        "semantic_reinterpretation_allowed": False,
        "cross_substrate_planner_mutation_allowed": False,
        "implicit_substrate_inheritance_allowed": False,
        "hidden_orchestration_allowed": False,
        "memory_writes_allowed": False,
        "hidden_autonomy_allowed": False,
    }


def validate_cross_substrate_interaction(
    *,
    source_substrate: str,
    target_substrate: str,
    interaction_type: str,
    payload: Mapping[str, Any] | None = None,
    explicit_contract_id: str | None = None,
    source: str = "cross_substrate_boundary",
) -> dict[str, Any]:
    source_id = _safe_string(source_substrate)
    target_id = _safe_string(target_substrate)
    interaction_id = _safe_string(interaction_type)
    blocked: list[str] = []

    if source_id not in SUBSTRATES:
        blocked.append("source_substrate")
    if target_id not in SUBSTRATES:
        blocked.append("target_substrate")
    if source_id == target_id and source_id is not None:
        blocked.append("target_substrate")
    if explicit_contract_id != CROSS_SUBSTRATE_CONTRACT_ID:
        blocked.append("explicit_contract_id")

    direction = (source_id or "", target_id or "", interaction_id or "")
    if direction not in ALLOWED_INFLUENCE_DIRECTIONS:
        blocked.append("allowed_influence_direction")

    blocked.extend(
        _payload_boundary_violations(
            payload,
            source_substrate=source_id,
            target_substrate=target_id,
        )
    )

    if target_id == "visibility" and interaction_id == "observational_diagnostic":
        blocked.extend(_visibility_surface_violations(payload))

    return _diagnostic(
        source=source,
        allowed=not blocked,
        source_substrate=source_id,
        target_substrate=target_id,
        interaction_type=interaction_id,
        blocked_fields=_unique(blocked),
        reason=(
            "Cross-substrate interaction is explicit and allowed."
            if not blocked
            else "Cross-substrate interaction violates the substrate contract."
        ),
    )


def assert_cross_substrate_interaction_allowed(
    *,
    source_substrate: str,
    target_substrate: str,
    interaction_type: str,
    payload: Mapping[str, Any] | None = None,
    explicit_contract_id: str | None = None,
    source: str = "cross_substrate_boundary",
) -> dict[str, Any]:
    diagnostic = validate_cross_substrate_interaction(
        source_substrate=source_substrate,
        target_substrate=target_substrate,
        interaction_type=interaction_type,
        payload=payload,
        explicit_contract_id=explicit_contract_id,
        source=source,
    )
    if diagnostic["allowed"] is not True:
        raise SubstrateBoundaryError(diagnostic)
    return diagnostic


def validate_substrate_boundary_payload(
    payload: Mapping[str, Any] | None,
    *,
    owning_substrate: str,
) -> dict[str, Any]:
    substrate_id = _safe_string(owning_substrate)
    blocked = _payload_boundary_violations(
        payload,
        source_substrate=substrate_id,
        target_substrate=substrate_id,
    )
    return _diagnostic(
        source="substrate_payload_boundary",
        allowed=not blocked,
        source_substrate=substrate_id,
        target_substrate=substrate_id,
        interaction_type="owned_payload",
        blocked_fields=_unique(blocked),
        reason=(
            "Substrate payload preserves its semantic boundary."
            if not blocked
            else "Substrate payload contains implicit coupling fields."
        ),
    )


def _payload_boundary_violations(
    payload: Mapping[str, Any] | None,
    *,
    source_substrate: str | None,
    target_substrate: str | None,
) -> list[str]:
    if payload is None:
        return []
    if not isinstance(payload, Mapping):
        return ["payload"]

    blocked: list[str] = []
    if payload.get("semantic_reinterpretation_performed") is True:
        blocked.append("semantic_reinterpretation_performed")
    if payload.get("cross_substrate_planner_mutation_performed") is True:
        blocked.append("cross_substrate_planner_mutation_performed")
    if payload.get("implicit_substrate_inheritance_performed") is True:
        blocked.append("implicit_substrate_inheritance_performed")
    if payload.get("hidden_orchestration_performed") is True:
        blocked.append("hidden_orchestration_performed")

    blocked.extend(_matching_paths(payload, MEMORY_FIELDS, allow_false=True))
    blocked.extend(_matching_paths(payload, AUTONOMY_FIELDS, allow_false=True))
    blocked.extend(_matching_paths(payload, MUTATION_FIELDS, allow_false=True))

    if target_substrate not in {"visibility", None}:
        blocked.extend(
            _matching_paths(
                payload,
                SEMANTIC_AUTHORITY_FIELDS,
                false_allowed_fields=frozenset({"planner_semantic_authority"}),
            )
        )

    if target_substrate != "visibility":
        for substrate, fields in SUBSTRATE_STATE_FIELDS.items():
            if substrate not in {source_substrate, target_substrate}:
                blocked.extend(_matching_paths(payload, fields))

    return blocked


def _visibility_surface_violations(payload: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["payload"]
    if _safe_string(payload.get("diagnostic_type")):
        diagnostic = validate_diagnostic_visibility_surface(payload)
    else:
        diagnostic = validate_operator_visibility_surface(payload)
    return [f"visibility.{field}" for field in diagnostic.get("blocked_fields", [])]


def _diagnostic(
    *,
    source: str,
    allowed: bool,
    source_substrate: str | None,
    target_substrate: str | None,
    interaction_type: str | None,
    blocked_fields: list[str],
    reason: str,
) -> dict[str, Any]:
    return {
        "contract_id": CROSS_SUBSTRATE_CONTRACT_ID,
        "diagnostic_type": CROSS_SUBSTRATE_DIAGNOSTIC_TYPE,
        "source": _safe_string(source) or "cross_substrate_boundary",
        "allowed": bool(allowed),
        "source_substrate": source_substrate,
        "target_substrate": target_substrate,
        "interaction_type": interaction_type,
        "content_safe": True,
        "observational_only": True,
        "explicit_interaction": True,
        "auditable": True,
        "planner_semantic_authority": False,
        "semantic_reinterpretation_performed": False,
        "cross_substrate_planner_mutation_performed": False,
        "implicit_substrate_inheritance_performed": False,
        "hidden_orchestration_performed": False,
        "hidden_context_injection_performed": False,
        "memory_write_performed": False,
        "hidden_autonomy_escalation_performed": False,
        "blocked_fields": blocked_fields,
        "prohibited_implicit_coupling_paths": sorted(
            PROHIBITED_IMPLICIT_COUPLING_PATHS
        ),
        "skipped_reasons": ([] if allowed else ["substrate_boundary_violation"]),
        "validator_lineage": validator_lineage(
            owner="runtime.governance.substrate_boundary",
            validator=(
                "validate_substrate_boundary_payload"
                if interaction_type == "owned_payload"
                else "validate_cross_substrate_interaction"
            ),
            contract_id=CROSS_SUBSTRATE_CONTRACT_ID,
            source=source,
            child_validators=(
                ["runtime.governance.visibility_isolation"]
                if target_substrate == "visibility"
                and interaction_type == "observational_diagnostic"
                else []
            ),
        ),
        "reason": reason,
    }


@lru_cache(maxsize=None)
def _load_cross_substrate_contract(root: str) -> dict[str, Any]:
    path = Path(root) / CROSS_SUBSTRATE_CONTRACTS_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    for contract in data.get("contracts", []):
        if contract.get("id") == CROSS_SUBSTRATE_CONTRACT_ID:
            return dict(contract)
    return {}


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
    "ALLOWED_INFLUENCE_DIRECTIONS",
    "CROSS_SUBSTRATE_CONTRACTS_PATH",
    "CROSS_SUBSTRATE_CONTRACT_ID",
    "CROSS_SUBSTRATE_DIAGNOSTIC_TYPE",
    "PROHIBITED_IMPLICIT_COUPLING_PATHS",
    "SUBSTRATES",
    "SubstrateBoundaryError",
    "assert_cross_substrate_interaction_allowed",
    "cross_substrate_interaction_contract",
    "substrate_boundary_policy",
    "validate_cross_substrate_interaction",
    "validate_substrate_boundary_payload",
]
