from __future__ import annotations

import json
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Protocol

from runtime.artifacts.external_search_execution_receipt import (
    build_external_search_execution_receipt,
)
from runtime.execution_classes import (
    EXECUTION_CLASS_PAID_EXTERNAL_PROVIDER,
    dry_run_requested,
    evaluate_execution_class_dry_run,
)
from runtime.artifacts.external_retrieval_lineage import (
    build_normalized_external_retrieval_result_lineage,
)
from runtime.adapters.external_search import (
    ExternalSearchAdapterRequest,
    build_external_search_adapter_request,
)
from runtime.policies.external_search_provider_authorization import (
    ExternalSearchProviderAuthorizationDecision,
    ExternalSearchProviderAuthorizationInput,
    evaluate_external_search_provider_authorization,
    validate_external_search_live_provider_execution_authorization,
)
from runtime.registries.external_search_registry import (
    ExternalSearchValidationError,
    get_external_search_contract,
    validate_external_search_request,
)


EXTERNAL_SEARCH_PROVIDER_EXECUTION_POLICY_PATH = Path(
    "agents/shared/policies/external_search_provider_execution.json"
)
EXECUTION_MODE_DISABLED = "disabled"
EXECUTION_MODE_AUDIT_ONLY = "audit_only"
EXECUTION_MODE_ALLOWED = "allowed"
ALLOWED_EXECUTION_MODES = frozenset(
    {EXECUTION_MODE_DISABLED, EXECUTION_MODE_AUDIT_ONLY, EXECUTION_MODE_ALLOWED}
)
FORBIDDEN_CONFIG_FIELDS = {
    "api_key",
    "credential",
    "credential_env_var",
    "fallback_provider_id",
    "ranking",
    "summarizer",
}
PROVIDER_EXECUTION_DISABLED_STATUS = "provider_execution_disabled"
PROVIDER_EXECUTION_COMPLETED_STATUS = "provider_execution_completed"
PROVIDER_EXECUTION_FAILED_STATUS = "provider_execution_failed"


class ExternalSearchProviderExecutionPolicyError(RuntimeError):
    pass


class ExternalSearchProviderNormalizationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExternalSearchProviderExecutionConfig:
    provider_id: str
    provider_type: str
    resource_id: str
    execution_mode: str
    enabled: bool
    live_provider_execution_allowed: bool
    max_results: int
    timeout_ms: int
    cost_allowed: bool
    implementation_status: str

    @classmethod
    def from_mapping(cls, value: Any) -> "ExternalSearchProviderExecutionConfig":
        if not isinstance(value, dict):
            raise ExternalSearchProviderExecutionPolicyError(
                "provider execution config must be an object"
            )
        forbidden = _forbidden_field_paths(value)
        if forbidden:
            raise ExternalSearchProviderExecutionPolicyError(
                "provider execution config contains forbidden fields"
            )
        execution_mode = _required_string(value.get("execution_mode"))
        if execution_mode not in ALLOWED_EXECUTION_MODES:
            raise ExternalSearchProviderExecutionPolicyError("invalid execution mode")
        max_results = value.get("max_results")
        timeout_ms = value.get("timeout_ms")
        if (
            not isinstance(max_results, int)
            or isinstance(max_results, bool)
            or max_results < 1
            or max_results > 10
        ):
            raise ExternalSearchProviderExecutionPolicyError("invalid max_results")
        if (
            not isinstance(timeout_ms, int)
            or isinstance(timeout_ms, bool)
            or timeout_ms < 0
        ):
            raise ExternalSearchProviderExecutionPolicyError("invalid timeout_ms")
        return cls(
            provider_id=_required_string(value.get("provider_id")),
            provider_type=_required_string(value.get("provider_type")),
            resource_id=_required_string(value.get("resource_id")),
            execution_mode=execution_mode,
            enabled=_required_bool(value.get("enabled")),
            live_provider_execution_allowed=_required_bool(
                value.get("live_provider_execution_allowed")
            ),
            max_results=max_results,
            timeout_ms=timeout_ms,
            cost_allowed=_required_bool(value.get("cost_allowed")),
            implementation_status=_required_string(value.get("implementation_status")),
        )


@dataclass(frozen=True)
class NormalizedExternalSearchProviderRequest:
    search_id: str
    query: str
    max_results: int
    semantic_type: str = "external_search"
    freshness_policy: dict[str, Any] | None = None
    source_policy: dict[str, Any] | None = None
    result_bounds: dict[str, Any] | None = None

    def to_provider_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "search_id": self.search_id,
            "semantic_type": self.semantic_type,
            "query": self.query,
            "max_results": self.max_results,
        }
        if self.freshness_policy is not None:
            payload["freshness_policy"] = deepcopy(self.freshness_policy)
        if self.source_policy is not None:
            payload["source_policy"] = deepcopy(self.source_policy)
        if self.result_bounds is not None:
            payload["result_bounds"] = deepcopy(self.result_bounds)
        return payload


@dataclass(frozen=True)
class NormalizedExternalSearchProviderResponse:
    raw_results: tuple[dict[str, Any], ...]
    source_refs: tuple[dict[str, Any], ...]
    citations: tuple[dict[str, Any], ...]
    rejected_raw_results: tuple[dict[str, Any], ...]
    result_lineage: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class ExternalSearchProviderExecutionResult:
    provider_id: str
    provider_type: str | None
    status: str
    execution_performed: bool
    external_call_performed: bool
    cost_incurred: bool
    normalized_request: NormalizedExternalSearchProviderRequest | None
    normalized_response: NormalizedExternalSearchProviderResponse | None
    authorization: ExternalSearchProviderAuthorizationDecision
    disabled_reasons: tuple[str, ...] = ()
    request_errors: tuple[ExternalSearchValidationError, ...] = ()
    provider_error: str | None = None
    receipt: dict[str, Any] | None = None
    dry_run_decision: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.status == PROVIDER_EXECUTION_COMPLETED_STATUS


class ExternalSearchProvider(Protocol):
    provider_id: str
    provider_type: str

    def execute(
        self,
        request: NormalizedExternalSearchProviderRequest,
        *,
        config: ExternalSearchProviderExecutionConfig,
    ) -> Any:
        ...


def execute_external_search_provider(
    request: ExternalSearchAdapterRequest | dict[str, Any],
    *,
    provider: ExternalSearchProvider,
    provider_id: str,
    root: str | Path | None = None,
    resource_id: str | None = None,
    provider_config: ExternalSearchProviderExecutionConfig | dict[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> ExternalSearchProviderExecutionResult:
    started_at = _utc_now()
    started_perf = time.perf_counter()
    adapter_request = (
        request
        if isinstance(request, ExternalSearchAdapterRequest)
        else build_external_search_adapter_request(request)
    )
    normalized_provider_id = _required_string(provider_id)
    config = _resolve_provider_config(
        provider_id=normalized_provider_id,
        root=root,
        provider_config=provider_config,
    )
    provider_type = config.provider_type if config else _safe_string(
        getattr(provider, "provider_type", None)
    )
    resolved_resource_id = resource_id or (config.resource_id if config else None)
    authorization = evaluate_external_search_provider_authorization(
        ExternalSearchProviderAuthorizationInput(
            provider_id=normalized_provider_id,
            resource_id=resolved_resource_id,
        ),
        root=root,
        environ=environ,
    )
    contract_request = adapter_request.to_contract_request()
    request_errors = tuple(
        validate_external_search_request(contract_request, root=root)
    )
    normalized_request = _normalize_provider_request(
        adapter_request,
        config=config,
        root=root,
    )
    dry_run_decision = evaluate_execution_class_dry_run(
        EXECUTION_CLASS_PAID_EXTERNAL_PROVIDER,
        dry_run=dry_run_requested(environ),
    )

    disabled_reasons = _execution_disabled_reasons(
        config=config,
        authorization=authorization,
        request_errors=request_errors,
        provider=provider,
        provider_id=normalized_provider_id,
        dry_run_decision=dry_run_decision.to_diagnostics(),
    )
    if disabled_reasons:
        result = ExternalSearchProviderExecutionResult(
            provider_id=normalized_provider_id,
            provider_type=provider_type,
            status=PROVIDER_EXECUTION_DISABLED_STATUS,
            execution_performed=False,
            external_call_performed=False,
            cost_incurred=False,
            normalized_request=normalized_request,
            normalized_response=None,
            authorization=authorization,
            disabled_reasons=disabled_reasons,
            request_errors=request_errors,
            dry_run_decision=dry_run_decision.to_diagnostics(),
        )
        return _with_execution_receipt(
            result,
            adapter_request=adapter_request,
            config=config,
            started_at=started_at,
            started_perf=started_perf,
        )

    assert config is not None
    try:
        raw_response = provider.execute(normalized_request, config=config)
    except Exception as error:  # noqa: BLE001
        result = ExternalSearchProviderExecutionResult(
            provider_id=normalized_provider_id,
            provider_type=config.provider_type,
            status=PROVIDER_EXECUTION_FAILED_STATUS,
            execution_performed=True,
            external_call_performed=True,
            cost_incurred=False,
            normalized_request=normalized_request,
            normalized_response=None,
            authorization=authorization,
            provider_error=error.__class__.__name__,
            dry_run_decision=dry_run_decision.to_diagnostics(),
        )
        return _with_execution_receipt(
            result,
            adapter_request=adapter_request,
            config=config,
            started_at=started_at,
            started_perf=started_perf,
        )

    normalized_response = normalize_external_search_provider_response(
        raw_response,
        provider_id=normalized_provider_id,
        max_results=normalized_request.max_results,
    )
    if not normalized_response.raw_results:
        result = ExternalSearchProviderExecutionResult(
            provider_id=normalized_provider_id,
            provider_type=config.provider_type,
            status=PROVIDER_EXECUTION_FAILED_STATUS,
            execution_performed=True,
            external_call_performed=True,
            cost_incurred=False,
            normalized_request=normalized_request,
            normalized_response=normalized_response,
            authorization=authorization,
            provider_error=ExternalSearchProviderNormalizationError.__name__,
            dry_run_decision=dry_run_decision.to_diagnostics(),
        )
        return _with_execution_receipt(
            result,
            adapter_request=adapter_request,
            config=config,
            started_at=started_at,
            started_perf=started_perf,
        )
    result = ExternalSearchProviderExecutionResult(
        provider_id=normalized_provider_id,
        provider_type=config.provider_type,
        status=PROVIDER_EXECUTION_COMPLETED_STATUS,
        execution_performed=True,
        external_call_performed=True,
        cost_incurred=False,
        normalized_request=normalized_request,
        normalized_response=normalized_response,
        authorization=authorization,
        dry_run_decision=dry_run_decision.to_diagnostics(),
    )
    return _with_execution_receipt(
        result,
        adapter_request=adapter_request,
        config=config,
        started_at=started_at,
        started_perf=started_perf,
    )


def normalize_external_search_provider_response(
    response: Any,
    *,
    provider_id: str,
    max_results: int,
) -> NormalizedExternalSearchProviderResponse:
    raw_items = _response_items(response)
    raw_results: list[dict[str, Any]] = []
    source_refs: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    result_lineage: list[dict[str, Any]] = []

    for index, item in enumerate(raw_items[:max_results]):
        normalized = _normalize_result_item(
            item,
            provider_id=provider_id,
            index=index,
        )
        if normalized is None:
            rejected.append(
                {
                    "index": index,
                    "rejection_reason": "missing_required_result_fields",
                }
            )
            continue
        raw_results.append(normalized)
        source_ref = {
            "provider_result_id": normalized["provider_result_id"],
            "url": normalized["url"],
            "title": normalized.get("title"),
        }
        citation_ref = {
            "provider_result_id": normalized["provider_result_id"],
            "url": normalized["url"],
            "title": normalized.get("title"),
        }
        source_refs.append(source_ref)
        citations.append(citation_ref)
        result_lineage.append(
            build_normalized_external_retrieval_result_lineage(
                provider_id=provider_id,
                provider_result_id=normalized["provider_result_id"],
                raw_result_index=index,
                raw_result_ref=f"provider_response.results[{index}]",
                source_ref=source_ref,
                citation_ref=citation_ref,
            )
        )

    return NormalizedExternalSearchProviderResponse(
        raw_results=tuple(raw_results),
        source_refs=tuple(source_refs),
        citations=tuple(citations),
        rejected_raw_results=tuple(rejected),
        result_lineage=tuple(result_lineage),
    )


@lru_cache(maxsize=None)
def load_external_search_provider_execution_configs(
    root: str | Path | None = None,
) -> tuple[ExternalSearchProviderExecutionConfig, ...]:
    try:
        data = _read_policy(root)
        if data.get("version") != 1:
            raise ExternalSearchProviderExecutionPolicyError("invalid version")
        if data.get("semantic_type") != "external_search":
            raise ExternalSearchProviderExecutionPolicyError("invalid semantic type")
        if data.get("default_execution_mode") != EXECUTION_MODE_DISABLED:
            raise ExternalSearchProviderExecutionPolicyError("default must be disabled")
        modes = data.get("execution_modes")
        if not isinstance(modes, list) or set(modes) != ALLOWED_EXECUTION_MODES:
            raise ExternalSearchProviderExecutionPolicyError("invalid execution modes")
        _validate_runtime_bounds(data.get("runtime_bounds"))
        configs = tuple(
            ExternalSearchProviderExecutionConfig.from_mapping(entry)
            for entry in data.get("provider_execution_configs", [])
        )
        if len({config.provider_id for config in configs}) != len(configs):
            raise ExternalSearchProviderExecutionPolicyError("duplicate provider config")
        return configs
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        ExternalSearchProviderExecutionPolicyError,
    ):
        return ()


def get_external_search_provider_execution_config(
    provider_id: str,
    *,
    root: str | Path | None = None,
) -> ExternalSearchProviderExecutionConfig | None:
    normalized = _safe_string(provider_id)
    if normalized is None:
        return None
    for config in load_external_search_provider_execution_configs(root):
        if config.provider_id == normalized:
            return config
    return None


def _resolve_provider_config(
    *,
    provider_id: str,
    root: str | Path | None,
    provider_config: ExternalSearchProviderExecutionConfig | dict[str, Any] | None,
) -> ExternalSearchProviderExecutionConfig | None:
    if isinstance(provider_config, ExternalSearchProviderExecutionConfig):
        return provider_config
    if isinstance(provider_config, dict):
        return ExternalSearchProviderExecutionConfig.from_mapping(provider_config)
    return get_external_search_provider_execution_config(provider_id, root=root)


def _normalize_provider_request(
    request: ExternalSearchAdapterRequest,
    *,
    config: ExternalSearchProviderExecutionConfig | None,
    root: str | Path | None,
) -> NormalizedExternalSearchProviderRequest:
    contract = get_external_search_contract(request.semantic_type, root=root)
    contract_max = 10
    if contract is not None and isinstance(contract.bounds.get("max_results"), int):
        contract_max = contract.bounds["max_results"]
    config_max = config.max_results if config is not None else contract_max
    requested_max = request.max_results
    if requested_max is None and isinstance(request.result_bounds, dict):
        bounded = request.result_bounds.get("max_results")
        requested_max = bounded if isinstance(bounded, int) else None
    if (
        not isinstance(requested_max, int)
        or isinstance(requested_max, bool)
        or requested_max < 1
    ):
        requested_max = min(contract_max, config_max)
    max_results = max(1, min(requested_max, contract_max, config_max))
    return NormalizedExternalSearchProviderRequest(
        search_id=request.search_id,
        query=request.query.strip(),
        max_results=max_results,
        semantic_type="external_search",
        freshness_policy=deepcopy(request.freshness_policy),
        source_policy=deepcopy(request.source_policy),
        result_bounds=deepcopy(request.result_bounds),
    )


def _execution_disabled_reasons(
    *,
    config: ExternalSearchProviderExecutionConfig | None,
    authorization: ExternalSearchProviderAuthorizationDecision,
    request_errors: tuple[ExternalSearchValidationError, ...],
    provider: ExternalSearchProvider,
    provider_id: str,
    dry_run_decision: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if isinstance(dry_run_decision, dict) and dry_run_decision.get("allowed") is False:
        reasons.append(str(dry_run_decision.get("reason") or "blocked_by_dry_run"))
    if request_errors:
        reasons.append("invalid_external_search_request")
    if config is None:
        reasons.append("missing_provider_execution_config")
    else:
        if config.provider_id != provider_id:
            reasons.append("provider_config_id_mismatch")
        if config.enabled is not True:
            reasons.append("provider_execution_config_disabled")
        if config.execution_mode != EXECUTION_MODE_ALLOWED:
            reasons.append("provider_execution_mode_not_allowed")
        if config.live_provider_execution_allowed is not True:
            reasons.append("provider_config_disallows_live_execution")
        if config.cost_allowed is not True:
            reasons.append("provider_config_disallows_cost")
    if _safe_string(getattr(provider, "provider_id", None)) != provider_id:
        reasons.append("provider_id_mismatch")
    reasons.extend(
        validate_external_search_live_provider_execution_authorization(authorization)
    )
    return tuple(dict.fromkeys(reasons))


def _response_items(response: Any) -> list[Any]:
    if isinstance(response, dict):
        results = response.get("results")
        if isinstance(results, list):
            return results
        return []
    if isinstance(response, list):
        return response
    return []


def _normalize_result_item(
    item: Any,
    *,
    provider_id: str,
    index: int,
) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    url = _safe_string(item.get("url"))
    title = _safe_string(item.get("title"))
    if url is None or title is None:
        return None
    provider_result_id = (
        _safe_string(item.get("provider_result_id"))
        or _safe_string(item.get("id"))
        or f"{provider_id}-{index + 1}"
    )
    normalized = {
        "provider_result_id": provider_result_id,
        "provider_id": provider_id,
        "title": title,
        "url": url,
    }
    snippet = _safe_string(item.get("snippet")) or _safe_string(item.get("content"))
    if snippet is not None:
        normalized["snippet"] = snippet
    published_at = _safe_string(item.get("published_at"))
    if published_at is not None:
        normalized["published_at"] = published_at
    return normalized


def _with_execution_receipt(
    result: ExternalSearchProviderExecutionResult,
    *,
    adapter_request: ExternalSearchAdapterRequest,
    config: ExternalSearchProviderExecutionConfig | None,
    started_at: datetime,
    started_perf: float,
) -> ExternalSearchProviderExecutionResult:
    completed_at = _utc_now()
    duration_ms = max(0, int((time.perf_counter() - started_perf) * 1000))
    receipt = build_external_search_execution_receipt(
        request_id=adapter_request.search_id,
        search_id=adapter_request.search_id,
        provider_id=result.provider_id,
        provider_type=result.provider_type,
        authorization_decision=result.authorization.to_audit_record(),
        execution_state=result.status,
        execution_performed=result.execution_performed,
        external_call_performed=result.external_call_performed,
        cost_incurred=result.cost_incurred,
        timing={
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_ms": duration_ms,
        },
        bounds=_receipt_bounds(
            adapter_request=adapter_request,
            result=result,
            config=config,
        ),
        normalized_result_metadata=_receipt_result_metadata(result),
        failure=_receipt_failure(result),
    )
    return ExternalSearchProviderExecutionResult(
        provider_id=result.provider_id,
        provider_type=result.provider_type,
        status=result.status,
        execution_performed=result.execution_performed,
        external_call_performed=result.external_call_performed,
        cost_incurred=result.cost_incurred,
        normalized_request=result.normalized_request,
        normalized_response=result.normalized_response,
        authorization=result.authorization,
        disabled_reasons=result.disabled_reasons,
        request_errors=result.request_errors,
        provider_error=result.provider_error,
        receipt=receipt,
        dry_run_decision=(
            dict(result.dry_run_decision)
            if isinstance(result.dry_run_decision, dict)
            else None
        ),
    )


def _receipt_bounds(
    *,
    adapter_request: ExternalSearchAdapterRequest,
    result: ExternalSearchProviderExecutionResult,
    config: ExternalSearchProviderExecutionConfig | None,
) -> dict[str, Any]:
    requested_max = adapter_request.max_results
    if requested_max is None and isinstance(adapter_request.result_bounds, dict):
        bounded = adapter_request.result_bounds.get("max_results")
        requested_max = bounded if isinstance(bounded, int) else None
    normalized_max = (
        result.normalized_request.max_results
        if result.normalized_request is not None
        else None
    )
    return {
        "requested_max_results": requested_max,
        "normalized_max_results": normalized_max,
        "timeout_ms": config.timeout_ms if config is not None else None,
        "freshness_policy_present": adapter_request.freshness_policy is not None,
        "source_policy_present": adapter_request.source_policy is not None,
        "result_bounds_present": adapter_request.result_bounds is not None,
    }


def _receipt_result_metadata(
    result: ExternalSearchProviderExecutionResult,
) -> dict[str, int]:
    response = result.normalized_response
    if response is None:
        return {
            "raw_result_count": 0,
            "source_ref_count": 0,
            "citation_count": 0,
            "rejected_result_count": 0,
        }
    return {
        "raw_result_count": len(response.raw_results),
        "source_ref_count": len(response.source_refs),
        "citation_count": len(response.citations),
        "rejected_result_count": len(response.rejected_raw_results),
    }


def _receipt_failure(result: ExternalSearchProviderExecutionResult) -> dict[str, Any]:
    failed = result.status in {
        PROVIDER_EXECUTION_DISABLED_STATUS,
        PROVIDER_EXECUTION_FAILED_STATUS,
    }
    reasons = list(result.disabled_reasons)
    if result.request_errors:
        reasons.extend(error.error_code for error in result.request_errors)
    return {
        "failed": failed,
        "failure_reasons": list(dict.fromkeys(reasons)),
        "error_class": result.provider_error,
    }


def _read_policy(root: str | Path | None) -> dict[str, Any]:
    path = EXTERNAL_SEARCH_PROVIDER_EXECUTION_POLICY_PATH
    full_path = path if root is None else Path(root) / path
    data = json.loads(full_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ExternalSearchProviderExecutionPolicyError("policy root must be object")
    return data


def _validate_runtime_bounds(value: Any) -> None:
    if not isinstance(value, dict):
        raise ExternalSearchProviderExecutionPolicyError("runtime bounds required")
    required_true = (
        "authorization_required_before_provider_execution",
        "config_must_enable_provider_execution",
    )
    required_false = (
        "workflow_to_provider_calls_allowed",
        "provider_selection_allowed",
        "hidden_fallbacks_allowed",
        "hidden_retries_allowed",
        "article_scraping_allowed",
        "summarization_allowed",
        "ranking_allowed",
        "domain_normalization_allowed",
        "memory_writes_allowed",
    )
    for field in required_true:
        if value.get(field) is not True:
            raise ExternalSearchProviderExecutionPolicyError(
                "required runtime bound missing"
            )
    for field in required_false:
        if value.get(field) is not False:
            raise ExternalSearchProviderExecutionPolicyError(
                "forbidden runtime bound enabled"
            )


def _forbidden_field_paths(value: Any, *, prefix: str = "") -> tuple[str, ...]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, item in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if key_text in FORBIDDEN_CONFIG_FIELDS:
                paths.append(path)
            paths.extend(_forbidden_field_paths(item, prefix=path))
        return tuple(paths)
    if isinstance(value, list):
        paths = []
        for index, item in enumerate(value):
            paths.extend(_forbidden_field_paths(item, prefix=f"{prefix}[{index}]"))
        return tuple(paths)
    return ()


def _required_string(value: Any) -> str:
    normalized = _safe_string(value)
    if normalized is None:
        raise ExternalSearchProviderExecutionPolicyError("string required")
    return normalized


def _required_bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ExternalSearchProviderExecutionPolicyError("boolean required")
    return value


def _safe_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "ALLOWED_EXECUTION_MODES",
    "EXECUTION_MODE_ALLOWED",
    "EXECUTION_MODE_AUDIT_ONLY",
    "EXECUTION_MODE_DISABLED",
    "EXTERNAL_SEARCH_PROVIDER_EXECUTION_POLICY_PATH",
    "PROVIDER_EXECUTION_COMPLETED_STATUS",
    "PROVIDER_EXECUTION_DISABLED_STATUS",
    "PROVIDER_EXECUTION_FAILED_STATUS",
    "ExternalSearchProvider",
    "ExternalSearchProviderExecutionConfig",
    "ExternalSearchProviderNormalizationError",
    "ExternalSearchProviderExecutionPolicyError",
    "ExternalSearchProviderExecutionResult",
    "NormalizedExternalSearchProviderRequest",
    "NormalizedExternalSearchProviderResponse",
    "execute_external_search_provider",
    "get_external_search_provider_execution_config",
    "load_external_search_provider_execution_configs",
    "normalize_external_search_provider_response",
]
