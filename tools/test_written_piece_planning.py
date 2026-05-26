import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.alexis import AlexisAgent
from planner.request_gate import InteractionMode
from runtime import request_planner
from runtime.request_planner import plan_request
from gateway.routing.juniper import DispatchDecision


TEXT = "write 150 words about AI regulation"


def main():
    original_load = request_planner.load_active_artifact

    def fail_if_loaded(**kwargs):
        raise AssertionError(
            "Active artifact should not load for standalone written_piece."
        )

    request_planner.load_active_artifact = fail_if_loaded

    try:
        planning = plan_request(
            text=TEXT,
            agent=AlexisAgent(),
            user_id="test_written_piece_user",
            recent_memory=[],
            context_packet={},
            dispatch=DispatchDecision(
                target_agent="alexis",
                cognition="LOCAL",
                task_type="written_piece_planning",
                tools_needed=[],
                reason="Focused written_piece planning test.",
                confidence=1.0,
            ),
        )
    finally:
        request_planner.load_active_artifact = original_load

    gate = planning.gate
    plan = planning.plan

    assert gate.interaction_mode == InteractionMode.NEW_REQUEST.value, (
        f"Expected NEW_REQUEST, got {gate.interaction_mode!r}"
    )
    assert gate.uses_active_artifact is False, (
        "Expected standalone prose to avoid active artifact context."
    )
    assert planning.active_artifact is None, (
        "Expected no active artifact attachment."
    )
    assert plan.semantic_output_type == "written_piece", (
        f"Expected written_piece, got {plan.semantic_output_type!r}"
    )
    assert plan.semantic_output_type != "email_draft"

    print("PASS written_piece planning")


if __name__ == "__main__":
    main()
