import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.actions.parser import parse_agent_output
from gateway.context_resolver import ContextResolution
from planner.request_gate import InteractionMode, RequestGateDecision
from runtime import request_planner
from runtime.request_planner import plan_request
from runtime.validation_manager import validate_runtime_response
from gateway.routing.juniper import DispatchDecision


@dataclass
class DummyAgent:
    name: str = "alexis"
    agent_root: Path = ROOT / "agents" / "alexis"
    requires_structured_output: bool = True
    output_parser = staticmethod(parse_agent_output)

    def validate_response(
        self,
        *,
        plan,
        response,
        actions,
        parsed_payload,
    ):
        class Result:
            ok = True
            error = None

        return Result()


def _action_gate():
    return RequestGateDecision(
        is_standalone=False,
        needs_followup_resolution=True,
        needs_capability_context=True,
        needs_full_planning=True,
        requires_artifact_context=False,
        safe_for_fast_path=False,
        reason="Workflow action on active artifact.",
        operation="CONTINUE",
        interaction_mode=InteractionMode.CONTINUE_WORKFLOW.value,
        transform_intent=None,
        requires_active_artifact="optional",
        uses_active_artifact=True,
        preserves_artifact_type=False,
    )


def test_action_attachment_planning():
    original_gate = request_planner.analyze_request_gate
    original_resolve = request_planner.resolve_followup
    original_load = request_planner.load_active_artifact

    try:
        request_planner.analyze_request_gate = (
            lambda text, has_session_history=False: _action_gate()
        )
        request_planner.resolve_followup = (
            lambda text, context: ContextResolution(
                original_text=text,
                resolved_text=text,
                is_followup=True,
                action="CONTINUE",
                confidence=1.0,
                reason="Continue workflow.",
            )
        )
        request_planner.load_active_artifact = lambda **kwargs: {
            "artifact_id": "artifact-action-test",
            "request_id": "request-action-test",
            "artifact_type": "producer_note",
            "content": "Remote guest from London.",
        }

        planning = plan_request(
            text="Send it to me by email.",
            agent=DummyAgent(),
            user_id="test_user",
            recent_memory=[{"role": "user", "content": "seed"}],
            context_packet={},
            dispatch=DispatchDecision(
                target_agent="alexis",
                cognition="LOCAL",
                task_type="test",
                tools_needed=[],
                reason="test",
                confidence=1.0,
            ),
        )

    finally:
        request_planner.analyze_request_gate = original_gate
        request_planner.resolve_followup = original_resolve
        request_planner.load_active_artifact = original_load

    assert planning.active_artifact is not None
    assert planning.transform_type is None
    assert planning.semantic_output_type is None
    assert planning.plan.expected_output_type == "action"
    assert planning.plan.semantic_output_type is None
    assert planning.plan.transform_type is None
    assert "Transform this existing" not in planning.resolved_text


def test_action_validation_skips_artifact_quality():
    events = []

    plan = type(
        "Plan",
        (),
        {
            "expected_output_type": "action",
            "semantic_output_type": None,
            "transform_type": None,
        },
    )()

    gate = _action_gate()
    raw = (
        '{"assistant_response":"Email request queued.",'
        '"actions":[{"action_type":"send_email",'
        '"requires_approval":true,"payload":{"subject":"Test",'
        '"body":"Remote guest from London."},'
        '"confidence":1.0,"reason":"User requested email."}]}'
    )

    result = validate_runtime_response(
        agent=DummyAgent(),
        plan=plan,
        gate=gate,
        normalized_response=raw,
        parsed_payload=None,
        is_dry_run=False,
        source_bot="test",
        user_id="test_user",
        request_id="request",
        report_event=lambda *args, **kwargs: events.append(
            (args, kwargs)
        ),
    )

    assert result.response == "Email request queued."
    assert len(result.actions) == 1
    assert result.actions[0].action_type == "send_email"
    assert not any(
        args[1] == "artifact_quality_failure"
        for args, _kwargs in events
    )


def main():
    test_action_attachment_planning()
    test_action_validation_skips_artifact_quality()
    print("PASS action attachment semantics")


if __name__ == "__main__":
    main()
