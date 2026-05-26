from __future__ import annotations

from copy import deepcopy
from typing import Any


BLOCKED_EXECUTION_RESPONSE = (
    "Cloud/web lookup is currently disabled by runtime governance."
)
GOVERNANCE_BLOCKED_RESPONSE_PREFIX = BLOCKED_EXECUTION_RESPONSE
GOVERNANCE_OPERATOR_ACTIONS = {
    "cloud_execution": "start cloud",
    "tavily_execution": "enable Tavily",
    "provider_authorization": "authorize provider",
}

FORBIDDEN_EXECUTION_PAYLOAD_MARKERS = (
    "[CLOUD DRY RUN]",
    "Messages that would have been sent",
    "Response format:",
    "raw model payload",
    "raw response format",
    "internal planner payload",
)


def render_blocked_execution_response(
    diagnostics: dict | None = None,
    *,
    include_operator_action: bool = False,
) -> str:
    return render_governance_blocked_execution_response(
        diagnostics,
        include_operator_action=include_operator_action,
    )


def render_governance_blocked_execution_response(
    diagnostics: dict | None = None,
    *,
    include_operator_action: bool = False,
) -> str:
    actions = _operator_actions_for_governance_block(diagnostics)
    if not include_operator_action or not actions:
        return GOVERNANCE_BLOCKED_RESPONSE_PREFIX
    return (
        f"{GOVERNANCE_BLOCKED_RESPONSE_PREFIX} "
        f"Operator action: {', '.join(actions)}."
    )


def contains_execution_payload_leak(value: Any) -> bool:
    if not isinstance(value, str):
        return False

    lowered = value.lower()
    return any(
        marker.lower() in lowered
        for marker in FORBIDDEN_EXECUTION_PAYLOAD_MARKERS
    )


def build_blocked_execution_diagnostics(
    *,
    messages,
    engine: dict,
    model: str,
    response_format=None,
    control_diagnostics: dict | None = None,
    execution_class: str | None = None,
    dry_run_effect: str | None = None,
    blocked_reason: str | None = None,
) -> dict:
    return {
        "diagnostic_type": "blocked_provider_execution",
        "visibility": "operator_internal_only",
        "contained_from_user_response": True,
        "execution_class": execution_class,
        "dry_run_effect": dry_run_effect,
        "blocked_reason": blocked_reason,
        "provider": engine.get("provider"),
        "model": model,
        "web_search": bool(engine.get("web_search", False)),
        "response_format": deepcopy(response_format),
        "messages": deepcopy(messages),
        "control": deepcopy(control_diagnostics),
        "execution_performed": False,
        "provider_request_sent": False,
        "planner_semantic_authority": False,
        "semantic_reinterpretation_performed": False,
    }


def build_governance_blocked_response_diagnostics(
    diagnostics: dict | None,
) -> dict:
    return {
        "diagnostic_type": "governance_blocked_response_rendering",
        "visibility": "operator_internal_only",
        "content_safe": True,
        "observational_only": True,
        "user_response_rendered": "governance_blocked_execution",
        "operator_actions": _operator_actions_for_governance_block(diagnostics),
        "execution_performed": False,
        "external_call_performed": False,
        "provider_request_sent": False,
        "hidden_execution_retry_performed": False,
        "hidden_context_injection_performed": False,
        "planner_semantic_authority": False,
        "semantic_reinterpretation_performed": False,
    }


def contain_execution_result(
    result: dict,
    *,
    reason: str = "blocked_provider_execution",
) -> dict:
    contained = dict(result)
    text = contained.get("text", contained.get("response", ""))
    should_contain = (
        bool(contained.get("dry_run"))
        or bool(contained.get("provider_blocked"))
        or contains_execution_payload_leak(text)
    )

    if not should_contain:
        return contained

    diagnostics = dict(contained.get("operational_diagnostics") or {})
    diagnostics.setdefault("diagnostic_type", reason)
    diagnostics["contained_from_user_response"] = True
    diagnostics["user_response_rendered"] = "blocked_execution"
    diagnostics["leak_markers_detected"] = contains_execution_payload_leak(text)
    diagnostics.setdefault("execution_performed", False)
    diagnostics.setdefault("provider_request_sent", False)

    render_diagnostics = build_governance_blocked_response_diagnostics(diagnostics)
    diagnostics.update(render_diagnostics)

    safe_text = render_blocked_execution_response(
        diagnostics,
        include_operator_action=False,
    )
    if "text" in contained:
        contained["text"] = safe_text
    if "response" in contained:
        contained["response"] = safe_text
    contained["operational_diagnostics"] = diagnostics
    return contained


def _operator_actions_for_governance_block(
    diagnostics: dict | None,
) -> list[str]:
    if not isinstance(diagnostics, dict):
        return []
    controls = _governance_controls(diagnostics)
    actions = [
        GOVERNANCE_OPERATOR_ACTIONS[control]
        for control in controls
        if control in GOVERNANCE_OPERATOR_ACTIONS
    ]
    reasons = _string_list(
        diagnostics.get("disabled_reasons")
        or diagnostics.get("skipped_reasons")
        or diagnostics.get("reason_codes")
    )
    if any("tavily" in reason for reason in reasons):
        actions.append(GOVERNANCE_OPERATOR_ACTIONS["tavily_execution"])
    if any(
        "provider_authorization" in reason
        or "authorization" in reason
        or "state_not_allowed" in reason
        for reason in reasons
    ):
        actions.append(GOVERNANCE_OPERATOR_ACTIONS["provider_authorization"])
    return list(dict.fromkeys(actions))


def _governance_controls(diagnostics: dict) -> list[str]:
    controls: list[str] = []
    control = diagnostics.get("control")
    if isinstance(control, str) and control:
        controls.append(control)

    nested_control = diagnostics.get("control_diagnostics")
    if isinstance(nested_control, dict):
        controls.extend(_governance_controls(nested_control))

    runtime_governance = diagnostics.get("runtime_governance")
    if isinstance(runtime_governance, dict):
        controls.extend(_governance_controls(runtime_governance))

    control_payload = diagnostics.get("control")
    if isinstance(control_payload, dict):
        controls.extend(_governance_controls(control_payload))

    operational_controls = diagnostics.get("operational_controls")
    if isinstance(operational_controls, list):
        for item in operational_controls:
            if isinstance(item, dict):
                controls.extend(_governance_controls(item))
    return list(dict.fromkeys(controls))


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


__all__ = [
    "BLOCKED_EXECUTION_RESPONSE",
    "FORBIDDEN_EXECUTION_PAYLOAD_MARKERS",
    "GOVERNANCE_OPERATOR_ACTIONS",
    "build_blocked_execution_diagnostics",
    "build_governance_blocked_response_diagnostics",
    "contain_execution_result",
    "contains_execution_payload_leak",
    "render_blocked_execution_response",
    "render_governance_blocked_execution_response",
]
