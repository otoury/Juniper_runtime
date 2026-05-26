import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import planner.execution as execution_planner  # noqa: E402
from planner.execution import build_execution_plan  # noqa: E402
from runtime.request_planner import plan_request  # noqa: E402


def dispatch():
    return SimpleNamespace(
        target_agent="alexis",
        cognition="LOCAL",
        task_type="planned_shared_capability_test",
        tools_needed=[],
        reason="Focused planned shared capability test.",
        confidence=1.0,
    )


def plan_semantic_text(text: str):
    return plan_request(
        text=text,
        agent=SimpleNamespace(
            name="alexis",
            agent_root=ROOT / "agents" / "alexis",
        ),
        user_id="planned_shared_capability_user",
        recent_memory=[],
        context_packet={},
        dispatch=dispatch(),
    )


def test_lower_third_maps_to_create_lower_third():
    planning = plan_semantic_text(
        "Write a lower third about the AI regulation hearing today."
    )

    plan = planning.plan

    assert plan.semantic_output_type == "lower_third"
    assert plan.shared_capability == "create_lower_third"
    assert planning.shared_capability == "create_lower_third"


def test_outreach_email_draft_maps_to_draft_email():
    planning = plan_semantic_text(
        "Draft an outreach email to Dr. Lee about joining the AI segment."
    )

    plan = planning.plan

    assert plan.semantic_output_type == "email_draft"
    assert plan.shared_capability == "draft_email"


def test_producer_note_maps_to_producer_note():
    planning = plan_semantic_text(
        "Write a quick producer note reminding the control room that the guest is remote."
    )

    plan = planning.plan

    assert plan.semantic_output_type == "producer_note"
    assert plan.shared_capability == "producer_note"


def test_explicit_send_email_action_maps_to_send_email():
    plan = build_execution_plan(
        original_text="Send the active email draft.",
        resolved_text="Send the active email draft.",
        resolution=SimpleNamespace(action="CONTINUE"),
        dispatch=dispatch(),
        user_id="planned_shared_capability_user",
        shared_capability="send_email",
    )

    assert plan.expected_output_type == "action"
    assert plan.semantic_output_type is None
    assert plan.shared_capability == "send_email"


def test_ambiguous_request_leaves_capability_none():
    original_call = execution_planner._call_planner_ai

    def fake_call_planner_ai(**kwargs):
        return {
            "task_family": "general",
            "reasoning_depth": "low",
            "style_sensitivity": "low",
            "requires_current_information": False,
            "requires_web": False,
            "requires_source_fidelity": False,
            "privacy_sensitivity": "low",
            "latency_preference": "fast",
            "output_risk": "low",
            "input_type": "short_text",
            "expected_output_type": "general_answer",
            "requires_approval": False,
            "reason": "Ambiguous request with no shared capability.",
        }

    execution_planner._call_planner_ai = fake_call_planner_ai

    try:
        plan = build_execution_plan(
            original_text="What should we do next?",
            resolved_text="What should we do next?",
            resolution=SimpleNamespace(action="NONE"),
            dispatch=dispatch(),
            user_id="planned_shared_capability_user",
        )
    finally:
        execution_planner._call_planner_ai = original_call

    assert plan.semantic_output_type is None
    assert plan.shared_capability is None


def test_transform_request_leaves_capability_none():
    plan = build_execution_plan(
        original_text="Make it shorter.",
        resolved_text="Make it shorter.",
        resolution=SimpleNamespace(action="TRANSFORM"),
        dispatch=dispatch(),
        user_id="planned_shared_capability_user",
        transform_type="shorten",
        semantic_output_type="email_draft",
    )

    assert plan.transform_type == "shorten"
    assert plan.semantic_output_type == "email_draft"
    assert plan.shared_capability is None


def main():
    test_lower_third_maps_to_create_lower_third()
    test_outreach_email_draft_maps_to_draft_email()
    test_producer_note_maps_to_producer_note()
    test_explicit_send_email_action_maps_to_send_email()
    test_ambiguous_request_leaves_capability_none()
    test_transform_request_leaves_capability_none()
    print("PASS planned shared capability")


if __name__ == "__main__":
    main()
