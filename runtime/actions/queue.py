import json
import uuid
from pathlib import Path
from datetime import datetime, timezone

from core.atomic_write import atomic_write_text

QUEUE_PATH = Path("data/pending_actions.jsonl")
QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)


def enqueue_action(
    *,
    source_bot: str,
    agent: str,
    user_id: str,
    request_id: str,
    action,
    workflow_id: str | None = None,
):
    action_id = str(uuid.uuid4())[:8]

    record = {
        "action_id": action_id,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_bot": source_bot,
        "agent": agent,
        "user_id": user_id,
        "request_id": request_id,
        "action_type": action.action_type,
        "requires_approval": action.requires_approval,
        "confidence": action.confidence,
        "reason": action.reason,
        "payload": action.payload,
        "workflow_id": workflow_id,
    }

    with QUEUE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return record


def load_actions(status: str | None = None):
    if not QUEUE_PATH.exists():
        return []

    actions = []

    for line in QUEUE_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        try:
            item = json.loads(line)
        except Exception:
            continue

        if status and item.get("status") != status:
            continue

        actions.append(item)

    return actions


def get_action(action_id: str):
    for action in load_actions():
        if action.get("action_id") == action_id:
            return action

    return None


def update_action_status(action_id: str, status: str):
    actions = load_actions()
    changed = None

    for action in actions:
        if action.get("action_id") == action_id:
            action["status"] = status
            action["updated_at"] = datetime.now(timezone.utc).isoformat()
            changed = action
            break

    if not changed:
        return None

    atomic_write_text(
        QUEUE_PATH,
        "\n".join(json.dumps(a, ensure_ascii=False) for a in actions) + "\n",
        encoding="utf-8",
    )

    return changed
