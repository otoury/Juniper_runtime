from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from runtime.context_composer import compose_bounded_context


MICRO_BLOCK = (
    "BOUNDED CONTEXT (synthetic, attributed, no retrieval):\n"
    "[Bounded guest context: guest_db is available for booking context.]"
)


@dataclass(frozen=True)
class MicroContextInjectionResult:
    messages: list[dict[str, Any]]
    injection_performed: bool
    item_count: int
    estimated_tokens: int
    sources: list[str]
    skipped_reasons: list[str] = field(default_factory=list)


def _report(
    report_event: Callable[..., Any] | None,
    *,
    source_bot: str,
    request_id: str,
    payload: dict[str, Any],
) -> None:
    if report_event is None:
        return

    try:
        report_event(
            source_bot,
            "bounded_context_injection",
            payload,
            request_id=request_id,
        )
    except Exception:
        pass


def maybe_apply_micro_context_injection(
    messages: list[dict[str, Any]],
    *,
    request_id: str,
    agent_name: str,
    shared_capability: str | None,
    operation: str | None,
    report_event: Callable[..., Any] | None = None,
    source_bot: str = "runtime",
) -> MicroContextInjectionResult:
    composition = compose_bounded_context(
        request_id=request_id,
        agent=agent_name,
        shared_capability=shared_capability,
        planner_mode=operation,
    )
    _report(
        report_event,
        source_bot=source_bot,
        request_id=request_id,
        payload=composition.trace_payload,
    )

    if not composition.injection_performed:
        return MicroContextInjectionResult(
            messages=messages,
            injection_performed=False,
            item_count=0,
            estimated_tokens=0,
            sources=[],
            skipped_reasons=composition.skipped_reasons,
        )

    injected_messages = [
        dict(message)
        for message in messages
    ]

    for block in composition.rendered_blocks:
        injected_messages.append(
            {
                "role": "system",
                "content": block,
            }
        )

    return MicroContextInjectionResult(
        messages=injected_messages,
        injection_performed=True,
        item_count=len(composition.items),
        estimated_tokens=sum(
            item.estimated_tokens
            for item in composition.items
        ),
        sources=list(
            composition.trace_payload.get("source_attribution", [])
        ),
        skipped_reasons=[],
    )


__all__ = [
    "MICRO_BLOCK",
    "MicroContextInjectionResult",
    "maybe_apply_micro_context_injection",
]
