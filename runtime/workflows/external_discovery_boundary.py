from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
from typing import Any, Callable

from runtime.adapters.cloud_web_ai import (
    CloudWebAIAdapter,
    CloudWebAIAdapterRequest,
    CloudWebAIAdapterResult,
    CloudWebAIExecutionLimits,
)
from runtime.artifacts.external_discovery_execution_receipt import (
    build_external_discovery_execution_receipt,
)
from runtime.artifacts.external_discovery_result import (
    EXTERNAL_DISCOVERY_RESULT_SET_ARTIFACT,
    build_external_discovery_result_set,
)
from runtime.artifacts.web_guest_discovery_query_plan import (
    WEB_GUEST_DISCOVERY_QUERY_PLAN_ARTIFACT,
    validate_web_guest_discovery_query_plan,
)
from runtime.policies.cloud_provider_authorization import (
    CloudProviderAuthorizationInput,
    CloudProviderAuthorizationPolicy,
    evaluate_cloud_provider_authorization,
)
from runtime.policies.cloud_provider_pilot_authorization import (
    evaluate_cloud_provider_pilot_authorization_metadata,
)
from runtime.registries.external_discovery_provider_registry import (
    ExternalDiscoveryProviderDeclaration,
    get_external_discovery_provider_declaration,
)


CLOUD_DRY_RUN_ENV = "CLOUD_DRY_RUN"
EXTERNAL_DISCOVERY_ACTION_TYPE = "external_guest_discovery"
DRY_RUN_BLOCKED_REASON = "cloud_dry_run_provider_execution_blocked"
EXECUTION_STATE_DRY_RUN = "dry_run"
EXECUTION_STATE_LIVE_AUTHORIZED_NOT_IMPLEMENTED = (
    "live_authorized_not_implemented"
)
EXECUTION_STATE_FAKE_ADAPTER_EXECUTED = "fake_adapter_executed"
EXECUTION_STATE_LIVE_ADAPTER_EXECUTED = "live_adapter_executed"
EXECUTION_STATE_LIVE_ADAPTER_FAILED = "live_adapter_failed"
EXECUTION_STATE_BLOCKED = "blocked"
PROVIDER_CALL_NOT_IMPLEMENTED_REASON = "provider_call_not_implemented"
FAKE_ADAPTER_EXECUTED_REASON = "fake_test_adapter_executed"
LIVE_ADAPTER_EXECUTED_REASON = "live_adapter_executed"
LIVE_ADAPTER_FAILED_REASON = "live_adapter_failed"


@dataclass(frozen=True)
class ExternalDiscoveryBoundaryResult:
    artifact: dict[str, Any] | None
    materialized: bool
    provider_id: str | None
    governance_state: str | None
    execution_state: str
    cloud_dry_run: bool
    execution_allowed: bool
    live_authorized: bool
    provider_call_implemented: bool
    skipped_reasons: tuple[str, ...]
    receipt: dict[str, Any]


def materialize_external_discovery_dry_run_result(
    *,
    query_plan: dict[str, Any],
    provider_id: str,
    provider_declaration: ExternalDiscoveryProviderDeclaration | None = None,
    agent_id: str | None = None,
    actor_id: str | None = None,
    user_id: str | None = None,
    channel: str | None = None,
    request_source: str | None = None,
    query_plan_ref: str | None = None,
    result_artifact_ref: str | None = None,
    created_at: datetime | str | None = None,
    is_test_context: bool = False,
    authorization_policy: CloudProviderAuthorizationPolicy | None = None,
    root: str | Path | None = None,
    env: dict[str, str] | None = None,
    adapter: CloudWebAIAdapter | None = None,
    adapter_resolver: Callable[
        [str, dict[str, Any]], CloudWebAIAdapter | None
    ]
    | None = None,
    provider_config: dict[str, Any] | None = None,
    execution_limits: CloudWebAIExecutionLimits | dict[str, Any] | None = None,
) -> ExternalDiscoveryBoundaryResult:
    cloud_dry_run = _cloud_dry_run_enabled(env)
    declaration = provider_declaration or get_external_discovery_provider_declaration(
        provider_id,
        root=root,
    )

    if declaration is None:
        return _closed(
            provider_id=provider_id,
            governance_state=None,
            cloud_dry_run=cloud_dry_run,
            skipped_reasons=("provider_declaration_not_found",),
            created_at=created_at,
        )

    if query_plan.get("artifact_type") != WEB_GUEST_DISCOVERY_QUERY_PLAN_ARTIFACT:
        return _closed(
            provider_id=declaration.provider_id,
            governance_state=declaration.governance_state,
            cloud_dry_run=cloud_dry_run,
            skipped_reasons=("invalid_query_plan_artifact_type",),
            created_at=created_at,
        )

    validation_errors = validate_web_guest_discovery_query_plan(query_plan)
    if validation_errors:
        return _closed(
            provider_id=declaration.provider_id,
            governance_state=declaration.governance_state,
            cloud_dry_run=cloud_dry_run,
            skipped_reasons=("query_plan_contract_failed",),
            validation_errors=tuple(error.field for error in validation_errors),
            created_at=created_at,
        )

    authorization = _authorization_decision(
        provider_id=declaration.provider_id,
        agent_id=agent_id,
        actor_id=actor_id,
        user_id=user_id,
        channel=channel,
        request_source=request_source,
        is_test_context=is_test_context,
        cloud_dry_run=cloud_dry_run,
        governance_state=declaration.governance_state,
        authorization_policy=authorization_policy,
        root=root,
        env=env,
    )
    execution_state = _execution_state(
        cloud_dry_run=cloud_dry_run,
        authorization=authorization,
    )
    governed_dry_run = authorization.get("dry_run_required") is True
    execution_allowed = (
        execution_state == EXECUTION_STATE_LIVE_AUTHORIZED_NOT_IMPLEMENTED
    )
    live_authorized = bool(authorization.get("live_execution_authorized"))
    provider_call_implemented = False

    if execution_state == EXECUTION_STATE_BLOCKED:
        skipped_reasons = tuple(
            authorization.get("skipped_reasons") or ("blocked",)
        )
        return _closed(
            provider_id=declaration.provider_id,
            provider_type=declaration.provider_type,
            governance_state=declaration.governance_state,
            cloud_dry_run=governed_dry_run,
            execution_state=execution_state,
            authorization=authorization,
            skipped_reasons=skipped_reasons,
            created_at=created_at,
        )

    resolved_provider_config = _provider_config(
        declaration=declaration,
        provider_config=provider_config,
    )
    resolved_adapter = adapter
    if (
        resolved_adapter is None
        and adapter_resolver is not None
        and execution_state == EXECUTION_STATE_LIVE_AUTHORIZED_NOT_IMPLEMENTED
        and live_authorized
        and not governed_dry_run
    ):
        resolved_adapter = adapter_resolver(
            declaration.provider_id,
            deepcopy(resolved_provider_config),
        )

    if (
        resolved_adapter is not None
        and execution_state == EXECUTION_STATE_LIVE_AUTHORIZED_NOT_IMPLEMENTED
        and live_authorized
        and not governed_dry_run
    ):
        try:
            adapter_result = resolved_adapter.execute(
                CloudWebAIAdapterRequest(
                    query_plan=deepcopy(query_plan),
                    provider_config=deepcopy(resolved_provider_config),
                    execution_limits=_execution_limits(
                        declaration=declaration,
                        authorization=authorization,
                        execution_limits=execution_limits,
                    ),
                )
            )
        except Exception as exc:  # pragma: no cover - defensive boundary guard
            adapter_result = CloudWebAIAdapterResult(
                raw_provider_payload={
                    "failure_reason": "adapter_exception",
                    "error_type": type(exc).__name__,
                    "external_call_performed": False,
                    "cost_incurred": False,
                },
                raw_results=(),
                source_refs=(),
                citations=(),
                provider_metadata={
                    "provider_call_implemented": True,
                    "external_call_performed": False,
                    "cost_incurred": False,
                    "failure_reason": "adapter_exception",
                    "error_type": type(exc).__name__,
                },
            )
        return _adapter_result(
            declaration=declaration,
            query_plan=query_plan,
            query_plan_ref=query_plan_ref,
            result_artifact_ref=result_artifact_ref,
            adapter=resolved_adapter,
            adapter_result=adapter_result,
            authorization=authorization,
            created_at=created_at,
        )

    blocked_reason = (
        DRY_RUN_BLOCKED_REASON
        if execution_state == EXECUTION_STATE_DRY_RUN
        else PROVIDER_CALL_NOT_IMPLEMENTED_REASON
    )
    receipt = _execution_receipt(
        declaration=declaration,
        execution_state=execution_state,
        cloud_dry_run=governed_dry_run,
        query_plan_ref=_query_plan_ref(query_plan, query_plan_ref),
        result_artifact_ref=result_artifact_ref,
        authorization=authorization,
        created_at=created_at,
        execution_allowed=execution_allowed,
        live_authorized=live_authorized,
        provider_call_implemented=provider_call_implemented,
        blocked_reason=blocked_reason,
        adapter_metadata=None,
    )
    provider_metadata = {
        **declaration.to_metadata(),
        "execution_state": execution_state,
        "dry_run": governed_dry_run,
        "dry_run_executed": governed_dry_run,
        "cloud_dry_run_flag": cloud_dry_run,
        "live_authorized": live_authorized,
        "provider_call_implemented": provider_call_implemented,
        "external_call_performed": False,
        "cost_incurred": False,
        "discovery_executed": False,
        "execution_allowed": execution_allowed,
        "blocked_reason": blocked_reason,
        "execution_receipt": deepcopy(receipt),
        "authorization": deepcopy(authorization),
    }
    artifact = build_external_discovery_result_set(
        provider_metadata=provider_metadata,
        raw_provider_payload={
            "execution_state": execution_state,
            "dry_run": governed_dry_run,
            "cloud_dry_run_flag": cloud_dry_run,
            "live_authorized": live_authorized,
            "provider_call_implemented": provider_call_implemented,
            "external_call_performed": False,
            "cost_incurred": False,
            "discovery_executed": False,
            "query_plan_artifact_type": WEB_GUEST_DISCOVERY_QUERY_PLAN_ARTIFACT,
            "query_plan_ref": _query_plan_ref(query_plan, query_plan_ref),
            "result_artifact_ref": _safe_optional_string(result_artifact_ref),
            "query_plan": deepcopy(query_plan),
            "provider_declaration": declaration.to_metadata(),
            "execution_receipt": deepcopy(receipt),
        },
        raw_results=[],
        source_refs=[],
        citations=[],
        provenance={
            **receipt,
            "artifact_type": EXTERNAL_DISCOVERY_RESULT_SET_ARTIFACT,
            "execution_state": execution_state,
            "dry_run": governed_dry_run,
            "dry_run_executed": governed_dry_run,
            "cloud_dry_run_flag": cloud_dry_run,
            "live_authorized": live_authorized,
            "provider_call_implemented": provider_call_implemented,
            "external_call_performed": False,
            "cost_incurred": False,
            "discovery_executed": False,
            "query_plan_artifact_type": WEB_GUEST_DISCOVERY_QUERY_PLAN_ARTIFACT,
            "query_plan_ref": _query_plan_ref(query_plan, query_plan_ref),
            "result_artifact_ref": _safe_optional_string(result_artifact_ref),
            "blocked_reason": blocked_reason,
        },
    )

    return ExternalDiscoveryBoundaryResult(
        artifact=artifact,
        materialized=True,
        provider_id=declaration.provider_id,
        governance_state=declaration.governance_state,
        execution_state=execution_state,
        cloud_dry_run=cloud_dry_run,
        execution_allowed=execution_allowed,
        live_authorized=live_authorized,
        provider_call_implemented=provider_call_implemented,
        skipped_reasons=(),
        receipt=receipt,
    )


def _adapter_result(
    *,
    declaration: ExternalDiscoveryProviderDeclaration,
    query_plan: dict[str, Any],
    query_plan_ref: str | None,
    result_artifact_ref: str | None,
    adapter: CloudWebAIAdapter,
    adapter_result: CloudWebAIAdapterResult,
    authorization: dict[str, Any],
    created_at: datetime | str | None,
) -> ExternalDiscoveryBoundaryResult:
    adapter_metadata = _adapter_metadata(adapter)
    adapter_success = _adapter_success(adapter_result)
    fake_adapter = adapter_metadata.get("fake_test_adapter_used") is True
    execution_state = (
        EXECUTION_STATE_FAKE_ADAPTER_EXECUTED
        if fake_adapter
        else (
            EXECUTION_STATE_LIVE_ADAPTER_EXECUTED
            if adapter_success
            else EXECUTION_STATE_LIVE_ADAPTER_FAILED
        )
    )
    external_call_performed = _metadata_bool(
        adapter_result.provider_metadata,
        "external_call_performed",
        default=False,
    )
    cost_incurred = _metadata_bool(
        adapter_result.provider_metadata,
        "cost_incurred",
        default=False,
    )
    discovery_executed = bool(adapter_success and external_call_performed)
    blocked_reason = (
        FAKE_ADAPTER_EXECUTED_REASON
        if fake_adapter
        else (
            LIVE_ADAPTER_EXECUTED_REASON
            if adapter_success
            else _safe_optional_string(
                adapter_result.provider_metadata.get("failure_reason")
            )
            or LIVE_ADAPTER_FAILED_REASON
        )
    )
    receipt = _execution_receipt(
        declaration=declaration,
        execution_state=execution_state,
        cloud_dry_run=False,
        query_plan_ref=_query_plan_ref(query_plan, query_plan_ref),
        result_artifact_ref=result_artifact_ref,
        authorization=authorization,
        created_at=created_at,
        execution_allowed=adapter_success,
        live_authorized=True,
        provider_call_implemented=True,
        blocked_reason=blocked_reason,
        external_call_performed=external_call_performed,
        cost_incurred=cost_incurred,
        adapter_metadata=adapter_metadata,
    )
    provider_metadata = {
        **declaration.to_metadata(),
        **deepcopy(adapter_result.provider_metadata),
        **adapter_metadata,
        "execution_state": execution_state,
        "dry_run": False,
        "dry_run_executed": False,
        "live_authorized": True,
        "provider_call_implemented": True,
        "external_call_performed": external_call_performed,
        "cost_incurred": cost_incurred,
        "cost_known": "cost_incurred" in adapter_result.provider_metadata,
        "cost_estimated": bool(
            adapter_result.provider_metadata.get("cost_estimated") is True
        ),
        "discovery_executed": discovery_executed,
        "execution_allowed": adapter_success,
        "blocked_reason": blocked_reason,
        "execution_receipt": deepcopy(receipt),
        "authorization": deepcopy(authorization),
    }
    if external_call_performed and not adapter_success:
        return ExternalDiscoveryBoundaryResult(
            artifact=None,
            materialized=False,
            provider_id=declaration.provider_id,
            governance_state=declaration.governance_state,
            execution_state=execution_state,
            cloud_dry_run=False,
            execution_allowed=False,
            live_authorized=True,
            provider_call_implemented=True,
            skipped_reasons=(blocked_reason,),
            receipt=receipt,
        )
    artifact = build_external_discovery_result_set(
        provider_metadata=provider_metadata,
        raw_provider_payload=deepcopy(adapter_result.raw_provider_payload),
        raw_results=list(adapter_result.raw_results),
        source_refs=list(adapter_result.source_refs),
        citations=list(adapter_result.citations),
        rejected_raw_results=list(adapter_result.rejected_raw_results),
        provenance={
            **receipt,
            "artifact_type": EXTERNAL_DISCOVERY_RESULT_SET_ARTIFACT,
            "execution_state": execution_state,
            "dry_run": False,
            "dry_run_executed": False,
            "live_authorized": True,
            "provider_call_implemented": True,
            "external_call_performed": external_call_performed,
            "cost_incurred": cost_incurred,
            "cost_known": "cost_incurred" in adapter_result.provider_metadata,
            "cost_estimated": bool(
                adapter_result.provider_metadata.get("cost_estimated") is True
            ),
            "discovery_executed": discovery_executed,
            "query_plan_artifact_type": WEB_GUEST_DISCOVERY_QUERY_PLAN_ARTIFACT,
            "query_plan_ref": _query_plan_ref(query_plan, query_plan_ref),
            "result_artifact_ref": _safe_optional_string(result_artifact_ref),
            "blocked_reason": blocked_reason,
            **adapter_metadata,
        },
    )
    return ExternalDiscoveryBoundaryResult(
        artifact=artifact,
        materialized=True,
        provider_id=declaration.provider_id,
        governance_state=declaration.governance_state,
        execution_state=execution_state,
        cloud_dry_run=False,
        execution_allowed=adapter_success,
        live_authorized=True,
        provider_call_implemented=True,
        skipped_reasons=() if adapter_success else (blocked_reason,),
        receipt=receipt,
    )


def _cloud_dry_run_enabled(env: dict[str, str] | None) -> bool:
    source = os.environ if env is None else env
    return str(source.get(CLOUD_DRY_RUN_ENV, "false")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _authorization_decision(
    *,
    provider_id: str | None,
    agent_id: str | None,
    actor_id: str | None,
    user_id: str | None,
    channel: str | None,
    request_source: str | None,
    is_test_context: bool,
    cloud_dry_run: bool,
    governance_state: str | None,
    authorization_policy: CloudProviderAuthorizationPolicy | None,
    root: str | Path | None,
    env: dict[str, str] | None,
) -> dict[str, Any]:
    request = CloudProviderAuthorizationInput(
        provider_id=provider_id,
        agent_id=agent_id,
        channel=channel,
        request_source=request_source,
        actor_id=actor_id,
        user_id=user_id,
        is_test_context=is_test_context,
        cloud_dry_run=cloud_dry_run,
        governance_state=governance_state,
    )
    return evaluate_cloud_provider_pilot_authorization_metadata(
        request,
        policy=authorization_policy,
        root=root,
        environ=env,
    )


def _execution_state(
    *,
    cloud_dry_run: bool,
    authorization: dict[str, Any],
) -> str:
    if authorization.get("dry_run_required") is True:
        return EXECUTION_STATE_DRY_RUN
    if authorization.get("live_execution_authorized") is True:
        return EXECUTION_STATE_LIVE_AUTHORIZED_NOT_IMPLEMENTED
    return EXECUTION_STATE_BLOCKED


def _execution_receipt(
    *,
    declaration: ExternalDiscoveryProviderDeclaration,
    execution_state: str,
    cloud_dry_run: bool,
    query_plan_ref: str | None,
    result_artifact_ref: str | None,
    authorization: dict[str, Any],
    created_at: datetime | str | None,
    execution_allowed: bool,
    live_authorized: bool,
    provider_call_implemented: bool,
    blocked_reason: str,
    adapter_metadata: dict[str, Any] | None = None,
    external_call_performed: bool = False,
    cost_incurred: bool = False,
) -> dict[str, Any]:
    receipt = build_external_discovery_execution_receipt(
        provider_id=declaration.provider_id,
        provider_type=declaration.provider_type,
        action_type=EXTERNAL_DISCOVERY_ACTION_TYPE,
        query_plan_ref=query_plan_ref,
        result_artifact_ref=result_artifact_ref,
        dry_run=cloud_dry_run,
        external_call_performed=external_call_performed,
        cost_incurred=cost_incurred,
        governance_state=declaration.governance_state,
        execution_allowed=execution_allowed,
        blocked_reason=blocked_reason,
        authorization=authorization,
        created_at=created_at,
    )
    receipt["execution_state"] = execution_state
    receipt["cloud_dry_run"] = cloud_dry_run
    if isinstance(authorization, dict) and "cloud_dry_run" in authorization:
        receipt["cloud_dry_run_flag"] = bool(authorization.get("cloud_dry_run"))
    receipt["live_authorized"] = live_authorized
    receipt["provider_call_implemented"] = provider_call_implemented
    if adapter_metadata is not None:
        receipt.update(deepcopy(adapter_metadata))
    receipt["actor_authorization_checked"] = bool(
        authorization.get("actor_authorization_checked")
    )
    receipt["channel_authorization_checked"] = bool(
        authorization.get("channel_authorization_checked")
    )
    return receipt


def _closed(
    *,
    provider_id: str | None,
    provider_type: str | None = None,
    governance_state: str | None,
    cloud_dry_run: bool,
    execution_state: str = EXECUTION_STATE_BLOCKED,
    authorization: dict[str, Any] | None = None,
    skipped_reasons: tuple[str, ...],
    validation_errors: tuple[str, ...] = (),
    created_at: datetime | str | None = None,
) -> ExternalDiscoveryBoundaryResult:
    if authorization is None:
        authorization = evaluate_cloud_provider_authorization(
            CloudProviderAuthorizationInput(
                provider_id=provider_id,
                cloud_dry_run=cloud_dry_run,
                governance_state=governance_state,
            )
        ).to_metadata()
    receipt = build_external_discovery_execution_receipt(
        provider_id=provider_id,
        provider_type=provider_type,
        action_type=EXTERNAL_DISCOVERY_ACTION_TYPE,
        query_plan_ref=None,
        result_artifact_ref=None,
        dry_run=cloud_dry_run,
        external_call_performed=False,
        cost_incurred=False,
        governance_state=governance_state,
        execution_allowed=False,
        blocked_reason=skipped_reasons[0] if skipped_reasons else "closed",
        authorization=authorization,
        created_at=created_at,
    )
    receipt["execution_state"] = execution_state
    receipt["cloud_dry_run"] = cloud_dry_run
    receipt["live_authorized"] = bool(authorization.get("live_execution_authorized"))
    receipt["provider_call_implemented"] = False
    receipt["actor_authorization_checked"] = bool(
        authorization.get("actor_authorization_checked")
    )
    receipt["channel_authorization_checked"] = bool(
        authorization.get("channel_authorization_checked")
    )
    receipt["skipped_reasons"] = list(skipped_reasons)
    receipt["validation_errors"] = list(validation_errors)
    return ExternalDiscoveryBoundaryResult(
        artifact=None,
        materialized=False,
        provider_id=provider_id,
        governance_state=governance_state,
        execution_state=execution_state,
        cloud_dry_run=cloud_dry_run,
        execution_allowed=False,
        live_authorized=False,
        provider_call_implemented=False,
        skipped_reasons=skipped_reasons,
        receipt=receipt,
    )


def _query_plan_ref(
    query_plan: dict[str, Any],
    explicit_ref: str | None,
) -> str | None:
    return _safe_optional_string(explicit_ref) or _safe_optional_string(
        query_plan.get("artifact_ref")
    )


def _safe_optional_string(value: str | None) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _adapter_metadata(adapter: CloudWebAIAdapter) -> dict[str, Any]:
    return {
        "adapter_id": _safe_optional_string(getattr(adapter, "adapter_id", None)),
        "adapter_kind": _safe_optional_string(
            getattr(adapter, "adapter_kind", None)
        ),
        "fake_test_adapter_used": getattr(adapter, "adapter_kind", None) == "fake",
    }


def _adapter_success(adapter_result: CloudWebAIAdapterResult) -> bool:
    if _safe_optional_string(adapter_result.provider_metadata.get("failure_reason")):
        return False
    if not (
        adapter_result.raw_results
        and adapter_result.source_refs
        and adapter_result.citations
    ):
        return False
    source_result_ids = _provider_result_ids(adapter_result.source_refs)
    citation_result_ids = _provider_result_ids(adapter_result.citations)
    for raw_result in adapter_result.raw_results:
        provider_result_id = _safe_optional_string(
            raw_result.get("provider_result_id")
        )
        if (
            provider_result_id is None
            or provider_result_id not in source_result_ids
            or provider_result_id not in citation_result_ids
        ):
            return False
    return True


def _provider_result_ids(items: tuple[dict[str, Any], ...]) -> set[str]:
    result_ids: set[str] = set()
    for item in items:
        provider_result_id = _safe_optional_string(item.get("provider_result_id"))
        if provider_result_id is not None:
            result_ids.add(provider_result_id)
    return result_ids


def _metadata_bool(
    metadata: dict[str, Any],
    field: str,
    *,
    default: bool,
) -> bool:
    value = metadata.get(field)
    if isinstance(value, bool):
        return value
    return default


def _provider_config(
    *,
    declaration: ExternalDiscoveryProviderDeclaration,
    provider_config: dict[str, Any] | None,
) -> dict[str, Any]:
    config = declaration.to_metadata()
    if isinstance(provider_config, dict):
        config.update(deepcopy(provider_config))
    return config


def _execution_limits(
    *,
    declaration: ExternalDiscoveryProviderDeclaration,
    authorization: dict[str, Any] | None,
    execution_limits: CloudWebAIExecutionLimits | dict[str, Any] | None,
) -> CloudWebAIExecutionLimits:
    base = {
        "max_queries": declaration.max_queries,
        "max_results": declaration.max_results,
        "max_cost": deepcopy(declaration.max_cost),
    }
    if isinstance(authorization, dict):
        base["max_queries"] = _minimum_positive_int(
            base.get("max_queries"),
            authorization.get("pilot_max_queries"),
        )
        base["max_results"] = _minimum_positive_int(
            base.get("max_results"),
            authorization.get("pilot_max_results"),
        )
    if isinstance(execution_limits, CloudWebAIExecutionLimits):
        base["max_queries"] = _minimum_positive_int(
            base.get("max_queries"),
            execution_limits.max_queries,
        )
        base["max_results"] = _minimum_positive_int(
            base.get("max_results"),
            execution_limits.max_results,
        )
        if execution_limits.max_cost is not None:
            base["max_cost"] = deepcopy(execution_limits.max_cost)
    if isinstance(execution_limits, dict):
        base["max_queries"] = _minimum_positive_int(
            base.get("max_queries"),
            execution_limits.get("max_queries"),
        )
        base["max_results"] = _minimum_positive_int(
            base.get("max_results"),
            execution_limits.get("max_results"),
        )
        if "max_cost" in execution_limits:
            base["max_cost"] = deepcopy(execution_limits.get("max_cost"))
    return CloudWebAIExecutionLimits(
        max_queries=base.get("max_queries"),
        max_results=base.get("max_results"),
        max_cost=base.get("max_cost"),
    )


def _minimum_positive_int(*values: Any) -> int | None:
    positive_values = [
        value
        for value in values
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    ]
    if not positive_values:
        return None
    return min(positive_values)


__all__ = [
    "CLOUD_DRY_RUN_ENV",
    "EXECUTION_STATE_BLOCKED",
    "EXECUTION_STATE_DRY_RUN",
    "EXECUTION_STATE_FAKE_ADAPTER_EXECUTED",
    "EXECUTION_STATE_LIVE_ADAPTER_EXECUTED",
    "EXECUTION_STATE_LIVE_ADAPTER_FAILED",
    "EXECUTION_STATE_LIVE_AUTHORIZED_NOT_IMPLEMENTED",
    "ExternalDiscoveryBoundaryResult",
    "FAKE_ADAPTER_EXECUTED_REASON",
    "LIVE_ADAPTER_EXECUTED_REASON",
    "LIVE_ADAPTER_FAILED_REASON",
    "PROVIDER_CALL_NOT_IMPLEMENTED_REASON",
    "materialize_external_discovery_dry_run_result",
]
