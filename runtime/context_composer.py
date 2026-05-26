from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from runtime.context_adapter_factory import (
    create_context_adapter,
    get_context_adapter_factory,
)
from runtime.context_adapter_telemetry import build_context_adapter_trace
from runtime.context_adapter_output import validate_adapter_output
from runtime.context_collection import validate_context_item_collection
from runtime.context_injection import (
    ContextInjectionPolicy,
    build_context_injection_plan,
)
from runtime.context_provenance import validate_context_provenance
from runtime.context_renderer import render_context_item
from runtime.context_rendering import (
    RenderedContextBlock,
    RenderedContextItem,
)
from runtime.context_telemetry import summarize_context_collection
from runtime.context_trace import (
    build_context_trace_payload,
    trace_planned_context,
)
from runtime.context_types import (
    ResolvedContextItem,
    validate_resolved_context_item,
)
from runtime.lookup.telemetry import build_bounded_lookup_trace
from runtime.registries.context_injection_binding_registry import (
    ContextInjectionContract,
    ContextInjectionRegistryError,
    find_context_injection_contracts,
)
from runtime.registries.adapter_binding_registry import (
    ContextAdapterContract,
    get_context_adapter_for_source,
)


DEFAULT_ROLLBACK_ENV_FLAG = "JUNIPER_DISABLE_CONTEXT_INJECTION"
EXTERNAL_CONTEXT_READS_ENV_FLAG = "JUNIPER_ENABLE_EXTERNAL_CONTEXT_READS"


@dataclass(frozen=True)
class ContextCompositionResult:
    items: list[ResolvedContextItem]
    rendered_blocks: list[str]
    trace_payload: dict[str, Any]
    injection_performed: bool
    skipped_reasons: list[str] = field(default_factory=list)


def _flag_enabled() -> bool:
    return os.getenv("JUNIPER_ENABLE_CONTEXT_INJECTION") == "1"


def _rollback_enabled(
    env_flag: str = DEFAULT_ROLLBACK_ENV_FLAG,
) -> bool:
    return os.getenv(env_flag) == "1"


def _external_context_reads_enabled() -> bool:
    return os.getenv(EXTERNAL_CONTEXT_READS_ENV_FLAG) == "1"


def _capability_allowed(
    shared_capability: str | None,
    contract: ContextInjectionContract,
) -> bool:
    if shared_capability not in contract.shared_capability_scope:
        return False

    raw = os.getenv("JUNIPER_ENABLE_CONTEXT_INJECTION_CAPABILITIES")

    if not raw:
        return True

    allowed = {
        item.strip()
        for item in raw.split(",")
        if item.strip()
    }

    return shared_capability in allowed


def _trace_payload(
    *,
    request_id: str | None,
    agent: str,
    shared_capability: str | None,
    injection_performed: bool,
    skipped_reasons: list[str],
    collection_summary: dict[str, Any] | None = None,
    contract: ContextInjectionContract | None = None,
    item_count: int = 0,
    estimated_tokens: int = 0,
    sources: list[str] | None = None,
    adapter_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rollback_env_flag = (
        contract.rollback_env_flag
        if contract
        else DEFAULT_ROLLBACK_ENV_FLAG
    )
    payload = build_context_trace_payload(
        request_id=request_id,
        agent=agent,
        shared_capability=shared_capability,
        injection_id=contract.id if contract else None,
        source_contract_id=(
            contract.source_contract_id
            if contract
            else None
        ),
        injection_performed=injection_performed,
        skipped_reasons=skipped_reasons,
        collection_summary=collection_summary,
        provenance_validated=(
            contract.requires_provenance_validation
            if contract
            else False
        ),
        rollback_enabled=_rollback_enabled(rollback_env_flag),
    )
    payload.update({
        "enabled": _flag_enabled(),
        "telemetry_label": (
            contract.telemetry_label
            if contract
            else None
        ),
        "item_count": item_count,
        "estimated_tokens": estimated_tokens,
        "source_attribution": list(sources or []),
        "rollback_env_flag": rollback_env_flag,
        "context_collection": collection_summary,
        "adapter_trace": adapter_trace,
    })
    return payload


def _skipped(
    *,
    request_id: str | None,
    agent: str,
    shared_capability: str | None,
    skipped_reasons: list[str],
    contract: ContextInjectionContract | None = None,
    adapter_trace: dict[str, Any] | None = None,
) -> ContextCompositionResult:
    return ContextCompositionResult(
        items=[],
        rendered_blocks=[],
        trace_payload=_trace_payload(
            request_id=request_id,
            agent=agent,
            shared_capability=shared_capability,
            injection_performed=False,
            skipped_reasons=skipped_reasons,
            contract=contract,
            adapter_trace=adapter_trace,
        ),
        injection_performed=False,
        skipped_reasons=skipped_reasons,
    )


def _adapter_contract_for_injection(
    contract: ContextInjectionContract,
) -> ContextAdapterContract | None:
    return get_context_adapter_for_source(
        contract.source_contract_id
    )


def _is_supported_synthetic_adapter(
    adapter_contract: ContextAdapterContract,
) -> bool:
    return (
        adapter_contract.adapter_id == "synthetic_guest_context"
        and adapter_contract.adapter_type == "synthetic"
        and adapter_contract.execution_mode == "synthetic_only"
    )


def _is_supported_guest_db_fixture_adapter(
    adapter_contract: ContextAdapterContract,
) -> bool:
    return (
        adapter_contract.adapter_id == "guest_db_readonly_fixture"
        and adapter_contract.adapter_type == "structured_database"
        and adapter_contract.execution_mode == "read_only_fixture"
    )


def _is_declared_guest_db_readonly_adapter(
    adapter_contract: ContextAdapterContract,
) -> bool:
    return (
        adapter_contract.adapter_id == "guest_db_readonly"
        and adapter_contract.adapter_type == "structured_database"
        and adapter_contract.execution_mode == "read_only_declared"
    )


def _is_supported_guest_db_readonly_adapter(
    adapter_contract: ContextAdapterContract,
) -> bool:
    return (
        adapter_contract.adapter_id == "guest_db_readonly"
        and adapter_contract.adapter_type == "structured_database"
        and adapter_contract.execution_mode == "read_only_fixed_id"
    )


def _is_supported_adapter(
    adapter_contract: ContextAdapterContract,
) -> bool:
    return (
        (
            _is_supported_synthetic_adapter(adapter_contract)
            or _is_supported_guest_db_fixture_adapter(adapter_contract)
            or _is_supported_guest_db_readonly_adapter(adapter_contract)
        )
        and get_context_adapter_factory(adapter_contract.adapter_id)
        is not None
    )


def _adapter_for_contract(
    adapter_contract: ContextAdapterContract,
    contract: ContextInjectionContract,
):
    return create_context_adapter(
        adapter_contract.adapter_id,
        contract,
        adapter_contract,
    )


def _adapter_trace(
    *,
    contract: ContextInjectionContract,
    adapter_contract: ContextAdapterContract | None,
    adapter_invoked: bool,
    items_returned: int,
    skipped_reasons: list[str],
    raw_items_returned: int | None = None,
    valid_items_returned: int | None = None,
    exception_type: str | None = None,
    lookup_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_context_adapter_trace(
        source_contract_id=contract.source_contract_id,
        adapter_id=(
            adapter_contract.adapter_id
            if adapter_contract
            else None
        ),
        adapter_type=(
            adapter_contract.adapter_type
            if adapter_contract
            else None
        ),
        execution_mode=(
            adapter_contract.execution_mode
            if adapter_contract
            else None
        ),
        adapter_invoked=adapter_invoked,
        items_returned=items_returned,
        skipped_reasons=skipped_reasons,
        raw_items_returned=raw_items_returned,
        valid_items_returned=valid_items_returned,
        exception_type=exception_type,
        external_reads_allowed=(
            adapter_contract.external_reads_allowed
            if adapter_contract
            else None
        ),
        read_scope=(
            adapter_contract.read_scope
            if adapter_contract
            else None
        ),
        read_target=(
            adapter_contract.read_target
            if adapter_contract
            else None
        ),
        max_records=(
            adapter_contract.max_records
            if adapter_contract
            else None
        ),
        writes_allowed=(
            adapter_contract.writes_allowed
            if adapter_contract
            else None
        ),
        lookup_trace=lookup_trace,
    )


def _lookup_trace_for_adapter(
    *,
    adapter_contract: ContextAdapterContract,
    adapter: object,
) -> dict[str, Any] | None:
    lookup_request = adapter_contract.lookup_request

    if lookup_request is None:
        return None

    lookup_result = getattr(adapter, "last_lookup_result", None)

    return build_bounded_lookup_trace(
        request=lookup_request,
        result=lookup_result,
    )


def _raw_adapter_item_count(items: object) -> int:
    if not isinstance(items, list):
        return 0

    return len(items)


def compose_bounded_context(
    *,
    request_id: str | None,
    agent: str,
    shared_capability: str | None,
    planner_mode: str | None,
) -> ContextCompositionResult:
    if not _flag_enabled():
        return _skipped(
            request_id=request_id,
            agent=agent,
            shared_capability=shared_capability,
            skipped_reasons=["context_injection_disabled"],
        )

    if _rollback_enabled():
        return _skipped(
            request_id=request_id,
            agent=agent,
            shared_capability=shared_capability,
            skipped_reasons=["context_injection_rollback_enabled"],
        )

    try:
        matching_contracts = find_context_injection_contracts(
            agent_name=agent,
            shared_capability=shared_capability,
            operation=planner_mode,
        )
    except ContextInjectionRegistryError:
        return _skipped(
            request_id=request_id,
            agent=agent,
            shared_capability=shared_capability,
            skipped_reasons=["registry_load_failed"],
        )

    if not matching_contracts:
        return _skipped(
            request_id=request_id,
            agent=agent,
            shared_capability=shared_capability,
            skipped_reasons=["no_matching_injection_contract"],
        )

    contract = matching_contracts[0]

    if _rollback_enabled(contract.rollback_env_flag):
        return _skipped(
            request_id=request_id,
            agent=agent,
            shared_capability=shared_capability,
            skipped_reasons=["context_injection_rollback_enabled"],
            contract=contract,
        )

    if not contract.enabled:
        return _skipped(
            request_id=request_id,
            agent=agent,
            shared_capability=shared_capability,
            skipped_reasons=["injection_contract_disabled"],
            contract=contract,
        )

    if not _capability_allowed(shared_capability, contract):
        return _skipped(
            request_id=request_id,
            agent=agent,
            shared_capability=shared_capability,
            skipped_reasons=["capability_not_allowed"],
            contract=contract,
        )

    planned_trace = trace_planned_context(
        request_id=request_id or "",
        agent_name=agent,
        shared_capability=shared_capability or "",
    )
    injection_plan = build_context_injection_plan(
        planned_trace,
        policy=ContextInjectionPolicy(
            enabled=True,
            max_items=contract.max_items,
            max_tokens=contract.max_tokens,
            allowed_source_types=[contract.source_type],
            redact_sensitive=True,
            approval_sensitive=False,
        ),
    )

    selected_items = [
        item for item in injection_plan.planned_items
        if item.source == contract.source_name
        and item.source_type == contract.source_type
        and item.attributable
        and not item.injected
    ][:contract.max_items]

    if len(selected_items) != 1:
        return _skipped(
            request_id=request_id,
            agent=agent,
            shared_capability=shared_capability,
            skipped_reasons=["required_source_not_planned"],
            contract=contract,
        )

    adapter_contract = _adapter_contract_for_injection(contract)

    if adapter_contract is None or not adapter_contract.enabled:
        skipped_reasons = ["context_adapter_mapping_unavailable"]
        return _skipped(
            request_id=request_id,
            agent=agent,
            shared_capability=shared_capability,
            skipped_reasons=skipped_reasons,
            contract=contract,
            adapter_trace=_adapter_trace(
                contract=contract,
                adapter_contract=adapter_contract,
                adapter_invoked=False,
                items_returned=0,
                skipped_reasons=skipped_reasons,
            ),
        )

    if _is_declared_guest_db_readonly_adapter(adapter_contract):
        skipped_reasons = ["context_adapter_not_implemented"]
        return _skipped(
            request_id=request_id,
            agent=agent,
            shared_capability=shared_capability,
            skipped_reasons=skipped_reasons,
            contract=contract,
            adapter_trace=_adapter_trace(
                contract=contract,
                adapter_contract=adapter_contract,
                adapter_invoked=False,
                items_returned=0,
                skipped_reasons=skipped_reasons,
            ),
        )

    if (
        adapter_contract.external_reads_allowed
        and not _external_context_reads_enabled()
    ):
        skipped_reasons = ["external_context_reads_disabled"]
        return _skipped(
            request_id=request_id,
            agent=agent,
            shared_capability=shared_capability,
            skipped_reasons=skipped_reasons,
            contract=contract,
            adapter_trace=_adapter_trace(
                contract=contract,
                adapter_contract=adapter_contract,
                adapter_invoked=False,
                items_returned=0,
                skipped_reasons=skipped_reasons,
            ),
        )

    if not _is_supported_adapter(adapter_contract):
        skipped_reasons = ["context_adapter_mapping_unavailable"]
        return _skipped(
            request_id=request_id,
            agent=agent,
            shared_capability=shared_capability,
            skipped_reasons=skipped_reasons,
            contract=contract,
            adapter_trace=_adapter_trace(
                contract=contract,
                adapter_contract=adapter_contract,
                adapter_invoked=False,
                items_returned=0,
                skipped_reasons=skipped_reasons,
            ),
        )

    adapter = _adapter_for_contract(adapter_contract, contract)

    if adapter is None:
        skipped_reasons = ["context_adapter_mapping_unavailable"]
        return _skipped(
            request_id=request_id,
            agent=agent,
            shared_capability=shared_capability,
            skipped_reasons=skipped_reasons,
            contract=contract,
            adapter_trace=_adapter_trace(
                contract=contract,
                adapter_contract=adapter_contract,
                adapter_invoked=False,
                items_returned=0,
                skipped_reasons=skipped_reasons,
            ),
        )

    try:
        raw_resolved_items = adapter.retrieve(
            request_id=request_id,
            agent=agent,
            shared_capability=shared_capability,
        )
    except Exception as exc:
        skipped_reasons = ["context_adapter_exception"]
        lookup_trace = _lookup_trace_for_adapter(
            adapter_contract=adapter_contract,
            adapter=adapter,
        )
        return _skipped(
            request_id=request_id,
            agent=agent,
            shared_capability=shared_capability,
            skipped_reasons=skipped_reasons,
            contract=contract,
            adapter_trace=_adapter_trace(
                contract=contract,
                adapter_contract=adapter_contract,
                adapter_invoked=True,
                items_returned=0,
                skipped_reasons=skipped_reasons,
                raw_items_returned=0,
                valid_items_returned=0,
                exception_type=type(exc).__name__,
                lookup_trace=lookup_trace,
            ),
        )

    lookup_trace = _lookup_trace_for_adapter(
        adapter_contract=adapter_contract,
        adapter=adapter,
    )
    resolved_items = validate_adapter_output(raw_resolved_items)
    raw_items_returned = _raw_adapter_item_count(raw_resolved_items)
    adapter_trace = _adapter_trace(
        contract=contract,
        adapter_contract=adapter_contract,
        adapter_invoked=True,
        items_returned=len(resolved_items),
        skipped_reasons=[],
        raw_items_returned=raw_items_returned,
        valid_items_returned=len(resolved_items),
        lookup_trace=lookup_trace,
    )

    if len(resolved_items) != 1:
        skipped_reasons = ["context_adapter_no_item"]
        return _skipped(
            request_id=request_id,
            agent=agent,
            shared_capability=shared_capability,
            skipped_reasons=skipped_reasons,
            contract=contract,
            adapter_trace=_adapter_trace(
                contract=contract,
                adapter_contract=adapter_contract,
                adapter_invoked=True,
                items_returned=len(resolved_items),
                skipped_reasons=skipped_reasons,
                raw_items_returned=raw_items_returned,
                valid_items_returned=len(resolved_items),
                lookup_trace=lookup_trace,
            ),
        )

    resolved_item = resolved_items[0]
    item_errors = validate_resolved_context_item(resolved_item)

    if item_errors:
        return _skipped(
            request_id=request_id,
            agent=agent,
            shared_capability=shared_capability,
            skipped_reasons=[
                f"resolved_context_item:{error.field}"
                for error in item_errors
            ],
            contract=contract,
            adapter_trace=adapter_trace,
        )

    if resolved_item.estimated_tokens > contract.max_tokens:
        return _skipped(
            request_id=request_id,
            agent=agent,
            shared_capability=shared_capability,
            skipped_reasons=["token_budget_exceeded"],
            contract=contract,
            adapter_trace=adapter_trace,
        )

    accepted_items = validate_context_item_collection(
        resolved_items,
        max_items=contract.max_items,
        max_total_tokens=contract.max_tokens,
    )
    collection_summary = summarize_context_collection(
        resolved_items,
        accepted_items,
        max_items=contract.max_items,
        max_total_tokens=contract.max_tokens,
    )

    if len(accepted_items) != 1:
        return _skipped(
            request_id=request_id,
            agent=agent,
            shared_capability=shared_capability,
            skipped_reasons=["context_collection_no_items"],
            contract=contract,
            adapter_trace=adapter_trace,
        )

    accepted_item = accepted_items[0]
    prompt_text = render_context_item(accepted_item)

    if prompt_text is None:
        return _skipped(
            request_id=request_id,
            agent=agent,
            shared_capability=shared_capability,
            skipped_reasons=["context_renderer_no_output"],
            contract=contract,
            adapter_trace=adapter_trace,
        )

    rendered_block = RenderedContextBlock(
        request_id=request_id or "",
        agent_name=agent,
        shared_capability=shared_capability or "",
        rendered_text=prompt_text,
        rendered_items=[
            RenderedContextItem(
                source=contract.source_name,
                rendered_preview=prompt_text,
                truncated=False,
                attributable=True,
                token_estimate=min(
                    accepted_item.estimated_tokens,
                    selected_items[0].token_count,
                ),
                preview_only=True,
            )
        ],
        estimated_tokens=accepted_item.estimated_tokens,
        truncation_applied=False,
        preview_only=True,
        injection_performed=False,
    )

    if contract.requires_provenance_validation:
        provenance = validate_context_provenance(
            planned_trace,
            injection_plan,
            rendered_block,
        )

        if provenance.provenance_errors:
            return _skipped(
                request_id=request_id,
                agent=agent,
                shared_capability=shared_capability,
                skipped_reasons=[
                    f"provenance:{error.error_code}"
                    for error in provenance.provenance_errors
                ],
                contract=contract,
                adapter_trace=adapter_trace,
            )

    return ContextCompositionResult(
        items=[accepted_item],
        rendered_blocks=[prompt_text],
        trace_payload=_trace_payload(
            request_id=request_id,
            agent=agent,
            shared_capability=shared_capability,
            injection_performed=True,
            skipped_reasons=[],
            collection_summary=collection_summary,
            contract=contract,
            item_count=1,
            estimated_tokens=accepted_item.estimated_tokens,
            sources=[contract.source_name],
            adapter_trace=adapter_trace,
        ),
        injection_performed=True,
        skipped_reasons=[],
    )


__all__ = [
    "ContextCompositionResult",
    "compose_bounded_context",
]
