from __future__ import annotations

from typing import Any, Mapping

from runtime.governance.boundary_terms import (
    ALLOWED_DIAGNOSTIC_ATTACHMENT_TARGETS,
    ALLOWED_VISIBILITY_ATTACHMENT_TARGETS,
    FORBIDDEN_ATTACHMENT_TARGETS,
    FORBIDDEN_CONTENT_FIELDS,
    SEMANTIC_AUTHORITY_FIELDS,
    boundary_terms_policy,
)
from runtime.governance.validator_support import (
    matching_paths,
    safe_string,
    unique_values,
    validator_lineage,
)

VISIBILITY_ISOLATION_CONTRACT_ID = "visibility_isolation_v1"
VISIBILITY_ISOLATION_DIAGNOSTIC_TYPE = "visibility_isolation_diagnostic"
_MUTATION_FLAGS = frozenset(
    {
        "artifact_mutation_performed",
        "candidate_mutation_performed",
        "db_write_performed",
        "governance_state_mutation_performed",
        "memory_write_performed",
        "workflow_state_mutation_performed",
    }
)


class VisibilityIsolationError(ValueError):
    def __init__(self, diagnostic: Mapping[str, Any]):
        self.diagnostic = dict(diagnostic)
        super().__init__(
            self.diagnostic.get("reason", "visibility isolation violation")
        )


def visibility_isolation_policy() -> dict[str, Any]:
    return {
        "policy_id": VISIBILITY_ISOLATION_CONTRACT_ID,
        "visibility_observational_only": True,
        "diagnostics_observational_only": True,
        "diagnostics_planner_context_allowed": False,
        "diagnostics_runtime_semantic_context_allowed": False,
        "visibility_derived_routing_allowed": False,
        "memory_writes_allowed": False,
        "hidden_context_injection_allowed": False,
        "canonical_boundary_terms": boundary_terms_policy()["canonical_boundary_terms"],
        "compatibility_aliases": boundary_terms_policy()["compatibility_aliases"],
        "allowed_visibility_attachment_targets": sorted(
            ALLOWED_VISIBILITY_ATTACHMENT_TARGETS
        ),
        "allowed_diagnostic_attachment_targets": sorted(
            ALLOWED_DIAGNOSTIC_ATTACHMENT_TARGETS
        ),
        "forbidden_attachment_targets": sorted(FORBIDDEN_ATTACHMENT_TARGETS),
        "content_boundary": {
            "content_safe_required": True,
            "raw_content_fields_allowed": False,
            "receipt_refs_allowed": True,
        },
    }


def validate_operator_visibility_surface(payload: Mapping[str, Any]) -> dict[str, Any]:
    blocked: list[str] = []
    if not isinstance(payload, Mapping):
        return _diagnostic(
            allowed=False,
            source="visibility_surface",
            reason="Visibility surface must be an object.",
            blocked_fields=["payload"],
        )
    if not _safe_text(payload.get("visibility_type")):
        blocked.append("visibility_type")
    if payload.get("content_safe") is not True:
        blocked.append("content_safe")
    if payload.get("semantic_reinterpretation_performed") is not False:
        blocked.append("semantic_reinterpretation_performed")
    blocked.extend(_forbidden_content_paths(payload))
    blocked.extend(_semantic_authority_paths(payload))
    return _diagnostic(
        allowed=not blocked,
        source="visibility_surface",
        reason=(
            "Visibility surface is observational and content-safe."
            if not blocked
            else "Visibility surface crossed content or semantic boundaries."
        ),
        blocked_fields=_unique(blocked),
    )


def validate_diagnostic_visibility_surface(payload: Mapping[str, Any]) -> dict[str, Any]:
    blocked: list[str] = []
    if not isinstance(payload, Mapping):
        return _diagnostic(
            allowed=False,
            source="diagnostic_surface",
            reason="Diagnostic surface must be an object.",
            blocked_fields=["payload"],
        )
    if not _safe_text(payload.get("diagnostic_type")):
        blocked.append("diagnostic_type")
    if payload.get("observational_only") is not True:
        blocked.append("observational_only")
    if payload.get("hidden_context_injection_performed") is not False:
        blocked.append("hidden_context_injection_performed")
    if payload.get("planner_semantic_authority") is not False:
        blocked.append("planner_semantic_authority")
    for flag in sorted(_MUTATION_FLAGS):
        if flag in payload and payload.get(flag) is not False:
            blocked.append(flag)
    blocked.extend(_forbidden_content_paths(payload))
    blocked.extend(_semantic_authority_paths(payload))
    return _diagnostic(
        allowed=not blocked,
        source="diagnostic_surface",
        reason=(
            "Diagnostic surface is observational and content-safe."
            if not blocked
            else "Diagnostic surface crossed content or semantic boundaries."
        ),
        blocked_fields=_unique(blocked),
    )


def validate_visibility_attachment(
    payload: Mapping[str, Any],
    *,
    target: str,
) -> dict[str, Any]:
    target_id = _safe_text(target) or "unknown"
    blocked: list[str] = []
    surface_kind = _surface_kind(payload)
    if target_id in FORBIDDEN_ATTACHMENT_TARGETS:
        blocked.append(target_id)
    if surface_kind == "diagnostic":
        if target_id not in ALLOWED_DIAGNOSTIC_ATTACHMENT_TARGETS:
            blocked.append(target_id)
        surface = validate_diagnostic_visibility_surface(payload)
    elif surface_kind == "visibility":
        if target_id not in ALLOWED_VISIBILITY_ATTACHMENT_TARGETS:
            blocked.append(target_id)
        surface = validate_operator_visibility_surface(payload)
    else:
        blocked.append("payload")
        surface = _diagnostic(
            allowed=False,
            source="visibility_attachment",
            reason="Payload is not a recognized visibility or diagnostic surface.",
            blocked_fields=["payload"],
        )
    blocked.extend(surface.get("blocked_fields", []))
    return _diagnostic(
        allowed=not blocked,
        source=f"visibility_attachment:{target_id}",
        reason=(
            "Visibility attachment target is explicitly allowed."
            if not blocked
            else "Visibility attachment target is not allowed for this surface."
        ),
        blocked_fields=_unique(blocked),
    )


def assert_visibility_attachment_allowed(
    payload: Mapping[str, Any],
    *,
    target: str,
) -> dict[str, Any]:
    diagnostic = validate_visibility_attachment(payload, target=target)
    if diagnostic["allowed"] is not True:
        raise VisibilityIsolationError(diagnostic)
    return diagnostic


def _surface_kind(payload: Any) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    if _safe_text(payload.get("diagnostic_type")):
        return "diagnostic"
    if _safe_text(payload.get("visibility_type")):
        return "visibility"
    return None


def _semantic_authority_paths(value: Any, *, prefix: str = "") -> list[str]:
    return matching_paths(
        value,
        SEMANTIC_AUTHORITY_FIELDS,
        prefix=prefix,
        false_allowed_fields=frozenset(
            {
                "memory_write_allowed",
                "memory_writes_allowed",
                "planner_semantic_authority",
            }
        ),
    )


def _forbidden_content_paths(value: Any, *, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            path = f"{prefix}.{key}" if prefix else key
            if key in FORBIDDEN_CONTENT_FIELDS:
                paths.append(path)
            paths.extend(_forbidden_content_paths(item, prefix=path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            paths.extend(_forbidden_content_paths(item, prefix=f"{prefix}[{index}]"))
    return paths


def _diagnostic(
    *,
    allowed: bool,
    source: str,
    reason: str,
    blocked_fields: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "contract_id": VISIBILITY_ISOLATION_CONTRACT_ID,
        "diagnostic_type": VISIBILITY_ISOLATION_DIAGNOSTIC_TYPE,
        "source": source,
        "allowed": bool(allowed),
        "visibility_observational_only": True,
        "diagnostics_observational_only": True,
        "planner_semantic_authority_preserved": bool(allowed),
        "semantic_reinterpretation_performed": False,
        "hidden_context_injection_performed": False,
        "memory_write_performed": False,
        "blocked_fields": list(blocked_fields or []),
        "validator_lineage": validator_lineage(
            owner="runtime.governance.visibility_isolation",
            validator=source.split(":", 1)[0],
            contract_id=VISIBILITY_ISOLATION_CONTRACT_ID,
            source=source,
        ),
        "reason": reason,
    }


def _safe_text(value: Any) -> str | None:
    return safe_string(value)


def _unique(values: list[str]) -> list[str]:
    return unique_values(values)


__all__ = [
    "ALLOWED_DIAGNOSTIC_ATTACHMENT_TARGETS",
    "ALLOWED_VISIBILITY_ATTACHMENT_TARGETS",
    "FORBIDDEN_ATTACHMENT_TARGETS",
    "FORBIDDEN_CONTENT_FIELDS",
    "SEMANTIC_AUTHORITY_FIELDS",
    "VISIBILITY_ISOLATION_CONTRACT_ID",
    "VISIBILITY_ISOLATION_DIAGNOSTIC_TYPE",
    "VisibilityIsolationError",
    "assert_visibility_attachment_allowed",
    "validate_diagnostic_visibility_surface",
    "validate_operator_visibility_surface",
    "validate_visibility_attachment",
    "visibility_isolation_policy",
]
