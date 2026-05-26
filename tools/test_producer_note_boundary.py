import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.alexis import AlexisAgent
from memory.artifacts import load_active_artifact
from memory.context_packet import build_context_packet
from memory.store import load_session_memory
from planner.request_gate import InteractionMode
from runtime.request_planner import plan_request
from runtime.request_runner import run_request
from runtime.telemetry_manager import get_session_id
from gateway.routing.juniper import DispatchDecision


USER_ID = "test_pipeline_user"
SEED_TEXT = (
    "Draft outreach email to Dr. Shikha Jain about AI in medicine."
)
TARGET_TEXT = (
    "Write a quick producer note reminding the control room "
    "that the guest is remote from London."
)


def main():
    agent = AlexisAgent()
    session_id = get_session_id()

    run_request(
        source_bot="alexis",
        agent=agent,
        user_id=USER_ID,
        text=SEED_TEXT,
    )

    seeded_artifact = load_active_artifact(
        agent_name=agent.name,
        user_id=USER_ID,
    )

    assert seeded_artifact is not None, "Expected an active artifact after seeding."
    assert seeded_artifact.get("artifact_type") == "email_draft", (
        "Expected the seed request to create an email_draft active artifact."
    )

    context_packet = build_context_packet(
        agent_name=agent.name,
        user_id=USER_ID,
    )

    recent_memory = load_session_memory(
        agent.name,
        USER_ID,
        session_id=session_id,
        limit=6,
    )

    dispatch = DispatchDecision(
        target_agent=agent.name,
        cognition="LOCAL",
        task_type="producer_note_boundary",
        tools_needed=[],
        reason="Boundary test dispatch.",
        confidence=1.0,
    )

    planning = plan_request(
        text=TARGET_TEXT,
        agent=agent,
        user_id=USER_ID,
        recent_memory=recent_memory,
        context_packet=context_packet,
        dispatch=dispatch,
    )

    gate = planning.gate

    assert gate.interaction_mode == InteractionMode.NEW_REQUEST.value, (
        f"Expected NEW_REQUEST, got {gate.interaction_mode!r}"
    )
    assert gate.uses_active_artifact is False, (
        "Expected the standalone deliverable to avoid active-artifact attachment."
    )
    assert planning.active_artifact is None, (
        "Expected no active artifact to be loaded for the producer note request."
    )
    assert planning.plan.semantic_output_type == "producer_note", (
        f"Expected producer_note output, got {planning.plan.semantic_output_type!r}"
    )
    assert planning.plan.expected_output_type == "artifact", (
        f"Expected artifact output, got {planning.plan.expected_output_type!r}"
    )

    print("PASS producer_note boundary test")


if __name__ == "__main__":
    main()
