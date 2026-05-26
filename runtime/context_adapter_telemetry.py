from __future__ import annotations


def build_context_adapter_trace(
    *,
    source_contract_id: str | None,
    adapter_id: str | None,
    adapter_type: str | None,
    execution_mode: str | None,
    adapter_invoked: bool,
    items_returned: int,
    skipped_reasons: list[str],
    raw_items_returned: int | None = None,
    valid_items_returned: int | None = None,
    exception_type: str | None = None,
    external_reads_allowed: bool | None = None,
    read_scope: str | None = None,
    read_target: str | None = None,
    max_records: int | None = None,
    writes_allowed: bool | None = None,
    lookup_trace: dict | None = None,
) -> dict:
    normalized_items_returned = max(0, int(items_returned))

    trace = {
        "source_contract_id": source_contract_id,
        "adapter_id": adapter_id,
        "adapter_type": adapter_type,
        "execution_mode": execution_mode,
        "adapter_invoked": bool(adapter_invoked),
        "items_returned": normalized_items_returned,
        "raw_items_returned": (
            normalized_items_returned
            if raw_items_returned is None
            else max(0, int(raw_items_returned))
        ),
        "valid_items_returned": (
            normalized_items_returned
            if valid_items_returned is None
            else max(0, int(valid_items_returned))
        ),
        "skipped_reasons": list(skipped_reasons),
        "exception_type": exception_type,
        "external_reads_allowed": external_reads_allowed,
        "read_scope": read_scope,
        "read_target": read_target,
        "max_records": max_records,
        "writes_allowed": writes_allowed,
    }

    if lookup_trace is not None:
        trace["lookup_trace"] = dict(lookup_trace)

    return trace


__all__ = ["build_context_adapter_trace"]
