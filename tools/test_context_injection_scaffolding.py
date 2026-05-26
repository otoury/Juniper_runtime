import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.context_injection import (  # noqa: E402
    ContextInjectionPolicy,
    build_context_injection_plan,
    context_injection_plan_dict,
    validate_context_injection_policy,
)
from runtime.context_trace import trace_planned_context  # noqa: E402


def alexis_draft_trace():
    return trace_planned_context(
        request_id="req_injection_scaffold",
        agent_name="alexis",
        shared_capability="draft_email",
    )


def valid_policy(**overrides):
    values = {
        "enabled": True,
        "max_items": 3,
        "max_tokens": 500,
        "allowed_source_types": [
            "agent_resource",
            "recent_artifacts",
            "memory",
            "contract",
        ],
        "redact_sensitive": True,
        "approval_sensitive": False,
    }
    values.update(overrides)
    return ContextInjectionPolicy(**values)


def test_valid_policy():
    policy, errors = validate_context_injection_policy(
        valid_policy()
    )

    assert errors == []
    assert policy is not None
    assert policy.enabled is True
    assert policy.max_items == 3
    assert policy.max_tokens == 500


def test_invalid_policy():
    policy, errors = validate_context_injection_policy(
        {
            "enabled": "yes",
            "max_items": -1,
            "max_tokens": 0,
            "allowed_source_types": ["unknown"],
        }
    )

    assert policy is None
    assert len(errors) >= 4
    assert all(
        error.error_code == "invalid_injection_policy"
        for error in errors
    )


def test_disabled_by_default_behavior():
    plan = build_context_injection_plan(
        alexis_draft_trace(),
    )

    assert plan.enabled is False
    assert plan.injection_performed is False
    assert plan.provenance_only is True
    assert plan.planned_items == []
    assert any(
        error.error_code == "injection_disabled"
        for error in plan.errors
    )


def test_no_injection_performed():
    plan = build_context_injection_plan(
        alexis_draft_trace(),
        policy=valid_policy(),
    )

    assert plan.enabled is False
    assert plan.injection_performed is False
    assert plan.provenance_only is True
    assert plan.planned_items
    assert all(item.injected is False for item in plan.planned_items)


def test_no_retrieval_execution():
    plan = build_context_injection_plan(
        alexis_draft_trace(),
        policy=valid_policy(),
    )

    assert all(
        item.retrieval_scope == "planned_only"
        for item in plan.planned_items
    )
    assert all(item.injected is False for item in plan.planned_items)


def test_bounded_item_enforcement():
    plan = build_context_injection_plan(
        alexis_draft_trace(),
        policy=valid_policy(max_items=1),
    )

    assert len(plan.planned_items) == 1
    assert any(
        error.error_code == "max_items_enforced"
        for error in plan.errors
    )


def test_provenance_flags_remain_correct():
    plan = build_context_injection_plan(
        alexis_draft_trace(),
        policy=valid_policy(max_tokens=500),
    )
    payload = context_injection_plan_dict(plan)
    encoded = json.dumps(payload)

    assert "injection_performed" in encoded
    assert payload["enabled"] is False
    assert payload["injection_performed"] is False
    assert payload["provenance_only"] is True
    assert all(
        item["attributable"] is True
        for item in payload["planned_items"]
    )
    assert all(
        item["injected"] is False
        for item in payload["planned_items"]
    )


def main():
    test_valid_policy()
    test_invalid_policy()
    test_disabled_by_default_behavior()
    test_no_injection_performed()
    test_no_retrieval_execution()
    test_bounded_item_enforcement()
    test_provenance_flags_remain_correct()
    print("PASS context injection scaffolding")


if __name__ == "__main__":
    main()
