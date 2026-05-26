from __future__ import annotations

import hashlib
from typing import Any, Mapping


TRUST_LINEAGE_TYPE = "capability_scoped_trust_lineage"
TRUST_SCOPE_VERSION = 1


def build_capability_scoped_trust_lineage(
    *,
    owning_agent: str | None,
    workflow_id: str | None,
    workflow_type: str | None,
    step_id: str | None = None,
    capability: str | None = None,
    action_type: str | None = None,
) -> dict[str, Any] | None:
    agent = _optional_string(owning_agent)
    workflow = _optional_string(workflow_id)
    workflow_kind = _optional_string(workflow_type)
    capability_name = _optional_string(capability)
    if agent is None or workflow is None or workflow_kind is None:
        return None
    if capability_name is None:
        return None

    scope = {
        "owning_agent": agent,
        "workflow_id": workflow,
        "workflow_type": workflow_kind,
        "capability": capability_name,
        "action_type": _optional_string(action_type),
    }
    scope_key = _scope_key(scope)
    return {
        "lineage_type": TRUST_LINEAGE_TYPE,
        "scope_version": TRUST_SCOPE_VERSION,
        **scope,
        "step_id": _optional_string(step_id),
        "scope_key": scope_key,
        "lineage_id": f"trust_lineage_{_digest(scope_key)}",
        "trust_inheritance_boundary": "workflow_capability_scope",
        "cross_scope_trust_inheritance_allowed": False,
    }


def trust_lineage_scope_key(lineage: Mapping[str, Any] | None) -> str | None:
    if not isinstance(lineage, Mapping):
        return None
    if lineage.get("lineage_type") != TRUST_LINEAGE_TYPE:
        return None
    scope_key = _optional_string(lineage.get("scope_key"))
    if scope_key is not None:
        return scope_key
    scope = {
        "owning_agent": _optional_string(lineage.get("owning_agent")),
        "workflow_id": _optional_string(lineage.get("workflow_id")),
        "workflow_type": _optional_string(lineage.get("workflow_type")),
        "capability": _optional_string(lineage.get("capability")),
        "action_type": _optional_string(lineage.get("action_type")),
    }
    if scope["owning_agent"] is None or scope["workflow_id"] is None:
        return None
    if scope["workflow_type"] is None or scope["capability"] is None:
        return None
    return _scope_key(scope)


def trust_lineage_scopes_match(
    prior_lineage: Mapping[str, Any] | None,
    current_lineage: Mapping[str, Any] | None,
) -> bool:
    prior_key = trust_lineage_scope_key(prior_lineage)
    current_key = trust_lineage_scope_key(current_lineage)
    return prior_key is not None and current_key is not None and prior_key == current_key


def _scope_key(scope: Mapping[str, Any]) -> str:
    parts = (
        _optional_string(scope.get("owning_agent")) or "",
        _optional_string(scope.get("workflow_id")) or "",
        _optional_string(scope.get("workflow_type")) or "",
        _optional_string(scope.get("capability")) or "",
        _optional_string(scope.get("action_type")) or "",
    )
    return "|".join(parts)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "TRUST_LINEAGE_TYPE",
    "TRUST_SCOPE_VERSION",
    "build_capability_scoped_trust_lineage",
    "trust_lineage_scope_key",
    "trust_lineage_scopes_match",
]
