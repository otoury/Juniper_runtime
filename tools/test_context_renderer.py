import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.context_micro_injection import (  # noqa: E402
    MICRO_BLOCK,
    maybe_apply_micro_context_injection,
)
from runtime.context_renderer import render_context_item  # noqa: E402
from runtime.context_types import (  # noqa: E402
    ResolvedContextItem,
    ResolvedContextProvenance,
)


def valid_item(**overrides):
    data = {
        "id": "ctx_render_1",
        "source_contract_id": "alexis_guest_db",
        "content": "[Bounded guest context: guest_db is available for booking context.]",
        "content_type": "synthetic_notice",
        "provenance": ResolvedContextProvenance(
            source_contract_id="alexis_guest_db",
            retrieval_executed=False,
            attribution="synthetic_system_notice",
        ),
        "estimated_tokens": 8,
        "trust_level": "system_declared",
        "rendering_policy": "bounded_context_block",
        "metadata": {},
    }
    data.update(overrides)
    return ResolvedContextItem(**data)


def test_inline_notice_renders_content():
    item = valid_item(rendering_policy="inline_notice")

    assert render_context_item(item) == item.content


def test_bounded_context_block_renders_content():
    item = valid_item(rendering_policy="bounded_context_block")

    assert render_context_item(item) == item.content


def test_cite_only_does_not_render_content():
    item = valid_item(rendering_policy="cite_only")

    assert render_context_item(item) is None


def test_hidden_from_prompt_does_not_render_content():
    item = valid_item(rendering_policy="hidden_from_prompt")

    assert render_context_item(item) is None


def test_invalid_item_fails_closed():
    item = valid_item(content="")

    assert render_context_item(item) is None


def test_source_provenance_mismatch_fails_closed():
    item = valid_item(
        provenance=ResolvedContextProvenance(
            source_contract_id="different_source",
            retrieval_executed=False,
            attribution="synthetic_system_notice",
        )
    )

    assert render_context_item(item) is None


def test_synthetic_injection_behavior_remains_unchanged():
    previous_enable = os.environ.get("JUNIPER_ENABLE_CONTEXT_INJECTION")
    previous_disable = os.environ.get("JUNIPER_DISABLE_CONTEXT_INJECTION")

    try:
        os.environ["JUNIPER_ENABLE_CONTEXT_INJECTION"] = "1"
        os.environ.pop("JUNIPER_DISABLE_CONTEXT_INJECTION", None)
        result = maybe_apply_micro_context_injection(
            [{"role": "user", "content": "draft outreach"}],
            request_id="req_context_renderer",
            agent_name="alexis",
            shared_capability="draft_email",
            operation="NEW_REQUEST",
        )
    finally:
        if previous_enable is None:
            os.environ.pop("JUNIPER_ENABLE_CONTEXT_INJECTION", None)
        else:
            os.environ["JUNIPER_ENABLE_CONTEXT_INJECTION"] = previous_enable

        if previous_disable is None:
            os.environ.pop("JUNIPER_DISABLE_CONTEXT_INJECTION", None)
        else:
            os.environ["JUNIPER_DISABLE_CONTEXT_INJECTION"] = previous_disable

    assert result.injection_performed is True
    assert result.messages[-1]["content"] == MICRO_BLOCK
    assert result.sources == ["alexis.guest_db"]


def main():
    test_inline_notice_renders_content()
    test_bounded_context_block_renders_content()
    test_cite_only_does_not_render_content()
    test_hidden_from_prompt_does_not_render_content()
    test_invalid_item_fails_closed()
    test_source_provenance_mismatch_fails_closed()
    test_synthetic_injection_behavior_remains_unchanged()
    print("PASS context renderer")


if __name__ == "__main__":
    main()
