import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.context_injection import (  # noqa: E402
    ContextInjectionPolicy,
    build_context_injection_plan,
)
from runtime.context_rendering import (  # noqa: E402
    render_context_preview,
    rendered_context_block_dict,
)
from runtime.context_trace import trace_planned_context  # noqa: E402


def injection_plan():
    trace = trace_planned_context(
        request_id="req_context_render",
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


def test_render_synthetic_preview():
    block = render_context_preview(injection_plan())

    assert "BEGIN BOUNDED CONTEXT PREVIEW" in block.rendered_text
    assert "[Guest summary preview:" in block.rendered_text
    assert "[User preference preview:" in block.rendered_text
    assert block.rendered_items


def test_truncation_preview():
    block = render_context_preview(
        injection_plan(),
        max_tokens=5,
    )

    assert block.truncation_applied is True
    assert any(item.truncated for item in block.rendered_items)
    assert "TRUNCATED PREVIEW" in block.rendered_text


def test_preview_only_remains_true():
    block = render_context_preview(injection_plan())
    payload = rendered_context_block_dict(block)

    assert payload["preview_only"] is True
    assert all(
        item["preview_only"] is True
        for item in payload["rendered_items"]
    )
    json.dumps(payload)


def test_injection_performed_remains_false():
    block = render_context_preview(injection_plan())

    assert block.injection_performed is False
    assert "injection_performed: false" in block.rendered_text


def test_no_retrieval_execution():
    plan = injection_plan()
    block = render_context_preview(plan)

    assert all(item.retrieval_scope == "planned_only" for item in plan.planned_items)
    assert block.preview_only is True


def test_no_runtime_message_mutation():
    messages = [{"role": "user", "content": "original"}]
    before = list(messages)

    render_context_preview(injection_plan())

    assert messages == before


def test_attribution_preserved():
    block = render_context_preview(injection_plan())

    assert all(item.attributable is True for item in block.rendered_items)


def main():
    test_render_synthetic_preview()
    test_truncation_preview()
    test_preview_only_remains_true()
    test_injection_performed_remains_false()
    test_no_retrieval_execution()
    test_no_runtime_message_mutation()
    test_attribution_preserved()
    print("PASS context rendering")


if __name__ == "__main__":
    main()
