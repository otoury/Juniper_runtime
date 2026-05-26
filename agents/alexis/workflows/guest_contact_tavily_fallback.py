from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from agents.alexis.normalizers.external_guest_discovery import (
    normalize_external_discovery_to_guest_candidate_list,
)
from agents.alexis.workflows.guest_external_discovery_handoff import (
    build_guest_external_discovery_handoff,
    prepare_external_search_request_from_guest_handoff,
    validate_guest_external_discovery_handoff,
)
from runtime.adapters.external_search_provider_execution import (
    EXECUTION_MODE_ALLOWED,
    PROVIDER_EXECUTION_COMPLETED_STATUS,
    ExternalSearchProvider,
    execute_external_search_provider,
)
from runtime.adapters.tavily import TavilySearchProvider
from runtime.artifacts.external_discovery_result import (
    build_external_discovery_result_set,
    validate_external_discovery_result_set,
)
from runtime.artifacts.external_search_execution_receipt import (
    validate_external_search_execution_receipt,
)
from runtime.governance.operational_controls import evaluate_tavily_execution_control
from runtime.policies.contact_discovery_safety import (
    VERIFICATION_PUBLIC_SOURCE_UNVERIFIED,
    VERIFICATION_VERIFIED_PUBLIC_PROFESSIONAL,
    evaluate_contact_discovery_safety,
    validate_contact_safety_audit_record,
)
from runtime.policies.external_search_provider_authorization import (
    TAVILY_PROVIDER_ID,
    resolve_tavily_api_key,
)


GUEST_CONTACT_TAVILY_FALLBACK_DIAGNOSTIC = "guest_contact_tavily_fallback"
TAVILY_RESOURCE_ID = "external_search_provider_resource"
TAVILY_MAX_RESULTS = 5
TAVILY_TIMEOUT_MS = 10000
PUBLIC_PROFESSIONAL_QUERY_TERMS = (
    "official profile",
    "press contact",
    "booking representative",
    "professional biography",
)


def run_guest_contact_tavily_fallback(
    *,
    adequacy_artifact: Mapping[str, Any],
    lookup_intent: Mapping[str, Any] | None,
    external_discovery_governance: Mapping[str, Any] | None = None,
    operator_live_fallback: bool = False,
    provider: ExternalSearchProvider | None = None,
    root: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    handoff = build_guest_external_discovery_handoff(
        adequacy_artifact=adequacy_artifact,
        lookup_intent=lookup_intent,
        external_discovery_governance=external_discovery_governance,
        generated_at=generated_at,
    )
    request = prepare_external_search_request_from_guest_handoff(handoff)
    if request is not None:
        request = replace(
            request,
            query=_public_professional_query(request.query),
        )

    execution = None
    receipt = None
    discovery_artifact = None
    normalized_candidates = None
    contact_observations: list[dict[str, Any]] = []
    receipt_errors = ()
    discovery_errors = ()
    runtime_governance = evaluate_tavily_execution_control(
        root=root,
        environ=environ,
        now=generated_at,
    )

    execution_attempt_allowed = request is not None and operator_live_fallback is True
    if execution_attempt_allowed:
        api_key, credential_diagnostic = resolve_tavily_api_key(environ)
        active_provider = provider or TavilySearchProvider(api_key=api_key)
        execution = execute_external_search_provider(
            request,
            provider=active_provider,
            provider_id=TAVILY_PROVIDER_ID,
            root=root,
            provider_config=_operator_tavily_provider_config(
                enabled=operator_live_fallback,
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
            contact_observations = _classify_contact_observations(
                execution.normalized_response.raw_results,
                root=root,
            )
            discovery_artifact = _external_discovery_result_from_execution(
                execution=execution,
                receipt_ref=receipt["receipt_ref"],
                contact_observations=contact_observations,
            )
            discovery_errors = validate_external_discovery_result_set(
                discovery_artifact
            )
            if not discovery_errors:
                normalized_candidates = normalize_external_discovery_to_guest_candidate_list(
                    discovery_artifact,
                    artifact_ref=(
                        "artifact:external_discovery_result_set:"
                        f"{request.search_id}"
                    ),
                ).artifact
        credential_state = credential_diagnostic.credential_state
        credential_configured = credential_diagnostic.credential_configured
    else:
        _, credential_diagnostic = resolve_tavily_api_key(environ)
        credential_state = credential_diagnostic.credential_state
        credential_configured = credential_diagnostic.credential_configured

    diagnostics = {
        "diagnostic_type": GUEST_CONTACT_TAVILY_FALLBACK_DIAGNOSTIC,
        "provider_id": TAVILY_PROVIDER_ID,
        "operator_live_fallback": bool(operator_live_fallback),
        "guest_db_inadequate": _guest_db_inadequate(adequacy_artifact),
        "handoff_eligible": handoff.get("handoff_eligible") is True,
        "handoff_valid": validate_guest_external_discovery_handoff(handoff),
        "bounded_public_professional_query_prepared": request is not None,
        "runtime_governance": runtime_governance.to_diagnostics(),
        "runtime_governance_allowed": runtime_governance.allowed,
        "runtime_governance_effective_state": runtime_governance.effective_state,
        "runtime_governance_reason_codes": list(runtime_governance.reason_codes),
        "execution_state": execution.status if execution else "not_attempted",
        "execution_performed": execution.execution_performed if execution else False,
        "external_call_performed": (
            execution.external_call_performed if execution else False
        ),
        "cost_incurred": execution.cost_incurred if execution else False,
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
        "disabled_reasons": list(execution.disabled_reasons) if execution else [],
        "receipt_bearing": receipt is not None,
        "receipt_ref": receipt.get("receipt_ref") if isinstance(receipt, dict) else None,
        "receipt_valid": receipt is not None and not receipt_errors,
        "receipt_error_fields": [error.field for error in receipt_errors],
        "external_discovery_artifact_materialized": discovery_artifact is not None,
        "external_discovery_artifact_valid": (
            discovery_artifact is not None and not discovery_errors
        ),
        "external_discovery_artifact_error_fields": [
            error.field for error in discovery_errors
        ],
        "normalized_candidate_artifact_materialized": normalized_candidates is not None,
        "normalized_candidate_count": _candidate_count(normalized_candidates),
        "contact_observation_count": len(contact_observations),
        "allowed_contact_observation_count": sum(
            1
            for observation in contact_observations
            if observation.get("allowed_for_contact_use") is True
        ),
        "credential_configured": credential_configured,
        "credential_state": credential_state,
        "db_write_performed": False,
        "memory_write_performed": False,
        "automatic_contact_promotion_performed": False,
        "contact_value_generation_performed": False,
        "email_pattern_inference_performed": False,
        "private_phone_harvesting_performed": False,
        "personal_address_discovery_performed": False,
        "social_engineering_path_performed": False,
        "ranking_performed": False,
        "selection_performed": False,
        "delivery_performed": False,
        "planner_semantic_authority": False,
        "content_safety": {
            "query_suppressed": True,
            "raw_results_suppressed": True,
            "source_refs_suppressed": True,
            "citations_suppressed": True,
            "provider_payload_suppressed": True,
            "contact_values_suppressed": True,
            "receipt_ref_allowed": True,
        },
    }

    return {
        "artifact_type": GUEST_CONTACT_TAVILY_FALLBACK_DIAGNOSTIC,
        "handled": execution_attempt_allowed,
        "diagnostics": diagnostics,
        "guest_external_discovery_handoff": handoff,
        "execution_receipt": receipt,
        "external_discovery_artifact": discovery_artifact,
        "normalized_candidate_artifact": normalized_candidates,
        "contact_safety_observations": contact_observations,
    }


def validate_guest_contact_tavily_fallback_diagnostics(payload: Any) -> bool:
    if not isinstance(payload, Mapping):
        return False
    if payload.get("diagnostic_type") != GUEST_CONTACT_TAVILY_FALLBACK_DIAGNOSTIC:
        return False
    if payload.get("handoff_valid") is not True:
        return False
    for field in (
        "db_write_performed",
        "memory_write_performed",
        "automatic_contact_promotion_performed",
        "contact_value_generation_performed",
        "email_pattern_inference_performed",
        "private_phone_harvesting_performed",
        "personal_address_discovery_performed",
        "social_engineering_path_performed",
        "ranking_performed",
        "selection_performed",
        "delivery_performed",
        "planner_semantic_authority",
    ):
        if payload.get(field) is not False:
            return False
    if not isinstance(payload.get("provider_authorization_skipped_reasons"), list):
        return False
    if not isinstance(payload.get("disabled_reasons"), list):
        return False
    if payload.get("receipt_bearing") is True and not payload.get("receipt_valid"):
        return False
    if (
        payload.get("external_discovery_artifact_materialized") is True
        and not payload.get("external_discovery_artifact_valid")
    ):
        return False
    content_safety = payload.get("content_safety")
    if not isinstance(content_safety, Mapping):
        return False
    return all(value is True for value in content_safety.values())


def _public_professional_query(query: str) -> str:
    base = " ".join(query.split())[:120]
    suffix = " ".join(PUBLIC_PROFESSIONAL_QUERY_TERMS)
    return f"{base} {suffix}"[:240].strip()


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
        "implementation_status": "operator_guest_contact_tavily_fallback",
    }


def _external_discovery_result_from_execution(
    *,
    execution: Any,
    receipt_ref: str,
    contact_observations: list[dict[str, Any]],
) -> dict[str, Any]:
    response = execution.normalized_response
    assert response is not None
    return build_external_discovery_result_set(
        provider_metadata={
            "provider_id": TAVILY_PROVIDER_ID,
            "provider_type": "tavily",
            "execution_receipt_ref": receipt_ref,
            "contact_safety_observation_count": len(contact_observations),
            "external_call_performed": True,
        },
        raw_provider_payload={
            "payload_preserved": False,
            "suppression_reason": "content_safe_guest_contact_boundary",
        },
        raw_results=[_guest_observation_result(item) for item in response.raw_results],
        source_refs=response.source_refs,
        citations=response.citations,
        rejected_raw_results=response.rejected_raw_results,
        provenance={
            "governance_state": "operator_guest_contact_tavily_fallback",
            "provider_execution_performed": False,
            "provider_executed": False,
            "web_search_executed": False,
            "search_api_called": False,
            "browser_api_called": False,
            "cloud_model_called": False,
            "external_adapter_called": False,
            "external_call_performed": True,
            "cost_incurred": execution.cost_incurred,
            "discovery_executed": True,
            "dry_run": False,
            "live_authorized": True,
            "provider_call_implemented": True,
            "execution_state": "live_adapter_executed",
            "normalization_performed": False,
            "ranking_performed": False,
            "selection_performed": False,
            "delivery_performed": False,
            "db_write_performed": False,
            "memory_write_performed": False,
            "automatic_contact_promotion_performed": False,
            "execution_receipt_refs": [receipt_ref],
            "contact_safety_observations": deepcopy(contact_observations),
        },
    )


def _guest_observation_result(raw_result: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(raw_result))
    title = _safe_text(result.get("title")) or "Public professional source"
    result.setdefault("display_name", title)
    result.setdefault("canonical_name", " ".join(title.lower().split()))
    result.setdefault("candidate_origin", "external_public_source")
    result.setdefault("contact_verification_state", "public_source_observed")
    result.setdefault("verification_state", "public_source_observed")
    result.setdefault("source_scope", "web")
    result.pop("email", None)
    result.pop("phone", None)
    result.pop("address", None)
    return result


def _classify_contact_observations(
    raw_results: Any,
    *,
    root: str | Path | None,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for index, raw_result in enumerate(raw_results if isinstance(raw_results, tuple) else ()):
        if not isinstance(raw_result, Mapping):
            continue
        contact_record = _contact_record_from_public_result(raw_result)
        decision = evaluate_contact_discovery_safety(contact_record, root=root)
        audit_record = {
            **decision.to_audit_record(),
            "observation_index": index,
            "provider_id": TAVILY_PROVIDER_ID,
            "source_public": True,
            "source_professional": True,
        }
        if validate_contact_safety_audit_record(audit_record):
            continue
        observations.append(audit_record)
    return observations


def _contact_record_from_public_result(raw_result: Mapping[str, Any]) -> dict[str, Any]:
    haystack = " ".join(
        _safe_text(raw_result.get(field)) or ""
        for field in ("title", "url", "snippet")
    ).lower()
    source_type = "official_profile"
    contact_type = "possible_contact_form"
    verification_state = VERIFICATION_PUBLIC_SOURCE_UNVERIFIED
    if "linkedin.com" in haystack or "professional profile" in haystack:
        source_type = "professional_social_profile"
        contact_type = "social_profile"
    elif "press" in haystack or "media" in haystack:
        source_type = "official_press_page"
        contact_type = "press_form"
        verification_state = VERIFICATION_VERIFIED_PUBLIC_PROFESSIONAL
    elif "booking" in haystack or "speaker" in haystack or "agent" in haystack:
        source_type = "official_booking_page"
        contact_type = "booking_form"
        verification_state = VERIFICATION_VERIFIED_PUBLIC_PROFESSIONAL
    elif "staff" in haystack or "directory" in haystack:
        source_type = "official_staff_page"
        contact_type = "possible_email"
    return {
        "contact_type": contact_type,
        "source_type": source_type,
        "source_public": True,
        "source_professional": True,
        "acquisition_method": "declared_public_professional",
        "verification_state": verification_state,
    }


def _guest_db_inadequate(artifact: Mapping[str, Any]) -> bool:
    return (
        isinstance(artifact, Mapping)
        and artifact.get("artifact_type") == "guest_db_adequacy"
        and artifact.get("adequate") is False
        and artifact.get("outcome") == "inadequate"
    )


def _candidate_count(artifact: Any) -> int:
    if isinstance(artifact, Mapping):
        value = artifact.get("candidate_count")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return 0


def _safe_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return " ".join(value.split())[:240]
    return None


def _timestamp(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


__all__ = [
    "GUEST_CONTACT_TAVILY_FALLBACK_DIAGNOSTIC",
    "run_guest_contact_tavily_fallback",
    "validate_guest_contact_tavily_fallback_diagnostics",
]
