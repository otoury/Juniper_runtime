import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.context_budgeting import (  # noqa: E402
    context_budget_validation_dict,
    estimate_context_tokens,
    plan_context_truncation,
    validate_context_budget,
)
from runtime.context_injection import (  # noqa: E402
    ContextInjectionPolicy,
    build_context_injection_plan,
)
from runtime.context_trace import trace_planned_context  # noqa: E402


def injection_plan():
    trace = trace_planned_context(
        request_id="req_context_budget",
        agent_name="alexis",
        shared_capability="draft_email",
    )
    return build_context_injection_plan(
        trace,
        policy=ContextInjectionPolicy(
            enabled=False,
            max_items=3,
            max_tokens=1000,
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


def test_under_budget():
    validation = validate_context_budget(
        injection_plan(),
        max_tokens=200,
    )

    assert validation.over_budget is False
    assert validation.truncation_plans == []
    assert validation.errors == []
    assert validation.preview_only is True


def test_over_budget():
    validation = validate_context_budget(
        injection_plan(),
        max_tokens=5,
    )

    assert validation.over_budget is True
    assert validation.truncation_plans
    assert validation.preview_only is True


def test_truncation_required():
    validation = validate_context_budget(
        injection_plan(),
        max_tokens=5,
    )

    assert any(
        plan.truncation_required
        for plan in validation.truncation_plans
    )
    assert all(
        plan.preview_only is True
        for plan in validation.truncation_plans
    )


def test_invalid_max_token_policy():
    validation = validate_context_budget(
        injection_plan(),
        max_tokens=0,
    )

    assert validation.errors
    assert validation.errors[0].error_code == "invalid_max_tokens"
    assert validation.preview_only is True


def test_synthetic_estimate_behavior():
    estimate = estimate_context_tokens(
        "alexis.guest_db",
        metadata={
            "source": "alexis.guest_db",
            "source_type": "agent_resource",
            "inclusion_reason": "Synthetic metadata estimate.",
        },
    )

    assert estimate.estimated_tokens > 0
    assert estimate.content_available is False
    assert estimate.method == "metadata_synthetic_preview"
    assert estimate.preview_only is True


def test_explicit_content_estimate_behavior():
    estimate = estimate_context_tokens(
        "test.content",
        content="one two three",
    )

    assert estimate.estimated_tokens == 3
    assert estimate.content_available is True
    assert estimate.method == "whitespace_content_preview"
    assert estimate.preview_only is True


def test_preview_only_remains_true():
    validation = validate_context_budget(
        injection_plan(),
        max_tokens=200,
    )
    payload = context_budget_validation_dict(validation)

    assert payload["preview_only"] is True
    assert all(
        estimate["preview_only"] is True
        for estimate in payload["estimates"]
    )
    json.dumps(payload)


def test_no_retrieval_content_loading_occurs():
    validation = validate_context_budget(
        injection_plan(),
        max_tokens=200,
    )

    assert all(
        estimate.content_available is False
        for estimate in validation.estimates
    )


def test_unsupported_truncation_strategy():
    plans, errors = plan_context_truncation(
        [
            estimate_context_tokens(
                "source",
                metadata={"source": "source"},
            )
        ],
        max_tokens=1,
        truncation_strategy="unknown",
    )

    assert plans == []
    assert errors[0].error_code == "unsupported_truncation_strategy"


def main():
    test_under_budget()
    test_over_budget()
    test_truncation_required()
    test_invalid_max_token_policy()
    test_synthetic_estimate_behavior()
    test_explicit_content_estimate_behavior()
    test_preview_only_remains_true()
    test_no_retrieval_content_loading_occurs()
    test_unsupported_truncation_strategy()
    print("PASS context budgeting")


if __name__ == "__main__":
    main()
