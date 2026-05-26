import json
import sys
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.context_diff import (  # noqa: E402
    context_diff_dict,
    diff_context_plans,
)
from runtime.context_injection import (  # noqa: E402
    ContextInjectionPolicy,
    InjectedContextItem,
    build_context_injection_plan,
)
from runtime.context_trace import trace_planned_context  # noqa: E402


def alexis_draft_trace():
    return trace_planned_context(
        request_id="req_context_diff",
        agent_name="alexis",
        shared_capability="draft_email",
    )


def permissive_plan(trace):
    return build_context_injection_plan(
        trace,
        policy=ContextInjectionPolicy(
            enabled=True,
            max_items=3,
            max_tokens=500,
            allowed_source_types=[
                "agent_resource",
                "recent_artifacts",
                "memory",
                "contract",
            ],
            redact_sensitive=True,
            approval_sensitive=False,
        ),
    )


def test_identical_planned_injection_plans():
    trace = alexis_draft_trace()
    plan = permissive_plan(trace)
    diff = diff_context_plans(trace, plan)

    assert diff.planned_context_count == 2
    assert diff.injection_plan_count == 2
    assert diff.added_items == []
    assert diff.removed_items == []
    assert diff.changed_items == []
    assert diff.summary.added_count == 0
    assert diff.summary.removed_count == 0
    assert diff.summary.changed_count == 0
    assert diff.summary.injection_enabled is False


def test_added_item_detection():
    trace = alexis_draft_trace()
    plan = permissive_plan(trace)
    extra = InjectedContextItem(
        source="contract.outreach_email",
        source_type="contract",
        inclusion_reason="Contract hint would be included.",
        token_count=5,
        truncation_status="not_truncated",
        attributable=True,
        retrieval_scope="planned_only",
        injected=False,
    )
    changed_plan = replace(
        plan,
        planned_items=[*plan.planned_items, extra],
        total_estimated_tokens=plan.total_estimated_tokens + 5,
    )
    diff = diff_context_plans(trace, changed_plan)

    assert diff.summary.added_count == 1
    assert diff.added_items[0].source == "contract.outreach_email"
    assert diff.added_items[0].change_type == "added"
    assert diff.added_items[0].attributable is True
    assert diff.added_items[0].bounded is True


def test_token_delta_calculation():
    trace = alexis_draft_trace()
    plan = permissive_plan(trace)
    diff = diff_context_plans(trace, plan)

    assert diff.token_delta == plan.total_estimated_tokens
    assert diff.summary.estimated_token_delta == (
        plan.total_estimated_tokens
    )


def test_provenance_flags_remain_true():
    trace = alexis_draft_trace()
    plan = permissive_plan(trace)
    diff = diff_context_plans(trace, plan)
    payload = context_diff_dict(diff)

    assert payload["provenance_only"] is True
    assert payload["summary"]["injection_enabled"] is False
    json.dumps(payload)


def test_no_injection_performed():
    trace = alexis_draft_trace()
    plan = permissive_plan(trace)

    assert plan.injection_performed is False
    assert all(item.injected is False for item in plan.planned_items)

    diff = diff_context_plans(trace, plan)

    assert diff.provenance_only is True
    assert diff.summary.injection_enabled is False


def test_no_retrieval_execution():
    trace = alexis_draft_trace()
    plan = permissive_plan(trace)

    assert trace.retrieval_policy["retrieval_execution"] is False
    assert trace.retrieval_policy["message_injection"] is False
    assert all(
        item.retrieval_scope == "planned_only"
        for item in plan.planned_items
    )

    diff = diff_context_plans(trace, plan)

    assert diff.provenance_only is True


def main():
    test_identical_planned_injection_plans()
    test_added_item_detection()
    test_token_delta_calculation()
    test_provenance_flags_remain_true()
    test_no_injection_performed()
    test_no_retrieval_execution()
    print("PASS context diff")


if __name__ == "__main__":
    main()
