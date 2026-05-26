from __future__ import annotations

from typing import Any, Mapping

from runtime.governance.visibility_isolation import (
    validate_diagnostic_visibility_surface,
    validate_visibility_attachment,
)
from runtime.governance.boundary_terms import SEMANTIC_AUTHORITY_FIELDS


GOVERNANCE_BOUNDARY_CONTRACT_ID = "planner_governance_boundary_v1"
GOVERNANCE_BOUNDARY_DIAGNOSTIC_TYPE = "planner_governance_boundary_diagnostic"

_GOVERNANCE_MARKERS = (
    "approval",
    "autonomy",
    "governance",
    "memory",
    "trust",
    "visibility",
)

_DIAGNOSTIC_MARKERS = (
    "diagnostic",
    "diagnostics",
)

_SEMANTIC_MUTATION_KEYS = SEMANTIC_AUTHORITY_FIELDS

_PLANNER_VISIBLE_GOVERNANCE_KEYS = frozenset(
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


class PlannerGovernanceBoundaryError(ValueError):
    def __init__(self, diagnostic: Mapping[str, Any]):
        self.diagnostic = dict(diagnostic)
        super().__init__(
            self.diagnostic.get(
                "reason",
                "planner governance boundary violation",
            )
        )


def build_governance_boundary_diagnostic(
    *,
    source: str,
    allowed: bool,
    reason: str,
    blocked_fields: list[str] | None = None,
    metadata_visible: bool = False,
    isolation_diagnostics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    diagnostic = {
        "contract_id": GOVERNANCE_BOUNDARY_CONTRACT_ID,
        "diagnostic_type": GOVERNANCE_BOUNDARY_DIAGNOSTIC_TYPE,
        "source": _safe_string(source) or "unknown",
        "allowed": bool(allowed),
        "metadata_visible": bool(metadata_visible),
        "planner_semantic_authority_preserved": bool(allowed),
        "semantic_reinterpretation_performed": False,
        "governance_can_constrain_execution_only": True,
        "blocked_fields": list(blocked_fields or []),
        "reason": _safe_string(reason) or "Planner governance boundary decision.",
    }
    if isinstance(isolation_diagnostics, Mapping):
        diagnostic["visibility_isolation"] = dict(isolation_diagnostics)
    return diagnostic


def assert_no_governance_semantic_mutation(
    payload: Mapping[str, Any] | None,
    *,
    source: str,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return build_governance_boundary_diagnostic(
            source=source,
            allowed=True,
            reason="No governance payload was provided to planner semantics.",
        )

    blocked = _find_governance_semantic_mutations(payload)
    if blocked:
        diagnostic = build_governance_boundary_diagnostic(
            source=source,
            allowed=False,
            reason=(
                "Governance/trust metadata attempted to mutate planner "
                "semantic authority."
            ),
            blocked_fields=blocked,
            metadata_visible=True,
        )
        raise PlannerGovernanceBoundaryError(diagnostic)

    return build_governance_boundary_diagnostic(
        source=source,
        allowed=True,
        reason=(
            "Governance/trust metadata was not used to mutate planner "
            "semantics."
        ),
        metadata_visible=_contains_governance_marker(payload),
    )


def validate_planner_visible_governance_metadata(
    metadata: Mapping[str, Any] | None,
    *,
    source: str,
) -> dict[str, Any]:
    if metadata is None:
        return build_governance_boundary_diagnostic(
            source=source,
            allowed=True,
            reason="No planner-visible governance metadata was provided.",
        )
    if not isinstance(metadata, Mapping):
        diagnostic = build_governance_boundary_diagnostic(
            source=source,
            allowed=False,
            reason="Planner-visible governance metadata must be an object.",
            metadata_visible=True,
        )
        raise PlannerGovernanceBoundaryError(diagnostic)

    unknown = sorted(
        str(key)
        for key in metadata
        if str(key) not in _PLANNER_VISIBLE_GOVERNANCE_KEYS
    )
    semantic = sorted(
        str(key)
        for key in metadata
        if str(key) in _SEMANTIC_MUTATION_KEYS
    )
    blocked = _unique([*unknown, *semantic])
    if metadata.get("content_safe") is not True:
        blocked.append("content_safe")
    if metadata.get("semantic_reinterpretation_performed") is not False:
        blocked.append("semantic_reinterpretation_performed")

    if blocked:
        diagnostic = build_governance_boundary_diagnostic(
            source=source,
            allowed=False,
            reason=(
                "Planner-visible governance metadata must be content-safe, "
                "observational, and non-semantic."
            ),
            blocked_fields=_unique(blocked),
            metadata_visible=True,
        )
        raise PlannerGovernanceBoundaryError(diagnostic)

    attachment_diagnostic = validate_visibility_attachment(
        metadata,
        target="planner_visible_governance_metadata",
    )
    if attachment_diagnostic["allowed"] is not True:
        diagnostic = build_governance_boundary_diagnostic(
            source=source,
            allowed=False,
            reason="Planner-visible visibility metadata failed isolation policy.",
            blocked_fields=attachment_diagnostic.get("blocked_fields", []),
            metadata_visible=True,
            isolation_diagnostics=attachment_diagnostic,
        )
        raise PlannerGovernanceBoundaryError(diagnostic)

    return build_governance_boundary_diagnostic(
        source=source,
        allowed=True,
        reason=(
            "Planner-visible governance metadata is observational only and "
            "cannot redefine semantic intent."
        ),
        metadata_visible=True,
        isolation_diagnostics=attachment_diagnostic,
    )


def _find_governance_semantic_mutations(
    value: Any,
    *,
    path: str = "",
    in_governance_scope: bool = False,
) -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        has_unbounded_governance_marker = any(
            _is_governance_marker(str(key))
            and str(key) != "governance_visibility"
            for key in value
        )
        for raw_key, item in value.items():
            key = str(raw_key)
            key_path = f"{path}.{key}" if path else key
            marker_scope = in_governance_scope or _is_governance_marker(key)
            if has_unbounded_governance_marker and key in _SEMANTIC_MUTATION_KEYS:
                found.append(key_path)
            if _is_diagnostic_marker(key):
                found.append(key_path)
                if isinstance(item, Mapping):
                    diagnostic = validate_diagnostic_visibility_surface(item)
                    found.extend(
                        f"{key_path}.{field}"
                        for field in diagnostic.get("blocked_fields", [])
                    )
            if _is_governance_marker(key) and key != "governance_visibility":
                found.append(key_path)
            if marker_scope and key in _SEMANTIC_MUTATION_KEYS:
                found.append(key_path)
            if key == "governance_visibility":
                validate_planner_visible_governance_metadata(
                    item,
                    source=key_path,
                )
                continue
            found.extend(
                _find_governance_semantic_mutations(
                    item,
                    path=key_path,
                    in_governance_scope=marker_scope,
                )
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(
                _find_governance_semantic_mutations(
                    item,
                    path=f"{path}[{index}]",
                    in_governance_scope=in_governance_scope,
                )
            )
    return _unique(found)


def _contains_governance_marker(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if (
                _is_governance_marker(str(key))
                or _contains_governance_marker(item)
            ):
                return True
    if isinstance(value, list):
        return any(_contains_governance_marker(item) for item in value)
    return False


def _is_governance_marker(key: str) -> bool:
    if key == "requires_approval":
        return False
    lowered = key.lower()
    return any(marker in lowered for marker in _GOVERNANCE_MARKERS)


def _is_diagnostic_marker(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _DIAGNOSTIC_MARKERS)


def _safe_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


__all__ = [
    "GOVERNANCE_BOUNDARY_CONTRACT_ID",
    "GOVERNANCE_BOUNDARY_DIAGNOSTIC_TYPE",
    "PlannerGovernanceBoundaryError",
    "assert_no_governance_semantic_mutation",
    "build_governance_boundary_diagnostic",
    "validate_planner_visible_governance_metadata",
]
