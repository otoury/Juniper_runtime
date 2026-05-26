# actions/parser.py

from __future__ import annotations

from runtime.actions.contracts import (
    ActionEnvelope,
    AgentOutput,
)
from core.json_utils import extract_json


def _parse_actions(data: dict) -> list[ActionEnvelope]:
    actions = []

    for item in data.get("actions", []):
        actions.append(
            ActionEnvelope(
                action_type=item["action_type"],
                requires_approval=item.get(
                    "requires_approval",
                    True,
                ),
                payload=item.get("payload", {}),
                confidence=float(
                    item.get("confidence", 1.0)
                ),
                reason=item.get("reason", ""),
            )
        )

    return actions


def parse_agent_output(text: str) -> AgentOutput:
    """
    Parse only the action-envelope output shape.

    If the model returned artifact JSON, email JSON, guest JSON,
    or any other non-envelope payload, leave the already-normalized
    response intact and return no actions.
    """

    text = (text or "").strip()

    if not text:
        return AgentOutput(
            assistant_response="",
            actions=[],
        )

    try:
        data = extract_json(text)
    except Exception:
        return AgentOutput(
            assistant_response=text,
            actions=[],
        )

    if not isinstance(data, dict):
        return AgentOutput(
            assistant_response=text,
            actions=[],
        )

    has_envelope = (
        "assistant_response" in data
        or "actions" in data
    )

    if not has_envelope:
        return AgentOutput(
            assistant_response=text,
            actions=[],
        )

    return AgentOutput(
        assistant_response=str(
            data.get("assistant_response", "")
        ).strip(),
        actions=_parse_actions(data),
    )
