from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def build_schedule_cadence_diagnostics(declaration: Any) -> dict[str, Any]:
    schedule_type = _text(getattr(declaration, "schedule_type", ""))
    schedule = getattr(declaration, "schedule", {})
    cadence_seconds = None
    cadence = "unknown"
    if schedule_type == "interval" and isinstance(schedule, dict):
        cadence_seconds = _interval_seconds(schedule.get("every_ms"))
        cadence = (
            f"every_{cadence_seconds}_seconds"
            if cadence_seconds is not None
            else "malformed_interval"
        )
    elif schedule_type == "cron":
        cadence = "cron"
    return {
        "schedule_type": schedule_type,
        "cadence": cadence,
        "cadence_seconds": cadence_seconds,
    }


def build_run_staleness_diagnostics(
    *,
    last_run_at: Any,
    now: datetime,
    cadence_seconds: Any,
) -> dict[str, Any]:
    last_run = _parse_timestamp(last_run_at)
    safe_cadence = (
        cadence_seconds
        if isinstance(cadence_seconds, int)
        and not isinstance(cadence_seconds, bool)
        and cadence_seconds > 0
        else None
    )
    age_seconds = None
    if last_run is not None:
        age_seconds = max(0, int((_normalize_timestamp(now) - last_run).total_seconds()))
    return {
        "last_run_age_seconds": age_seconds,
        "stale_after_seconds": safe_cadence,
        "is_stale": (
            bool(age_seconds is not None and age_seconds > safe_cadence)
            if safe_cadence is not None
            else False
        ),
    }


def _interval_seconds(value: Any) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return None
    return value // 1000


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        return _normalize_timestamp(datetime.fromisoformat(normalized))
    except ValueError:
        return None


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


__all__ = [
    "build_run_staleness_diagnostics",
    "build_schedule_cadence_diagnostics",
]
