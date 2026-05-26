from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import os
from typing import Any, Protocol

from runtime.governance.operational_controls import evaluate_tavily_execution_control


@dataclass(frozen=True)
class SearchAPIAdapterRequest:
    query: str
    max_results: int
    provider_config: dict[str, Any]
    freshness_policy: dict[str, Any] | None = None
    source_policy: dict[str, Any] | None = None


@dataclass(frozen=True)
class SearchAPIProviderRequest:
    provider_id: str
    provider_type: str
    provider_name: str
    query: str
    max_results: int
    freshness_policy: dict[str, Any]
    source_policy: dict[str, Any]
    provider_options: dict[str, Any]


@dataclass(frozen=True)
class SearchAPIAdapterResult:
    raw_provider_payload: Any
    raw_results: tuple[dict[str, Any], ...]
    source_refs: tuple[dict[str, Any], ...] = ()
    citations: tuple[dict[str, Any], ...] = ()
    provider_metadata: dict[str, Any] = field(default_factory=dict)
    rejected_raw_results: tuple[dict[str, Any], ...] = ()


class SearchAPIAdapter(Protocol):
    adapter_id: str
    adapter_kind: str

    def execute(
        self,
        request: SearchAPIAdapterRequest,
    ) -> SearchAPIAdapterResult:
        ...


class TavilySearchAPIAdapter:
    adapter_id = "tavily_search_api"
    adapter_kind = "real_skeleton"

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
        request: SearchAPIAdapterRequest,
    ) -> SearchAPIProviderRequest:
        provider_config = request.provider_config
        return SearchAPIProviderRequest(
            provider_id=_safe_string(provider_config.get("provider_id"))
            or "search_api",
            provider_type=_safe_string(provider_config.get("provider_type"))
            or "search_api",
            provider_name=_safe_string(provider_config.get("provider_name"))
            or "tavily",
            query=_safe_string(request.query) or "",
            max_results=_bounded_positive_int(
                request.max_results,
                provider_config.get("max_results"),
                default=5,
            ),
            freshness_policy=deepcopy(request.freshness_policy or {}),
            source_policy=deepcopy(request.source_policy or {}),
            provider_options=deepcopy(
                provider_config.get("provider_options")
                if isinstance(provider_config.get("provider_options"), dict)
                else {}
            ),
        )

    def execute(
        self,
        request: SearchAPIAdapterRequest,
    ) -> SearchAPIAdapterResult:
        provider_request = self.prepare_provider_request(request)
        if _config_bool(request.provider_config.get("dry_run"), default=True):
            return self._closed_result(
                provider_request,
                failure_reason="dry_run_no_live_call",
                dry_run=True,
            )

        if request.provider_config.get("allow_live_call") is not True:
            return self._closed_result(
                provider_request,
                failure_reason="live_call_not_allowed",
            )

        runtime_governance = evaluate_tavily_execution_control(
            root=request.provider_config.get("governance_root"),
            environ=self._env_source(),
        )
        if not runtime_governance.allowed:
            return self._closed_result(
                provider_request,
                failure_reason="runtime_governance_blocked",
                runtime_governance=runtime_governance.to_diagnostics(),
            )

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
        provider_request: SearchAPIProviderRequest,
        credential: str,
    ) -> Any:
        return self._provider_invoker(provider_request, credential)

    def _closed_result(
        self,
        provider_request: SearchAPIProviderRequest,
        *,
        failure_reason: str,
        dry_run: bool = False,
        runtime_governance: dict[str, Any] | None = None,
    ) -> SearchAPIAdapterResult:
        return SearchAPIAdapterResult(
            raw_provider_payload={
                "adapter_id": self.adapter_id,
                "adapter_kind": self.adapter_kind,
                "provider_request": _provider_request_payload(provider_request),
                "failure_reason": failure_reason,
                "dry_run": dry_run,
                "external_call_performed": False,
                "cost_incurred": False,
                "runtime_governance": deepcopy(runtime_governance),
            },
            raw_results=(),
            provider_metadata={
                "adapter_id": self.adapter_id,
                "adapter_kind": self.adapter_kind,
                "provider_id": provider_request.provider_id,
                "provider_type": provider_request.provider_type,
                "provider_name": provider_request.provider_name,
                "provider_request_prepared": True,
                "provider_call_implemented": True,
                "dry_run": dry_run,
                "external_call_performed": False,
                "cost_incurred": False,
                "failure_reason": failure_reason,
                "runtime_governance": deepcopy(runtime_governance),
            },
        )

    def _result_from_provider_payload(
        self,
        *,
        provider_request: SearchAPIProviderRequest,
        provider_payload: Any,
    ) -> SearchAPIAdapterResult:
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

            result_id = _safe_string(item.get("id")) or f"tavily-result-{index + 1}"
            title = _safe_string(item.get("title"))
            url = _safe_string(item.get("url"))
            snippet = _safe_string(item.get("snippet")) or _safe_string(
                item.get("content")
            )
            if not title or not url:
                rejected_raw_results.append(
                    {
                        "raw_result_index": index,
                        "provider_result_id": result_id,
                        "rejection_reason": "provider_result_missing_source_metadata",
                        "raw_item": deepcopy(item),
                    }
                )
                continue

            source_metadata = {
                "source_type": _safe_string(item.get("source_type")) or "web_page",
                "published_date": _safe_string(item.get("published_date")),
                "score": item.get("score"),
            }
            source_ref_id = f"{provider_request.provider_id}:{result_id}"
            raw_results.append(
                {
                    "provider_result_id": result_id,
                    "source_ref_id": source_ref_id,
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "source_metadata": source_metadata,
                    "provider_metadata": {
                        "provider_id": provider_request.provider_id,
                        "provider_type": provider_request.provider_type,
                        "provider_name": provider_request.provider_name,
                    },
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
                    "source_type": source_metadata["source_type"],
                    "title": title,
                    "published_date": source_metadata["published_date"],
                }
            )
            citations.append(
                {
                    "citation_id": f"citation:{source_ref_id}",
                    "source_ref_id": source_ref_id,
                    "provider_result_id": result_id,
                    "source_url": url,
                    "title": title,
                }
            )

        if not raw_results:
            return SearchAPIAdapterResult(
                raw_provider_payload=deepcopy(provider_payload),
                raw_results=(),
                provider_metadata={
                    "adapter_id": self.adapter_id,
                    "adapter_kind": self.adapter_kind,
                    "provider_id": provider_request.provider_id,
                    "provider_type": provider_request.provider_type,
                    "provider_name": provider_request.provider_name,
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

        return SearchAPIAdapterResult(
            raw_provider_payload=deepcopy(provider_payload),
            raw_results=tuple(raw_results),
            source_refs=tuple(source_refs),
            citations=tuple(citations),
            provider_metadata={
                "adapter_id": self.adapter_id,
                "adapter_kind": self.adapter_kind,
                "provider_id": provider_request.provider_id,
                "provider_type": provider_request.provider_type,
                "provider_name": provider_request.provider_name,
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


def _provider_request_payload(
    provider_request: SearchAPIProviderRequest,
) -> dict[str, Any]:
    return {
        "provider_id": provider_request.provider_id,
        "provider_type": provider_request.provider_type,
        "provider_name": provider_request.provider_name,
        "query": provider_request.query,
        "max_results": provider_request.max_results,
        "freshness_policy": deepcopy(provider_request.freshness_policy),
        "source_policy": deepcopy(provider_request.source_policy),
        "provider_options": deepcopy(provider_request.provider_options),
    }


def _bounded_positive_int(
    requested: Any,
    limit: Any,
    *,
    default: int,
) -> int:
    value = requested if isinstance(requested, int) and not isinstance(requested, bool) else default
    if value < 1:
        value = default
    if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0:
        return min(value, limit)
    return value


def _config_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _safe_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "SearchAPIAdapter",
    "SearchAPIAdapterRequest",
    "SearchAPIAdapterResult",
    "SearchAPIProviderRequest",
    "TavilySearchAPIAdapter",
]
