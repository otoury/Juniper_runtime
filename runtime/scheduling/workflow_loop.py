from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Callable

from runtime.scheduling.workflow_audit import SCHEDULED_WORKFLOW_AUDIT_LOG_PATH
from runtime.scheduling.workflow_executor import (
    EXECUTION_MODE_SCHEDULED,
    ScheduledWorkflowExecutionResult,
    execute_scheduled_workflow_manually,
)
from runtime.scheduling.workflow_locking import (
    ScheduledWorkflowLockState,
    acquire_scheduled_workflow_lock,
)
from runtime.scheduling.workflow_orchestration import (
    ScheduledWorkflowExecutionPlan,
    build_due_scheduled_workflow_plans,
    discover_scheduled_workflows,
)
from runtime.scheduling.workflow_telemetry import (
    DEFAULT_HEARTBEAT_MIN_INTERVAL_SECONDS,
    SCHEDULED_EXECUTOR_STATUS_LOG_PATH,
    ScheduledExecutorTelemetryState,
    emit_scheduled_executor_heartbeat,
    emit_scheduled_executor_started,
    emit_scheduled_task_completed,
    emit_scheduled_task_due,
    emit_scheduled_task_failed,
)


DEFAULT_POLL_INTERVAL_SECONDS = 60
MAX_POLL_INTERVAL_SECONDS = 3600


@dataclass(frozen=True)
class ScheduledWorkflowLoopIteration:
    iteration: int
    timestamp: str
    discovered_count: int
    plan_count: int
    execution_attempt_count: int
    execution_performed_count: int
    skipped_plan_count: int
    duplicate_skipped_count: int
    skipped_reasons: tuple[str, ...]

    def to_trace(self) -> dict[str, object]:
        return {
            "iteration": self.iteration,
            "timestamp": self.timestamp,
            "discovered_count": self.discovered_count,
            "plan_count": self.plan_count,
            "execution_attempt_count": self.execution_attempt_count,
            "execution_performed_count": self.execution_performed_count,
            "skipped_plan_count": self.skipped_plan_count,
            "duplicate_skipped_count": self.duplicate_skipped_count,
            "skipped_reasons": list(self.skipped_reasons),
        }


@dataclass(frozen=True)
class ScheduledWorkflowLoopResult:
    iterations_run: int
    stopped_reason: str
    execution_results: tuple[ScheduledWorkflowExecutionResult, ...]
    iteration_traces: tuple[ScheduledWorkflowLoopIteration, ...]

    def to_trace(self) -> dict[str, object]:
        return {
            "iterations_run": self.iterations_run,
            "stopped_reason": self.stopped_reason,
            "execution_result_count": len(self.execution_results),
            "execution_performed_count": sum(
                1 for result in self.execution_results if result.execution_performed
            ),
            "iteration_traces": [
                iteration.to_trace() for iteration in self.iteration_traces
            ],
        }


def run_scheduler_loop(
    *,
    agent: str = "alexis",
    root: str | Path | None = None,
    declarations: tuple[object, ...] | None = None,
    max_iterations: int = 1,
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
    now_provider: Callable[[], datetime] | None = None,
    sleep_fn: Callable[[int], None] = sleep,
    audit_path: str | Path = SCHEDULED_WORKFLOW_AUDIT_LOG_PATH,
    lock_state: ScheduledWorkflowLockState | None = None,
    status_path: str | Path = SCHEDULED_EXECUTOR_STATUS_LOG_PATH,
    telemetry_state: ScheduledExecutorTelemetryState | None = None,
    heartbeat_min_interval_seconds: int = DEFAULT_HEARTBEAT_MIN_INTERVAL_SECONDS,
    emit_started_event: bool = True,
    telemetry_enabled: bool = True,
) -> ScheduledWorkflowLoopResult:
    iterations = _bounded_iterations(max_iterations)
    interval = _bounded_poll_interval(poll_interval_seconds)
    current_time = now_provider or _utc_now

    execution_results: list[ScheduledWorkflowExecutionResult] = []
    iteration_traces: list[ScheduledWorkflowLoopIteration] = []
    locks = lock_state or ScheduledWorkflowLockState()
    heartbeat_state = telemetry_state or ScheduledExecutorTelemetryState()
    started_event_emitted = False

    for index in range(iterations):
        now = _normalize_timestamp(current_time())
        loaded_declarations = declarations
        skipped_reasons: list[str] = []
        if loaded_declarations is None:
            discovered, errors = discover_scheduled_workflows(
                agent,
                root=str(root) if root is not None else None,
            )
            loaded_declarations = discovered
            skipped_reasons.extend(
                f"registry_error:{error.field}" for error in errors
            )

        if emit_started_event and not started_event_emitted:
            emit_scheduled_executor_started(
                agent=agent,
                timestamp=now,
                poll_interval_seconds=interval,
                max_iterations=iterations,
                task_count=len(loaded_declarations),
                enabled_task_count=sum(
                    1
                    for declaration in tuple(loaded_declarations)
                    if getattr(declaration, "governance_state", "")
                    == "enabled"
                ),
                status_path=status_path,
                telemetry_enabled=telemetry_enabled,
            )
            started_event_emitted = True

        plans = build_due_scheduled_workflow_plans(
            tuple(loaded_declarations),
            now=now,
        )
        executable_plans = tuple(
            plan for plan in plans if _eligible_for_execution(plan)
        )
        skipped_reasons.extend(
            _skip_reason_for_plan(plan)
            for plan in plans
            if not _eligible_for_execution(plan)
        )

        locked_plans = []
        duplicate_skipped_count = 0
        declarations_by_id = {
            getattr(declaration, "id", ""): declaration
            for declaration in tuple(loaded_declarations)
        }
        for plan in executable_plans:
            decision = acquire_scheduled_workflow_lock(
                plan,
                due_at=now,
                state=locks,
                declaration=declarations_by_id.get(plan.task_id),
            )
            if decision.acquired:
                locked_plans.append(plan)
                continue
            duplicate_skipped_count += 1
            if decision.skipped_reason:
                skipped_reasons.append(decision.skipped_reason)

        for plan in locked_plans:
            emit_scheduled_task_due(
                plan=plan,
                timestamp=now,
                telemetry_enabled=telemetry_enabled,
            )
            try:
                result = execute_scheduled_workflow_manually(
                    plan,
                    execution_mode=EXECUTION_MODE_SCHEDULED,
                    audit_path=audit_path,
                )
            except Exception as exc:
                emit_scheduled_task_failed(
                    plan=plan,
                    timestamp=now,
                    reason=exc.__class__.__name__,
                    telemetry_enabled=telemetry_enabled,
                )
                raise
            execution_results.append(result)
            if _result_failed(result):
                emit_scheduled_task_failed(
                    plan=plan,
                    timestamp=now,
                    reason="workflow_reported_failed",
                    telemetry_enabled=telemetry_enabled,
                )
            elif result.execution_performed:
                emit_scheduled_task_completed(
                    result=result,
                    timestamp=now,
                    telemetry_enabled=telemetry_enabled,
                )
            else:
                emit_scheduled_task_failed(
                    plan=plan,
                    timestamp=now,
                    reason="execution_not_performed",
                    telemetry_enabled=telemetry_enabled,
                )

        execution_performed_count = sum(
            1 for result in execution_results if result.execution_performed
        )
        unique_skipped_reasons = tuple(_unique_strings(skipped_reasons))
        iteration_traces.append(
            ScheduledWorkflowLoopIteration(
                iteration=index + 1,
                timestamp=now.isoformat(),
                discovered_count=len(loaded_declarations),
                plan_count=len(plans),
                execution_attempt_count=len(executable_plans),
                execution_performed_count=execution_performed_count,
                skipped_plan_count=(
                    len(plans) - len(executable_plans) + duplicate_skipped_count
                ),
                duplicate_skipped_count=duplicate_skipped_count,
                skipped_reasons=unique_skipped_reasons,
            )
        )
        emit_scheduled_executor_heartbeat(
            agent=agent,
            timestamp=now,
            iteration=index + 1,
            declarations=tuple(loaded_declarations),
            plans=plans,
            execution_performed_count=execution_performed_count,
            skipped_reasons=unique_skipped_reasons,
            audit_path=audit_path,
            status_path=status_path,
            state=heartbeat_state,
            heartbeat_min_interval_seconds=heartbeat_min_interval_seconds,
            telemetry_enabled=telemetry_enabled,
        )

        if index < iterations - 1 and interval > 0:
            sleep_fn(interval)

    return ScheduledWorkflowLoopResult(
        iterations_run=iterations,
        stopped_reason="max_iterations_reached",
        execution_results=tuple(execution_results),
        iteration_traces=tuple(iteration_traces),
    )


def _eligible_for_execution(plan: ScheduledWorkflowExecutionPlan) -> bool:
    return plan.governance_state == "enabled"


def _skip_reason_for_plan(plan: ScheduledWorkflowExecutionPlan) -> str:
    if plan.governance_state == "disabled":
        return "governance_disabled"
    if plan.governance_state == "audit_only":
        return "governance_audit_only"
    return "not_execution_eligible"


def _result_failed(result: ScheduledWorkflowExecutionResult) -> bool:
    summary = result.audit_summary
    if not isinstance(summary, dict):
        return False
    return summary.get("execution_status") == "failed"


def _bounded_iterations(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return 0
    return value


def _bounded_poll_interval(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return DEFAULT_POLL_INTERVAL_SECONDS
    return min(value, MAX_POLL_INTERVAL_SECONDS)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _unique_strings(values: list[str]) -> list[str]:
    unique = []
    for value in values:
        if value and value not in unique:
            unique.append(value)
    return unique


__all__ = [
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "MAX_POLL_INTERVAL_SECONDS",
    "ScheduledWorkflowLoopIteration",
    "ScheduledWorkflowLoopResult",
    "run_scheduler_loop",
]
