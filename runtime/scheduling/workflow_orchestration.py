from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from runtime.registries.scheduled_task_registry import (
    ScheduledTaskDeclaration,
    ScheduledTaskValidationError,
    audit_agent_scheduled_task_declarations,
)


PLAN_MODE_DRY_RUN = "dry_run"
RESOLUTION_DUE = "due"
RESOLUTION_NOT_DUE = "not_due"
RESOLUTION_SKIPPED = "skipped"
SUPPORTED_CRON_TIMEZONE = "UTC"


@dataclass(frozen=True)
class ScheduledWorkflowDueResolution:
    task_id: str
    agent: str
    workflow: str
    binding_id: str
    governance_state: str
    schedule_type: str
    due: bool
    resolution_status: str
    skipped_reasons: tuple[str, ...]
    declaration: ScheduledTaskDeclaration | None = None

    def to_trace(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent": self.agent,
            "workflow": self.workflow,
            "binding_id": self.binding_id,
            "governance_state": self.governance_state,
            "schedule_type": self.schedule_type,
            "due": self.due,
            "resolution_status": self.resolution_status,
            "skipped_reasons": list(self.skipped_reasons),
        }


@dataclass(frozen=True)
class ScheduledWorkflowExecutionPlan:
    task_id: str
    agent: str
    workflow: str
    binding_id: str
    semantic_operation: dict[str, Any]
    governance_state: str
    schedule_type: str
    plan_mode: str
    dry_run: bool
    execution_allowed_by_governance: bool
    execution_performed: bool
    max_runtime_ms: int
    max_concurrent_runs: int
    retry_policy: str
    skipped_reasons: tuple[str, ...]
    manifest_path: str

    def to_trace(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent": self.agent,
            "workflow": self.workflow,
            "binding_id": self.binding_id,
            "semantic_operation": dict(self.semantic_operation),
            "governance_state": self.governance_state,
            "schedule_type": self.schedule_type,
            "plan_mode": self.plan_mode,
            "dry_run": self.dry_run,
            "execution_allowed_by_governance": (
                self.execution_allowed_by_governance
            ),
            "execution_performed": self.execution_performed,
            "max_runtime_ms": self.max_runtime_ms,
            "max_concurrent_runs": self.max_concurrent_runs,
            "retry_policy": self.retry_policy,
            "skipped_reasons": list(self.skipped_reasons),
            "manifest_path": self.manifest_path,
        }


def discover_scheduled_workflows(
    agent: str,
    *,
    root: str | None = None,
) -> tuple[
    tuple[ScheduledTaskDeclaration, ...],
    tuple[ScheduledTaskValidationError, ...],
]:
    return audit_agent_scheduled_task_declarations(agent, root=root)


def resolve_due_scheduled_workflows(
    declarations: tuple[ScheduledTaskDeclaration, ...],
    *,
    now: datetime,
) -> tuple[ScheduledWorkflowDueResolution, ...]:
    timestamp = _normalize_timestamp(now)
    return tuple(
        _resolve_declaration_due(declaration, timestamp=timestamp)
        for declaration in declarations
    )


def build_due_scheduled_workflow_plans(
    declarations: tuple[ScheduledTaskDeclaration, ...],
    *,
    now: datetime,
) -> tuple[ScheduledWorkflowExecutionPlan, ...]:
    resolutions = resolve_due_scheduled_workflows(declarations, now=now)
    return tuple(
        _dry_run_plan(resolution)
        for resolution in resolutions
        if resolution.due and resolution.declaration is not None
    )


def scheduled_workflow_trace_payload(
    plans: tuple[ScheduledWorkflowExecutionPlan, ...],
    *,
    now: datetime,
) -> dict[str, Any]:
    timestamp = _normalize_timestamp(now)
    return {
        "trace_type": "scheduled_workflow_dry_run_plan",
        "timestamp": timestamp.isoformat(),
        "plan_count": len(plans),
        "dry_run": True,
        "execution_performed": False,
        "plans": [plan.to_trace() for plan in plans],
    }


def build_scheduled_workflow_summary(
    resolutions: tuple[ScheduledWorkflowDueResolution, ...],
    plans: tuple[ScheduledWorkflowExecutionPlan, ...],
) -> dict[str, Any]:
    return {
        "scheduled_workflows": {
            "discovered_count": len(resolutions),
            "due_count": sum(1 for resolution in resolutions if resolution.due),
            "dry_run_plan_count": len(plans),
            "execution_performed": False,
            "disabled_count": sum(
                1
                for resolution in resolutions
                if resolution.governance_state == "disabled"
            ),
            "audit_only_count": sum(
                1
                for resolution in resolutions
                if resolution.governance_state == "audit_only"
            ),
            "enabled_count": sum(
                1
                for resolution in resolutions
                if resolution.governance_state == "enabled"
            ),
            "skipped_reasons": _unique_skipped_reasons(resolutions, plans),
            "planned_task_ids": [plan.task_id for plan in plans],
        }
    }


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _resolve_declaration_due(
    declaration: ScheduledTaskDeclaration,
    *,
    timestamp: datetime,
) -> ScheduledWorkflowDueResolution:
    if declaration.governance_state == "disabled":
        return _resolution(
            declaration,
            due=False,
            status=RESOLUTION_SKIPPED,
            skipped_reasons=("governance_disabled",),
        )

    schedule_due, skipped_reasons = _schedule_due(declaration, timestamp)
    if not schedule_due:
        status = RESOLUTION_SKIPPED if skipped_reasons else RESOLUTION_NOT_DUE
        return _resolution(
            declaration,
            due=False,
            status=status,
            skipped_reasons=skipped_reasons,
        )

    return _resolution(
        declaration,
        due=True,
        status=RESOLUTION_DUE,
        skipped_reasons=(),
    )


def _resolution(
    declaration: ScheduledTaskDeclaration,
    *,
    due: bool,
    status: str,
    skipped_reasons: tuple[str, ...],
) -> ScheduledWorkflowDueResolution:
    return ScheduledWorkflowDueResolution(
        task_id=declaration.id,
        agent=declaration.agent,
        workflow=declaration.workflow,
        binding_id=declaration.binding_id,
        governance_state=declaration.governance_state,
        schedule_type=declaration.schedule_type,
        due=due,
        resolution_status=status,
        skipped_reasons=skipped_reasons,
        declaration=declaration,
    )


def _schedule_due(
    declaration: ScheduledTaskDeclaration,
    timestamp: datetime,
) -> tuple[bool, tuple[str, ...]]:
    if declaration.schedule_type == "cron":
        return _cron_due(declaration.schedule, timestamp)
    if declaration.schedule_type == "interval":
        return _interval_due(declaration.schedule, timestamp)
    return False, ("unsupported_schedule_type",)


def _cron_due(
    schedule: dict[str, Any],
    timestamp: datetime,
) -> tuple[bool, tuple[str, ...]]:
    if schedule.get("timezone") != SUPPORTED_CRON_TIMEZONE:
        return False, ("unsupported_cron_timezone",)

    expression = schedule.get("expression")
    if not isinstance(expression, str):
        return False, ("malformed_cron_expression",)

    fields = expression.split()
    if len(fields) != 5:
        return False, ("unsupported_cron_expression",)

    minute, hour, day_of_month, month, day_of_week = fields
    matchers = (
        _field_matches(minute, timestamp.minute, minimum=0, maximum=59),
        _field_matches(hour, timestamp.hour, minimum=0, maximum=23),
        _field_matches(
            day_of_month,
            timestamp.day,
            minimum=1,
            maximum=31,
        ),
        _field_matches(month, timestamp.month, minimum=1, maximum=12),
        _field_matches(
            day_of_week,
            _cron_day_of_week(timestamp),
            minimum=0,
            maximum=6,
        ),
    )
    if any(result is None for result in matchers):
        return False, ("unsupported_cron_expression",)
    return all(matchers), ()


def _field_matches(
    field: str,
    value: int,
    *,
    minimum: int,
    maximum: int,
) -> bool | None:
    if field == "*":
        return True
    if not field.isdecimal():
        return None
    parsed = int(field)
    if parsed < minimum or parsed > maximum:
        return None
    return parsed == value


def _cron_day_of_week(timestamp: datetime) -> int:
    return (timestamp.weekday() + 1) % 7


def _interval_due(
    schedule: dict[str, Any],
    timestamp: datetime,
) -> tuple[bool, tuple[str, ...]]:
    every_ms = schedule.get("every_ms")
    if not isinstance(every_ms, int) or isinstance(every_ms, bool) or every_ms < 1:
        return False, ("malformed_interval_schedule",)
    timestamp_ms = int(timestamp.timestamp() * 1000)
    return timestamp_ms % every_ms == 0, ()


def _dry_run_plan(
    resolution: ScheduledWorkflowDueResolution,
) -> ScheduledWorkflowExecutionPlan:
    declaration = resolution.declaration
    if declaration is None:
        raise ValueError("due resolution must include a declaration")

    governance_state = declaration.governance_state
    execution_allowed = governance_state == "enabled"
    skipped_reasons = ()
    if governance_state == "audit_only":
        skipped_reasons = ("governance_audit_only",)

    return ScheduledWorkflowExecutionPlan(
        task_id=declaration.id,
        agent=declaration.agent,
        workflow=declaration.workflow,
        binding_id=declaration.binding_id,
        semantic_operation=dict(declaration.semantic_operation),
        governance_state=governance_state,
        schedule_type=declaration.schedule_type,
        plan_mode=PLAN_MODE_DRY_RUN,
        dry_run=True,
        execution_allowed_by_governance=execution_allowed,
        execution_performed=False,
        max_runtime_ms=declaration.max_runtime_ms,
        max_concurrent_runs=declaration.max_concurrent_runs,
        retry_policy=declaration.retry_policy,
        skipped_reasons=skipped_reasons,
        manifest_path=str(declaration.manifest_path),
    )


def _unique_skipped_reasons(
    resolutions: tuple[ScheduledWorkflowDueResolution, ...],
    plans: tuple[ScheduledWorkflowExecutionPlan, ...],
) -> list[str]:
    reasons = []
    for item in (*resolutions, *plans):
        for reason in item.skipped_reasons:
            if reason not in reasons:
                reasons.append(reason)
    return reasons


__all__ = [
    "PLAN_MODE_DRY_RUN",
    "RESOLUTION_DUE",
    "RESOLUTION_NOT_DUE",
    "RESOLUTION_SKIPPED",
    "ScheduledWorkflowDueResolution",
    "ScheduledWorkflowExecutionPlan",
    "build_due_scheduled_workflow_plans",
    "build_scheduled_workflow_summary",
    "discover_scheduled_workflows",
    "resolve_due_scheduled_workflows",
    "scheduled_workflow_trace_payload",
]
