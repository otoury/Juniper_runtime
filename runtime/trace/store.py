import json

from pathlib import Path
from datetime import datetime, timezone


BASE = Path("traces")
BASE.mkdir(parents=True, exist_ok=True)


def trace_path(request_id: str):
    return BASE / f"{request_id}.json"


def create_trace(
    *,
    request_id: str,
    session_id: str,
    source_bot: str,
    user_id: str,
    original_text: str,
):
    data = {
        "request_id": request_id,
        "session_id": session_id,
        "source_bot": source_bot,
        "user_id": user_id,
        "created_at": datetime.now(
            timezone.utc
        ).isoformat(),

        "original_text": original_text,

        "routing": None,
        "request_gate": None,
        "context_resolution": None,
        "execution_plan": None,
        "runtime_execution": [],
        "actions": [],
        "workflow_updates": [],
        "tool_calls": [],
        "final_response": None,
        "errors": [],
        "state": "received",
        "state_history": [],
    }

    trace_path(request_id).write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return data

def append_trace_list(
    request_id: str,
    field: str,
    value,
):
    path = trace_path(request_id)

    if not path.exists():
        return

    data = json.loads(
        path.read_text(encoding="utf-8")
    )

    data.setdefault(field, [])
    data[field].append(value)

    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

def transition_trace_state(
    request_id: str,
    new_state: str,
    reason: str = "",
):
    path = trace_path(request_id)

    if not path.exists():
        return

    data = json.loads(path.read_text(encoding="utf-8"))

    old_state = data.get("state")

    data["state"] = new_state
    data.setdefault("state_history", []).append({
        "from": old_state,
        "to": new_state,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )