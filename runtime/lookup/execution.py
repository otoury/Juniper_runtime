from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import queue
import signal
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from runtime.lookup.execution_policy import LookupExecutionPolicy
from runtime.registries.exact_entity_lookup_registry import (
    validate_exact_entity_lookup_request,
)
from runtime.registries.bounded_entity_search_registry import (
    validate_bounded_entity_search_request,
)
from runtime.registries.lookup_capability_registry import (
    ResolvedLookupCapability,
)
from runtime.lookup.governance import governance_block_reason
from runtime.lookup.lifecycle import normalize_lookup_status
from runtime.lookup.lineage import lineage_from_lookup_request


LookupExecutor = Callable[[dict[str, Any]], Any]


class LookupExecutionCancelled(Exception):
    pass


class LookupExecutionTimeout(Exception):
    pass


@dataclass(frozen=True)
class LookupExecutionResult:
    request: dict[str, Any]
    payloads: list[dict[str, Any]]
    retrieval_executed: bool
    skipped_reasons: tuple[str, ...]
    trace: dict[str, Any]


def execute_lookup_requests(
    *,
    agent: Any,
    lookup_requests: Iterable[dict[str, Any]],
    lookup_capability: ResolvedLookupCapability | None = None,
    require_lookup_capability: bool = False,
) -> list[LookupExecutionResult]:
    requests = list(lookup_requests)
    max_workers = _max_concurrent_lookups(lookup_capability)
    if len(requests) <= 1 or max_workers <= 1:
        return [
            execute_lookup_request(
                agent=agent,
                lookup_request=request,
                lookup_capability=lookup_capability,
                require_lookup_capability=require_lookup_capability,
            )
            for request in requests
        ]

    results: list[LookupExecutionResult | None] = [None] * len(requests)
    with ThreadPoolExecutor(max_workers=min(max_workers, len(requests))) as pool:
        future_by_index = {
            pool.submit(
                execute_lookup_request,
                agent=agent,
                lookup_request=request,
                lookup_capability=lookup_capability,
                require_lookup_capability=require_lookup_capability,
            ): index
            for index, request in enumerate(requests)
        }
        for future, index in future_by_index.items():
            try:
                results[index] = future.result()
            except Exception:
                results[index] = _closed(
                    request=requests[index],
                    retrieval_executed=False,
                    skipped_reasons=("lookup_executor_exception",),
                    execution_policy=(
                        lookup_capability.execution_policy
                        if lookup_capability is not None
                        else None
                    ),
                )

    return [result for result in results if result is not None]


def _max_concurrent_lookups(
    lookup_capability: ResolvedLookupCapability | None,
) -> int:
    if lookup_capability is None:
        return 1

    return lookup_capability.execution_policy.max_concurrent_lookups


def execute_lookup_request(
    *,
    agent: Any,
    lookup_request: dict[str, Any],
    lookup_capability: ResolvedLookupCapability | None = None,
    require_lookup_capability: bool = False,
) -> LookupExecutionResult:
    if isinstance(lookup_request, dict):
        lookup_type = lookup_request.get("lookup_type")
    else:
        lookup_type = None

    if lookup_type == "bounded_entity_search":
        validation_errors = validate_bounded_entity_search_request(
            lookup_request,
            allow_policy_fields=True,
        )
        invalid_reason = "invalid_bounded_entity_search_request"
    else:
        validation_errors = validate_exact_entity_lookup_request(
            lookup_request
        )
        invalid_reason = "invalid_exact_entity_lookup_request"

    if validation_errors:
        return _closed(
            request=lookup_request,
            retrieval_executed=False,
            skipped_reasons=(invalid_reason,),
        )

    if require_lookup_capability and lookup_capability is None:
        return _closed(
            request=lookup_request,
            retrieval_executed=False,
            skipped_reasons=("lookup_capability_resolution_failed",),
        )

    if (
        lookup_capability is not None
        and not lookup_capability.governance.execution_allowed
    ):
        return _closed(
            request=lookup_request,
            retrieval_executed=False,
            skipped_reasons=(
                governance_block_reason(lookup_capability.governance.state),
            ),
            governance_state=lookup_capability.governance.state,
        )

    capability_errors = _capability_mismatch_reasons(
        lookup_request=lookup_request,
        lookup_capability=lookup_capability,
    )
    if capability_errors:
        return _closed(
            request=lookup_request,
            retrieval_executed=False,
            skipped_reasons=capability_errors,
        )

    executor = _resolve_executor(
        agent=agent,
        lookup_request=lookup_request,
        lookup_capability=lookup_capability,
    )
    if executor is None:
        skipped_reason = (
            "bounded_entity_search_not_implemented"
            if lookup_type == "bounded_entity_search"
            else "lookup_executor_unavailable"
        )
        return _closed(
            request=lookup_request,
            retrieval_executed=False,
            skipped_reasons=(skipped_reason,),
        )

    execution_policy = (
        lookup_capability.execution_policy
        if lookup_capability is not None
        else None
    )
    try:
        raw_result = _execute_with_timeout(
            executor=executor,
            lookup_request=lookup_request,
            execution_policy=execution_policy,
        )
    except LookupExecutionTimeout:
        return _closed(
            request=lookup_request,
            retrieval_executed=False,
            skipped_reasons=("lookup_execution_timeout",),
            governance_state=(
                lookup_capability.governance.state
                if lookup_capability is not None
                else None
            ),
            execution_policy=execution_policy,
        )
    except LookupExecutionCancelled:
        return _closed(
            request=lookup_request,
            retrieval_executed=False,
            skipped_reasons=("lookup_execution_cancelled",),
            governance_state=(
                lookup_capability.governance.state
                if lookup_capability is not None
                else None
            ),
            execution_policy=execution_policy,
        )
    except Exception:
        return _closed(
            request=lookup_request,
            retrieval_executed=False,
            skipped_reasons=("lookup_executor_exception",),
            execution_policy=execution_policy,
        )

    return _from_executor_result(
        request=lookup_request,
        raw_result=raw_result,
        governance_state=(
            lookup_capability.governance.state
            if lookup_capability is not None
            else None
        ),
        execution_policy=execution_policy,
    )


def _execute_with_timeout(
    *,
    executor: LookupExecutor,
    lookup_request: dict[str, Any],
    execution_policy: LookupExecutionPolicy | None,
) -> Any:
    if execution_policy is None:
        return executor(lookup_request)

    timeout_seconds = execution_policy.timeout_ms / 1000
    if threading.current_thread() is threading.main_thread() and hasattr(
        signal,
        "setitimer",
    ):
        return _execute_with_signal_timeout(
            executor=executor,
            lookup_request=lookup_request,
            timeout_seconds=timeout_seconds,
        )

    return _execute_with_thread_timeout(
        executor=executor,
        lookup_request=lookup_request,
        timeout_seconds=timeout_seconds,
    )


def _execute_with_signal_timeout(
    *,
    executor: LookupExecutor,
    lookup_request: dict[str, Any],
    timeout_seconds: float,
) -> Any:
    def _timeout_handler(_signum, _frame):
        raise LookupExecutionTimeout()

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _timeout_handler)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        return executor(lookup_request)
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)


def _execute_with_thread_timeout(
    *,
    executor: LookupExecutor,
    lookup_request: dict[str, Any],
    timeout_seconds: float,
) -> Any:
    result_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

    def _target() -> None:
        try:
            result_queue.put(("ok", executor(lookup_request)))
        except BaseException as exc:
            result_queue.put(("error", exc))

    worker = threading.Thread(target=_target, daemon=True)
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        raise LookupExecutionTimeout()

    try:
        status, value = result_queue.get_nowait()
    except queue.Empty:
        raise LookupExecutionCancelled()

    if status == "error":
        raise value

    return value


def _resolve_executor(
    *,
    agent: Any,
    lookup_request: dict[str, Any],
    lookup_capability: ResolvedLookupCapability | None,
) -> LookupExecutor | None:
    resolver = getattr(agent, "get_lookup_executor", None)
    if not callable(resolver):
        return None

    metadata = (
        lookup_capability.registration.to_metadata()
        if lookup_capability is not None
        else None
    )

    try:
        executor = resolver(lookup_request, metadata)
    except TypeError:
        executor = resolver(lookup_request)

    if callable(executor):
        return executor

    return None


def _capability_mismatch_reasons(
    *,
    lookup_request: dict[str, Any],
    lookup_capability: ResolvedLookupCapability | None,
) -> tuple[str, ...]:
    if lookup_capability is None:
        return ()

    registration = lookup_capability.registration
    reasons: list[str] = []
    if lookup_request.get("lookup_type") not in (
        registration.supported_lookup_types
    ):
        reasons.append("lookup_type_not_supported_by_capability")

    if lookup_request.get("source_scope") not in registration.source_scopes:
        reasons.append("source_scope_not_supported_by_capability")

    return tuple(reasons)


def _from_executor_result(
    *,
    request: dict[str, Any],
    raw_result: Any,
    governance_state: str | None = None,
    execution_policy: LookupExecutionPolicy | None = None,
) -> LookupExecutionResult:
    retrieval_executed = _bool_attr(raw_result, "retrieval_executed")
    skipped_reasons = _string_tuple_attr(raw_result, "skipped_reasons")
    ok = getattr(raw_result, "ok", False) is True
    payload = getattr(raw_result, "payload", None)
    payloads_attr = getattr(raw_result, "payloads", None)

    if ok and isinstance(payloads_attr, list):
        payloads = [
            dict(item) for item in payloads_attr if isinstance(item, dict)
        ]
    else:
        payloads = [dict(payload)] if ok and isinstance(payload, dict) else []
    if ok and not payloads:
        skipped_reasons = ("malformed_lookup_payload",)

    return LookupExecutionResult(
        request=dict(request),
        payloads=payloads,
        retrieval_executed=retrieval_executed,
        skipped_reasons=skipped_reasons,
        trace=_safe_trace(
            request=request,
            retrieval_executed=retrieval_executed,
            records_returned=len(payloads),
            skipped_reasons=skipped_reasons,
            governance_state=governance_state,
            execution_policy=execution_policy,
        ),
    )


def _bool_attr(value: Any, name: str) -> bool:
    attr = getattr(value, name, False)
    return attr if isinstance(attr, bool) else False


def _string_tuple_attr(value: Any, name: str) -> tuple[str, ...]:
    attr = getattr(value, name, ())
    if not isinstance(attr, (list, tuple)):
        return ()

    return tuple(item for item in attr if isinstance(item, str))


def _closed(
    *,
    request: dict[str, Any],
    retrieval_executed: bool,
    skipped_reasons: tuple[str, ...],
    governance_state: str | None = None,
    execution_policy: LookupExecutionPolicy | None = None,
) -> LookupExecutionResult:
    return LookupExecutionResult(
        request=dict(request) if isinstance(request, dict) else {},
        payloads=[],
        retrieval_executed=retrieval_executed,
        skipped_reasons=skipped_reasons,
        trace=_safe_trace(
            request=request if isinstance(request, dict) else {},
            retrieval_executed=retrieval_executed,
            records_returned=0,
            skipped_reasons=skipped_reasons,
            governance_state=governance_state,
            execution_policy=execution_policy,
        ),
    )


def _safe_trace(
    *,
    request: dict[str, Any],
    retrieval_executed: bool,
    records_returned: int,
    skipped_reasons: tuple[str, ...],
    governance_state: str | None = None,
    execution_policy: LookupExecutionPolicy | None = None,
) -> dict[str, Any]:
    lookup_status = normalize_lookup_status(
        retrieval_executed=retrieval_executed,
        records_returned=records_returned,
        skipped_reasons=skipped_reasons,
    )
    return {
        "lookup_id": request.get("lookup_id"),
        **lineage_from_lookup_request(request),
        "lookup_type": request.get("lookup_type"),
        "entity_type": request.get("entity_type"),
        "workflow_topic": request.get("workflow_topic"),
        "source_scope": request.get("source_scope"),
        "lookup_status": lookup_status,
        "governance_state": governance_state,
        "timeout_ms": (
            execution_policy.timeout_ms
            if execution_policy is not None
            else None
        ),
        "cancellation_behavior": (
            execution_policy.cancellation_behavior
            if execution_policy is not None
            else None
        ),
        "max_concurrent_lookups": (
            execution_policy.max_concurrent_lookups
            if execution_policy is not None
            else None
        ),
        "retrieval_executed": retrieval_executed,
        "records_returned": records_returned,
        "skipped_reasons": list(skipped_reasons),
    }


def lookup_execution_result_to_metadata(
    result: LookupExecutionResult,
) -> dict[str, Any]:
    lookup_status = normalize_lookup_status(
        retrieval_executed=result.retrieval_executed,
        records_returned=len(result.payloads),
        skipped_reasons=result.skipped_reasons,
    )
    return {
        "lookup_id": result.request.get("lookup_id"),
        **lineage_from_lookup_request(result.request),
        "lookup_type": result.request.get("lookup_type"),
        "entity_type": result.request.get("entity_type"),
        "workflow_topic": result.request.get("workflow_topic"),
        "source_scope": result.request.get("source_scope"),
        "lookup_status": lookup_status,
        "governance_state": result.trace.get("governance_state"),
        "timeout_ms": result.trace.get("timeout_ms"),
        "cancellation_behavior": result.trace.get("cancellation_behavior"),
        "max_concurrent_lookups": result.trace.get("max_concurrent_lookups"),
        "retrieval_executed": result.retrieval_executed,
        "records_returned": len(result.payloads),
        "skipped_reasons": list(result.skipped_reasons),
        "payloads": [dict(payload) for payload in result.payloads],
    }

__all__ = [
    "LookupExecutionResult",
    "LookupExecutionCancelled",
    "LookupExecutionTimeout",
    "LookupExecutor",
    "execute_lookup_request",
    "execute_lookup_requests",
    "lookup_execution_result_to_metadata",
]
