from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from runtime.adapters.external_search_provider_execution import (
    EXECUTION_MODE_ALLOWED,
    PROVIDER_EXECUTION_COMPLETED_STATUS,
    ExternalSearchProvider,
    execute_external_search_provider,
)
from runtime.adapters.tavily import TavilySearchProvider
from runtime.artifacts.external_search import (
    build_external_search_result_set,
    validate_external_search_result_set,
)
from runtime.artifacts.external_search_execution_receipt import (
    validate_external_search_execution_receipt,
)
from runtime.governance.operational_controls import evaluate_tavily_execution_control
from runtime.execution_classes import (
    EXECUTION_CLASS_PAID_EXTERNAL_PROVIDER,
    dry_run_requested,
    evaluate_execution_class_dry_run,
)
from runtime.policies.external_search_provider_authorization import (
    TAVILY_PROVIDER_ID,
    resolve_tavily_api_key,
)
from runtime.policies.rss_external_live_retrieval import (
    LIVE_RETRIEVAL_STATUS_ALLOWED,
    LIVE_RETRIEVAL_STATUS_BLOCKED,
    RSS_EXTERNAL_LIVE_RETRIEVAL_GOVERNANCE_ARTIFACT,
    validate_rss_external_live_retrieval_governance,
)
from runtime.workflows.rss_external_search_handoff import (
    build_rss_external_search_handoff,
    prepare_external_search_request_from_rss_handoff,
    validate_rss_external_search_handoff,
)


LATEST_NEWS_TAVILY_FALLBACK_DIAGNOSTIC = "latest_news_tavily_fallback_pilot"
TAVILY_RESOURCE_ID = "external_search_provider_resource"
TAVILY_MAX_RESULTS = 5
TAVILY_TIMEOUT_MS = 10000


def run_latest_news_tavily_fallback_pilot(
    *,
    adequacy_artifact: Mapping[str, Any],
    operator_live_fallback: bool = False,
    provider: ExternalSearchProvider | None = None,
    root: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    working_adequacy = deepcopy(dict(adequacy_artifact))
    live_governance = _pilot_live_governance(
        adequacy_artifact=working_adequacy,
        operator_live_fallback=operator_live_fallback,
        generated_at=generated_at,
    )
    working_adequacy["external_live_retrieval_governance"] = live_governance
    handoff = build_rss_external_search_handoff(
        adequacy_artifact=working_adequacy,
        generated_at=generated_at,
    )
    request = prepare_external_search_request_from_rss_handoff(handoff)

    execution = None
    receipt = None
    result_artifact = None
    receipt_errors = ()
    result_errors = ()
    runtime_governance = evaluate_tavily_execution_control(
        root=root,
        environ=environ,
        now=generated_at,
    )
    dry_run_decision = evaluate_execution_class_dry_run(
        EXECUTION_CLASS_PAID_EXTERNAL_PROVIDER,
        dry_run=dry_run_requested(environ),
    )

    provider_boundary_allowed = bool(
        operator_live_fallback
        and runtime_governance.allowed
        and dry_run_decision.allowed
    )

    if request is not None and operator_live_fallback:
        api_key, credential_diagnostic = resolve_tavily_api_key(environ)
        active_provider = provider or TavilySearchProvider(api_key=api_key)
        execution = execute_external_search_provider(
            request,
            provider=active_provider,
            provider_id=TAVILY_PROVIDER_ID,
            root=root,
            provider_config=_operator_tavily_provider_config(
                enabled=provider_boundary_allowed,
            ),
            environ=environ,
        )
        receipt = execution.receipt
        receipt_errors = (
            validate_external_search_execution_receipt(receipt) if receipt else ()
        )
        if (
            execution.status == PROVIDER_EXECUTION_COMPLETED_STATUS
            and execution.normalized_response is not None
            and receipt is not None
        ):
            result_artifact = build_external_search_result_set(
                search_id=request.search_id,
                query=request.query,
                raw_results=execution.normalized_response.raw_results,
                source_refs=execution.normalized_response.source_refs,
                citations=execution.normalized_response.citations,
                rejected_raw_results=execution.normalized_response.rejected_raw_results,
                execution_receipt_refs=[receipt["receipt_ref"]],
                result_lineage=execution.normalized_response.result_lineage,
                provenance={
                    "governance_state": "operator_latest_news_tavily_fallback",
                    "rss_first_preserved": True,
                    "operator_triggered": True,
                    "planner_context_injection_performed": False,
                    "planner_semantic_authority": False,
                    "memory_write_performed": False,
                    "article_body_fetch_performed": False,
                    "provider_payload_attached": False,
                },
            )
            result_errors = validate_external_search_result_set(result_artifact)
        credential_state = credential_diagnostic.credential_state
        credential_configured = credential_diagnostic.credential_configured
    else:
        _, credential_diagnostic = resolve_tavily_api_key(environ)
        credential_state = credential_diagnostic.credential_state
        credential_configured = credential_diagnostic.credential_configured

    diagnostics = {
        "diagnostic_type": LATEST_NEWS_TAVILY_FALLBACK_DIAGNOSTIC,
        "workflow_id": working_adequacy.get("workflow_id"),
        "provider_id": TAVILY_PROVIDER_ID,
        "execution_class": dry_run_decision.execution_class,
        "dry_run_effect": dry_run_decision.dry_run_effect,
        "execution_class_allowed": dry_run_decision.allowed,
        "execution_class_reason": dry_run_decision.reason,
        "rss_primary_preserved": True,
        "operator_live_fallback": bool(operator_live_fallback),
        "rss_inadequate": _rss_inadequate(working_adequacy),
        "fallback_eligible": handoff.get("handoff_eligible") is True,
        "handoff_status": handoff.get("status"),
        "handoff_reason_codes": list(handoff.get("reason_codes", [])),
        "handoff_valid": validate_rss_external_search_handoff(handoff),
        "live_governance_status": live_governance.get("status"),
        "runtime_governance": runtime_governance.to_diagnostics(),
        "runtime_governance_allowed": runtime_governance.allowed,
        "runtime_governance_effective_state": runtime_governance.effective_state,
        "runtime_governance_reason_codes": list(runtime_governance.reason_codes),
        "live_governance_valid": validate_rss_external_live_retrieval_governance(
            live_governance
        ),
        "provider_authorization_status": (
            execution.authorization.authorization_status if execution else None
        ),
        "provider_authorized": (
            execution.authorization.live_provider_execution_authorized
            if execution
            else False
        ),
        "provider_authorization_skipped_reasons": (
            list(execution.authorization.skipped_reasons) if execution else []
        ),
        "execution_state": execution.status if execution else "not_attempted",
        "execution_performed": execution.execution_performed if execution else False,
        "external_call_performed": (
            execution.external_call_performed if execution else False
        ),
        "cost_incurred": execution.cost_incurred if execution else False,
        "disabled_reasons": _disabled_reasons(
            execution_disabled_reasons=(
                execution.disabled_reasons if execution else ()
            ),
            dry_run_decision=dry_run_decision.to_diagnostics(),
            runtime_governance=runtime_governance.to_diagnostics(),
        ),
        "receipt_bearing": receipt is not None,
        "receipt_ref": receipt.get("receipt_ref") if isinstance(receipt, dict) else None,
        "receipt_valid": receipt is not None and not receipt_errors,
        "receipt_error_fields": [error.field for error in receipt_errors],
        "result_artifact_materialized": result_artifact is not None,
        "result_artifact_valid": result_artifact is not None and not result_errors,
        "result_artifact_error_fields": [error.field for error in result_errors],
        "credential_configured": credential_configured,
        "credential_state": credential_state,
        "article_body_fetch_performed": False,
        "summarization_performed": False,
        "ranking_performed": False,
        "delivery_performed": False,
        "planner_semantic_authority": False,
        "hidden_fallback_performed": False,
        "content_safety": {
            "query_suppressed": True,
            "raw_results_suppressed": True,
            "source_refs_suppressed": True,
            "citations_suppressed": True,
            "provider_payload_suppressed": True,
            "receipt_ref_allowed": True,
        },
    }

    return {
        "artifact_type": LATEST_NEWS_TAVILY_FALLBACK_DIAGNOSTIC,
        "handled": request is not None and operator_live_fallback,
        "diagnostics": diagnostics,
        "live_governance": live_governance,
        "external_search_handoff": handoff,
        "execution_receipt": receipt,
        "result_artifact": result_artifact,
    }


def validate_latest_news_tavily_fallback_diagnostics(payload: Any) -> bool:
    if not isinstance(payload, Mapping):
        return False
    if payload.get("diagnostic_type") != LATEST_NEWS_TAVILY_FALLBACK_DIAGNOSTIC:
        return False
    for field in (
        "rss_primary_preserved",
        "handoff_valid",
        "live_governance_valid",
    ):
        if payload.get(field) is not True:
            return False
    for field in (
        "article_body_fetch_performed",
        "summarization_performed",
        "ranking_performed",
        "delivery_performed",
        "planner_semantic_authority",
        "hidden_fallback_performed",
    ):
        if payload.get(field) is not False:
            return False
    if not isinstance(payload.get("handoff_reason_codes"), list):
        return False
    if not isinstance(payload.get("provider_authorization_skipped_reasons"), list):
        return False
    if payload.get("receipt_bearing") is True and not payload.get("receipt_valid"):
        return False
    content_safety = payload.get("content_safety")
    if not isinstance(content_safety, Mapping):
        return False
    return all(value is True for value in content_safety.values())


def _disabled_reasons(
    *,
    execution_disabled_reasons: tuple[str, ...],
    dry_run_decision: Mapping[str, Any],
    runtime_governance: Mapping[str, Any],
) -> list[str]:
    reasons = list(execution_disabled_reasons)
    if runtime_governance.get("allowed") is False:
        for reason in runtime_governance.get("reason_codes", []):
            if isinstance(reason, str) and reason:
                reasons.append(reason)
    if dry_run_decision.get("allowed") is False:
        reason = dry_run_decision.get("reason")
        if isinstance(reason, str) and reason:
            reasons.append(reason)
    return list(dict.fromkeys(reasons))


def _pilot_live_governance(
    *,
    adequacy_artifact: Mapping[str, Any],
    operator_live_fallback: bool,
    generated_at: datetime | None,
) -> dict[str, Any]:
    skipped_reasons: list[str] = []
    rss_inadequate = _rss_inadequate(adequacy_artifact)
    if not rss_inadequate:
        skipped_reasons.append("rss_inadequacy_required")
    if not operator_live_fallback:
        skipped_reasons.append("explicit_operator_live_fallback_required")
    live_allowed = not skipped_reasons
    source_scope = _safe_text(adequacy_artifact.get("source_scope")) or "rss_metadata_cache"
    return {
        "artifact_type": RSS_EXTERNAL_LIVE_RETRIEVAL_GOVERNANCE_ARTIFACT,
        "policy_id": "latest_news_tavily_fallback_pilot_v1",
        "source_artifact_type": "rss_coverage_adequacy",
        "source_scope": source_scope,
        "fallback_provider_id": TAVILY_PROVIDER_ID,
        "fallback_provider_type": "tavily",
        "status": (
            LIVE_RETRIEVAL_STATUS_ALLOWED
            if live_allowed
            else LIVE_RETRIEVAL_STATUS_BLOCKED
        ),
        "live_allowed": live_allowed,
        "external_call_allowed": live_allowed,
        "external_call_performed": False,
        "cost_allowed": live_allowed,
        "cost_incurred": False,
        "delivery_allowed": False,
        "delivery_performed": False,
        "explicit_live_request": bool(operator_live_fallback),
        "rss_inadequate": rss_inadequate,
        "fallback_eligible": rss_inadequate,
        "authorization_mode": "operator_explicit_live_flag",
        "channel": "operator",
        "request_source": "operator",
        "actor_id": None,
        "user_id": None,
        "cloud_dry_run": False,
        "workflow_dry_run": False,
        "is_test_context": False,
        "provider": {
            "provider_id": TAVILY_PROVIDER_ID,
            "provider_type": "tavily",
            "governed": True,
            "source_refs_required": True,
            "citations_required": True,
            "execution_authorized_here": False,
        },
        "source_refs_required": True,
        "citations_required": True,
        "cost_awareness_required": True,
        "source_normalization_required_before_summary": True,
        "evaluated_at": _timestamp(generated_at),
        "skipped_reasons": skipped_reasons,
        "provenance": {
            "kind": "rss_external_live_retrieval_governance",
            "source_artifact_type": "rss_coverage_adequacy",
            "source_scope": source_scope,
            "fallback_provider_id": TAVILY_PROVIDER_ID,
            "external_call_performed": False,
            "cost_incurred": False,
            "delivery_performed": False,
        },
    }


def _operator_tavily_provider_config(*, enabled: bool) -> dict[str, Any]:
    return {
        "provider_id": TAVILY_PROVIDER_ID,
        "provider_type": "tavily",
        "resource_id": TAVILY_RESOURCE_ID,
        "execution_mode": EXECUTION_MODE_ALLOWED if enabled else "audit_only",
        "enabled": bool(enabled),
        "live_provider_execution_allowed": bool(enabled),
        "max_results": TAVILY_MAX_RESULTS,
        "timeout_ms": TAVILY_TIMEOUT_MS if enabled else 0,
        "cost_allowed": bool(enabled),
        "implementation_status": "operator_latest_news_tavily_fallback_pilot",
    }


def _rss_inadequate(artifact: Mapping[str, Any]) -> bool:
    return (
        artifact.get("artifact_type") == "rss_coverage_adequacy"
        and artifact.get("source_scope") == "rss_metadata_cache"
        and artifact.get("outcome") == "inadequate"
        and artifact.get("adequate") is False
    )


def _timestamp(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def _safe_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return " ".join(value.split())[:240]
    return None


__all__ = [
    "LATEST_NEWS_TAVILY_FALLBACK_DIAGNOSTIC",
    "run_latest_news_tavily_fallback_pilot",
    "validate_latest_news_tavily_fallback_diagnostics",
]
