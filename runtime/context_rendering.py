from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from runtime.context_budgeting import (
    ContextBudgetValidation,
    ContextTruncationPlan,
    validate_context_budget,
)
from runtime.context_injection import (
    ContextInjectionPlan,
    InjectedContextItem,
)


@dataclass(frozen=True)
class RenderedContextItem:
    source: str
    rendered_preview: str
    truncated: bool
    attributable: bool
    token_estimate: int
    preview_only: bool


@dataclass(frozen=True)
class ContextRenderError:
    error_code: str
    message: str
    source: str | None
    preview_only: bool


@dataclass(frozen=True)
class RenderedContextBlock:
    request_id: str
    agent_name: str
    shared_capability: str
    rendered_text: str
    rendered_items: list[RenderedContextItem]
    estimated_tokens: int
    truncation_applied: bool
    preview_only: bool
    injection_performed: bool
    errors: list[ContextRenderError] = field(default_factory=list)


def _error(
    error_code: str,
    message: str,
    source: str | None = None,
) -> ContextRenderError:
    return ContextRenderError(
        error_code=error_code,
        message=message,
        source=source,
        preview_only=True,
    )


def _template_for_item(item: InjectedContextItem) -> str:
    if item.source_type == "agent_resource" and "guest" in item.source:
        return "[Guest summary preview: bounded booking context]"

    if item.source_type == "contract":
        return "[Formatting constraint preview: bounded contract hints]"

    if item.source_type == "recent_artifacts":
        return (
            "[Recent artifact preview: bounded prior "
            f"{item.source} context]"
        )

    if item.source_type == "memory":
        return "[User preference preview: concise newsroom tone]"

    return (
        "[Context preview: bounded synthetic context from "
        f"{item.source}]"
    )


def _truncate_preview(
    text: str,
    target_tokens: int,
) -> str:
    if target_tokens <= 0:
        return "[TRUNCATED PREVIEW: omitted by token budget]"

    tokens = text.split()

    if len(tokens) <= target_tokens:
        return text

    return " ".join(tokens[:target_tokens]) + " [TRUNCATED PREVIEW]"


def render_context_item_preview(
    item: InjectedContextItem,
    *,
    truncation_plan: ContextTruncationPlan | None = None,
) -> RenderedContextItem:
    rendered = _template_for_item(item)
    truncated = False
    token_estimate = item.token_count

    if truncation_plan and truncation_plan.truncation_required:
        rendered = _truncate_preview(
            rendered,
            truncation_plan.target_tokens,
        )
        truncated = True
        token_estimate = truncation_plan.target_tokens

    return RenderedContextItem(
        source=item.source,
        rendered_preview=rendered,
        truncated=truncated,
        attributable=bool(item.attributable),
        token_estimate=token_estimate,
        preview_only=True,
    )


def _plans_by_source(
    validation: ContextBudgetValidation,
) -> dict[str, ContextTruncationPlan]:
    return {
        plan.source: plan
        for plan in validation.truncation_plans
    }


def render_context_preview(
    context_injection_plan: ContextInjectionPlan,
    *,
    max_tokens: int | None = None,
) -> RenderedContextBlock:
    budget_validation = None
    truncation_by_source: dict[str, ContextTruncationPlan] = {}
    errors: list[ContextRenderError] = []

    if max_tokens is not None:
        budget_validation = validate_context_budget(
            context_injection_plan,
            max_tokens=max_tokens,
        )
        truncation_by_source = _plans_by_source(budget_validation)

        for error in budget_validation.errors:
            errors.append(
                _error(
                    error.error_code,
                    error.message,
                    ",".join(error.details) if error.details else None,
                )
            )

    rendered_items = [
        render_context_item_preview(
            item,
            truncation_plan=truncation_by_source.get(item.source),
        )
        for item in context_injection_plan.planned_items
    ]

    lines = [
        "BEGIN BOUNDED CONTEXT PREVIEW",
        f"agent: {context_injection_plan.agent_name}",
        f"shared_capability: {context_injection_plan.shared_capability}",
        "injection_performed: false",
        "preview_only: true",
    ]

    for item in rendered_items:
        marker = " truncated" if item.truncated else ""
        lines.append(
            f"- source={item.source}{marker}: {item.rendered_preview}"
        )

    lines.append("END BOUNDED CONTEXT PREVIEW")

    estimated_tokens = (
        budget_validation.total_estimated_tokens
        if budget_validation
        else sum(item.token_estimate for item in rendered_items)
    )

    return RenderedContextBlock(
        request_id=context_injection_plan.request_id,
        agent_name=context_injection_plan.agent_name,
        shared_capability=context_injection_plan.shared_capability,
        rendered_text="\n".join(lines),
        rendered_items=rendered_items,
        estimated_tokens=estimated_tokens,
        truncation_applied=any(item.truncated for item in rendered_items),
        preview_only=True,
        injection_performed=False,
        errors=errors,
    )


def rendered_context_block_dict(
    block: RenderedContextBlock,
) -> dict[str, Any]:
    return asdict(block)


__all__ = [
    "ContextRenderError",
    "RenderedContextBlock",
    "RenderedContextItem",
    "render_context_item_preview",
    "render_context_preview",
    "rendered_context_block_dict",
]
