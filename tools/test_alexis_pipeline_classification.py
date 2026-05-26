import importlib.util
import inspect
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.alexis import AlexisAgent
from agents.alexis.semantics import classify_guest_semantic_intent
from gateway.context_resolver import ContextResolution
from gateway.routing.juniper import DispatchDecision
from planner import execution as planner_execution
from planner import request_gate
from planner.direct_response import (
    CLOSED_DIRECT_RESPONSE_TYPES,
    DIRECT_RESPONSE_TAXONOMY,
    classify_deterministic_direct_response,
)
from runtime import request_runner
from runtime.request_planner import build_planning_result_without_lookup_execution
from tools.test_alexis_pipeline import check_test


def _event(event_type, payload):
    return {"event_type": event_type, "payload": payload}


def test_pre_gate_error_classifies_environment_unavailable():
    req_events = [
        _event("request_received", {"text": "make it punchier"}),
        _event("error", {"error": "ConnectError('[Errno -3] Temporary failure in name resolution')"}),
    ]
    outcome = check_test(
        "pre-gate infra failure",
        req_events,
        {"error": False, "requires_artifact_context": True},
        0.01,
    )
    assert outcome == "environment_unavailable", outcome


def test_post_gate_mismatch_stays_semantic_failure():
    req_events = [
        _event("request_received", {"text": "make it punchier"}),
        _event(
            "request_gate_decision",
            {"requires_artifact_context": False, "interaction_mode": "NEW_REQUEST"},
        ),
        _event("context_resolved", {"transform_type": None}),
    ]
    outcome = check_test(
        "post-gate mismatch",
        req_events,
        {"requires_artifact_context": True},
        0.01,
    )
    assert outcome == "semantic_failure", outcome


def _run_direct_response_case(text: str):
    events = []
    snapshots = []

    def capture_event(source_bot, event_type, payload, request_id=None):
        events.append(
            {
                "source_bot": source_bot,
                "event_type": event_type,
                "payload": payload,
                "request_id": request_id,
            }
        )

    def capture_snapshot(source_bot, request_id, label):
        snapshots.append((source_bot, request_id, label))

    def fail_if_called(*args, **kwargs):
        raise AssertionError("timeout-prone execution path was called")

    originals = {
        "create_trace": request_runner.create_trace,
        "report_event": request_runner.report_event,
        "report_memory_snapshot": request_runner.report_memory_snapshot,
        "load_session_memory": request_runner.load_session_memory,
        "build_context_packet": request_runner.build_context_packet,
        "execute_request": request_runner.execute_request,
        "maybe_apply_micro_context_injection": (
            request_runner.maybe_apply_micro_context_injection
        ),
        "maybe_inject_lookup_context": request_runner.maybe_inject_lookup_context,
        "emit_lookup_context_injection_trace": (
            request_runner.emit_lookup_context_injection_trace
        ),
        "emit_lookup_pipeline_trace_events": (
            request_runner.emit_lookup_pipeline_trace_events
        ),
        "persist_runtime_result": request_runner.persist_runtime_result,
        "persist_conversation_memory": request_runner.persist_conversation_memory,
        "save_active_artifact": request_runner.save_active_artifact,
    }

    try:
        request_runner.create_trace = lambda **kwargs: {}
        request_runner.report_event = capture_event
        request_runner.report_memory_snapshot = capture_snapshot
        request_runner.load_session_memory = lambda *args, **kwargs: []
        request_runner.build_context_packet = lambda *args, **kwargs: {}
        request_runner.execute_request = fail_if_called
        request_runner.maybe_apply_micro_context_injection = fail_if_called
        request_runner.maybe_inject_lookup_context = fail_if_called
        request_runner.emit_lookup_context_injection_trace = fail_if_called
        request_runner.emit_lookup_pipeline_trace_events = fail_if_called
        request_runner.persist_runtime_result = lambda *args, **kwargs: None
        request_runner.persist_conversation_memory = lambda *args, **kwargs: None
        request_runner.save_active_artifact = lambda *args, **kwargs: None

        with tempfile.TemporaryDirectory() as tmpdir:
            response = request_runner.run_request(
                source_bot="alexis",
                agent=AlexisAgent(workspace_path=tmpdir),
                user_id="classification_greeting_user",
                text=text,
            )
    finally:
        for name, value in originals.items():
            setattr(request_runner, name, value)

    return response, events


def test_simple_greeting_uses_direct_fast_path_only():
    response, events = _run_direct_response_case("Hi")
    event_types = [event["event_type"] for event in events]
    gate_event = next(
        event for event in events
        if event["event_type"] == "request_gate_decision"
    )
    plan_event = next(
        event for event in events
        if event["event_type"] == "execution_plan_created"
    )
    response_event = next(
        event for event in events
        if event["event_type"] == "execution_response"
    )

    assert response == "Hi, I'm Alexis. How can I help?"
    assert gate_event["payload"]["interaction_mode"] == "ANSWER_QUESTION"
    assert gate_event["payload"]["operation"] == "ANSWER"
    assert gate_event["payload"]["safe_for_fast_path"] is True
    assert gate_event["payload"]["deterministic_direct_response"] is True
    assert gate_event["payload"]["direct_response_type"] == "greeting"
    assert plan_event["payload"]["semantic_output_type"] is None
    assert plan_event["payload"]["shared_capability"] is None
    assert plan_event["payload"]["execution_target"] == "fast_path_direct_response"
    assert plan_event["payload"]["direct_response_type"] == "greeting"
    assert response_event["payload"]["attempted"] == []
    assert response_event["payload"]["execution_tier"] == "runtime_direct"

    forbidden_events = {
        "lookup_context_injection_trace",
        "bounded_context_injection",
        "agent_local_workflow_completed",
        "raw_model_response",
        "artifact_normalized",
        "action_queued",
        "delivery_action_materialized",
        "external_discovery_materialized",
    }
    assert not (set(event_types) & forbidden_events)
    assert "booking" not in repr(events).lower()
    assert "email_draft" not in repr(events)
    assert "external_discovery" not in repr(events)
    assert "delivery" not in repr(events).lower()
    assert "local_reasoner_fallback" not in repr(events)


def test_direct_response_classifier_covers_low_content_acts_only():
    greeting = classify_deterministic_direct_response("hello")
    thanks = classify_deterministic_direct_response("thanks")
    ok = classify_deterministic_direct_response("ok")
    capability = classify_deterministic_direct_response("What can you do?")

    assert greeting is not None
    assert greeting.response_type == "greeting"
    assert thanks is not None
    assert thanks.response_type == "acknowledgement"
    assert ok is not None
    assert ok.response_type == "acknowledgement"
    assert capability is not None
    assert capability.response_type == "capability_summary"
    assert capability.deterministic_direct_response is True
    assert capability.needs_model is False
    assert capability.needs_lookup_context is False
    assert capability.needs_workflow is False
    assert classify_deterministic_direct_response(
        "What is happening with tariffs?"
    ) is None
    assert classify_deterministic_direct_response(
        "Hi, find me guests on tariffs"
    ) is None
    assert classify_deterministic_direct_response(
        "Find me guests on tariffs"
    ) is None


def test_direct_response_taxonomy_is_closed_and_gate_owns_no_phrases():
    assert CLOSED_DIRECT_RESPONSE_TYPES == {
        "greeting",
        "acknowledgement",
        "farewell",
        "capability_summary",
    }
    assert set(DIRECT_RESPONSE_TAXONOMY) == CLOSED_DIRECT_RESPONSE_TYPES

    gate_source = inspect.getsource(request_gate)
    for phrase in (
        "cool",
        "good night",
        "what can you do",
        "sounds good",
    ):
        assert phrase not in gate_source.lower()


def test_low_content_acknowledgements_use_direct_classifier_only():
    for text in (
        "Cool.",
        "Nice.",
        "Great.",
        "Awesome.",
        "Got it.",
        "Sounds good.",
        "OK",
        "okay",
    ):
        decision = classify_deterministic_direct_response(text)

        assert decision is not None
        assert decision.response_type == "acknowledgement"


def test_low_content_farewells_use_direct_classifier_only():
    for text in (
        "Good night",
        "goodnight",
        "Bye",
        "goodbye",
        "see you",
        "talk later",
    ):
        decision = classify_deterministic_direct_response(text)

        assert decision is not None
        assert decision.response_type == "farewell"
        assert decision.needs_model is False
        assert decision.needs_lookup_context is False
        assert decision.needs_workflow is False


def test_hello_uses_direct_greeting_fast_path():
    response, events = _run_direct_response_case("hello")
    gate_event = next(
        event for event in events
        if event["event_type"] == "request_gate_decision"
    )

    assert response == "Hi, I'm Alexis. How can I help?"
    assert gate_event["payload"]["deterministic_direct_response"] is True
    assert gate_event["payload"]["direct_response_type"] == "greeting"


def test_acknowledgements_use_direct_fast_path():
    for text in ("thanks", "ok", "Cool.", "Got it.", "Sounds good."):
        response, events = _run_direct_response_case(text)
        event_types = [event["event_type"] for event in events]
        gate_event = next(
            event for event in events
            if event["event_type"] == "request_gate_decision"
        )
        response_event = next(
            event for event in events
            if event["event_type"] == "execution_response"
        )

        assert response == "Got it."
        assert gate_event["payload"]["deterministic_direct_response"] is True
        assert gate_event["payload"]["direct_response_type"] == "acknowledgement"
        assert response_event["payload"]["attempted"] == []
        assert "lookup_context_injection_trace" not in event_types
        assert "raw_model_response" not in event_types
        assert "local_reasoner_fallback" not in repr(events)


def test_farewells_use_direct_fast_path():
    for text in ("Good night", "Bye"):
        response, events = _run_direct_response_case(text)
        event_types = [event["event_type"] for event in events]
        gate_event = next(
            event for event in events
            if event["event_type"] == "request_gate_decision"
        )
        plan_event = next(
            event for event in events
            if event["event_type"] == "execution_plan_created"
        )
        response_event = next(
            event for event in events
            if event["event_type"] == "execution_response"
        )

        assert response == "Goodbye."
        assert gate_event["payload"]["deterministic_direct_response"] is True
        assert gate_event["payload"]["direct_response_type"] == "farewell"
        assert plan_event["payload"]["execution_target"] == (
            "fast_path_direct_response"
        )
        assert response_event["payload"]["attempted"] == []
        assert "lookup_context_injection_trace" not in event_types
        assert "raw_model_response" not in event_types
        assert "local_reasoner_fallback" not in repr(events)


def test_normal_answer_question_is_not_direct_response_fast_path():
    original_call = planner_execution._call_planner_ai

    try:
        planner_execution._call_planner_ai = lambda **kwargs: {
            "task_family": "general",
            "reasoning_depth": "medium",
            "style_sensitivity": "medium",
            "requires_current_information": False,
            "requires_web": False,
            "requires_source_fidelity": False,
            "privacy_sensitivity": "low",
            "latency_preference": "balanced",
            "output_risk": "low",
            "input_type": "query",
            "expected_output_type": "general_answer",
            "requires_approval": False,
            "reason": "Normal answer question requires model reasoning.",
        }
        plan = planner_execution.build_execution_plan(
            original_text="What is happening with tariffs?",
            resolved_text="What is happening with tariffs?",
            resolution=ContextResolution(
                original_text="What is happening with tariffs?",
                resolved_text="What is happening with tariffs?",
                is_followup=False,
                action="NONE",
                confidence=1.0,
                reason="Normal question.",
            ),
            dispatch=DispatchDecision(
                target_agent="alexis",
                cognition="LOCAL",
                task_type="direct_bot_message",
                tools_needed=[],
                reason="test",
                confidence=1.0,
            ),
            user_id="classification_greeting_user",
            direct_response_type=None,
        )
    finally:
        planner_execution._call_planner_ai = original_call

    assert plan.expected_output_type == "general_answer"
    assert plan.execution_target != "fast_path_direct_response"
    assert plan.direct_response_type is None


def test_capability_question_uses_direct_capability_summary_path():
    response, events = _run_direct_response_case("What can you do?")
    event_types = [event["event_type"] for event in events]
    gate_event = next(
        event for event in events
        if event["event_type"] == "request_gate_decision"
    )
    plan_event = next(
        event for event in events
        if event["event_type"] == "execution_plan_created"
    )
    response_event = next(
        event for event in events
        if event["event_type"] == "execution_response"
    )

    decision = classify_deterministic_direct_response("What can you do?")

    assert decision is not None
    assert decision.response_type == "capability_summary"
    assert decision.needs_model is False
    assert decision.needs_lookup_context is False
    assert decision.needs_workflow is False
    assert gate_event["payload"]["deterministic_direct_response"] is True
    assert gate_event["payload"]["direct_response_type"] == "capability_summary"
    assert gate_event["payload"]["needs_capability_context"] is False
    assert plan_event["payload"]["direct_response_type"] == "capability_summary"
    assert plan_event["payload"]["reasoning_depth"] == "low"
    assert plan_event["payload"]["latency_preference"] == "fast"
    assert plan_event["payload"]["requires_web"] is False
    assert plan_event["payload"]["shared_capability"] is None
    assert plan_event["payload"]["execution_target"] == "fast_path_direct_response"
    assert response_event["payload"]["engine"] == "fast_path_direct_response"
    assert response_event["payload"]["attempted"] == []
    assert "guest" in response.lower()
    assert "outreach" in response.lower()
    assert "lookup_context_injection_trace" not in event_types
    assert "raw_model_response" not in event_types
    assert "local_reasoner_fallback" not in repr(events)


def test_deeper_question_can_still_use_stronger_reasoner_when_needed():
    original_call = planner_execution._call_planner_ai

    try:
        planner_execution._call_planner_ai = lambda **kwargs: {
            "task_family": "analysis",
            "reasoning_depth": "deep",
            "style_sensitivity": "medium",
            "requires_current_information": False,
            "requires_web": False,
            "requires_source_fidelity": False,
            "privacy_sensitivity": "low",
            "latency_preference": "balanced",
            "output_risk": "medium",
            "input_type": "query",
            "expected_output_type": "general_answer",
            "requires_approval": False,
            "reason": "Complex analysis requires stronger reasoning.",
        }
        plan = planner_execution.build_execution_plan(
            original_text="Compare the strategic tradeoffs in tariff policy.",
            resolved_text="Compare the strategic tradeoffs in tariff policy.",
            resolution=ContextResolution(
                original_text="Compare the strategic tradeoffs in tariff policy.",
                resolved_text="Compare the strategic tradeoffs in tariff policy.",
                is_followup=False,
                action="NONE",
                confidence=1.0,
                reason="Deep question.",
            ),
            dispatch=DispatchDecision(
                target_agent="alexis",
                cognition="LOCAL",
                task_type="direct_bot_message",
                tools_needed=[],
                reason="test",
                confidence=1.0,
            ),
            user_id="classification_greeting_user",
        )
    finally:
        planner_execution._call_planner_ai = original_call

    assert plan.reasoning_depth == "deep"
    assert plan.execution_target in {
        "local_reasoner_fallback",
        "cloud_deep",
        "cloud_web_deep",
    }


def test_guest_discovery_semantics_are_distinct_from_outreach_drafting():
    discovery = classify_guest_semantic_intent("Find me guests on tariffs")
    mixed = classify_guest_semantic_intent("Hi, find me guests on tariffs")
    draft = classify_guest_semantic_intent("Draft outreach to these guests")
    contact = classify_guest_semantic_intent("Contact these guests")
    mixed_outreach = classify_guest_semantic_intent("Great, draft outreach to them")

    assert discovery is not None
    assert discovery.semantic_operation == "guest_discovery"
    assert discovery.semantic_output_type == "guest_candidate_list"
    assert discovery.shared_capability == "discover_entities"
    assert mixed is not None
    assert mixed.semantic_operation == "guest_discovery"
    assert draft is not None
    assert draft.semantic_operation == "outreach_drafting"
    assert draft.semantic_output_type == "email_draft"
    assert contact is not None
    assert contact.semantic_operation == "outreach_drafting"
    assert contact.semantic_output_type == "email_draft"
    assert mixed_outreach is not None
    assert mixed_outreach.semantic_operation == "outreach_drafting"
    assert mixed_outreach.semantic_output_type == "email_draft"


def test_mixed_intents_are_not_swallowed_as_acknowledgements():
    assert classify_deterministic_direct_response(
        "Cool, find me guests on tariffs"
    ) is None
    assert classify_deterministic_direct_response(
        "Great, draft outreach to them"
    ) is None
    assert classify_deterministic_direct_response("OK, send it") is None
    assert classify_deterministic_direct_response(
        "Nice, who else can we book?"
    ) is None

    discovery = classify_guest_semantic_intent(
        "Cool, find me guests on tariffs"
    )
    outreach = classify_guest_semantic_intent(
        "Great, draft outreach to them"
    )

    assert discovery is not None
    assert discovery.semantic_operation == "guest_discovery"
    assert outreach is not None
    assert outreach.semantic_operation == "outreach_drafting"


def test_mixed_farewell_task_requests_are_not_swallowed():
    assert classify_deterministic_direct_response(
        "Good night, find me guests on tariffs"
    ) is None
    assert classify_deterministic_direct_response(
        "Bye, draft outreach to them"
    ) is None

    discovery = classify_guest_semantic_intent(
        "Good night, find me guests on tariffs"
    )
    outreach = classify_guest_semantic_intent(
        "Bye, draft outreach to them"
    )

    assert discovery is not None
    assert discovery.semantic_operation == "guest_discovery"
    assert outreach is not None
    assert outreach.semantic_operation == "outreach_drafting"


def test_guest_semantics_are_owned_by_alexis_not_planner():
    assert importlib.util.find_spec("planner.guest_semantics") is None
    assert importlib.util.find_spec("agents.alexis.semantics") is not None

    with tempfile.TemporaryDirectory() as tmpdir:
        agent = AlexisAgent(workspace_path=tmpdir)
        intent = agent.classify_semantic_intent("Find me guests on tariffs")

    assert intent is not None
    assert intent.semantic_operation == "guest_discovery"
    assert intent.semantic_output_type == "guest_candidate_list"
    assert intent.shared_capability == "discover_entities"


def _planning_for_text(text: str):
    with tempfile.TemporaryDirectory() as tmpdir:
        return build_planning_result_without_lookup_execution(
            text=text,
            agent=AlexisAgent(workspace_path=tmpdir),
            user_id="classification_greeting_user",
            recent_memory=[],
            context_packet={},
            dispatch=DispatchDecision(
                target_agent="alexis",
                cognition="LOCAL",
                task_type="direct_bot_message",
                tools_needed=[],
                reason="test",
                confidence=1.0,
            ),
        )


def test_booking_contact_discovery_requires_current_web_source_fidelity():
    text = "find the best booking contacts for Congressman Massie of Indiana?"
    intent = classify_guest_semantic_intent(text)

    assert intent is not None
    assert intent.semantic_operation == "booking_contact_discovery"
    assert intent.semantic_output_type == "sourced_contact_result"
    assert intent.shared_capability == "discover_entities"
    assert intent.planning_metadata["requires_current_information"] is True
    assert intent.planning_metadata["requires_web"] is True
    assert intent.planning_metadata["requires_source_fidelity"] is True
    assert intent.planning_metadata["minimum_engine_tier"] == "cloud_web_deep"

    planning = _planning_for_text(text)
    plan = planning.plan

    assert plan.semantic_output_type == "sourced_contact_result"
    assert plan.expected_output_type == "artifact"
    assert plan.requires_current_information is True
    assert plan.requires_web is True
    assert plan.requires_source_fidelity is True
    assert plan.reasoning_depth == "deep"
    assert plan.execution_target == "cloud_web_deep"
    assert plan.execution_target != "cloud_fast"
    assert "cloud_fast" not in plan.fallback_engines
    assert plan.requires_approval is False


def test_normal_guest_discovery_is_not_forced_to_deep_web():
    planning = _planning_for_text("Find me guests on tariffs")
    plan = planning.plan

    assert plan.semantic_output_type == "guest_candidate_list"
    assert plan.requires_current_information is False
    assert plan.requires_web is False
    assert plan.requires_source_fidelity is False
    assert plan.execution_target != "cloud_web_deep"


def test_find_guests_materializes_candidate_flow_only():
    response, events = _run_direct_response_case("Find me guests on tariffs")
    event_types = [event["event_type"] for event in events]
    gate_event = next(
        event for event in events
        if event["event_type"] == "request_gate_decision"
    )
    plan_event = next(
        event for event in events
        if event["event_type"] == "execution_plan_created"
    )
    materialized_event = next(
        event for event in events
        if event["event_type"] == "direct_artifact_materialized"
    )
    telemetry = materialized_event["payload"]["events"]["guest_workflow_telemetry"]

    assert gate_event["payload"]["interaction_mode"] == "NEW_REQUEST"
    assert plan_event["payload"]["semantic_output_type"] == "guest_candidate_list"
    assert plan_event["payload"]["shared_capability"] == "discover_entities"
    assert materialized_event["payload"]["artifact_type"] == (
        "ranked_guest_candidate_list"
    )
    assert materialized_event["payload"]["ranking_executed"] is True
    assert materialized_event["payload"]["draft_generated"] is False
    assert materialized_event["payload"]["delivery_performed"] is False
    assert "guest_db_adequacy" in materialized_event["payload"]["events"]
    assert "guest_external_discovery_handoff" in materialized_event["payload"]["events"]
    assert "contact_retrieval_diagnostics" in materialized_event["payload"]["events"]
    assert telemetry["observational_only"] is True
    assert telemetry["live_external_discovery_executed"] is False
    assert telemetry["external_call_performed"] is False
    assert telemetry["provider_adapter_called"] is False
    assert telemetry["db_write_performed"] is False
    assert telemetry["memory_write_performed"] is False
    assert telemetry["guest_db_adequacy"]["artifact_type"] == "guest_db_adequacy"
    assert telemetry["guest_external_discovery_handoff"]["artifact_type"] == (
        "guest_external_discovery_handoff"
    )
    assert telemetry["contact_safety_governance"]["live_contact_search_enabled"] is False
    assert telemetry["merge_receipt"]["merge_receipt_count"] >= 0
    assert "Guest candidates:" in response or "no matching guest candidates" in response
    assert "email_draft" not in repr(events)
    assert "Subject:" not in response
    assert "booking guests" not in response.lower()
    assert "raw_model_response" not in event_types
    assert "execution_attempt_started" not in event_types
    assert "lookup_context_injection_trace" not in event_types
    assert "delivery" not in response.lower()


def main():
    test_pre_gate_error_classifies_environment_unavailable()
    test_post_gate_mismatch_stays_semantic_failure()
    test_simple_greeting_uses_direct_fast_path_only()
    test_direct_response_classifier_covers_low_content_acts_only()
    test_direct_response_taxonomy_is_closed_and_gate_owns_no_phrases()
    test_low_content_acknowledgements_use_direct_classifier_only()
    test_low_content_farewells_use_direct_classifier_only()
    test_hello_uses_direct_greeting_fast_path()
    test_acknowledgements_use_direct_fast_path()
    test_farewells_use_direct_fast_path()
    test_normal_answer_question_is_not_direct_response_fast_path()
    test_capability_question_uses_direct_capability_summary_path()
    test_deeper_question_can_still_use_stronger_reasoner_when_needed()
    test_guest_discovery_semantics_are_distinct_from_outreach_drafting()
    test_mixed_intents_are_not_swallowed_as_acknowledgements()
    test_mixed_farewell_task_requests_are_not_swallowed()
    test_guest_semantics_are_owned_by_alexis_not_planner()
    test_booking_contact_discovery_requires_current_web_source_fidelity()
    test_normal_guest_discovery_is_not_forced_to_deep_web()
    test_find_guests_materializes_candidate_flow_only()
    print("PASS alexis pipeline classification")


if __name__ == "__main__":
    main()
