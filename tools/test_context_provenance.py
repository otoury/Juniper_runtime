import json
import sys
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.context_injection import (  # noqa: E402
    ContextInjectionPolicy,
    build_context_injection_plan,
)
from runtime.context_provenance import (  # noqa: E402
    context_provenance_report_dict,
    validate_context_provenance,
)
from runtime.context_rendering import (  # noqa: E402
    RenderedContextItem,
    render_context_preview,
)
from runtime.context_trace import trace_planned_context  # noqa: E402


def preview_chain(max_tokens: int | None = None):
    planned_trace = trace_planned_context(
        request_id="req_context_provenance",
        agent_name="alexis",
        shared_capability="draft_email",
    )
    injection_plan = build_context_injection_plan(
        planned_trace,
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
    rendered_block = render_context_preview(
        injection_plan,
        max_tokens=max_tokens,
    )
    return planned_trace, injection_plan, rendered_block


def test_matching_provenance():
    planned_trace, injection_plan, rendered_block = preview_chain()
    report = validate_context_provenance(
        planned_trace,
        injection_plan,
        rendered_block,
    )

    assert report.provenance_errors == []
    assert report.planned_items_count == 2
    assert report.rendered_items_count == 2
    assert len(report.matched_items) == 2
    assert report.unmatched_items == []
    assert report.token_consistency is True


def test_unmatched_rendered_item():
    planned_trace, injection_plan, rendered_block = preview_chain()
    extra = RenderedContextItem(
        source="undeclared.source",
        rendered_preview="[Undeclared preview]",
        truncated=False,
        attributable=True,
        token_estimate=1,
        preview_only=True,
    )
    changed_block = replace(
        rendered_block,
        rendered_items=[*rendered_block.rendered_items, extra],
    )
    report = validate_context_provenance(
        planned_trace,
        injection_plan,
        changed_block,
    )

    assert report.unmatched_items
    assert any(
        error.error_code == "unmatched_rendered_item"
        for error in report.provenance_errors
    )


def test_token_consistency_validation():
    planned_trace, injection_plan, rendered_block = preview_chain()
    inflated = replace(
        rendered_block.rendered_items[0],
        token_estimate=999,
    )
    changed_block = replace(
        rendered_block,
        rendered_items=[inflated, *rendered_block.rendered_items[1:]],
    )
    report = validate_context_provenance(
        planned_trace,
        injection_plan,
        changed_block,
    )

    assert report.token_consistency is False
    assert any(
        error.error_code == "token_estimate_inconsistent"
        for error in report.provenance_errors
    )


def test_truncation_consistency_validation():
    planned_trace, injection_plan, rendered_block = preview_chain()
    bad_truncation = replace(
        rendered_block.rendered_items[0],
        truncated=True,
        token_estimate=injection_plan.planned_items[0].token_count,
    )
    changed_block = replace(
        rendered_block,
        rendered_items=[
            bad_truncation,
            *rendered_block.rendered_items[1:],
        ],
    )
    report = validate_context_provenance(
        planned_trace,
        injection_plan,
        changed_block,
    )

    assert any(
        item.truncation_consistent is False
        for item in report.matched_items
    )
    assert any(
        error.error_code == "truncation_inconsistent"
        for error in report.provenance_errors
    )


def test_preview_only_remains_true():
    planned_trace, injection_plan, rendered_block = preview_chain()
    report = validate_context_provenance(
        planned_trace,
        injection_plan,
        rendered_block,
    )
    payload = context_provenance_report_dict(report)

    assert payload["preview_only"] is True
    assert all(
        error["preview_only"] is True
        for error in payload["provenance_errors"]
    )
    json.dumps(payload)


def test_no_retrieval_execution():
    planned_trace, injection_plan, rendered_block = preview_chain()
    report = validate_context_provenance(
        planned_trace,
        injection_plan,
        rendered_block,
    )

    assert planned_trace.retrieval_policy["retrieval_execution"] is False
    assert injection_plan.injection_performed is False
    assert rendered_block.injection_performed is False
    assert report.preview_only is True


def test_no_message_mutation():
    messages = [{"role": "user", "content": "original"}]
    before = list(messages)
    planned_trace, injection_plan, rendered_block = preview_chain()

    validate_context_provenance(
        planned_trace,
        injection_plan,
        rendered_block,
    )

    assert messages == before


def main():
    test_matching_provenance()
    test_unmatched_rendered_item()
    test_token_consistency_validation()
    test_truncation_consistency_validation()
    test_preview_only_remains_true()
    test_no_retrieval_execution()
    test_no_message_mutation()
    print("PASS context provenance")


if __name__ == "__main__":
    main()
