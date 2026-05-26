from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import os
from typing import Any, Protocol


@dataclass(frozen=True)
class CloudWebAIExecutionLimits:
    max_queries: int | None = None
    max_results: int | None = None
    max_cost: dict[str, Any] | None = None


@dataclass(frozen=True)
class CloudWebAIAdapterRequest:
    query_plan: dict[str, Any]
    provider_config: dict[str, Any]
    execution_limits: CloudWebAIExecutionLimits


@dataclass(frozen=True)
class CloudWebAIAdapterResult:
    raw_provider_payload: Any
    raw_results: tuple[dict[str, Any], ...]
    source_refs: tuple[dict[str, Any], ...]
    citations: tuple[dict[str, Any], ...]
    provider_metadata: dict[str, Any] = field(default_factory=dict)
    rejected_raw_results: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class CloudWebAIProviderRequest:
    provider_id: str
    provider_type: str
    model: str
    queries: tuple[str, ...]
    max_results: int
    max_cost: dict[str, Any] | None
    source_requirements: dict[str, Any]
    citation_requirements: dict[str, Any]
    query_plan_summary: dict[str, Any]


class CloudWebAIAdapter(Protocol):
    adapter_id: str
    adapter_kind: str

    def execute(
        self,
        request: CloudWebAIAdapterRequest,
    ) -> CloudWebAIAdapterResult:
        ...


class FakeCloudWebAIAdapter:
    adapter_id = "fake_cloud_web_ai"
    adapter_kind = "fake"

    def __init__(
        self,
        result: CloudWebAIAdapterResult | None = None,
    ) -> None:
        self._result = result
        self.calls: list[CloudWebAIAdapterRequest] = []

    def execute(
        self,
        request: CloudWebAIAdapterRequest,
    ) -> CloudWebAIAdapterResult:
        self.calls.append(request)
        if self._result is not None:
            return _copy_result(self._result)

        return CloudWebAIAdapterResult(
            raw_provider_payload={
                "adapter_id": self.adapter_id,
                "adapter_kind": self.adapter_kind,
                "fixture": "stage79_fake_cloud_web_ai",
                "query_plan_artifact_type": request.query_plan.get("artifact_type"),
                "provider_id": request.provider_config.get("provider_id"),
                "limits": {
                    "max_queries": request.execution_limits.max_queries,
                    "max_results": request.execution_limits.max_results,
                    "max_cost": deepcopy(request.execution_limits.max_cost),
                },
            },
            raw_results=(
                {
                    "provider_result_id": "fake-result-1",
                    "raw_title": "Fake external discovery source",
                    "raw_url": "https://example.test/fake-cloud-web-ai-source",
                    "raw_snippet": "Fixture-only source text.",
                },
            ),
            source_refs=(
                {
                    "source_ref_id": "fake-source-ref-1",
                    "provider_result_id": "fake-result-1",
                    "source_url": "https://example.test/fake-cloud-web-ai-source",
                    "source_type": "web_page",
                    "title": "Fake external discovery source",
                },
            ),
            citations=(
                {
                    "citation_id": "fake-citation-1",
                    "source_ref_id": "fake-source-ref-1",
                    "provider_result_id": "fake-result-1",
                    "source_url": "https://example.test/fake-cloud-web-ai-source",
                    "quote": "Fixture-only source text.",
                },
            ),
            provider_metadata={
                "adapter_id": self.adapter_id,
                "adapter_kind": self.adapter_kind,
                "fixture_only": True,
            },
        )


class RealCloudWebAIAdapter:
    adapter_id = "real_cloud_web_ai"
    adapter_kind = "real"

    def __init__(
        self,
        *,
        provider_invoker: Any | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._provider_invoker = provider_invoker
        self._env = env

    def prepare_provider_request(
        self,
        request: CloudWebAIAdapterRequest,
    ) -> CloudWebAIProviderRequest:
        provider_config = request.provider_config
        limits = request.execution_limits
        query_plan = request.query_plan
        max_queries = _bounded_positive_int(
            query_plan.get("max_queries"),
            limits.max_queries,
            default=1,
        )
        max_results = _bounded_positive_int(
            provider_config.get("max_results"),
            limits.max_results,
            default=1,
        )
        return CloudWebAIProviderRequest(
            provider_id=_safe_string(provider_config.get("provider_id"))
            or "cloud_web_ai",
            provider_type=_safe_string(provider_config.get("provider_type"))
            or "cloud_ai",
            model=_safe_string(provider_config.get("model")) or "unspecified",
            queries=tuple(_query_texts(query_plan)[:max_queries]),
            max_results=max_results,
            max_cost=deepcopy(limits.max_cost),
            source_requirements=deepcopy(
                provider_config.get("source_requirements")
                if isinstance(provider_config.get("source_requirements"), dict)
                else {}
            ),
            citation_requirements=deepcopy(
                provider_config.get("citation_requirements")
                if isinstance(provider_config.get("citation_requirements"), dict)
                else {}
            ),
            query_plan_summary={
                "artifact_type": query_plan.get("artifact_type"),
                "discovery_intent": _safe_string(
                    query_plan.get("discovery_intent")
                ),
                "topic_entity_focus": deepcopy(
                    query_plan.get("topic_entity_focus")
                    if isinstance(query_plan.get("topic_entity_focus"), dict)
                    else {}
                ),
                "preferred_guest_traits": _string_tuple(
                    query_plan.get("preferred_guest_traits")
                ),
                "preferred_signals": tuple(
                    signal.get("signal_id")
                    for signal in query_plan.get("preferred_signals", [])
                    if isinstance(signal, dict)
                    and _safe_string(signal.get("signal_id"))
                ),
            },
        )

    def execute(
        self,
        request: CloudWebAIAdapterRequest,
    ) -> CloudWebAIAdapterResult:
        provider_request = self.prepare_provider_request(request)
        credential_name = _safe_string(
            request.provider_config.get("credential_env_var")
        )
        if not credential_name:
            return self._closed_result(
                provider_request,
                failure_reason="missing_credential_config",
            )

        credential = _safe_string(self._env_source().get(credential_name))
        if not credential:
            return self._closed_result(
                provider_request,
                failure_reason="missing_credentials",
            )

        if self._provider_invoker is None:
            return self._closed_result(
                provider_request,
                failure_reason="provider_invoker_not_configured",
            )

        provider_payload = self._invoke_provider(
            provider_request=provider_request,
            credential=credential,
        )
        return self._result_from_provider_payload(
            provider_request=provider_request,
            provider_payload=provider_payload,
        )

    def _invoke_provider(
        self,
        *,
        provider_request: CloudWebAIProviderRequest,
        credential: str,
    ) -> Any:
        return self._provider_invoker(provider_request, credential)

    def _closed_result(
        self,
        provider_request: CloudWebAIProviderRequest,
        *,
        failure_reason: str,
    ) -> CloudWebAIAdapterResult:
        return CloudWebAIAdapterResult(
            raw_provider_payload={
                "adapter_id": self.adapter_id,
                "adapter_kind": self.adapter_kind,
                "provider_request": _provider_request_payload(provider_request),
                "failure_reason": failure_reason,
                "external_call_performed": False,
                "cost_incurred": False,
            },
            raw_results=(),
            source_refs=(),
            citations=(),
            provider_metadata={
                "adapter_id": self.adapter_id,
                "adapter_kind": self.adapter_kind,
                "provider_id": provider_request.provider_id,
                "provider_type": provider_request.provider_type,
                "provider_request_prepared": True,
                "provider_call_implemented": True,
                "external_call_performed": False,
                "cost_incurred": False,
                "failure_reason": failure_reason,
            },
        )

    def _result_from_provider_payload(
        self,
        *,
        provider_request: CloudWebAIProviderRequest,
        provider_payload: Any,
    ) -> CloudWebAIAdapterResult:
        if not isinstance(provider_payload, dict):
            return self._closed_result(
                provider_request,
                failure_reason="invalid_provider_payload",
            )

        raw_results: list[dict[str, Any]] = []
        source_refs: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        rejected_raw_results: list[dict[str, Any]] = []
        for index, item in enumerate(provider_payload.get("results", [])):
            if not isinstance(item, dict):
                rejected_raw_results.append(
                    {
                        "raw_result_index": index,
                        "rejection_reason": "provider_result_not_object",
                        "raw_item": deepcopy(item),
                    }
                )
                continue
            result_id = _safe_string(item.get("id")) or f"provider-result-{index + 1}"
            url = _safe_string(item.get("url"))
            title = _safe_string(item.get("title"))
            snippet = _safe_string(item.get("snippet"))
            if not url or not title:
                rejected_raw_results.append(
                    {
                        "raw_result_index": index,
                        "provider_result_id": result_id,
                        "rejection_reason": "provider_result_missing_source_metadata",
                        "raw_item": deepcopy(item),
                    }
                )
                continue
            source_ref_id = _safe_string(item.get("source_ref_id")) or (
                f"source-ref-{index + 1}"
            )
            item_citations: list[dict[str, Any]] = []
            for citation_index, citation in enumerate(item.get("citations", [])):
                if not isinstance(citation, dict):
                    continue
                quote = _safe_string(citation.get("quote"))
                citation_url = _safe_string(citation.get("source_url")) or url
                if not quote or not citation_url:
                    continue
                item_citations.append(
                    {
                        "citation_id": _safe_string(citation.get("citation_id"))
                        or f"citation-{index + 1}-{citation_index + 1}",
                        "source_ref_id": source_ref_id,
                        "provider_result_id": result_id,
                        "source_url": citation_url,
                        "quote": quote,
                    }
                )
            if not item_citations:
                rejected_raw_results.append(
                    {
                        "raw_result_index": index,
                        "provider_result_id": result_id,
                        "rejection_reason": "provider_result_missing_citations",
                        "raw_item": deepcopy(item),
                    }
                )
                continue
            raw_results.append(
                {
                    "provider_result_id": result_id,
                    "raw_title": title,
                    "raw_url": url,
                    "raw_snippet": snippet,
                    "raw_item": deepcopy(item),
                }
            )
            source_refs.append(
                {
                    "source_ref_id": source_ref_id,
                    "provider_result_id": result_id,
                    "source_url": url,
                    "source_type": _safe_string(item.get("source_type"))
                    or "web_page",
                    "title": title,
                }
            )
            citations.extend(item_citations)

        if not raw_results or not source_refs or not citations:
            return CloudWebAIAdapterResult(
                raw_provider_payload=deepcopy(provider_payload),
                raw_results=(),
                source_refs=(),
                citations=(),
                provider_metadata={
                    "adapter_id": self.adapter_id,
                    "adapter_kind": self.adapter_kind,
                    "provider_id": provider_request.provider_id,
                    "provider_type": provider_request.provider_type,
                    "provider_request_prepared": True,
                    "provider_call_implemented": True,
                    "external_call_performed": True,
                    "cost_incurred": bool(provider_payload.get("cost_incurred")),
                    "failure_reason": "provider_response_missing_required_sources",
                    "accepted_raw_result_count": 0,
                    "rejected_raw_result_count": len(rejected_raw_results),
                },
                rejected_raw_results=tuple(rejected_raw_results),
            )

        return CloudWebAIAdapterResult(
            raw_provider_payload=deepcopy(provider_payload),
            raw_results=tuple(raw_results),
            source_refs=tuple(source_refs),
            citations=tuple(citations),
            provider_metadata={
                "adapter_id": self.adapter_id,
                "adapter_kind": self.adapter_kind,
                "provider_id": provider_request.provider_id,
                "provider_type": provider_request.provider_type,
                "provider_request_prepared": True,
                "provider_call_implemented": True,
                "external_call_performed": True,
                "cost_incurred": bool(provider_payload.get("cost_incurred")),
                "accepted_raw_result_count": len(raw_results),
                "rejected_raw_result_count": len(rejected_raw_results),
            },
            rejected_raw_results=tuple(rejected_raw_results),
        )

    def _env_source(self) -> dict[str, str]:
        return os.environ if self._env is None else self._env


def _copy_result(result: CloudWebAIAdapterResult) -> CloudWebAIAdapterResult:
    return CloudWebAIAdapterResult(
        raw_provider_payload=deepcopy(result.raw_provider_payload),
        raw_results=tuple(deepcopy(item) for item in result.raw_results),
        source_refs=tuple(deepcopy(item) for item in result.source_refs),
        citations=tuple(deepcopy(item) for item in result.citations),
        provider_metadata=deepcopy(result.provider_metadata),
        rejected_raw_results=tuple(
            deepcopy(item) for item in result.rejected_raw_results
        ),
    )


def _provider_request_payload(
    provider_request: CloudWebAIProviderRequest,
) -> dict[str, Any]:
    return {
        "provider_id": provider_request.provider_id,
        "provider_type": provider_request.provider_type,
        "model": provider_request.model,
        "queries": list(provider_request.queries),
        "max_results": provider_request.max_results,
        "max_cost": deepcopy(provider_request.max_cost),
        "source_requirements": deepcopy(provider_request.source_requirements),
        "citation_requirements": deepcopy(provider_request.citation_requirements),
        "query_plan_summary": deepcopy(provider_request.query_plan_summary),
    }


def _query_texts(query_plan: dict[str, Any]) -> list[str]:
    focus = query_plan.get("topic_entity_focus")
    if not isinstance(focus, dict):
        focus = {}
    subjects = _string_tuple(focus.get("topics")) + _string_tuple(
        focus.get("entities")
    )
    traits = _string_tuple(query_plan.get("preferred_guest_traits"))
    intent = _safe_string(query_plan.get("discovery_intent"))
    base_parts = [part for part in (intent, ", ".join(subjects)) if part]
    trait_text = ", ".join(traits)
    query = " | ".join(base_parts)
    if trait_text:
        query = f"{query} | traits: {trait_text}" if query else trait_text
    return [query] if query else ["external discovery"]


def _bounded_positive_int(
    requested: Any,
    limit: int | None,
    *,
    default: int,
) -> int:
    value = requested if isinstance(requested, int) and not isinstance(requested, bool) else default
    if value < 1:
        value = default
    if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0:
        return min(value, limit)
    return value


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    )


def _safe_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "CloudWebAIAdapter",
    "CloudWebAIAdapterRequest",
    "CloudWebAIAdapterResult",
    "CloudWebAIExecutionLimits",
    "CloudWebAIProviderRequest",
    "FakeCloudWebAIAdapter",
    "RealCloudWebAIAdapter",
]
