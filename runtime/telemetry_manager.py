# runtime/telemetry_manager.py

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

try:
    import psutil
except ModuleNotFoundError:
    psutil = None

from runtime.trace.store import transition_trace_state


LOG_PATH = Path("logs/juniper_events.jsonl")
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

SESSION_PATH = Path("data/current_session_id.txt")
SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)


TRACE_STATE_BY_EVENT = {
    "request_received": "received",
    "request_gate_decision": "routed",
    "context_resolved": "context_resolved",
    "execution_plan_created": "planned",
    "execution_attempt_started": "executing",
    "agent_action_queued": "action_pending",
    "response_completed": "completed",
    "error": "failed",
}


def get_session_id() -> str:
    if SESSION_PATH.exists():
        return SESSION_PATH.read_text(encoding="utf-8").strip()

    session_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    SESSION_PATH.write_text(session_id, encoding="utf-8")
    return session_id


def report_event(
    source_bot: str,
    event_type: str,
    payload: dict,
    request_id: str | None = None,
):
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": get_session_id(),
        "request_id": request_id,
        "source_bot": source_bot,
        "event_type": event_type,
        "payload": payload,
    }

    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

    if request_id:
        state = TRACE_STATE_BY_EVENT.get(event_type)

        if state:
            try:
                transition_trace_state(
                    request_id,
                    state,
                    event_type,
                )
            except Exception:
                pass


def report_memory_snapshot(
    source_bot: str,
    request_id: str,
    label: str,
):
    if psutil is None:
        report_event(
            source_bot,
            "memory_snapshot",
            {
                "label": label,
                "rss_mb": None,
            },
            request_id=request_id,
        )
        return

    process = psutil.Process(os.getpid())

    report_event(
        source_bot,
        "memory_snapshot",
        {
            "label": label,
            "rss_mb": round(
                process.memory_info().rss / 1024 / 1024,
                2,
            ),
        },
        request_id=request_id,
    )


__all__ = [
    "get_session_id",
    "report_event",
    "report_memory_snapshot",
]
