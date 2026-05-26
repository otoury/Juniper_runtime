import json
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.alexis import AlexisAgent  # noqa: E402
from runtime.lookup.context_injection import maybe_inject_lookup_context  # noqa: E402
from runtime.lookup.pipeline_summary import (  # noqa: E402
    build_lookup_pipeline_summary,
)
from runtime.request_planner import plan_request  # noqa: E402


KNOWN_ENTITY_NAME = "Dr. Saju Matthew"


def dispatch():
    return SimpleNamespace(
        target_agent="alexis",
        cognition="LOCAL",
        task_type="lookup_pipeline_summary_test",
        tools_needed=[],
        reason="Focused lookup pipeline summary test.",
        confidence=1.0,
    )


def alexis_agent():
    return AlexisAgent(workspace_path="/tmp/juniper_stage_17a_alexis")


def injection_policy():
    return {
        "allowed": True,
        "require_render_decision": True,
        "require_rendered_context": True,
        "allowed_content_types": ["lookup_context_block"],
        "allowed_render_modes": ["structured_fact_block"],
        "max_blocks": 1,
        "max_facts_per_block": 5,
        "max_total_characters": 1200,
        "truncation_mode": "drop_tail",
    }


def planned(text):
    return plan_request(
        text=text,
        agent=alexis_agent(),
        user_id="lookup_summary_user",
        recent_memory=[],
        context_packet={},
        dispatch=dispatch(),
    )


def final_summary(planning):
    injection = maybe_inject_lookup_context(
        [{"role": "user", "content": "Draft"}],
        rendered_lookup_context=planning.rendered_lookup_context,
        render_decision=planning.lookup_context_render_decision,
        injection_policy=injection_policy(),
    )
    return build_lookup_pipeline_summary(
        planning=planning,
        injection_trace=injection.trace,
    )


def test_successful_lookup_lifecycle_summary_is_complete():
    planning = planned(
        f"Draft a booking email to {KNOWN_ENTITY_NAME} about Iran talks."
    )
    summary = final_summary(planning)["lookup_pipeline"]

    assert summary["attempted"] is True
    assert summary["request_created"] is True
    assert summary["execution_status"] == "success"
    assert summary["records_returned"] == 1
    assert summary["context_materialized"] is True
    assert summary["render_allowed"] is True
    assert summary["render_mode"] == "structured_fact_block"
    assert summary["injection_allowed"] is True
    assert summary["injected_block_count"] == 1
    assert summary["skipped_reasons"] == []
    assert summary["lineage_root"] == planning.lookup_requests[0][
        "lookup_lineage_id"
    ]
    assert summary["lookup_execution_id"] == planning.lookup_requests[0][
        "lookup_execution_id"
    ]


def test_failed_lookup_lifecycle_summary_has_fail_closed_reasons():
    planning = planned("Draft a booking email to Unknown Person about Iran.")
    summary = final_summary(planning)["lookup_pipeline"]

    assert summary["attempted"] is True
    assert summary["request_created"] is True
    assert summary["execution_status"] == "failed"
    assert summary["records_returned"] == 0
    assert summary["context_materialized"] is False
    assert summary["render_allowed"] is False
    assert summary["injection_allowed"] is False
    assert "no_exact_match" in summary["skipped_reasons"]
    assert "render_decision_not_allowed" in summary["skipped_reasons"]


def test_non_lookup_workflow_summary_is_not_attempted():
    planning = planned("Write a quick producer note about the rundown.")
    summary = final_summary(planning)["lookup_pipeline"]

    assert summary["attempted"] is False
    assert summary["request_created"] is False
    assert summary["execution_status"] == "not_attempted"
    assert summary["records_returned"] == 0
    assert summary["context_materialized"] is False
    assert summary["render_allowed"] is False
    assert summary["injection_allowed"] is False


def test_summary_is_content_safe():
    planning = planned(
        f"Draft a booking email to {KNOWN_ENTITY_NAME} about Iran talks."
    )
    serialized = json.dumps(final_summary(planning), sort_keys=True)

    assert KNOWN_ENTITY_NAME not in serialized
    assert "Family Practice Physician" not in serialized
    assert "GUESTS_CANONICAL.csv" not in serialized
    assert "raw_lookup_results" not in serialized
    assert "lookup_context_packets" not in serialized
    assert "payloads" not in serialized


def test_summary_agrees_with_execution_render_and_injection_traces():
    planning = planned(
        f"Draft a booking email to {KNOWN_ENTITY_NAME} about Iran talks."
    )
    injection = maybe_inject_lookup_context(
        [{"role": "user", "content": "Draft"}],
        rendered_lookup_context=planning.rendered_lookup_context,
        render_decision=planning.lookup_context_render_decision,
        injection_policy=injection_policy(),
    )
    summary = build_lookup_pipeline_summary(
        planning=planning,
        injection_trace=injection.trace,
    )["lookup_pipeline"]

    assert summary["records_returned"] == (
        planning.lookup_execution_traces[0]["records_returned"]
    )
    assert summary["render_allowed"] == (
        planning.lookup_context_render_decision["render_allowed"]
    )
    assert summary["injection_allowed"] == (
        injection.trace["injection_allowed"]
    )
    assert summary["injected_block_count"] == (
        injection.trace["injected_block_count"]
    )


def main():
    test_successful_lookup_lifecycle_summary_is_complete()
    test_failed_lookup_lifecycle_summary_has_fail_closed_reasons()
    test_non_lookup_workflow_summary_is_not_attempted()
    test_summary_is_content_safe()
    test_summary_agrees_with_execution_render_and_injection_traces()
    print("PASS lookup pipeline summary")


if __name__ == "__main__":
    main()
