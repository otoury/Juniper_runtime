from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from runtime.registries.scheduled_task_registry import ScheduledTaskDeclaration
from runtime.scheduling.workflow_orchestration import ScheduledWorkflowExecutionPlan


LOCK_ACQUIRED = "acquired"
LOCK_DUPLICATE = "duplicate_window"
LOCK_MALFORMED = "malformed_lock_state"


@dataclass
class ScheduledWorkflowLockState:
    completed_windows: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class ScheduledWorkflowLockDecision:
    acquired: bool
    lock_key: str
    status: str
    skipped_reason: str | None = None


def acquire_scheduled_workflow_lock(
    plan: ScheduledWorkflowExecutionPlan,
    *,
    due_at: datetime,
    state: ScheduledWorkflowLockState,
    declaration: ScheduledTaskDeclaration | None = None,
) -> ScheduledWorkflowLockDecision:
    if not isinstance(state, ScheduledWorkflowLockState) or not isinstance(
        state.completed_windows,
        set,
    ):
        return ScheduledWorkflowLockDecision(
            acquired=False,
            lock_key="",
            status=LOCK_MALFORMED,
            skipped_reason="malformed_lock_state",
        )

    lock_key = scheduled_workflow_window_key(
        plan,
        due_at=due_at,
        declaration=declaration,
    )
    if not lock_key:
        return ScheduledWorkflowLockDecision(
            acquired=False,
            lock_key="",
            status=LOCK_MALFORMED,
            skipped_reason="malformed_lock_key",
        )

    if lock_key in state.completed_windows:
        return ScheduledWorkflowLockDecision(
            acquired=False,
            lock_key=lock_key,
            status=LOCK_DUPLICATE,
            skipped_reason="duplicate_due_window",
        )

    state.completed_windows.add(lock_key)
    return ScheduledWorkflowLockDecision(
        acquired=True,
        lock_key=lock_key,
        status=LOCK_ACQUIRED,
    )


def scheduled_workflow_window_key(
    plan: ScheduledWorkflowExecutionPlan,
    *,
    due_at: datetime,
    declaration: ScheduledTaskDeclaration | None = None,
) -> str:
    timestamp = _normalize_timestamp(due_at)
    window = _window_value(plan, timestamp=timestamp, declaration=declaration)
    if not window:
        return ""
    return "|".join((plan.task_id, plan.schedule_type, window))


def _window_value(
    plan: ScheduledWorkflowExecutionPlan,
    *,
    timestamp: datetime,
    declaration: ScheduledTaskDeclaration | None,
) -> str:
    if plan.schedule_type == "cron":
        return timestamp.replace(second=0, microsecond=0).isoformat()
    if plan.schedule_type == "interval":
        every_ms = _interval_ms(declaration)
        if every_ms is None:
            return ""
        timestamp_ms = int(timestamp.timestamp() * 1000)
        window_index = timestamp_ms // every_ms
        return str(window_index)
    return ""


def _interval_ms(declaration: ScheduledTaskDeclaration | None) -> int | None:
    if declaration is None:
        return None
    schedule = declaration.schedule
    if not isinstance(schedule, dict):
        return None
    every_ms = schedule.get("every_ms")
    if not isinstance(every_ms, int) or isinstance(every_ms, bool) or every_ms < 1:
        return None
    return every_ms


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "LOCK_ACQUIRED",
    "LOCK_DUPLICATE",
    "LOCK_MALFORMED",
    "ScheduledWorkflowLockDecision",
    "ScheduledWorkflowLockState",
    "acquire_scheduled_workflow_lock",
    "scheduled_workflow_window_key",
]
