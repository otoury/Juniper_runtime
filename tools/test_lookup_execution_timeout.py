import sys
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from threading import Event, Lock


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.lookup.context_injection import maybe_inject_lookup_context  # noqa: E402
from runtime.lookup.context_materializer import (  # noqa: E402
    materialize_lookup_context_packets,
)
from runtime.lookup.context_render_gate import (  # noqa: E402
    evaluate_lookup_context_render_gate,
)
from runtime.lookup.context_renderer import render_lookup_context_blocks  # noqa: E402
from runtime.lookup.execution import (  # noqa: E402
    LookupExecutionCancelled,
    execute_lookup_requests,
    lookup_execution_result_to_metadata,
)
from runtime.lookup.execution_policy import LookupExecutionPolicy  # noqa: E402
from runtime.lookup.pipeline_summary import build_lookup_pipeline_summary  # noqa: E402
from runtime.registries.lookup_capability_registry import (  # noqa: E402
    resolve_lookup_capability,
)


def request(name="Example Entity", lookup_id="timeout-test"):
    return {
        "lookup_type": "exact_entity_lookup",
        "lookup_id": lookup_id,
        "entity_name": name,
        "entity_type": "guest",
        "workflow_topic": "bounded timeout",
        "source_scope": "alexis_guest_canonical_csv",
    }


def fast_result():
    return SimpleNamespace(
        ok=True,
        payload={
            "display_name": "Example Entity",
            "title": "Example title",
        },
        retrieval_executed=True,
        skipped_reasons=(),
    )


def agent_for(executor):
    return SimpleNamespace(get_lookup_executor=lambda *_args: executor)


def resolved_capability(timeout_ms=3000, max_concurrent_lookups=1):
    resolved = resolve_lookup_capability(
        agent="alexis",
        shared_capability="draft_email",
        root=ROOT,
    )
    return replace(
        resolved,
        execution_policy=LookupExecutionPolicy(
            timeout_ms=timeout_ms,
            cancellation_behavior="fail_closed",
            max_concurrent_lookups=max_concurrent_lookups,
        ),
    )


def materialization_policy():
    return {
        "enabled": True,
        "context_type": "bounded_lookup_result",
        "allowed_fields": ["display_name", "title"],
        "max_fields": 2,
    }


def render_policy():
    return {
        "allowed": True,
        "render_modes": ["structured_fact_block"],
        "max_packets": 2,
        "require_successful_retrieval": True,
        "allowed_context_types": ["bounded_lookup_result"],
        "allowed_lookup_types": ["exact_entity_lookup"],
        "allowed_source_scopes": ["alexis_guest_canonical_csv"],
        "allowed_entity_types": ["guest"],
        "field_order": ["display_name", "title"],
        "field_labels": {
            "display_name": "Display name",
            "title": "Title",
        },
    }


def injection_policy():
    return {
        "allowed": True,
        "require_render_decision": True,
        "require_rendered_context": True,
        "allowed_content_types": ["lookup_context_block"],
        "allowed_render_modes": ["structured_fact_block"],
        "max_blocks": 2,
        "max_facts_per_block": 2,
        "max_total_characters": 800,
        "truncation_mode": "drop_tail",
    }


def run_context_path(results):
    lookup_results = [
        lookup_execution_result_to_metadata(result)
        for result in results
    ]
    packets = materialize_lookup_context_packets(
        lookup_results=lookup_results,
        materialization_policy=materialization_policy(),
    )
    decision = evaluate_lookup_context_render_gate(
        lookup_context_packets=packets,
        render_policy=render_policy(),
    )
    rendered = render_lookup_context_blocks(
        lookup_context_packets=packets,
        render_decision=decision,
        render_policy=render_policy(),
    )
    injection = maybe_inject_lookup_context(
        [{"role": "user", "content": "Draft"}],
        rendered_lookup_context=rendered,
        render_decision=decision,
        injection_policy=injection_policy(),
    )
    planning = SimpleNamespace(
        lookup_requests=[result.request for result in results],
        lookup_request_traces=[],
        lookup_execution_traces=[result.trace for result in results],
        lookup_context_packets=packets,
        lookup_context_render_decision=decision,
    )
    summary = build_lookup_pipeline_summary(
        planning=planning,
        injection_trace=injection.trace,
    )
    return SimpleNamespace(
        lookup_results=lookup_results,
        packets=packets,
        decision=decision,
        rendered=rendered,
        injection=injection,
        summary=summary,
    )


def test_successful_execution_within_timeout_behaves_normally():
    result = execute_lookup_requests(
        agent=agent_for(lambda _request: fast_result()),
        lookup_requests=[request()],
        lookup_capability=resolved_capability(timeout_ms=3000),
    )[0]

    assert result.retrieval_executed is True
    assert len(result.payloads) == 1
    assert result.trace["lookup_status"] == "success"
    assert result.trace["timeout_ms"] == 3000
    assert result.trace["cancellation_behavior"] == "fail_closed"
    assert result.trace["max_concurrent_lookups"] == 1


def test_timeout_execution_fails_closed_deterministically_without_retry():
    attempts = {"count": 0}

    def slow_executor(_request):
        attempts["count"] += 1
        time.sleep(0.2)
        return fast_result()

    result = execute_lookup_requests(
        agent=agent_for(slow_executor),
        lookup_requests=[request()],
        lookup_capability=resolved_capability(timeout_ms=20),
    )[0]

    assert attempts["count"] == 1
    assert result.retrieval_executed is False
    assert result.payloads == []
    assert result.skipped_reasons == ("lookup_execution_timeout",)
    assert result.trace["lookup_status"] == "timeout"


def test_cancellation_state_propagates_through_summary_and_trace():
    result = execute_lookup_requests(
        agent=agent_for(lambda _request: (_ for _ in ()).throw(
            LookupExecutionCancelled()
        )),
        lookup_requests=[request()],
        lookup_capability=resolved_capability(timeout_ms=3000),
    )[0]
    context = run_context_path([result])

    assert result.trace["lookup_status"] == "cancelled"
    assert result.skipped_reasons == ("lookup_execution_cancelled",)
    assert context.summary["lookup_pipeline"]["execution_status"] == (
        "cancelled"
    )
    assert context.summary["lookup_pipeline"]["lookup_status_counts"] == {
        "cancelled": 1,
    }


def test_timed_out_lookup_never_materializes_renders_or_injects_context():
    result = execute_lookup_requests(
        agent=agent_for(lambda _request: (time.sleep(0.2), fast_result())[1]),
        lookup_requests=[request()],
        lookup_capability=resolved_capability(timeout_ms=20),
    )[0]
    context = run_context_path([result])

    assert context.packets == []
    assert context.rendered is None
    assert context.injection.trace["injection_allowed"] is False
    assert context.injection.trace["injected_block_count"] == 0
    assert "lookup_execution_timeout" in context.summary["lookup_pipeline"][
        "skipped_reasons"
    ]


def test_multi_entity_mixed_timeout_and_success_is_deterministic():
    attempts = {"slow": 0, "fast": 0}

    def mixed_executor(lookup_request):
        if lookup_request["entity_name"] == "Slow Entity":
            attempts["slow"] += 1
            time.sleep(0.2)
            return fast_result()

        attempts["fast"] += 1
        return fast_result()

    results = execute_lookup_requests(
        agent=agent_for(mixed_executor),
        lookup_requests=[
            request("Example Entity", "timeout-test:1"),
            request("Slow Entity", "timeout-test:2"),
        ],
        lookup_capability=resolved_capability(
            timeout_ms=20,
            max_concurrent_lookups=2,
        ),
    )
    context = run_context_path(results)

    assert attempts == {"slow": 1, "fast": 1}
    assert [result.trace["lookup_status"] for result in results] == [
        "success",
        "timeout",
    ]
    assert [packet["fields"]["display_name"] for packet in context.packets] == [
        "Example Entity",
    ]
    assert context.summary["lookup_pipeline"]["execution_status"] == (
        "partial_success"
    )
    assert context.summary["lookup_pipeline"]["lookup_status_counts"] == {
        "success": 1,
        "timeout": 1,
    }


def test_multiple_lookups_execute_concurrently_but_return_in_planner_order():
    lock = Lock()
    both_started = Event()
    release = Event()
    started: list[str] = []

    def concurrent_executor(lookup_request):
        with lock:
            started.append(lookup_request["entity_name"])
            if len(started) == 2:
                both_started.set()

        both_started.wait(0.5)
        release.set()
        release.wait(0.5)
        return SimpleNamespace(
            ok=True,
            payload={
                "display_name": lookup_request["entity_name"],
                "title": "Concurrent lookup",
            },
            retrieval_executed=True,
            skipped_reasons=(),
        )

    results = execute_lookup_requests(
        agent=agent_for(concurrent_executor),
        lookup_requests=[
            request("First Entity", "concurrent-test:1"),
            request("Second Entity", "concurrent-test:2"),
        ],
        lookup_capability=resolved_capability(
            timeout_ms=1000,
            max_concurrent_lookups=2,
        ),
    )
    context = run_context_path(results)

    assert both_started.is_set() is True
    assert sorted(started) == ["First Entity", "Second Entity"]
    assert [result.request["entity_name"] for result in results] == [
        "First Entity",
        "Second Entity",
    ]
    assert [result.trace["lookup_status"] for result in results] == [
        "success",
        "success",
    ]
    assert [packet["fields"]["display_name"] for packet in context.packets] == [
        "First Entity",
        "Second Entity",
    ]


def main():
    test_successful_execution_within_timeout_behaves_normally()
    test_timeout_execution_fails_closed_deterministically_without_retry()
    test_cancellation_state_propagates_through_summary_and_trace()
    test_timed_out_lookup_never_materializes_renders_or_injects_context()
    test_multi_entity_mixed_timeout_and_success_is_deterministic()
    test_multiple_lookups_execute_concurrently_but_return_in_planner_order()
    print("PASS lookup execution timeout")


if __name__ == "__main__":
    main()
