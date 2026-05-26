# runtime/self_audit.py

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def iter_events(log_path: Path):
    if not log_path.exists():
        return

    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            yield json.loads(line)
        except Exception:
            continue


def audit_runtime_events(
    *,
    log_path: Path = Path("logs/juniper_events.jsonl"),
    limit: int = 1000,
) -> list[dict]:
    events = list(iter_events(log_path) or [])[-limit:]

    event_counts = Counter(
        event.get("event_type")
        for event in events
    )

    suggestions = []

    repair_started = event_counts.get(
        "contract_repair_started",
        0,
    )

    repair_completed = event_counts.get(
        "contract_repair_completed",
        0,
    )

    semantic_failures = event_counts.get(
        "semantic_contract_failure",
        0,
    )

    validation_failures = (
        event_counts.get("contract_validation_failure", 0)
        + event_counts.get("agent_validation_failure", 0)
    )

    if repair_started and repair_completed < repair_started:
        suggestions.append({
            "type": "runtime_reliability",
            "priority": "high",
            "title": "Investigate incomplete contract repairs",
            "reason": (
                "Some contract repair attempts started but did "
                "not complete."
            ),
            "recommended_action": (
                "Inspect failed repair request IDs and check "
                "repair manager exception handling."
            ),
        })

    if semantic_failures:
        suggestions.append({
            "type": "contract_governance",
            "priority": "medium",
            "title": "Move semantic failures into contract validators",
            "reason": (
                "Semantic contract failures are still handled "
                "as runtime-level failures."
            ),
            "recommended_action": (
                "Convert anti-meta validation into contract-owned "
                "semantic validation with structured violations."
            ),
        })

    if validation_failures:
        suggestions.append({
            "type": "contract_governance",
            "priority": "medium",
            "title": "Review recurring contract violations",
            "reason": (
                "Contract validation failures indicate either "
                "model drift or under-specified contracts."
            ),
            "recommended_action": (
                "Group failures by semantic_output_type and "
                "add targeted repair instructions or schema tests."
            ),
        })

    qwen3_artifact_events = [
        event
        for event in events
        if event.get("event_type") == "execution_response"
        and "qwen3" in str(
            event.get("payload", {}).get("model", "")
        ).lower()
    ]

    if qwen3_artifact_events:
        suggestions.append({
            "type": "model_policy",
            "priority": "medium",
            "title": "Review qwen3 fallback usage",
            "reason": (
                "qwen3 appeared in recent execution responses. "
                "Prior bakeoffs showed it may be unstable for "
                "deterministic artifact work."
            ),
            "recommended_action": (
                "Restrict qwen3 to creative/deep-reasoning roles "
                "and avoid artifact repair/execution unless tested."
            ),
        })

    return suggestions


def print_audit_report():
    suggestions = audit_runtime_events()

    if not suggestions:
        print("No runtime improvement suggestions found.")
        return

    print("\n=== JUNIPER SELF-AUDIT SUGGESTIONS ===\n")

    for index, item in enumerate(suggestions, start=1):
        print(f"{index}. [{item['priority']}] {item['title']}")
        print(f"   type: {item['type']}")
        print(f"   reason: {item['reason']}")
        print(f"   action: {item['recommended_action']}")
        print()


if __name__ == "__main__":
    print_audit_report()
