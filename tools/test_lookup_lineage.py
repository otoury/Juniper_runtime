import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.alexis import AlexisAgent  # noqa: E402
from runtime.lookup.lineage import (  # noqa: E402
    derive_lookup_stage_id,
    lookup_lineage_ids,
    new_lookup_lineage_root,
)
from runtime.lookup.context_injection import maybe_inject_lookup_context  # noqa: E402
from runtime.request_planner import plan_request  # noqa: E402


KNOWN_ENTITY_NAME = "Dr. Saju Matthew"


def dispatch():
    return SimpleNamespace(
        target_agent="alexis",
        cognition="LOCAL",
        task_type="lookup_lineage_test",
        tools_needed=[],
        reason="Focused lookup lineage test.",
        confidence=1.0,
    )


def alexis_agent():
    return AlexisAgent(workspace_path="/tmp/juniper_stage_16b_alexis")


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


def planned_lookup():
    return plan_request(
        text=f"Draft a booking email to {KNOWN_ENTITY_NAME} about Iran talks.",
        agent=alexis_agent(),
        user_id="lookup_lineage_user",
        recent_memory=[],
        context_packet={},
        dispatch=dispatch(),
    )


def lineage_values(planned):
    request = planned.lookup_requests[0]
    packet_provenance = planned.lookup_context_packets[0]["provenance"]
    block_provenance = planned.rendered_lookup_context["blocks"][0][
        "provenance"
    ]
    injection = maybe_inject_lookup_context(
        [{"role": "user", "content": "Draft"}],
        rendered_lookup_context=planned.rendered_lookup_context,
        render_decision=planned.lookup_context_render_decision,
        injection_policy=injection_policy(),
    )

    return {
        "request": request,
        "request_trace": planned.lookup_request_traces[0],
        "execution_trace": planned.lookup_execution_traces[0],
        "metadata": planned.lookup_results[0],
        "packet": packet_provenance,
        "render_decision": planned.lookup_context_render_decision,
        "block": block_provenance,
        "injection_trace": injection.trace,
    }


def test_lookup_lineage_ids_propagate_across_pipeline():
    values = lineage_values(planned_lookup())
    root = values["request"]["lookup_lineage_id"]

    for key, stage_values in values.items():
        if key == "render_decision":
            continue
        assert stage_values["lookup_lineage_id"] == root

    assert root in values["render_decision"]["lookup_lineage_ids"]

    assert values["request"]["lookup_request_id"] == (
        values["request_trace"]["lookup_request_id"]
    )
    assert values["request"]["lookup_execution_id"] == (
        values["execution_trace"]["lookup_execution_id"]
    )
    assert values["request"]["lookup_packet_id"] == (
        values["packet"]["lookup_packet_id"]
    )
    assert values["request"]["lookup_render_id"] in (
        values["render_decision"]["lookup_render_ids"]
    )
    assert values["request"]["lookup_render_id"] == (
        values["block"]["lookup_render_id"]
    )
    assert values["request"]["lookup_injection_id"] == (
        values["injection_trace"]["lookup_injection_id"]
    )


def test_lookup_lineage_ids_are_stable_within_lifecycle():
    root = new_lookup_lineage_root()
    first = lookup_lineage_ids(root)
    second = lookup_lineage_ids(root)

    assert first == second
    assert first["lookup_request_id"] == derive_lookup_stage_id(
        root,
        "request",
    )


def test_lookup_lineage_ids_differ_across_lifecycles():
    first = planned_lookup().lookup_requests[0]["lookup_lineage_id"]
    second = planned_lookup().lookup_requests[0]["lookup_lineage_id"]

    assert first != second


def test_lookup_lineage_ids_are_content_safe():
    values = lineage_values(planned_lookup())
    serialized = repr(values)

    for key in (
        "lookup_lineage_id",
        "lookup_request_id",
        "lookup_execution_id",
        "lookup_packet_id",
        "lookup_render_id",
        "lookup_injection_id",
    ):
        assert values["request"][key]

    assert KNOWN_ENTITY_NAME not in values["request"]["lookup_lineage_id"]
    assert "GUESTS_CANONICAL.csv" not in serialized
    assert "/private" not in serialized


def test_failed_lookup_flow_has_safe_lineage_traces():
    planned = plan_request(
        text="Draft a booking email to Unknown Person about Iran talks.",
        agent=alexis_agent(),
        user_id="lookup_lineage_user",
        recent_memory=[],
        context_packet={},
        dispatch=dispatch(),
    )

    assert planned.lookup_requests[0]["lookup_lineage_id"]
    assert planned.lookup_execution_traces[0]["lookup_lineage_id"] == (
        planned.lookup_requests[0]["lookup_lineage_id"]
    )
    assert planned.lookup_execution_traces[0]["records_returned"] == 0
    assert planned.lookup_context_packets == []
    assert "Unknown Person" not in repr(planned.lookup_execution_traces)


def main():
    test_lookup_lineage_ids_propagate_across_pipeline()
    test_lookup_lineage_ids_are_stable_within_lifecycle()
    test_lookup_lineage_ids_differ_across_lifecycles()
    test_lookup_lineage_ids_are_content_safe()
    test_failed_lookup_flow_has_safe_lineage_traces()
    print("PASS lookup lineage")


if __name__ == "__main__":
    main()
