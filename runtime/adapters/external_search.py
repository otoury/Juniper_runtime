from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from runtime.artifacts.external_search import (
    build_external_search_result_set,
    validate_external_search_result_set,
)
from runtime.registries.external_search_registry import (
    ExternalSearchContract,
    ExternalSearchValidationError,
    get_external_search_contract,
    validate_external_search_request,
)
from runtime.policies.external_search_provider_authorization import (
    ExternalSearchProviderAuthorizationInput,
    evaluate_external_search_provider_authorization,
)


EXTERNAL_SEARCH_CLOSED_ADAPTER_ID = "runtime_external_search_closed_adapter"


@dataclass(frozen=True)
class ExternalSearchAdapterRequest:
    search_id: str
    query: str
    semantic_type: str = "external_search"
    max_results: int | None = None
    search_intent: str | None = None
    freshness_policy: dict[str, Any] | None = None
    source_policy: dict[str, Any] | None = None
    result_bounds: dict[str, Any] | None = None
    raw_request: dict[str, Any] = field(default_factory=dict)

    def to_contract_request(self) -> dict[str, Any]:
        request = {
            "semantic_type": self.semantic_type,
            "search_id": self.search_id,
            "query": self.query,
        }
        if self.max_results is not None:
            request["max_results"] = self.max_results
        if self.search_intent is not None:
            request["search_intent"] = self.search_intent
        if self.freshness_policy is not None:
            request["freshness_policy"] = deepcopy(self.freshness_policy)
        if self.source_policy is not None:
            request["source_policy"] = deepcopy(self.source_policy)
        if self.result_bounds is not None:
            request["result_bounds"] = deepcopy(self.result_bounds)
        for key, value in self.raw_request.items():
            request.setdefault(key, deepcopy(value))
        return request


@dataclass(frozen=True)
class ExternalSearchAdapterResult:
    adapter_id: str
    adapter_kind: str
    artifact: dict[str, Any] | None
    request_errors: tuple[ExternalSearchValidationError, ...] = ()
    artifact_errors: tuple[Any, ...] = ()
    blocked_reason: str | None = None

    @property
    def ok(self) -> bool:
        return (
            self.artifact is not None
            and not self.request_errors
            and not self.artifact_errors
            and self.blocked_reason is None
        )


class ExternalSearchAdapter(Protocol):
    adapter_id: str
    adapter_kind: str
    semantic_type: str
    execution_allowed: bool

    def execute(
        self,
        request: ExternalSearchAdapterRequest,
        *,
        root: str | Path | None = None,
    ) -> ExternalSearchAdapterResult:
        ...


class ClosedExternalSearchAdapter:
    adapter_id = EXTERNAL_SEARCH_CLOSED_ADAPTER_ID
    adapter_kind = "closed_contract_boundary"
    semantic_type = "external_search"
    execution_allowed = False

    def execute(
        self,
        request: ExternalSearchAdapterRequest,
        *,
        root: str | Path | None = None,
    ) -> ExternalSearchAdapterResult:
        contract_request = request.to_contract_request()
        request_errors = tuple(
            validate_external_search_request(contract_request, root=root)
        )
        contract = get_external_search_contract(request.semantic_type, root=root)
        if request_errors or contract is None:
            return ExternalSearchAdapterResult(
                adapter_id=self.adapter_id,
                adapter_kind=self.adapter_kind,
                artifact=None,
                request_errors=request_errors,
                blocked_reason="invalid_external_search_request",
            )

        artifact = build_external_search_result_set(
            search_id=request.search_id,
            query=request.query,
            provenance=_closed_provenance(
                adapter_id=self.adapter_id,
                contract=contract,
                request=request,
                root=root,
            ),
        )
        artifact_errors = validate_external_search_result_set(artifact)
        return ExternalSearchAdapterResult(
            adapter_id=self.adapter_id,
            adapter_kind=self.adapter_kind,
            artifact=artifact,
            artifact_errors=artifact_errors,
            blocked_reason=None if not artifact_errors else "invalid_result_artifact",
        )


class ExternalSearchAdapterRegistry:
    def __init__(self, adapters: list[ExternalSearchAdapter] | None = None) -> None:
        self._adapters: dict[str, ExternalSearchAdapter] = {}
        for adapter in adapters or []:
            self.register(adapter)

    def register(self, adapter: ExternalSearchAdapter) -> None:
        adapter_id = _safe_string(getattr(adapter, "adapter_id", None))
        semantic_type = _safe_string(getattr(adapter, "semantic_type", None))
        if not adapter_id:
            raise ValueError("external search adapters must declare adapter_id.")
        if semantic_type != "external_search":
            raise ValueError("external search adapters must use semantic_type external_search.")
        if getattr(adapter, "execution_allowed", None) is not False:
            raise ValueError("external search adapters must be non-executing at this stage.")
        if adapter_id in self._adapters:
            raise ValueError(f"duplicate external search adapter: {adapter_id}")
        self._adapters[adapter_id] = adapter

    def get(self, adapter_id: str) -> ExternalSearchAdapter | None:
        return self._adapters.get(str(adapter_id or "").strip())

    def default(self) -> ExternalSearchAdapter:
        return self._adapters[EXTERNAL_SEARCH_CLOSED_ADAPTER_ID]

    def adapter_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))


def default_external_search_adapter_registry() -> ExternalSearchAdapterRegistry:
    return ExternalSearchAdapterRegistry([ClosedExternalSearchAdapter()])


def build_external_search_adapter_request(
    request: dict[str, Any],
) -> ExternalSearchAdapterRequest:
    raw_request = deepcopy(request) if isinstance(request, dict) else {}
    return ExternalSearchAdapterRequest(
        search_id=_safe_string(raw_request.get("search_id")) or "external-search-request",
        semantic_type=_safe_string(raw_request.get("semantic_type"))
        or _safe_string(raw_request.get("operation_id"))
        or "external_search",
        query=_safe_string(raw_request.get("query")) or "",
        max_results=raw_request.get("max_results")
        if isinstance(raw_request.get("max_results"), int)
        and not isinstance(raw_request.get("max_results"), bool)
        else None,
        search_intent=_safe_string(raw_request.get("search_intent")),
        freshness_policy=_optional_object(raw_request.get("freshness_policy")),
        source_policy=_optional_object(raw_request.get("source_policy")),
        result_bounds=_optional_object(raw_request.get("result_bounds")),
        raw_request=raw_request,
    )


def _closed_provenance(
    *,
    adapter_id: str,
    contract: ExternalSearchContract,
    request: ExternalSearchAdapterRequest,
    root: str | Path | None = None,
) -> dict[str, Any]:
    requested_max_results = request.max_results
    if requested_max_results is None and isinstance(request.result_bounds, dict):
        bounded = request.result_bounds.get("max_results")
        requested_max_results = bounded if isinstance(bounded, int) else None
    provider_authorization = evaluate_external_search_provider_authorization(
        ExternalSearchProviderAuthorizationInput(provider_id=None),
        root=root,
    )

    return {
        "adapter_id": adapter_id,
        "operation_id": contract.operation_id,
        "semantic_type": contract.semantic_type,
        "requested_max_results": requested_max_results,
        "result_count": 0,
        "source_ref_count": 0,
        "governance_state": "closed_contract_boundary",
        "blocked_reason": "provider_integration_not_implemented",
        "provider_authorization": provider_authorization.to_audit_record(),
    }


def _optional_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return deepcopy(value)
    return None


def _safe_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "EXTERNAL_SEARCH_CLOSED_ADAPTER_ID",
    "ClosedExternalSearchAdapter",
    "ExternalSearchAdapter",
    "ExternalSearchAdapterRegistry",
    "ExternalSearchAdapterRequest",
    "ExternalSearchAdapterResult",
    "build_external_search_adapter_request",
    "default_external_search_adapter_registry",
]
