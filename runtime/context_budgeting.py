from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from runtime.context_injection import ContextInjectionPlan


SUPPORTED_TRUNCATION_STRATEGIES = {
    "drop_tail",
    "truncate_each",
}


@dataclass(frozen=True)
class ContextBudgetError:
    error_code: str
    message: str
    details: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ContextTokenEstimate:
    source: str
    estimated_tokens: int
    method: str
    content_available: bool
    preview_only: bool


@dataclass(frozen=True)
class ContextTruncationPlan:
    source: str
    original_estimated_tokens: int
    target_tokens: int
    truncation_required: bool
    truncation_strategy: str
    preview_only: bool


@dataclass(frozen=True)
class ContextBudgetValidation:
    max_tokens: int
    total_estimated_tokens: int
    over_budget: bool
    estimates: list[ContextTokenEstimate]
    truncation_plans: list[ContextTruncationPlan]
    errors: list[ContextBudgetError]
    preview_only: bool


def _error(
    error_code: str,
    message: str,
    details: list[str] | None = None,
) -> ContextBudgetError:
    return ContextBudgetError(
        error_code=error_code,
        message=message,
        details=list(details or []),
    )


def _count_tokens(text: str) -> int:
    return max(0, len((text or "").split()))


def estimate_context_tokens(
    source: str,
    *,
    content: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ContextTokenEstimate:
    if content is not None:
        return ContextTokenEstimate(
            source=source,
            estimated_tokens=_count_tokens(content),
            method="whitespace_content_preview",
            content_available=True,
            preview_only=True,
        )

    metadata = metadata or {}
    synthetic_text = " ".join(
        str(value)
        for key, value in metadata.items()
        if key in {"source", "source_type", "inclusion_reason"}
        and value is not None
    )

    return ContextTokenEstimate(
        source=source,
        estimated_tokens=_count_tokens(synthetic_text),
        method="metadata_synthetic_preview",
        content_available=False,
        preview_only=True,
    )


def plan_context_truncation(
    estimates: list[ContextTokenEstimate],
    *,
    max_tokens: int,
    truncation_strategy: str = "drop_tail",
) -> tuple[list[ContextTruncationPlan], list[ContextBudgetError]]:
    errors: list[ContextBudgetError] = []

    if (
        not isinstance(max_tokens, int)
        or isinstance(max_tokens, bool)
        or max_tokens <= 0
    ):
        return [], [
            _error(
                "invalid_max_tokens",
                "max_tokens must be a positive integer.",
                ["max_tokens"],
            )
        ]

    if truncation_strategy not in SUPPORTED_TRUNCATION_STRATEGIES:
        return [], [
            _error(
                "unsupported_truncation_strategy",
                "Unsupported truncation strategy.",
                [truncation_strategy],
            )
        ]

    plans: list[ContextTruncationPlan] = []

    if truncation_strategy == "drop_tail":
        remaining = max_tokens

        for estimate in estimates:
            target = min(estimate.estimated_tokens, max(0, remaining))
            plans.append(
                ContextTruncationPlan(
                    source=estimate.source,
                    original_estimated_tokens=estimate.estimated_tokens,
                    target_tokens=target,
                    truncation_required=target < estimate.estimated_tokens,
                    truncation_strategy=truncation_strategy,
                    preview_only=True,
                )
            )
            remaining -= target

        return plans, errors

    per_item_target = max(1, max_tokens // max(1, len(estimates)))

    for estimate in estimates:
        target = min(estimate.estimated_tokens, per_item_target)
        plans.append(
            ContextTruncationPlan(
                source=estimate.source,
                original_estimated_tokens=estimate.estimated_tokens,
                target_tokens=target,
                truncation_required=target < estimate.estimated_tokens,
                truncation_strategy=truncation_strategy,
                preview_only=True,
            )
        )

    return plans, errors


def validate_context_budget(
    context_injection_plan: ContextInjectionPlan,
    *,
    max_tokens: int,
    truncation_strategy: str = "drop_tail",
    content_by_source: dict[str, str] | None = None,
) -> ContextBudgetValidation:
    errors: list[ContextBudgetError] = []

    if (
        not isinstance(max_tokens, int)
        or isinstance(max_tokens, bool)
        or max_tokens <= 0
    ):
        errors.append(
            _error(
                "invalid_max_tokens",
                "max_tokens must be a positive integer.",
                ["max_tokens"],
            )
        )

    content_by_source = content_by_source or {}
    estimates: list[ContextTokenEstimate] = []

    for item in context_injection_plan.planned_items:
        estimate = estimate_context_tokens(
            item.source,
            content=content_by_source.get(item.source),
            metadata={
                "source": item.source,
                "source_type": item.source_type,
                "inclusion_reason": item.inclusion_reason,
            },
        )

        if estimate.estimated_tokens < 0:
            errors.append(
                _error(
                    "invalid_token_estimate",
                    "Token estimates must be non-negative.",
                    [item.source],
                )
            )

        estimates.append(estimate)

    total = sum(estimate.estimated_tokens for estimate in estimates)
    over_budget = (
        isinstance(max_tokens, int)
        and not isinstance(max_tokens, bool)
        and max_tokens > 0
        and total > max_tokens
    )
    truncation_plans: list[ContextTruncationPlan] = []

    if over_budget:
        truncation_plans, truncation_errors = plan_context_truncation(
            estimates,
            max_tokens=max_tokens,
            truncation_strategy=truncation_strategy,
        )
        errors.extend(truncation_errors)
    elif (
        truncation_strategy not in SUPPORTED_TRUNCATION_STRATEGIES
    ):
        errors.append(
            _error(
                "unsupported_truncation_strategy",
                "Unsupported truncation strategy.",
                [truncation_strategy],
            )
        )

    return ContextBudgetValidation(
        max_tokens=max_tokens,
        total_estimated_tokens=total,
        over_budget=over_budget,
        estimates=estimates,
        truncation_plans=truncation_plans,
        errors=errors,
        preview_only=True,
    )


def context_budget_validation_dict(
    validation: ContextBudgetValidation,
) -> dict[str, Any]:
    return asdict(validation)


__all__ = [
    "ContextBudgetError",
    "ContextBudgetValidation",
    "ContextTokenEstimate",
    "ContextTruncationPlan",
    "context_budget_validation_dict",
    "estimate_context_tokens",
    "plan_context_truncation",
    "validate_context_budget",
]
