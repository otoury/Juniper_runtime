from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from runtime.execution_containment import (
    render_governance_blocked_execution_response,
)


DEFAULT_OPERATOR_TIMEZONE = "UTC"


def format_operator_timestamp(
    value: datetime | str | None,
    *,
    local_tz: str | None = DEFAULT_OPERATOR_TIMEZONE,
    include_raw: bool = False,
) -> str:
    parsed = parse_operator_timestamp(value)
    if parsed is None:
        return _safe_text(value) or "unknown"

    utc_value = parsed.astimezone(timezone.utc)
    local_zone = _local_zone(local_tz)
    local_value = utc_value.astimezone(local_zone)
    local_label = _timezone_label(local_zone)
    local_display = _display_datetime(local_value)
    utc_display = _display_datetime(utc_value)

    if local_label == "UTC":
        rendered = f"{utc_display} UTC (Local: UTC)"
    else:
        rendered = f"{local_display} {local_label} (UTC: {utc_display} UTC)"
    if include_raw:
        rendered = f"{rendered}; raw={utc_value.isoformat()}"
    return rendered


def parse_operator_timestamp(value: datetime | str | None) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def render_status(
    label: str,
    state: Any,
    *,
    detail: str | None = None,
) -> str:
    normalized_label = _safe_text(label) or "Status"
    normalized_state = _safe_text(state) or "unknown"
    line = f"- {normalized_label}: {normalized_state}"
    if detail:
        line = f"{line} ({_safe_text(detail)})"
    return line


def render_diagnostic_footer(
    diagnostics: Mapping[str, Any] | None,
    *,
    verbose: bool = False,
) -> list[str]:
    if not isinstance(diagnostics, Mapping):
        return []
    hidden_context = diagnostics.get("hidden_context_injection_performed")
    if not isinstance(hidden_context, bool):
        hidden_context = diagnostics.get("hidden_fallback_performed")
    concise = [
        _bool_pair("external_call", diagnostics.get("external_call_performed")),
        _bool_pair("cost", diagnostics.get("cost_incurred")),
        _bool_pair("hidden_context", hidden_context),
    ]
    visible = [item for item in concise if item]
    lines = [f"Visibility: {', '.join(visible)}."] if visible else []
    if not verbose:
        return lines

    preserved = _bool_pair(
        "planner_authority",
        diagnostics.get("planner_semantic_authority"),
    )
    receipt = _bool_pair("receipt", diagnostics.get("receipt_bearing"))
    execution = _safe_text(
        diagnostics.get("execution_state") or diagnostics.get("execution_status")
    )
    verbose_parts = [part for part in (preserved, receipt, execution) if part]
    if verbose_parts:
        lines.append(f"Diagnostics: {', '.join(verbose_parts)}.")
    reasons = _safe_string_list(
        diagnostics.get("handoff_reason_codes")
        or diagnostics.get("skipped_reasons")
        or diagnostics.get("reason_codes")
    )
    if reasons:
        lines.append(f"Reasons: {', '.join(reasons[:6])}.")
    return lines


def render_latest_news_operator_status(
    *,
    freshness: datetime | str | None,
    fallback: Mapping[str, Any] | None = None,
    diagnostics: Mapping[str, Any] | None = None,
    verbose: bool = False,
) -> list[str]:
    lines = []
    if freshness is not None:
        lines.append(f"Fresh through {format_operator_timestamp(freshness)}.")
    if isinstance(fallback, Mapping):
        provider = _safe_text(
            fallback.get("fallback_provider_id")
            or fallback.get("fallback_provider_type")
            or fallback.get("provider_id")
        )
        live = _yes_no(fallback.get("live_allowed"))
        dry_run = _yes_no(fallback.get("dry_run"))
        if provider:
            lines.append(
                f"Fallback: {provider}; live={live}; dry_run={dry_run}."
            )
    lines.extend(render_diagnostic_footer(diagnostics, verbose=verbose))
    return lines


def render_governance_status(
    decisions: Sequence[tuple[str, Mapping[str, Any] | Any]],
    *,
    verbose: bool = False,
) -> str:
    lines = ["[RUNTIME GOVERNANCE]", "Runtime governance"]
    for label, decision in decisions:
        state = getattr(decision, "effective_state", None)
        allowed = getattr(decision, "allowed", None)
        source = getattr(decision, "source", None)
        if isinstance(decision, Mapping):
            state = decision.get("effective_state", state)
            allowed = decision.get("allowed", allowed)
            source = decision.get("source", source)
        detail = f"allowed={_yes_no(allowed)}"
        if verbose and source:
            detail = f"{detail}; source={_safe_text(source)}"
        lines.append(render_status(label, state, detail=detail))
    lines.append(
        "Boundaries: planner mutation=false; hidden execution=false; "
        "memory writes=false."
    )
    lines.append("Planner mutation: false")
    if not verbose:
        lines.append("Verbose diagnostics omitted.")
    return "\n".join(lines)


def render_governance_blocked_operator_response(
    diagnostics: Mapping[str, Any] | None,
    *,
    verbose: bool = False,
) -> str:
    safe_diagnostics = dict(diagnostics or {})
    lines = [
        render_governance_blocked_execution_response(
            safe_diagnostics,
            include_operator_action=True,
        ),
        "No provider request was sent.",
        "Boundaries: planner mutation=false; hidden retry=false; "
        "hidden context injection=false.",
    ]
    lines.extend(render_diagnostic_footer(safe_diagnostics, verbose=verbose))
    if not verbose:
        lines.append("Verbose diagnostics omitted.")
    return "\n".join(lines)


def render_scheduler_operator_report(
    payload: Mapping[str, Any],
    *,
    verbose: bool = False,
) -> str:
    due = _safe_string_list(payload.get("due_task_ids"))
    lines = [
        "Scheduled workflow status",
        f"Generated: {format_operator_timestamp(payload.get('timestamp'))}",
        (
            f"Agent: {_safe_text(payload.get('agent')) or 'unknown'} | "
            f"Scheduler: {'alive' if payload.get('scheduler_alive') else 'stale'} | "
            f"Due: {', '.join(due) if due else 'none'}"
        ),
        f"Tasks discovered: {payload.get('discovered_task_count', 0)}",
        (
            "Last heartbeat: "
            f"{format_operator_timestamp(payload.get('scheduler_last_heartbeat_at'))}"
        ),
        "Tasks:",
    ]
    for task in payload.get("task_statuses", []):
        if not isinstance(task, Mapping):
            continue
        lines.append(
            "- "
            f"{_safe_text(task.get('task_id')) or 'unknown'}: "
            f"{'enabled' if task.get('enabled') else 'disabled'}; "
            f"approval={_yes_no(_approval_required(task))}; "
            f"last={format_operator_timestamp(task.get('last_run_at'))}; "
            f"next={format_operator_timestamp(task.get('next_due_at'))}"
        )
    lines.append(
        "Visibility: execution_performed=false; "
        f"dry_run_plans={len(payload.get('dry_run_plans', []))}; "
        "external_calls=false."
    )
    if not verbose:
        lines.append("Verbose diagnostics omitted.")
    return "\n".join(lines)


def _approval_required(task: Mapping[str, Any]) -> Any:
    approval = task.get("approval_governance")
    if isinstance(approval, Mapping):
        return approval.get("requires_approval")
    return None


def _local_zone(local_tz: str | None) -> timezone | ZoneInfo:
    if not local_tz:
        return datetime.now().astimezone().tzinfo or timezone.utc
    try:
        return ZoneInfo(local_tz)
    except ZoneInfoNotFoundError:
        return timezone.utc


def _timezone_label(zone: timezone | ZoneInfo) -> str:
    key = getattr(zone, "key", None)
    if key:
        return key
    name = zone.tzname(None)
    return name or "Local"


def _display_datetime(value: datetime) -> str:
    month = value.strftime("%b")
    return f"{month} {value.day}, {value.year}, {value:%H:%M}"


def _safe_text(value: Any) -> str:
    if isinstance(value, str):
        return " ".join(value.split())[:200]
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return ""


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_safe_text(item) for item in value if _safe_text(item)]


def _bool_pair(label: str, value: Any) -> str:
    if not isinstance(value, bool):
        return ""
    return f"{label}={'true' if value else 'false'}"


def _yes_no(value: Any) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "unknown"


__all__ = [
    "format_operator_timestamp",
    "parse_operator_timestamp",
    "render_diagnostic_footer",
    "render_governance_status",
    "render_latest_news_operator_status",
    "render_scheduler_operator_report",
    "render_status",
]
