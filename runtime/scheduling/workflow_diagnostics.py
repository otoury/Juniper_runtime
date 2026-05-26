from __future__ import annotations

import hashlib
from typing import Any, Mapping


SCHEDULED_WORKFLOW_DIAGNOSTIC_TYPE = "scheduled_workflow_execution_visibility"
SCHEDULED_WORKFLOW_LINEAGE_TYPE = "scheduled_workflow_lineage"
SCHEDULED_WORKFLOW_DIAGNOSTIC_VERSION = 1

RETRIEVAL_OPERATION_TYPES = frozenset({"NEWS_INGESTION", "DATABASE_AUDIT"})


def build_scheduled_workflow_lineage(plan: Any) -> dict[str, Any]:
    operation = _semantic_operation(plan)
    fields = {
        "task_id": _text(getattr(plan, "task_id", "")),
        "agent": _text(getattr(plan, "agent", "")),
        "workflow": _text(getattr(plan, "workflow", "")),
        "binding_id": _text(getattr(plan, "binding_id", "")),
        "capability_id": _text(operation.get("capability_id")),
        "operation_type": _text(operation.get("operation_type")),
        "schedule_type": _text(getattr(plan, "schedule_type", "")),
        "manifest_path": _text(getattr(plan, "manifest_path", "")),
    }
    lineage_id = _digest(":".join(fields.values()))
    return {
        "lineage_type": SCHEDULED_WORKFLOW_LINEAGE_TYPE,
        "lineage_id": f"scheduled_workflow_lineage_{lineage_id}",
        **fields,
        "declared_task_only": True,
        "runtime_reinterpretation_performed": False,
    }


def build_scheduled_workflow_execution_diagnostics(
    plan: Any,
    *,
    execution_mode: Any = "scheduled",
    execution_status: Any,
    execution_performed: Any,
    skipped_reasons: Any = (),
    audit_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    operation = _semantic_operation(plan)
    summary = audit_summary if isinstance(audit_summary, Mapping) else {}
    execution_allowed = (
        getattr(plan, "governance_state", "") == "enabled"
        and _operation_allows_scheduler_execution(operation)
    )
    return {
        "diagnostic_type": SCHEDULED_WORKFLOW_DIAGNOSTIC_TYPE,
        "diagnostic_version": SCHEDULED_WORKFLOW_DIAGNOSTIC_VERSION,
        "observational_only": True,
        "content_safe": True,
        "planner_semantic_authority": False,
        "semantic_reinterpretation_performed": False,
        "hidden_context_injection_performed": False,
        "workflow_state_mutation_performed": False,
        "governance_state_mutation_performed": False,
        "memory_write_performed": False,
        "artifact_mutation_performed": False,
        "workflow_lineage": build_scheduled_workflow_lineage(plan),
        "execution_state": {
            "execution_status": _text(execution_status),
            "execution_performed": bool(execution_performed),
            "execution_mode": _text(execution_mode) or "scheduled",
            "plan_mode": _text(getattr(plan, "plan_mode", "")),
            "dry_run_plan_source": bool(getattr(plan, "dry_run", False)),
            "declared_task_only": True,
            "allowlisted": bool(_binding_matches_declared_task(plan)),
            "skipped_reasons": _string_list(skipped_reasons),
        },
        "approval_governance": {
            "governance_state": _text(getattr(plan, "governance_state", "")),
            "execution_allowed": bool(execution_allowed),
            "requires_approval": bool(operation.get("requires_approval")),
            "approval_bypass_performed": False,
            "approval_required_blocked_execution": bool(
                operation.get("requires_approval")
            ),
            "external_side_effects_allowed": bool(
                operation.get("external_side_effects_allowed")
            ),
            "memory_write_allowed": bool(operation.get("memory_write_allowed")),
            "scheduler_governance_bypass_performed": False,
        },
        "scheduler_decisions": _scheduler_decisions(
            plan,
            skipped_reasons=skipped_reasons,
            summary=summary,
        ),
        "retrieval_diagnostics": _retrieval_diagnostics(operation, summary),
    }


def scheduler_execution_block_reasons(plan: Any) -> tuple[str, ...]:
    operation = _semantic_operation(plan)
    reasons: list[str] = []
    if not _binding_matches_declared_task(plan):
        reasons.append("declared_binding_mismatch")
    if operation.get("requires_approval") is True:
        reasons.append("approval_required")
    if operation.get("external_side_effects_allowed") is True:
        reasons.append("external_side_effects_not_scheduler_executable")
    if operation.get("memory_write_allowed") is True:
        reasons.append("memory_write_not_scheduler_executable")
    return tuple(reasons)


def _retrieval_diagnostics(
    operation: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    operation_type = _text(operation.get("operation_type"))
    applicable = operation_type in RETRIEVAL_OPERATION_TYPES
    fetched = _int(summary.get("fetched_count"))
    failed = _int(summary.get("failed_count"))
    skipped = _int(summary.get("skipped_count"))
    source_count = _int(summary.get("source_count"))
    return {
        "retrieval_applicable": applicable,
        "retrieval_executed": bool(
            applicable and (fetched > 0 or failed > 0 or source_count > 0)
        ),
        "hidden_retrieval_performed": False,
        "external_call_performed": bool(summary.get("external_call_performed")),
        "records_returned": _int(summary.get("total_entry_count")),
        "source_count": source_count,
        "fetched_count": fetched,
        "failed_count": failed,
        "skipped_count": skipped,
        "retrieval_to_trust_or_approval_influence": False,
    }


def _scheduler_decisions(
    plan: Any,
    *,
    skipped_reasons: Any,
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    reasons = _string_list(skipped_reasons)
    return {
        "dry_run_plan": _text(getattr(plan, "plan_mode", "")) == "dry_run",
        "local_cache_operation_allowed": bool(
            summary.get("local_cache_operation_allowed")
        ),
        "local_cache_read_allowed": bool(summary.get("local_cache_read_allowed")),
        "local_cache_synthesis_allowed": bool(
            summary.get("local_cache_synthesis_allowed")
        ),
        "external_network_fetch_blocked": bool(
            summary.get("external_network_fetch_blocked")
        ),
        "external_network_fetch_reason": _text(
            summary.get("external_network_fetch_reason")
        ),
        "governance_disabled": (
            _text(getattr(plan, "governance_state", "")) == "disabled"
            or "governance_disabled" in reasons
        ),
        "governance_audit_only": (
            _text(getattr(plan, "governance_state", "")) == "audit_only"
            or "governance_audit_only" in reasons
        ),
        "workflow_not_allowlisted": "workflow_not_allowlisted" in reasons,
        "fail_closed_external_calls": not bool(
            summary.get("external_call_performed")
        )
        if bool(summary.get("external_network_fetch_blocked"))
        else True,
    }


def _operation_allows_scheduler_execution(operation: Mapping[str, Any]) -> bool:
    return (
        operation.get("requires_approval") is False
        and operation.get("external_side_effects_allowed") is False
        and operation.get("memory_write_allowed") is False
    )


def _binding_matches_declared_task(plan: Any) -> bool:
    task_id = _text(getattr(plan, "task_id", ""))
    return (
        task_id
        and task_id == _text(getattr(plan, "workflow", ""))
        and task_id == _text(getattr(plan, "binding_id", ""))
    )


def _semantic_operation(plan: Any) -> Mapping[str, Any]:
    operation = getattr(plan, "semantic_operation", {})
    return operation if isinstance(operation, Mapping) else {}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _int(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    found: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip() and item.strip() not in found:
            found.append(item.strip())
    return found


__all__ = [
    "SCHEDULED_WORKFLOW_DIAGNOSTIC_TYPE",
    "SCHEDULED_WORKFLOW_LINEAGE_TYPE",
    "build_scheduled_workflow_execution_diagnostics",
    "build_scheduled_workflow_lineage",
    "scheduler_execution_block_reasons",
]
