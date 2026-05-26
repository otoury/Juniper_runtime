from __future__ import annotations

from typing import Any, Mapping, Sequence

from runtime.governance.visibility_isolation import (
    assert_visibility_attachment_allowed,
)


GOVERNANCE_VISIBILITY_CONTRACT_ID = "governance_visibility_v1"
GOVERNANCE_VISIBILITY_TYPE = "operator_trust_governance_visibility"
GOVERNANCE_VISIBILITY_SCHEMA_VERSION = 1
VISIBILITY_CONSISTENCY_DIAGNOSTIC_TYPE = "visibility_consistency_diagnostic"

GOVERNANCE_VISIBILITY_DOMAINS = frozenset({"retrieval", "workflow"})

CANONICAL_GOVERNANCE_VISIBILITY_FIELDS = frozenset(
    {
        "action_type",
        "adapter_id",
        "capability",
        "content_safe",
        "execution_allowed",
        "execution_performed",
        "governance_state",
        "injection_allowed",
        "lookup_execution_id",
        "lookup_id",
        "lookup_lineage_id",
        "lookup_request_id",
        "lookup_type",
        "operation_domain",
        "owning_agent",
        "prior_trust_scope_match",
        "records_returned",
        "render_allowed",
        "requires_approval",
        "retrieval_executed",
        "schema_version",
        "semantic_reinterpretation_performed",
        "skipped_reasons",
        "source_binding_id",
        "source_scope",
        "step_id",
        "trust_inheritance_boundary",
        "trust_lineage_type",
        "trust_scope_bleed_prevented",
        "trust_scope_key",
        "trust_state",
        "visibility_contract_id",
        "visibility_type",
        "workflow_id",
        "workflow_type",
    }
)

_REQUIRED_BASE_FIELDS = frozenset(
    {
        "visibility_contract_id",
        "visibility_type",
        "schema_version",
        "operation_domain",
        "content_safe",
        "semantic_reinterpretation_performed",
    }
)

_DOMAIN_REQUIRED_FIELDS = {
    "retrieval": frozenset(),
    "workflow": frozenset(),
}


def build_governance_visibility_surface(
    *,
    operation_domain: str,
    fields: Mapping[str, Any] | None = None,
    target: str = "operator_report",
) -> dict[str, Any]:
    domain = _safe_text(operation_domain)
    surface = _without_empty(
        {
            "visibility_contract_id": GOVERNANCE_VISIBILITY_CONTRACT_ID,
            "visibility_type": GOVERNANCE_VISIBILITY_TYPE,
            "schema_version": GOVERNANCE_VISIBILITY_SCHEMA_VERSION,
            "operation_domain": domain,
            "content_safe": True,
            "semantic_reinterpretation_performed": False,
            **_canonical_fields(fields),
        }
    )
    diagnostic = validate_governance_visibility_schema(surface)
    if diagnostic["allowed"] is not True:
        raise ValueError(diagnostic["reason"])
    assert_visibility_attachment_allowed(surface, target=target)
    return surface


def validate_governance_visibility_schema(
    surface: Mapping[str, Any] | None,
) -> dict[str, Any]:
    blocked: list[str] = []
    if not isinstance(surface, Mapping):
        return _diagnostic(
            allowed=False,
            source="governance_visibility_schema",
            blocked_fields=["surface"],
            checked_surface_count=0,
            reason="Governance visibility surface must be an object.",
        )

    for field in sorted(_REQUIRED_BASE_FIELDS):
        if field not in surface:
            blocked.append(field)

    if surface.get("visibility_contract_id") != GOVERNANCE_VISIBILITY_CONTRACT_ID:
        blocked.append("visibility_contract_id")
    if surface.get("visibility_type") != GOVERNANCE_VISIBILITY_TYPE:
        blocked.append("visibility_type")
    if surface.get("schema_version") != GOVERNANCE_VISIBILITY_SCHEMA_VERSION:
        blocked.append("schema_version")
    if surface.get("content_safe") is not True:
        blocked.append("content_safe")
    if surface.get("semantic_reinterpretation_performed") is not False:
        blocked.append("semantic_reinterpretation_performed")

    domain = _safe_text(surface.get("operation_domain"))
    if domain not in GOVERNANCE_VISIBILITY_DOMAINS:
        blocked.append("operation_domain")
    else:
        for field in sorted(_DOMAIN_REQUIRED_FIELDS[domain]):
            if field not in surface:
                blocked.append(field)

    for key in surface:
        if str(key) not in CANONICAL_GOVERNANCE_VISIBILITY_FIELDS:
            blocked.append(str(key))

    return _diagnostic(
        allowed=not blocked,
        source="governance_visibility_schema",
        blocked_fields=_unique(blocked),
        checked_surface_count=1,
        reason=(
            "Governance visibility surface matches the canonical schema."
            if not blocked
            else "Governance visibility surface does not match the canonical schema."
        ),
    )


def build_visibility_consistency_diagnostic(
    surfaces: Sequence[Mapping[str, Any]] | None,
    *,
    source: str = "visibility_consistency",
) -> dict[str, Any]:
    items = _safe_mapping_list(surfaces)
    blocked: list[str] = []
    domains: list[str] = []
    types: list[str] = []
    versions: list[int] = []

    for index, surface in enumerate(items):
        schema = validate_governance_visibility_schema(surface)
        blocked.extend(
            f"surfaces[{index}].{field}"
            for field in schema.get("blocked_fields", [])
        )
        domain = _safe_text(surface.get("operation_domain"))
        visibility_type = _safe_text(surface.get("visibility_type"))
        if domain:
            domains.append(domain)
        if visibility_type:
            types.append(visibility_type)
        version = surface.get("schema_version")
        if isinstance(version, int) and not isinstance(version, bool):
            versions.append(version)

    if len(set(types)) > 1:
        blocked.append("visibility_type")
    if len(set(versions)) > 1:
        blocked.append("schema_version")
    if not items:
        blocked.append("surfaces")

    diagnostic = _diagnostic(
        allowed=not blocked,
        source=_safe_text(source) or "visibility_consistency",
        blocked_fields=_unique(blocked),
        checked_surface_count=len(items),
        reason=(
            "Visibility surfaces are schema-consistent and observational."
            if not blocked
            else "Visibility surfaces have inconsistent schema projections."
        ),
    )
    diagnostic["observed_operation_domains"] = sorted(set(domains))
    diagnostic["canonical_visibility_type"] = GOVERNANCE_VISIBILITY_TYPE
    assert_visibility_attachment_allowed(diagnostic, target="operator_report")
    return diagnostic


def _diagnostic(
    *,
    allowed: bool,
    source: str,
    blocked_fields: Sequence[str],
    checked_surface_count: int,
    reason: str,
) -> dict[str, Any]:
    return {
        "contract_id": GOVERNANCE_VISIBILITY_CONTRACT_ID,
        "diagnostic_type": VISIBILITY_CONSISTENCY_DIAGNOSTIC_TYPE,
        "source": source,
        "allowed": bool(allowed),
        "content_safe": True,
        "observational_only": True,
        "planner_semantic_authority": False,
        "semantic_reinterpretation_performed": False,
        "hidden_context_injection_performed": False,
        "hidden_routing_performed": False,
        "planner_mutation_performed": False,
        "memory_write_performed": False,
        "governance_state_mutation_performed": False,
        "workflow_state_mutation_performed": False,
        "retrieval_policy_mutation_performed": False,
        "checked_surface_count": checked_surface_count,
        "blocked_fields": list(blocked_fields),
        "skipped_reasons": ([] if allowed else ["visibility_consistency_violation"]),
        "reason": reason,
    }


def _canonical_fields(fields: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(fields, Mapping):
        return {}
    return {
        key: value
        for key, value in fields.items()
        if key
        not in {
            "visibility_contract_id",
            "visibility_type",
            "schema_version",
            "operation_domain",
            "content_safe",
            "semantic_reinterpretation_performed",
        }
    }


def _safe_mapping_list(
    value: Sequence[Mapping[str, Any]] | None,
) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _without_empty(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: item for key, item in value.items() if item is not None and item != []
    }


def _safe_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _unique(values: Sequence[str]) -> list[str]:
    found: list[str] = []
    for value in values:
        text = _safe_text(value)
        if text and text not in found:
            found.append(text)
    return found


__all__ = [
    "CANONICAL_GOVERNANCE_VISIBILITY_FIELDS",
    "GOVERNANCE_VISIBILITY_CONTRACT_ID",
    "GOVERNANCE_VISIBILITY_DOMAINS",
    "GOVERNANCE_VISIBILITY_SCHEMA_VERSION",
    "GOVERNANCE_VISIBILITY_TYPE",
    "VISIBILITY_CONSISTENCY_DIAGNOSTIC_TYPE",
    "build_governance_visibility_surface",
    "build_visibility_consistency_diagnostic",
    "validate_governance_visibility_schema",
]
