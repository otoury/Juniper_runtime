from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from runtime.context_trace import (
    ContextPlanningError,
    PlannedContextTrace,
    planned_context_trace_dict,
)


ALLOWED_SOURCE_TYPES = {
    "agent_resource",
    "recent_artifacts",
    "memory",
    "contract",
}

DEFAULT_INJECT_AS = "bounded_context_block"
DEFAULT_PROVENANCE_VISIBILITY = "telemetry_and_trace"


@dataclass(frozen=True)
class ContextInjectionPolicy:
    enabled: bool = False
    max_items: int = 0
    max_tokens: int = 1
    allowed_source_types: list[str] = field(default_factory=list)
    redact_sensitive: bool = True
    approval_sensitive: bool = False
    inject_as: str = DEFAULT_INJECT_AS
    provenance_visibility: str = DEFAULT_PROVENANCE_VISIBILITY


@dataclass(frozen=True)
class InjectedContextItem:
    source: str
    source_type: str
    inclusion_reason: str
    token_count: int
    truncation_status: str
    attributable: bool
    retrieval_scope: str
    injected: bool


@dataclass(frozen=True)
class ContextInjectionError:
    error_code: str
    message: str
    details: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ContextInjectionPlan:
    request_id: str
    agent_name: str
    shared_capability: str
    enabled: bool
    planned_items: list[InjectedContextItem]
    total_estimated_tokens: int
    injection_performed: bool
    provenance_only: bool
    errors: list[ContextInjectionError]


def _error(
    error_code: str,
    message: str,
    details: list[str] | None = None,
) -> ContextInjectionError:
    return ContextInjectionError(
        error_code=error_code,
        message=message,
        details=list(details or []),
    )


def _coerce_policy(
    policy: ContextInjectionPolicy | dict[str, Any] | None,
) -> ContextInjectionPolicy | None:
    if policy is None:
        return ContextInjectionPolicy()

    if isinstance(policy, ContextInjectionPolicy):
        return policy

    if not isinstance(policy, dict):
        return None

    return ContextInjectionPolicy(
        enabled=policy.get("enabled", False),
        max_items=policy.get("max_items", 0),
        max_tokens=policy.get("max_tokens", 1),
        allowed_source_types=list(
            policy.get("allowed_source_types", [])
        ),
        redact_sensitive=policy.get("redact_sensitive", True),
        approval_sensitive=policy.get("approval_sensitive", False),
        inject_as=policy.get("inject_as", DEFAULT_INJECT_AS),
        provenance_visibility=policy.get(
            "provenance_visibility",
            DEFAULT_PROVENANCE_VISIBILITY,
        ),
    )


def validate_context_injection_policy(
    policy: ContextInjectionPolicy | dict[str, Any] | None = None,
) -> tuple[ContextInjectionPolicy | None, list[ContextInjectionError]]:
    coerced = _coerce_policy(policy)

    if coerced is None:
        return None, [
            _error(
                "invalid_injection_policy",
                "Context injection policy must be an object.",
            )
        ]

    errors: list[ContextInjectionError] = []

    if not isinstance(coerced.enabled, bool):
        errors.append(
            _error(
                "invalid_injection_policy",
                "enabled must be a boolean.",
                ["enabled"],
            )
        )

    if (
        not isinstance(coerced.max_items, int)
        or isinstance(coerced.max_items, bool)
        or coerced.max_items < 0
    ):
        errors.append(
            _error(
                "invalid_injection_policy",
                "max_items must be a non-negative integer.",
                ["max_items"],
            )
        )

    if (
        not isinstance(coerced.max_tokens, int)
        or isinstance(coerced.max_tokens, bool)
        or coerced.max_tokens <= 0
    ):
        errors.append(
            _error(
                "invalid_injection_policy",
                "max_tokens must be a positive integer.",
                ["max_tokens"],
            )
        )

    if not isinstance(coerced.allowed_source_types, list) or any(
        not isinstance(item, str)
        for item in coerced.allowed_source_types
    ):
        errors.append(
            _error(
                "invalid_injection_policy",
                "allowed_source_types must be a list of strings.",
                ["allowed_source_types"],
            )
        )
    else:
        unknown = sorted(
            set(coerced.allowed_source_types) - ALLOWED_SOURCE_TYPES
        )

        if unknown:
            errors.append(
                _error(
                    "invalid_injection_policy",
                    "allowed_source_types contains unsupported sources.",
                    unknown,
                )
            )

    if not isinstance(coerced.redact_sensitive, bool):
        errors.append(
            _error(
                "invalid_injection_policy",
                "redact_sensitive must be a boolean.",
                ["redact_sensitive"],
            )
        )

    if not isinstance(coerced.approval_sensitive, bool):
        errors.append(
            _error(
                "invalid_injection_policy",
                "approval_sensitive must be a boolean.",
                ["approval_sensitive"],
            )
        )

    if not str(coerced.inject_as or "").strip():
        errors.append(
            _error(
                "invalid_injection_policy",
                "inject_as must be a non-empty string.",
                ["inject_as"],
            )
        )

    if not str(coerced.provenance_visibility or "").strip():
        errors.append(
            _error(
                "invalid_injection_policy",
                "provenance_visibility must be a non-empty string.",
                ["provenance_visibility"],
            )
        )

    if errors:
        return None, errors

    return coerced, []


def _trace_errors(
    planned_context_trace: PlannedContextTrace,
) -> list[ContextInjectionError]:
    errors = []

    for error in planned_context_trace.errors:
        if isinstance(error, ContextPlanningError):
            errors.append(
                _error(
                    error.error_code,
                    error.message,
                    error.details,
                )
            )
        else:
            errors.append(
                _error(
                    "context_trace_error",
                    str(error),
                )
            )

    return errors


def _estimated_tokens(text: str) -> int:
    return max(1, len((text or "").split()))


def _item_to_injection_item(
    item,
) -> InjectedContextItem:
    token_count = _estimated_tokens(
        f"{item.source_name} {item.inclusion_reason}"
    )

    return InjectedContextItem(
        source=item.source_name,
        source_type=item.source_type,
        inclusion_reason=item.inclusion_reason,
        token_count=token_count,
        truncation_status="not_truncated",
        attributable=bool(item.attributable),
        retrieval_scope="planned_only",
        injected=False,
    )


def build_context_injection_plan(
    planned_context_trace: PlannedContextTrace,
    *,
    policy: ContextInjectionPolicy | dict[str, Any] | None = None,
) -> ContextInjectionPlan:
    validated_policy, errors = validate_context_injection_policy(
        policy
    )
    trace_errors = _trace_errors(planned_context_trace)
    errors.extend(trace_errors)

    if validated_policy is None:
        return ContextInjectionPlan(
            request_id=planned_context_trace.request_id,
            agent_name=planned_context_trace.agent_name,
            shared_capability=planned_context_trace.shared_capability,
            enabled=False,
            planned_items=[],
            total_estimated_tokens=0,
            injection_performed=False,
            provenance_only=True,
            errors=errors,
        )

    if validated_policy.approval_sensitive:
        errors.append(
            _error(
                "approval_sensitive_injection_disabled",
                "Approval-sensitive context injection remains disabled.",
            )
        )

    if not validated_policy.enabled:
        errors.append(
            _error(
                "injection_disabled",
                "Context injection is disabled by policy.",
            )
        )

    allowed_sources = set(validated_policy.allowed_source_types)
    source_filtered = [
        item
        for item in planned_context_trace.planned_items
        if item.source_type in allowed_sources
    ]

    if len(source_filtered) < len(planned_context_trace.planned_items):
        errors.append(
            _error(
                "source_type_filtered",
                "Some planned context items were outside allowed_source_types.",
            )
        )

    bounded = source_filtered[:validated_policy.max_items]

    if len(source_filtered) > len(bounded):
        errors.append(
            _error(
                "max_items_enforced",
                "Context injection plan was bounded by max_items.",
                [
                    f"candidate_count={len(source_filtered)}",
                    f"max_items={validated_policy.max_items}",
                ],
            )
        )

    planned_items: list[InjectedContextItem] = []
    total_tokens = 0

    for item in bounded:
        injection_item = _item_to_injection_item(item)

        if total_tokens + injection_item.token_count > (
            validated_policy.max_tokens
        ):
            errors.append(
                _error(
                    "max_tokens_enforced",
                    "Context injection plan was bounded by max_tokens.",
                    [
                        f"max_tokens={validated_policy.max_tokens}",
                    ],
                )
            )
            break

        planned_items.append(injection_item)
        total_tokens += injection_item.token_count

    return ContextInjectionPlan(
        request_id=planned_context_trace.request_id,
        agent_name=planned_context_trace.agent_name,
        shared_capability=planned_context_trace.shared_capability,
        enabled=False,
        planned_items=planned_items,
        total_estimated_tokens=total_tokens,
        injection_performed=False,
        provenance_only=True,
        errors=errors,
    )


def context_injection_plan_dict(
    plan: ContextInjectionPlan,
) -> dict[str, Any]:
    return asdict(plan)


__all__ = [
    "ContextInjectionError",
    "ContextInjectionPlan",
    "ContextInjectionPolicy",
    "InjectedContextItem",
    "build_context_injection_plan",
    "context_injection_plan_dict",
    "validate_context_injection_policy",
]
