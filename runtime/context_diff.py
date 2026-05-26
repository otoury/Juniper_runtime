from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from runtime.context_injection import ContextInjectionPlan
from runtime.context_trace import PlannedContextTrace


@dataclass(frozen=True)
class ContextDiffItem:
    source: str
    change_type: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    attributable: bool
    bounded: bool


@dataclass(frozen=True)
class ContextDiffSummary:
    added_count: int
    removed_count: int
    changed_count: int
    estimated_token_delta: int
    injection_enabled: bool


@dataclass(frozen=True)
class ContextDiff:
    request_id: str
    agent_name: str
    shared_capability: str
    planned_context_count: int
    injection_plan_count: int
    added_items: list[ContextDiffItem]
    removed_items: list[ContextDiffItem]
    changed_items: list[ContextDiffItem]
    token_delta: int
    provenance_only: bool
    summary: ContextDiffSummary


def _planned_key(item) -> tuple[str, str]:
    return (item.source_type, item.source_name)


def _injection_key(item) -> tuple[str, str]:
    return (item.source_type, item.source)


def _planned_item_dict(item) -> dict[str, Any]:
    return {
        "source": item.source_name,
        "source_type": item.source_type,
        "inclusion_reason": item.inclusion_reason,
        "bounded": item.bounded,
        "attributable": item.attributable,
        "planned_only": item.planned_only,
    }


def _injection_item_dict(item) -> dict[str, Any]:
    return {
        "source": item.source,
        "source_type": item.source_type,
        "inclusion_reason": item.inclusion_reason,
        "token_count": item.token_count,
        "truncation_status": item.truncation_status,
        "attributable": item.attributable,
        "retrieval_scope": item.retrieval_scope,
        "injected": item.injected,
    }


def _comparable_planned(item) -> dict[str, Any]:
    return {
        "source": item.source_name,
        "source_type": item.source_type,
        "inclusion_reason": item.inclusion_reason,
        "attributable": item.attributable,
    }


def _comparable_injection(item) -> dict[str, Any]:
    return {
        "source": item.source,
        "source_type": item.source_type,
        "inclusion_reason": item.inclusion_reason,
        "attributable": item.attributable,
    }


def _diff_item(
    *,
    source: str,
    change_type: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    attributable: bool,
    bounded: bool,
) -> ContextDiffItem:
    return ContextDiffItem(
        source=source,
        change_type=change_type,
        before=before,
        after=after,
        attributable=attributable,
        bounded=bounded,
    )


def diff_context_plans(
    planned_context_trace: PlannedContextTrace,
    context_injection_plan: ContextInjectionPlan,
) -> ContextDiff:
    planned_by_key = {
        _planned_key(item): item
        for item in planned_context_trace.planned_items
    }
    injection_by_key = {
        _injection_key(item): item
        for item in context_injection_plan.planned_items
    }

    planned_keys = set(planned_by_key)
    injection_keys = set(injection_by_key)

    added_items = [
        _diff_item(
            source=injection_by_key[key].source,
            change_type="added",
            before=None,
            after=_injection_item_dict(injection_by_key[key]),
            attributable=bool(injection_by_key[key].attributable),
            bounded=True,
        )
        for key in sorted(injection_keys - planned_keys)
    ]

    removed_items = [
        _diff_item(
            source=planned_by_key[key].source_name,
            change_type="removed",
            before=_planned_item_dict(planned_by_key[key]),
            after=None,
            attributable=bool(planned_by_key[key].attributable),
            bounded=bool(planned_by_key[key].bounded),
        )
        for key in sorted(planned_keys - injection_keys)
    ]

    changed_items = []

    for key in sorted(planned_keys & injection_keys):
        planned = planned_by_key[key]
        injection = injection_by_key[key]

        if _comparable_planned(planned) != _comparable_injection(
            injection
        ):
            changed_items.append(
                _diff_item(
                    source=planned.source_name,
                    change_type="changed",
                    before=_planned_item_dict(planned),
                    after=_injection_item_dict(injection),
                    attributable=(
                        bool(planned.attributable)
                        and bool(injection.attributable)
                    ),
                    bounded=bool(planned.bounded),
                )
            )

    token_delta = context_injection_plan.total_estimated_tokens

    summary = ContextDiffSummary(
        added_count=len(added_items),
        removed_count=len(removed_items),
        changed_count=len(changed_items),
        estimated_token_delta=token_delta,
        injection_enabled=False,
    )

    return ContextDiff(
        request_id=planned_context_trace.request_id,
        agent_name=planned_context_trace.agent_name,
        shared_capability=planned_context_trace.shared_capability,
        planned_context_count=len(planned_context_trace.planned_items),
        injection_plan_count=len(context_injection_plan.planned_items),
        added_items=added_items,
        removed_items=removed_items,
        changed_items=changed_items,
        token_delta=token_delta,
        provenance_only=True,
        summary=summary,
    )


def context_diff_dict(diff: ContextDiff) -> dict[str, Any]:
    return asdict(diff)


__all__ = [
    "ContextDiff",
    "ContextDiffItem",
    "ContextDiffSummary",
    "context_diff_dict",
    "diff_context_plans",
]
