import sys
import json
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runtime.request_runner as request_runner  # noqa: E402
from agents.alexis import AlexisAgent  # noqa: E402


KNOWN_ENTITY_NAME = "Dr. Saju Matthew"


def alexis_agent():
    return AlexisAgent(workspace_path="/tmp/juniper_stage_15a_alexis")


def install_runtime_stubs(captured):
    originals = {
        "execute_request": request_runner.execute_request,
        "report_event": request_runner.report_event,
        "report_memory_snapshot": request_runner.report_memory_snapshot,
        "load_session_memory": request_runner.load_session_memory,
        "build_context_packet": request_runner.build_context_packet,
        "persist_runtime_result": request_runner.persist_runtime_result,
        "persist_conversation_memory": request_runner.persist_conversation_memory,
        "plan_request": request_runner.plan_request,
    }

    def fake_execute_request(**kwargs):
        captured["messages"] = kwargs["messages"]
        facts = _lookup_facts_from_messages(kwargs["messages"])
        display_name = facts.get("display_name", KNOWN_ENTITY_NAME)
        title = facts.get("title")
        fact_sentence = (
            f" Your work as {title} would help ground the conversation."
            if title
            else ""
        )
        response = (
            "Subject: Iran talks segment\n\n"
            f"Hi {display_name}, we would like to invite you."
            f"{fact_sentence}"
        )
        return {
            "execution_result": {
                "engine": "stub",
                "model": "stub-model",
                "execution_tier": "test",
                "attempted": ["stub"],
                "usage": {},
                "dry_run": True,
            },
            "raw_response": response,
            "normalized_response": response,
            "pipeline_result": SimpleNamespace(parsed_payload=None),
            "retried": False,
        }

    def fake_report_event(source_bot, event_type, payload, request_id=None):
        captured.setdefault("events", []).append(
            {
                "source_bot": source_bot,
                "event_type": event_type,
                "payload": payload,
                "request_id": request_id,
            }
        )

    request_runner.execute_request = fake_execute_request
    request_runner.report_event = fake_report_event
    request_runner.report_memory_snapshot = lambda *args, **kwargs: None
    request_runner.load_session_memory = lambda *args, **kwargs: []
    request_runner.build_context_packet = lambda *args, **kwargs: {}
    request_runner.persist_runtime_result = lambda *args, **kwargs: None
    request_runner.persist_conversation_memory = lambda *args, **kwargs: None

    def capturing_plan_request(**kwargs):
        planning = originals["plan_request"](**kwargs)
        captured["planning"] = planning
        return planning

    request_runner.plan_request = capturing_plan_request

    return originals


def restore_runtime_stubs(originals):
    for name, value in originals.items():
        setattr(request_runner, name, value)


def run_with_stubs(text):
    captured = {"events": []}
    originals = install_runtime_stubs(captured)
    try:
        response = request_runner.run_request(
            source_bot="stage15",
            agent=alexis_agent(),
            user_id="stage15_user",
            text=text,
        )
    finally:
        restore_runtime_stubs(originals)

    captured["response"] = response
    return captured


def event(captured, event_type):
    matches = [
        item for item in captured["events"]
        if item["event_type"] == event_type
    ]
    assert matches, f"missing event: {event_type}"
    return matches[-1]


def injected_lookup_message(captured):
    messages = captured["messages"]
    matches = [
        message for message in messages
        if message.get("role") == "system"
        and "LOOKUP_CONTEXT_BLOCK" in message.get("content", "")
    ]
    assert len(matches) == 1
    return matches[0]


def _lookup_facts_from_messages(messages):
    for message in messages:
        content = message.get("content", "")
        if "LOOKUP_CONTEXT_BLOCK" not in content:
            continue

        payload = content.split("LOOKUP_CONTEXT_BLOCK\n", 1)[1].split(
            "\nEND_LOOKUP_CONTEXT_BLOCK",
            1,
        )[0]
        fragment = json.loads(payload)
        facts = {}
        for block in fragment.get("blocks", []):
            for fact in block.get("facts", []):
                facts[fact.get("field")] = fact.get("value")
        return facts

    return {}


def test_booking_email_lookup_context_injected_end_to_end():
    captured = run_with_stubs(
        f"Draft a booking email to {KNOWN_ENTITY_NAME} about Iran talks."
    )

    assert captured["response"].startswith("Subject: Iran talks segment")
    assert "Family Practice Physician" in captured["response"]
    assert "raw_lookup_results" not in captured["response"]
    assert "lookup_context_packets" not in captured["response"]
    assert "GUESTS_CANONICAL.csv" not in captured["response"]

    request_trace = event(captured, "lookup_request_trace")["payload"]
    assert request_trace["request_created"] is True
    assert request_trace["lookup_type"] == "exact_entity_lookup"

    execution_trace = event(captured, "lookup_execution_trace")["payload"]
    assert execution_trace["retrieval_executed"] is True
    assert execution_trace["records_returned"] == 1

    materialized = event(captured, "lookup_context_materialized")["payload"]
    assert materialized["packet_count"] == 1
    assert materialized["context_types"] == ["bounded_lookup_result"]

    render_decision = event(
        captured,
        "lookup_context_render_decision",
    )["payload"]
    assert render_decision["render_allowed"] is True

    injection_trace = event(
        captured,
        "lookup_context_injection_trace",
    )["payload"]
    assert injection_trace["injection_allowed"] is True
    assert injection_trace["injected_block_count"] == 1
    assert injection_trace["skipped_reasons"] == []

    message = injected_lookup_message(captured)
    content = message["content"]
    assert "LOOKUP_CONTEXT_BLOCK" in content
    assert '"content_type": "lookup_context_block"' in content
    assert '"label": "Display name"' in content
    assert KNOWN_ENTITY_NAME in content
    assert "Family Practice Physician" in content
    assert "raw_lookup_results" not in content
    assert "lookup_results" not in content
    assert "lookup_context_packets" not in content
    assert "raw_database_path" not in content
    assert "GUESTS_CANONICAL.csv" not in content

    summary = captured["planning"].lookup_pipeline_summary["lookup_pipeline"]
    assert summary["request_created"] is True
    assert summary["execution_status"] == "success"
    assert summary["records_returned"] == 1
    assert summary["context_materialized"] is True
    assert summary["render_allowed"] is True
    assert summary["injection_allowed"] is True
    assert summary["injected_block_count"] == 1


def test_non_lookup_workflow_does_not_inject_lookup_context():
    captured = run_with_stubs("Write a quick producer note about the rundown.")

    assert all(
        "LOOKUP_CONTEXT_BLOCK" not in message.get("content", "")
        for message in captured["messages"]
    )
    injection_trace = event(
        captured,
        "lookup_context_injection_trace",
    )["payload"]
    assert injection_trace["injection_allowed"] is False
    assert injection_trace["injected_block_count"] == 0
    assert "Family Practice Physician" not in captured["response"]
    summary = captured["planning"].lookup_pipeline_summary["lookup_pipeline"]
    assert summary["attempted"] is False
    assert summary["injection_allowed"] is False


def test_failed_lookup_does_not_inject_lookup_context():
    captured = run_with_stubs(
        "Draft a booking email to Unknown Person about Iran talks."
    )

    assert all(
        "LOOKUP_CONTEXT_BLOCK" not in message.get("content", "")
        for message in captured["messages"]
    )
    assert "Unknown Person" not in captured["response"]
    assert "Family Practice Physician" not in captured["response"]

    execution_trace = event(captured, "lookup_execution_trace")["payload"]
    assert execution_trace["retrieval_executed"] is True
    assert execution_trace["records_returned"] == 0
    assert execution_trace["skipped_reasons"] == ["no_exact_match"]

    injection_trace = event(
        captured,
        "lookup_context_injection_trace",
    )["payload"]
    assert injection_trace["injection_allowed"] is False
    assert injection_trace["injected_block_count"] == 0
    summary = captured["planning"].lookup_pipeline_summary["lookup_pipeline"]
    assert summary["execution_status"] == "failed"
    assert summary["records_returned"] == 0
    assert summary["context_materialized"] is False
    assert summary["injection_allowed"] is False


def main():
    test_booking_email_lookup_context_injected_end_to_end()
    test_non_lookup_workflow_does_not_inject_lookup_context()
    test_failed_lookup_does_not_inject_lookup_context()
    print("PASS alexis lookup context e2e")


if __name__ == "__main__":
    main()
