import inspect
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runtime.request_runner as request_runner  # noqa: E402
from runtime.lookup.pipeline_telemetry import (  # noqa: E402
    emit_lookup_context_injection_trace,
    emit_lookup_pipeline_trace_events,
)


def collect_events():
    events = []

    def report_event(source_bot, event_type, payload, request_id=None):
        events.append(
            {
                "source_bot": source_bot,
                "event_type": event_type,
                "payload": payload,
                "request_id": request_id,
            }
        )

    return events, report_event


def planning():
    return SimpleNamespace(
        lookup_request_traces=[
            {
                "lookup_type": "exact_entity_lookup",
                "request_created": True,
                "payloads": [{"private": "drop"}],
            }
        ],
        lookup_execution_traces=[
            {
                "retrieval_executed": True,
                "records_returned": 1,
                "raw_database_path": "/private/source.csv",
            }
        ],
        lookup_context_packets=[
            {
                "context_type": "bounded_lookup_result",
                "fields": {
                    "display_name": "Jane Doe",
                },
                "provenance": {
                    "lookup_id": "lookup-001",
                },
            }
        ],
        lookup_context_render_decision={
            "render_allowed": True,
            "render_mode": "structured_fact_block",
            "packet_ids": ["lookup-001"],
            "blocks": [{"private": "drop"}],
        },
    )


def test_lookup_pipeline_telemetry_event_names_preserved():
    events, report_event = collect_events()

    emit_lookup_pipeline_trace_events(
        report_event=report_event,
        source_bot="stage15",
        request_id="req-1",
        user_id="user-1",
        agent_name="agent-1",
        planning=planning(),
    )
    emit_lookup_context_injection_trace(
        report_event=report_event,
        source_bot="stage15",
        request_id="req-1",
        user_id="user-1",
        agent_name="agent-1",
        trace={
            "injection_attempted": True,
            "injection_allowed": True,
            "injected_block_count": 1,
            "skipped_reasons": [],
            "rendered_lookup_context": {"private": "drop"},
        },
    )

    assert [event["event_type"] for event in events] == [
        "lookup_request_trace",
        "lookup_execution_trace",
        "lookup_context_materialized",
        "lookup_context_render_decision",
        "lookup_context_injection_trace",
    ]


def test_lookup_pipeline_telemetry_payloads_are_content_safe():
    events, report_event = collect_events()

    emit_lookup_pipeline_trace_events(
        report_event=report_event,
        source_bot="stage15",
        request_id="req-1",
        user_id="user-1",
        agent_name="agent-1",
        planning=planning(),
    )
    emit_lookup_context_injection_trace(
        report_event=report_event,
        source_bot="stage15",
        request_id="req-1",
        user_id="user-1",
        agent_name="agent-1",
        trace={
            "injection_attempted": True,
            "injection_allowed": True,
            "injected_block_count": 1,
            "skipped_reasons": [],
            "raw_lookup_results": [{"private": "drop"}],
        },
    )

    serialized = repr(events)
    assert "Jane Doe" not in serialized
    assert "/private/source.csv" not in serialized
    assert "raw_database_path" not in serialized
    assert "payloads" not in serialized
    assert "fields" not in serialized
    assert "blocks" not in serialized
    assert "raw_lookup_results" not in serialized


def test_request_runner_delegates_lookup_trace_payloads():
    source = inspect.getsource(request_runner)

    assert "emit_lookup_pipeline_trace_events(" in source
    assert "emit_lookup_context_injection_trace(" in source
    assert "def _emit_lookup_pipeline_trace_events" not in source
    assert "lookup_context_materialized" not in source
    assert '"lookup_context_render_decision"' not in source


def test_request_runner_uses_planned_lookup_capability_for_injection_policy():
    source = inspect.getsource(request_runner)

    assert "resolve_agent_binding" not in source
    assert "BindingResolutionError" not in source
    assert 'policy_section("lookup_context_injection_policy")' in source
    assert 'raw_binding_data.get("lookup_context_injection_policy")' not in source


def main():
    test_lookup_pipeline_telemetry_event_names_preserved()
    test_lookup_pipeline_telemetry_payloads_are_content_safe()
    test_request_runner_delegates_lookup_trace_payloads()
    test_request_runner_uses_planned_lookup_capability_for_injection_policy()
    print("PASS lookup pipeline telemetry")


if __name__ == "__main__":
    main()
