from __future__ import annotations

from runtime.context_types import (
    ResolvedContextItem,
    validate_context_item_source_contract,
    validate_rendering_policy,
    validate_resolved_context_item,
)


PROMPT_VISIBLE_RENDERING_POLICIES = {
    "inline_notice",
    "bounded_context_block",
}


def render_context_item(
    item: ResolvedContextItem,
) -> str | None:
    if validate_resolved_context_item(item):
        return None

    if validate_rendering_policy(item.rendering_policy) is not None:
        return None

    if validate_context_item_source_contract(item):
        return None

    if item.rendering_policy in PROMPT_VISIBLE_RENDERING_POLICIES:
        return item.content

    if item.rendering_policy in {"cite_only", "hidden_from_prompt"}:
        return None

    return None


__all__ = [
    "PROMPT_VISIBLE_RENDERING_POLICIES",
    "render_context_item",
]
