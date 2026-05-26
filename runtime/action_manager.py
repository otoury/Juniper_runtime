# runtime/action_manager.py

from __future__ import annotations

from pathlib import Path

from runtime.actions.queue import enqueue_action
from runtime.actions.registry import validate_action_capability
from runtime.governance.stop_asking import (
    DEFAULT_STOP_ASKING_POLICY_STORE_PATH,
    build_governance_boundary_diagnostics,
    build_stop_asking_operator_diagnostics,
    evaluate_stop_asking_policy,
    materialize_operator_override_receipt,
)


def process_actions(
    *,
    source_bot: str,
    agent_name: str,
    user_id: str,
    request_id: str,
    actions,
    report_event,
    notify_owner,
    stop_asking_policy_store_path: str | Path = DEFAULT_STOP_ASKING_POLICY_STORE_PATH,
    enqueue_action_fn=enqueue_action,
):
    queued_actions = []

    for action in actions:
        capability, normalized_action_type = validate_action_capability(
            agent_name=agent_name,
            action_type=action.action_type,
        )

        action.action_type = normalized_action_type
        action.requires_approval = capability.requires_approval

        queued = enqueue_action_fn(
            source_bot=source_bot,
            agent=agent_name,
            user_id=user_id,
            request_id=request_id,
            action=action,
        )

        queued_actions.append(queued)

        report_event(
            source_bot,
            "agent_action_queued",
            {
                "user_id": user_id,
                "agent": agent_name,
                "action_id": queued["action_id"],
                "action_type": action.action_type,
                "confidence": action.confidence,
                "requires_approval": action.requires_approval,
                "payload": action.payload,
                "reason": action.reason,
            },
            request_id=request_id,
        )

        if action.requires_approval:
            stop_asking_decision = evaluate_stop_asking_policy(
                context={
                    "source_bot": source_bot,
                    "agent": agent_name,
                    "user_id": user_id,
                    "action_type": action.action_type,
                    "workflow_id": _payload_scope_value(
                        action.payload,
                        "workflow_id",
                    ),
                    "step_id": _payload_scope_value(
                        action.payload,
                        "step_id",
                    ),
                },
                store_path=stop_asking_policy_store_path,
            )
            override_receipt = materialize_operator_override_receipt(
                stop_asking_decision
            )
            boundary_diagnostics = build_governance_boundary_diagnostics(
                stop_asking_decision,
                override_receipt,
            )
            operator_diagnostics = build_stop_asking_operator_diagnostics(
                stop_asking_decision,
                override_receipt,
            )
            report_event(
                source_bot,
                "operator_stop_asking_governance_evaluated",
                {
                    "user_id": user_id,
                    "agent": agent_name,
                    "action_id": queued["action_id"],
                    "action_type": action.action_type,
                    "stop_asking": stop_asking_decision.to_record(),
                    "operator_override_receipt": override_receipt.to_record(),
                    "governance_boundary_diagnostics": boundary_diagnostics,
                    "operator_stop_asking_diagnostics": operator_diagnostics,
                },
                request_id=request_id,
            )
            if stop_asking_decision.asking_suppressed:
                continue

        if action.requires_approval and notify_owner:
            notify_owner(
                "Pending action from "
                f"{agent_name}\n\n"
                f"Action ID: {queued['action_id']}\n"
                f"Type: {action.action_type}\n"
                f"Reason: {action.reason}\n\n"
                "Reply to Juniper:\n"
                f"approve action {queued['action_id']}\n"
                f"deny action {queued['action_id']}",
                request_id=request_id,
            )

    return queued_actions


def _payload_scope_value(payload, key: str) -> str:
    if not isinstance(payload, dict):
        return ""
    value = payload.get(key)
    return value.strip() if isinstance(value, str) else ""


__all__ = [
    "process_actions",
]
