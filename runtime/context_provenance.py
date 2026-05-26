from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from runtime.context_injection import ContextInjectionPlan
from runtime.context_rendering import RenderedContextBlock
from runtime.context_trace import PlannedContextTrace


@dataclass(frozen=True)
class ContextProvenanceError:
    error_code: str
    message: str
    source: str | None
    preview_only: bool


@dataclass(frozen=True)
class ContextProvenanceItem:
    source: str
    planned: bool
    rendered: bool
    attributable: bool
    token_estimate: int
    truncation_consistent: bool


@dataclass(frozen=True)
class ContextProvenanceReport:
    request_id: str
    agent_name: str
    shared_capability: str
    planned_items_count: int
    rendered_items_count: int
    matched_items: list[ContextProvenanceItem]
    unmatched_items: list[ContextProvenanceItem]
    provenance_errors: list[ContextProvenanceError]
    token_consistency: bool
    preview_only: bool


def _error(
    error_code: str,
    message: str,
    source: str | None = None,
) -> ContextProvenanceError:
    return ContextProvenanceError(
        error_code=error_code,
        message=message,
        source=source,
        preview_only=True,
    )


def _planned_by_source(
    planned_context_trace: PlannedContextTrace,
) -> dict[str, Any]:
    return {
        item.source_name: item
        for item in planned_context_trace.planned_items
    }


def _injection_by_source(
    context_injection_plan: ContextInjectionPlan,
) -> dict[str, Any]:
    return {
        item.source: item
        for item in context_injection_plan.planned_items
    }


def validate_context_provenance(
    planned_context_trace: PlannedContextTrace,
    context_injection_plan: ContextInjectionPlan,
    rendered_context_block: RenderedContextBlock,
) -> ContextProvenanceReport:
    planned_by_source = _planned_by_source(planned_context_trace)
    injection_by_source = _injection_by_source(context_injection_plan)
    errors: list[ContextProvenanceError] = []
    matched_items: list[ContextProvenanceItem] = []
    unmatched_items: list[ContextProvenanceItem] = []
    token_consistency = True

    if not planned_context_trace.retrieval_policy.get(
        "retrieval_execution"
    ) is False:
        errors.append(
            _error(
                "retrieval_execution_not_false",
                "Planned context trace must not execute retrieval.",
            )
        )

    if not context_injection_plan.provenance_only:
        errors.append(
            _error(
                "provenance_only_not_true",
                "Context injection plan must remain provenance-only.",
            )
        )

    if context_injection_plan.injection_performed:
        errors.append(
            _error(
                "injection_performed",
                "Context injection plan must not perform injection.",
            )
        )

    if not rendered_context_block.preview_only:
        errors.append(
            _error(
                "preview_only_not_true",
                "Rendered context block must remain preview-only.",
            )
        )

    if rendered_context_block.injection_performed:
        errors.append(
            _error(
                "rendered_injection_performed",
                "Rendered context block must not perform injection.",
            )
        )

    for rendered_item in rendered_context_block.rendered_items:
        planned_item = planned_by_source.get(rendered_item.source)
        injection_item = injection_by_source.get(rendered_item.source)
        planned = planned_item is not None
        injected_plan_exists = injection_item is not None
        attributable = bool(rendered_item.attributable)
        truncation_consistent = True

        if not planned or not injected_plan_exists:
            item = ContextProvenanceItem(
                source=rendered_item.source,
                planned=planned,
                rendered=True,
                attributable=attributable,
                token_estimate=rendered_item.token_estimate,
                truncation_consistent=False,
            )
            unmatched_items.append(item)
            errors.append(
                _error(
                    "unmatched_rendered_item",
                    "Rendered item does not map to planned provenance.",
                    rendered_item.source,
                )
            )
            continue

        if not attributable:
            errors.append(
                _error(
                    "rendered_item_not_attributable",
                    "Rendered item must remain attributable.",
                    rendered_item.source,
                )
            )

        if rendered_item.token_estimate > injection_item.token_count:
            token_consistency = False
            errors.append(
                _error(
                    "token_estimate_inconsistent",
                    "Rendered token estimate exceeds injection plan estimate.",
                    rendered_item.source,
                )
            )

        if rendered_item.truncated and (
            rendered_item.token_estimate >= injection_item.token_count
        ):
            truncation_consistent = False
            errors.append(
                _error(
                    "truncation_inconsistent",
                    "Rendered item is marked truncated without a lower "
                    "token estimate.",
                    rendered_item.source,
                )
            )

        matched_items.append(
            ContextProvenanceItem(
                source=rendered_item.source,
                planned=True,
                rendered=True,
                attributable=attributable,
                token_estimate=rendered_item.token_estimate,
                truncation_consistent=truncation_consistent,
            )
        )

    rendered_total = sum(
        item.token_estimate
        for item in rendered_context_block.rendered_items
    )

    if rendered_total > context_injection_plan.total_estimated_tokens:
        token_consistency = False
        errors.append(
            _error(
                "rendered_token_total_inconsistent",
                "Rendered token total exceeds injection plan token total.",
            )
        )

    return ContextProvenanceReport(
        request_id=planned_context_trace.request_id,
        agent_name=planned_context_trace.agent_name,
        shared_capability=planned_context_trace.shared_capability,
        planned_items_count=len(planned_context_trace.planned_items),
        rendered_items_count=len(rendered_context_block.rendered_items),
        matched_items=matched_items,
        unmatched_items=unmatched_items,
        provenance_errors=errors,
        token_consistency=token_consistency,
        preview_only=True,
    )


def context_provenance_report_dict(
    report: ContextProvenanceReport,
) -> dict[str, Any]:
    return asdict(report)


__all__ = [
    "ContextProvenanceError",
    "ContextProvenanceItem",
    "ContextProvenanceReport",
    "context_provenance_report_dict",
    "validate_context_provenance",
]
