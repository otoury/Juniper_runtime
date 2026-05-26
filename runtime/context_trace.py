from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
from typing import Any, Callable

from runtime.bindings import (
    BindingResolutionError,
    ROOT,
    resolve_agent_binding,
)


SUPPORTED_CONTEXT_POLICY_FIELDS = {
    "include_guest_context",
    "include_recent_artifacts",
    "include_user_preferences",
    "resource_scopes",
    "max_context_items",
}

RECENT_ARTIFACT_BY_CAPABILITY = {
    "draft_email": "email_draft",
    "create_lower_third": "lower_third",
    "producer_note": "producer_note",
}


@dataclass(frozen=True)
class PlannedContextItem:
    source_type: str
    source_name: str
    inclusion_reason: str
    bounded: bool
    attributable: bool
    planned_only: bool


@dataclass(frozen=True)
class ContextPlanningError:
    error_code: str
    message: str
    details: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PlannedContextTrace:
    request_id: str
    agent_name: str
    shared_capability: str
    context_policy: dict[str, Any] | None
    planned_items: list[PlannedContextItem]
    resolution_status: str
    errors: list[ContextPlanningError]
    bounded_item_count: int
    retrieval_policy: dict[str, Any]
    manifest_path: Path | None


def _error(
    error_code: str,
    message: str,
    details: list[str] | None = None,
) -> ContextPlanningError:
    return ContextPlanningError(
        error_code=error_code,
        message=message,
        details=list(details or []),
    )


def _validate_context_policy(
    policy: Any,
) -> tuple[dict[str, Any] | None, list[ContextPlanningError]]:
    errors: list[ContextPlanningError] = []

    if policy is None:
        return None, [
            _error(
                "missing_context_policy",
                "Binding does not declare a context_policy.",
            )
        ]

    if not isinstance(policy, dict):
        return None, [
            _error(
                "invalid_context_policy",
                "context_policy must be an object.",
            )
        ]

    unknown = sorted(set(policy) - SUPPORTED_CONTEXT_POLICY_FIELDS)

    if unknown:
        errors.append(
            _error(
                "unsupported_context_policy_fields",
                "context_policy contains unsupported fields.",
                unknown,
            )
        )

    bool_fields = [
        "include_guest_context",
        "include_recent_artifacts",
        "include_user_preferences",
    ]

    for field_name in bool_fields:
        if field_name in policy and not isinstance(
            policy[field_name],
            bool,
        ):
            errors.append(
                _error(
                    "invalid_context_policy",
                    f"{field_name} must be a boolean.",
                    [field_name],
                )
            )

    resource_scopes = policy.get("resource_scopes", [])

    if not isinstance(resource_scopes, list) or any(
        not isinstance(item, str) for item in resource_scopes
    ):
        errors.append(
            _error(
                "invalid_context_policy",
                "resource_scopes must be a list of strings.",
                ["resource_scopes"],
            )
        )

    max_context_items = policy.get("max_context_items", 0)

    if (
        not isinstance(max_context_items, int)
        or isinstance(max_context_items, bool)
        or max_context_items < 0
    ):
        errors.append(
            _error(
                "invalid_context_policy",
                "max_context_items must be a non-negative integer.",
                ["max_context_items"],
            )
        )

    if errors:
        return None, errors

    return {
        "include_guest_context": bool(
            policy.get("include_guest_context", False)
        ),
        "include_recent_artifacts": bool(
            policy.get("include_recent_artifacts", False)
        ),
        "include_user_preferences": bool(
            policy.get("include_user_preferences", False)
        ),
        "resource_scopes": list(resource_scopes),
        "max_context_items": max_context_items,
    }, []


def _planned_item(
    *,
    source_type: str,
    source_name: str,
    inclusion_reason: str,
) -> PlannedContextItem:
    return PlannedContextItem(
        source_type=source_type,
        source_name=source_name,
        inclusion_reason=inclusion_reason,
        bounded=True,
        attributable=True,
        planned_only=True,
    )


def _candidate_items(
    *,
    agent_name: str,
    shared_capability: str,
    binding_resources: list[str],
    context_policy: dict[str, Any],
) -> tuple[list[PlannedContextItem], list[ContextPlanningError]]:
    items: list[PlannedContextItem] = []
    errors: list[ContextPlanningError] = []

    if context_policy["include_guest_context"]:
        if "guest_db" not in binding_resources:
            errors.append(
                _error(
                    "missing_required_resource",
                    "guest context requires the guest_db binding resource.",
                    ["guest_db"],
                )
            )
        else:
            items.append(
                _planned_item(
                    source_type="agent_resource",
                    source_name=f"{agent_name}.guest_db",
                    inclusion_reason=(
                        "Binding context_policy includes bounded "
                        "guest context."
                    ),
                )
            )

    if context_policy["include_recent_artifacts"]:
        artifact_type = RECENT_ARTIFACT_BY_CAPABILITY.get(
            shared_capability
        )

        if artifact_type:
            items.append(
                _planned_item(
                    source_type="recent_artifacts",
                    source_name=artifact_type,
                    inclusion_reason=(
                        "Binding context_policy includes recent "
                        f"{artifact_type} artifacts."
                    ),
                )
            )
        else:
            errors.append(
                _error(
                    "unsupported_recent_artifact_context",
                    "No bounded recent-artifact context is defined for "
                    f"{shared_capability}.",
                    [shared_capability],
                )
            )

    if context_policy["include_user_preferences"]:
        items.append(
            _planned_item(
                source_type="memory",
                source_name="user_preferences",
                inclusion_reason=(
                    "Binding context_policy includes user preference "
                    "memory."
                ),
            )
        )

    return items, errors


def trace_planned_context(
    *,
    request_id: str,
    agent_name: str,
    shared_capability: str,
    root: Path = ROOT,
) -> PlannedContextTrace:
    result = resolve_agent_binding(
        agent_name,
        shared_capability,
        root=root,
    )

    retrieval_policy = {
        "mode": "planned_only",
        "retrieval_execution": False,
        "message_injection": False,
    }

    if isinstance(result, BindingResolutionError):
        return PlannedContextTrace(
            request_id=request_id,
            agent_name=agent_name,
            shared_capability=shared_capability,
            context_policy=None,
            planned_items=[],
            resolution_status="ERROR",
            errors=[
                _error(
                    result.error_code,
                    result.message,
                    result.details,
                )
            ],
            bounded_item_count=0,
            retrieval_policy=retrieval_policy,
            manifest_path=result.raw_manifest_path,
        )

    context_policy, errors = _validate_context_policy(
        result.raw_binding_data.get("context_policy")
    )

    if context_policy is None:
        return PlannedContextTrace(
            request_id=request_id,
            agent_name=agent_name,
            shared_capability=shared_capability,
            context_policy=None,
            planned_items=[],
            resolution_status="ERROR",
            errors=errors,
            bounded_item_count=0,
            retrieval_policy=retrieval_policy,
            manifest_path=result.raw_manifest_path,
        )

    candidates, item_errors = _candidate_items(
        agent_name=agent_name,
        shared_capability=shared_capability,
        binding_resources=result.resources,
        context_policy=context_policy,
    )
    errors.extend(item_errors)

    max_context_items = context_policy["max_context_items"]
    planned_items = candidates[:max_context_items]

    if len(candidates) > len(planned_items):
        errors.append(
            _error(
                "max_context_items_enforced",
                "Planned context items were bounded by max_context_items.",
                [
                    f"candidate_count={len(candidates)}",
                    f"max_context_items={max_context_items}",
                ],
            )
        )

    status = "OK" if not errors else "WARNING"

    return PlannedContextTrace(
        request_id=request_id,
        agent_name=agent_name,
        shared_capability=shared_capability,
        context_policy=context_policy,
        planned_items=planned_items,
        resolution_status=status,
        errors=errors,
        bounded_item_count=len(planned_items),
        retrieval_policy=retrieval_policy,
        manifest_path=result.raw_manifest_path,
    )


def planned_context_trace_dict(
    trace: PlannedContextTrace,
) -> dict[str, Any]:
    payload = asdict(trace)

    if trace.manifest_path:
        payload["manifest_path"] = str(trace.manifest_path)

    return payload


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)

    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}

    if isinstance(value, list):
        return [_json_safe(item) for item in value]

    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    return str(value)


def planned_context_trace_to_payload(
    trace: PlannedContextTrace,
) -> dict[str, Any]:
    retrieval_execution = bool(
        trace.retrieval_policy.get("retrieval_execution", False)
    )
    message_injection = bool(
        trace.retrieval_policy.get("message_injection", False)
    )

    payload = {
        "request_id": trace.request_id,
        "agent": trace.agent_name,
        "shared_capability": trace.shared_capability,
        "resolution_status": trace.resolution_status,
        "context_policy": trace.context_policy,
        "bounded_item_count": trace.bounded_item_count,
        "retrieval_execution": retrieval_execution,
        "message_injection": message_injection,
        "planned_items": [
            {
                "source_type": item.source_type,
                "source_name": item.source_name,
                "inclusion_reason": item.inclusion_reason,
                "bounded": item.bounded,
                "attributable": item.attributable,
                "planned_only": item.planned_only,
            }
            for item in trace.planned_items
        ],
        "errors": [
            {
                "error_code": error.error_code,
                "message": error.message,
                "details": list(error.details),
            }
            for error in trace.errors
        ],
        "manifest_path": (
            str(trace.manifest_path)
            if trace.manifest_path
            else None
        ),
    }

    return _json_safe(payload)


def build_context_trace_payload(
    *,
    request_id: str | None,
    agent: str,
    shared_capability: str | None,
    injection_id: str | None,
    source_contract_id: str | None,
    injection_performed: bool,
    skipped_reasons: list[str],
    collection_summary: dict | None,
    provenance_validated: bool,
    rollback_enabled: bool,
) -> dict[str, Any]:
    payload = {
        "request_id": request_id,
        "agent": agent,
        "shared_capability": shared_capability,
        "injection_id": injection_id,
        "source_contract_id": source_contract_id,
        "injection_performed": injection_performed,
        "skipped_reasons": list(skipped_reasons),
        "collection_summary": collection_summary,
        "provenance_validated": provenance_validated,
        "rollback_enabled": rollback_enabled,
    }

    return _json_safe(payload)


def context_trace_telemetry_enabled() -> bool:
    return os.getenv("JUNIPER_TRACE_BINDINGS") == "1"


def emit_planned_context_trace_telemetry(
    *,
    report_event: Callable[..., Any],
    source_bot: str,
    request_id: str,
    agent_name: str,
    shared_capability: str,
    user_id: str | None = None,
    root: Path = ROOT,
) -> PlannedContextTrace | None:
    if not context_trace_telemetry_enabled():
        return None

    trace = trace_planned_context(
        request_id=request_id,
        agent_name=agent_name,
        shared_capability=shared_capability,
        root=root,
    )
    payload = planned_context_trace_to_payload(trace)

    if user_id is not None:
        payload["user_id"] = user_id

    try:
        report_event(
            source_bot,
            "planned_context_trace",
            payload,
            request_id=request_id,
        )
    except Exception:
        pass

    return trace


__all__ = [
    "ContextPlanningError",
    "PlannedContextItem",
    "PlannedContextTrace",
    "build_context_trace_payload",
    "context_trace_telemetry_enabled",
    "emit_planned_context_trace_telemetry",
    "planned_context_trace_dict",
    "planned_context_trace_to_payload",
    "trace_planned_context",
]
