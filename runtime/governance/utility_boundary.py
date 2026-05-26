from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from runtime.governance.boundary_terms import (
    AUTONOMY_FIELDS,
    MEMORY_FIELDS,
    MUTATION_FIELDS,
    SEMANTIC_MUTATION_FIELDS,
)


ROOT = Path(__file__).resolve().parents[2]
UTILITY_BOUNDARY_RULES_PATH = Path(
    "agents/shared/contracts/runtime_utility_boundary_rules.json"
)

UTILITY_BOUNDARY_CONTRACT_ID = "runtime_utility_boundary_v1"
UTILITY_BOUNDARY_DIAGNOSTIC_TYPE = "runtime_utility_boundary_diagnostic"

ALLOWED_UTILITY_TOPOLOGY_ROOTS = frozenset({"runtime"})

PROHIBITED_UTILITY_INFLUENCE_PATHS = frozenset(
    {
        "utility_to_approval_state",
        "utility_to_execution_planning",
        "utility_to_governance_state",
        "utility_to_hidden_autonomy",
        "utility_to_hidden_orchestration",
        "utility_to_lookup_context_injection",
        "utility_to_memory_write",
        "utility_to_planner_semantic_mutation",
        "utility_to_retrieval_policy",
        "utility_to_retrieval_ranking",
        "utility_to_trust_state",
        "utility_to_workflow_mutation",
    }
)

UTILITY_CONTROL_FIELDS = frozenset(
    {
        "approval_state",
        "approval_routing",
        "execution_plan",
        "execution_planning_mutation_performed",
        "governance_state",
        "hidden_orchestration",
        "hidden_orchestration_performed",
        "hidden_retrieval_influence",
        "hidden_retrieval_influence_performed",
        "hidden_trust_influence",
        "hidden_trust_influence_performed",
        "lookup_context_injection_performed",
        "planner_mutation",
        "planner_semantic_mutation_performed",
        "retrieval_policy",
        "retrieval_rank",
        "retrieval_ranking",
        "trust_state",
        "trust_score",
        "utility_driven_workflow_mutation",
        "utility_driven_workflow_mutation_performed",
        "workflow_mutation",
        "workflow_state",
        "workflow_state_mutation_performed",
    }
)


class UtilityBoundaryError(ValueError):
    def __init__(self, diagnostic: Mapping[str, Any]):
        self.diagnostic = dict(diagnostic)
        super().__init__(
            self.diagnostic.get("reason", "runtime utility boundary violation")
        )


def runtime_utility_boundary_contract(*, root: Path | str = ROOT) -> dict[str, Any]:
    return _load_utility_contract(str(Path(root)))


def runtime_utility_boundary_policy() -> dict[str, Any]:
    return {
        "contract_id": UTILITY_BOUNDARY_CONTRACT_ID,
        "utilities_infrastructural_only": True,
        "utility_semantic_authority_allowed": False,
        "utility_orchestration_allowed": False,
        "utility_workflow_mutation_allowed": False,
        "utility_retrieval_influence_allowed": False,
        "utility_trust_influence_allowed": False,
        "memory_writes_allowed": False,
        "fail_closed_validation_required": True,
        "runtime_topology_conformance_required": True,
        "allowed_topology_roots": sorted(ALLOWED_UTILITY_TOPOLOGY_ROOTS),
        "prohibited_influence_paths": sorted(PROHIBITED_UTILITY_INFLUENCE_PATHS),
    }


def validate_runtime_utility_boundary(
    *,
    utility_name: str,
    utility_path: str | Path,
    input_payload: Mapping[str, Any] | None = None,
    output_payload: Mapping[str, Any] | None = None,
    declared_infrastructural_only: bool = True,
    source: str = "runtime_utility_boundary",
) -> dict[str, Any]:
    utility_id = _safe_string(utility_name)
    relative_path = _relative_posix_path(utility_path)
    blocked: list[str] = []

    if utility_id is None:
        blocked.append("utility_name")
    if relative_path is None:
        blocked.append("utility_path")
    elif _topology_root(relative_path) not in ALLOWED_UTILITY_TOPOLOGY_ROOTS:
        blocked.append("utility_path")

    if declared_infrastructural_only is not True:
        blocked.append("declared_infrastructural_only")

    blocked.extend(
        f"input.{field}" for field in _utility_payload_violations(input_payload)
    )
    blocked.extend(
        f"output.{field}" for field in _utility_payload_violations(output_payload)
    )

    blocked = _unique(blocked)
    return _diagnostic(
        source=source,
        utility_name=utility_id,
        utility_path=relative_path,
        allowed=not blocked,
        blocked_fields=blocked,
    )


def assert_runtime_utility_boundary(
    *,
    utility_name: str,
    utility_path: str | Path,
    input_payload: Mapping[str, Any] | None = None,
    output_payload: Mapping[str, Any] | None = None,
    declared_infrastructural_only: bool = True,
    source: str = "runtime_utility_boundary",
) -> dict[str, Any]:
    diagnostic = validate_runtime_utility_boundary(
        utility_name=utility_name,
        utility_path=utility_path,
        input_payload=input_payload,
        output_payload=output_payload,
        declared_infrastructural_only=declared_infrastructural_only,
        source=source,
    )
    if diagnostic["allowed"] is not True:
        raise UtilityBoundaryError(diagnostic)
    return diagnostic


def build_utility_isolation_diagnostic(
    *,
    utility_name: str,
    utility_path: str | Path,
    allowed: bool,
    blocked_fields: Sequence[str] | None = None,
    source: str = "runtime_utility_boundary",
) -> dict[str, Any]:
    return _diagnostic(
        source=source,
        utility_name=_safe_string(utility_name),
        utility_path=_relative_posix_path(utility_path),
        allowed=bool(allowed),
        blocked_fields=_unique(list(blocked_fields or [])),
    )


def _utility_payload_violations(payload: Mapping[str, Any] | None) -> list[str]:
    if payload is None:
        return []
    if not isinstance(payload, Mapping):
        return ["payload"]

    blocked: list[str] = []
    blocked.extend(_matching_paths(payload, UTILITY_CONTROL_FIELDS))
    blocked.extend(_matching_paths(payload, SEMANTIC_MUTATION_FIELDS))
    blocked.extend(_matching_paths(payload, MUTATION_FIELDS))
    blocked.extend(_matching_paths(payload, MEMORY_FIELDS))
    blocked.extend(_matching_paths(payload, AUTONOMY_FIELDS))

    if payload.get("utility_semantic_authority") is True:
        blocked.append("utility_semantic_authority")
    if payload.get("semantic_reinterpretation_performed") is True:
        blocked.append("semantic_reinterpretation_performed")
    if payload.get("hidden_orchestration_performed") is True:
        blocked.append("hidden_orchestration_performed")
    if payload.get("hidden_retrieval_influence_performed") is True:
        blocked.append("hidden_retrieval_influence_performed")
    if payload.get("hidden_trust_influence_performed") is True:
        blocked.append("hidden_trust_influence_performed")
    if payload.get("utility_driven_workflow_mutation_performed") is True:
        blocked.append("utility_driven_workflow_mutation_performed")
    if payload.get("memory_write_performed") is True:
        blocked.append("memory_write_performed")

    return _unique(blocked)


def _diagnostic(
    *,
    source: str,
    utility_name: str | None,
    utility_path: str | None,
    allowed: bool,
    blocked_fields: list[str],
) -> dict[str, Any]:
    return {
        "contract_id": UTILITY_BOUNDARY_CONTRACT_ID,
        "diagnostic_type": UTILITY_BOUNDARY_DIAGNOSTIC_TYPE,
        "source": _safe_string(source) or "runtime_utility_boundary",
        "utility_name": utility_name,
        "utility_path": utility_path,
        "allowed": bool(allowed),
        "utility_infrastructural_only": True,
        "utility_semantic_authority": False,
        "utility_hidden_orchestration_performed": False,
        "utility_driven_workflow_mutation_performed": False,
        "hidden_retrieval_influence_performed": False,
        "hidden_trust_influence_performed": False,
        "memory_write_performed": False,
        "runtime_topology_conformant": not any(
            field == "utility_path" for field in blocked_fields
        ),
        "semantic_isolation_preserved": bool(allowed),
        "fail_closed": not allowed,
        "blocked_fields": blocked_fields,
        "prohibited_influence_paths": sorted(PROHIBITED_UTILITY_INFLUENCE_PATHS),
        "skipped_reasons": ([] if allowed else ["runtime_utility_boundary_violation"]),
        "reason": (
            "Runtime utility preserved semantic isolation."
            if allowed
            else "Runtime utility failed semantic isolation validation."
        ),
    }


@lru_cache(maxsize=None)
def _load_utility_contract(root: str) -> dict[str, Any]:
    path = Path(root) / UTILITY_BOUNDARY_RULES_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    for contract in data.get("contracts", []):
        if contract.get("id") == UTILITY_BOUNDARY_CONTRACT_ID:
            return dict(contract)
    return {}


def _relative_posix_path(value: str | Path) -> str | None:
    try:
        path = Path(value)
    except TypeError:
        return None
    if path.is_absolute():
        try:
            path = path.relative_to(ROOT)
        except ValueError:
            return None
    text = path.as_posix().strip()
    return text or None


def _topology_root(path: str) -> str | None:
    parts = Path(path).parts
    return parts[0] if parts else None


def _matching_paths(
    value: Any,
    fields: frozenset[str],
    *,
    prefix: str = "",
) -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            path = f"{prefix}.{key}" if prefix else key
            if key in fields:
                paths.append(path)
            paths.extend(_matching_paths(item, fields, prefix=path))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            paths.extend(_matching_paths(item, fields, prefix=f"{prefix}[{index}]"))
    return paths


def _unique(values: Sequence[str]) -> list[str]:
    found: list[str] = []
    for value in values:
        text = _safe_string(value)
        if text and text not in found:
            found.append(text)
    return found


def _safe_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


__all__ = [
    "ALLOWED_UTILITY_TOPOLOGY_ROOTS",
    "PROHIBITED_UTILITY_INFLUENCE_PATHS",
    "UTILITY_BOUNDARY_CONTRACT_ID",
    "UTILITY_BOUNDARY_DIAGNOSTIC_TYPE",
    "UTILITY_BOUNDARY_RULES_PATH",
    "UtilityBoundaryError",
    "assert_runtime_utility_boundary",
    "build_utility_isolation_diagnostic",
    "runtime_utility_boundary_contract",
    "runtime_utility_boundary_policy",
    "validate_runtime_utility_boundary",
]
