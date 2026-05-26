from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from runtime.adapters.external_search_provider_execution import (
    EXECUTION_MODE_ALLOWED,
    get_external_search_provider_execution_config,
)
from runtime.policies.contact_discovery_safety import (
    load_contact_discovery_safety_contract,
    load_contact_discovery_safety_governance,
    load_contact_discovery_safety_policy,
)
from runtime.policies.external_search_provider_authorization import (
    ExternalSearchProviderAuthorizationInput,
    evaluate_external_search_provider_authorization,
)
from runtime.governance.visibility_isolation import (
    validate_diagnostic_visibility_surface,
)


GUEST_CONTACT_RETRIEVAL_DIAGNOSTIC = "guest_contact_retrieval_decision"
FORBIDDEN_DIAGNOSTIC_FIELDS = frozenset(
    {
        "address",
        "api_key",
        "authorization_header",
        "bearer_token",
        "citations",
        "contact",
        "contact_value",
        "credential",
        "credential_env_var",
        "email",
        "link",
        "phone",
        "prompt",
        "provider_payload",
        "query",
        "ranking",
        "raw_provider_payload",
        "raw_results",
        "rendered_context",
        "results",
        "secret",
        "snippet",
        "source_refs",
        "summary",
        "title",
        "token",
        "url",
    }
)


def build_guest_contact_retrieval_diagnostics(
    *,
    guest_db_adequacy_artifact: Mapping[str, Any] | None,
    handoff_artifact: Mapping[str, Any] | None = None,
    merge_artifact: Mapping[str, Any] | None = None,
    result_artifact: Mapping[str, Any] | None = None,
    provider_id: str | None = None,
    resource_id: str | None = None,
    receipt_refs: Sequence[str] | None = None,
    root: str | None = None,
) -> dict[str, Any]:
    safe_provider_id = _safe_optional_text(provider_id)
    safe_resource_id = _safe_optional_text(resource_id)
    authorization = evaluate_external_search_provider_authorization(
        ExternalSearchProviderAuthorizationInput(
            provider_id=safe_provider_id,
            resource_id=safe_resource_id,
        ),
        root=root,
    )
    execution_config = (
        get_external_search_provider_execution_config(safe_provider_id, root=root)
        if safe_provider_id
        else None
    )

    return {
        "diagnostic_type": GUEST_CONTACT_RETRIEVAL_DIAGNOSTIC,
        "semantic_boundary": "guest_db_then_governed_external_contact_discovery",
        "operator_report": True,
        "observational_only": True,
        "retrieval_executed": False,
        "external_call_performed": False,
        "db_write_performed": False,
        "artifact_mutation_performed": False,
        "candidate_mutation_performed": False,
        "workflow_state_mutation_performed": False,
        "memory_write_performed": False,
        "hidden_context_injection_performed": False,
        "planner_semantic_authority": False,
        "guest_db_adequacy": _guest_db_adequacy_summary(
            guest_db_adequacy_artifact
        ),
        "external_handoff": _handoff_summary(handoff_artifact),
        "contact_safety_governance": _contact_safety_summary(root=root),
        "provider_authorization": {
            "provider_id": authorization.provider_id,
            "resource_id": authorization.resource_id,
            "authorization_state": authorization.authorization_state,
            "authorization_status": authorization.authorization_status,
            "live_provider_execution_authorized": (
                authorization.live_provider_execution_authorized
            ),
            "external_call_allowed": authorization.external_call_allowed,
            "cost_allowed": authorization.cost_allowed,
            "audit_required": authorization.audit_required,
            "fail_closed": authorization.fail_closed,
            "skipped_reasons": list(authorization.skipped_reasons),
        },
        "execution_disabled_state": _execution_disabled_summary(
            provider_id=safe_provider_id,
            execution_config=execution_config,
            authorization_status=authorization.authorization_status,
            live_provider_execution_authorized=(
                authorization.live_provider_execution_authorized
            ),
        ),
        "candidate_merge": _candidate_merge_summary(merge_artifact),
        "receipt_refs": _receipt_refs(
            merge_artifact=merge_artifact,
            result_artifact=result_artifact,
            explicit_refs=receipt_refs,
        ),
        "content_safety": {
            "content_fields_suppressed": True,
            "contact_values_suppressed": True,
            "query_suppressed": True,
            "raw_results_suppressed": True,
            "source_refs_suppressed": True,
            "citations_suppressed": True,
            "receipt_refs_allowed": True,
        },
    }


def validate_guest_contact_retrieval_diagnostics(payload: Any) -> bool:
    if not isinstance(payload, Mapping):
        return False
    if payload.get("diagnostic_type") != GUEST_CONTACT_RETRIEVAL_DIAGNOSTIC:
        return False
    if payload.get("observational_only") is not True:
        return False
    for field in (
        "retrieval_executed",
        "external_call_performed",
        "db_write_performed",
        "artifact_mutation_performed",
        "candidate_mutation_performed",
        "workflow_state_mutation_performed",
        "memory_write_performed",
        "hidden_context_injection_performed",
        "planner_semantic_authority",
    ):
        if payload.get(field) is not False:
            return False
    if _forbidden_paths(payload):
        return False
    if validate_diagnostic_visibility_surface(payload)["allowed"] is not True:
        return False
    for field in (
        "guest_db_adequacy",
        "external_handoff",
        "contact_safety_governance",
        "provider_authorization",
        "execution_disabled_state",
        "candidate_merge",
        "content_safety",
    ):
        if not isinstance(payload.get(field), Mapping):
            return False
    if not isinstance(payload.get("receipt_refs"), list):
        return False
    return True


def _guest_db_adequacy_summary(
    artifact: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "artifact_type": _safe_optional_text(_value(artifact, "artifact_type")),
        "outcome": _safe_optional_text(_value(artifact, "outcome")),
        "adequate": _optional_bool(_value(artifact, "adequate")),
        "source_scope": _safe_optional_text(_value(artifact, "source_scope")),
        "candidate_count": _safe_non_negative_int(
            _value(artifact, "candidate_count")
        ),
        "min_required_candidates": _safe_non_negative_int(
            _value(artifact, "min_required_candidates")
        ),
        "exact_match": _optional_bool(_value(artifact, "exact_match")),
        "partial_match": _optional_bool(_value(artifact, "partial_match")),
        "ambiguous": _optional_bool(_value(artifact, "ambiguous")),
        "missing_contact_field_count": _safe_sequence_count(
            _value(artifact, "missing_contact_fields")
        ),
        "freshness_status": _safe_optional_text(
            _value(_mapping_value(artifact, "freshness"), "status")
        ),
        "booking_suitability": _safe_optional_text(
            _value(artifact, "booking_suitability")
        ),
        "reason_codes": _safe_text_list(_value(artifact, "reason_codes")),
        "inadequacy_reason_codes": _safe_text_list(
            _value(artifact, "inadequacy_reason_codes")
        ),
        "assessment_only": _optional_bool(
            _value(_mapping_value(artifact, "provenance"), "assessment_only")
        ),
    }


def _handoff_summary(handoff: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        "artifact_type": _safe_optional_text(_value(handoff, "artifact_type")),
        "status": _safe_optional_text(_value(handoff, "status")),
        "eligible": _optional_bool(_value(handoff, "handoff_eligible")),
        "reason_codes": _safe_text_list(_value(handoff, "reason_codes")),
        "discovery_reason_codes": _safe_text_list(
            _value(handoff, "discovery_reason_codes")
        ),
        "prepared_request_present": isinstance(
            _value(handoff, "prepared_request"),
            Mapping,
        ),
        "handoff_is_execution": _optional_bool(_value(handoff, "handoff_is_execution")),
        "external_call_performed": _optional_bool(
            _value(handoff, "external_call_performed")
        ),
        "provider_execution_allowed": _optional_bool(
            _value(handoff, "provider_execution_allowed")
        ),
        "contact_scraping_allowed": _optional_bool(
            _value(handoff, "contact_scraping_allowed")
        ),
    }


def _contact_safety_summary(*, root: str | None) -> dict[str, Any]:
    contract = load_contact_discovery_safety_contract(root)
    governance = load_contact_discovery_safety_governance(root)
    policy = load_contact_discovery_safety_policy(root)
    runtime_bounds = policy.runtime_bounds if policy else {}
    return {
        "contract_present": contract is not None,
        "governance_present": governance is not None,
        "policy_present": policy is not None,
        "contract_id": contract.id if contract else None,
        "governance_id": governance.id if governance else None,
        "policy_id": policy.id if policy else None,
        "governance_state": governance.governance_state if governance else None,
        "live_contact_search_enabled": (
            governance.live_contact_search_enabled if governance else False
        ),
        "public_professional_sources_only": (
            governance.public_professional_sources_only if governance else False
        ),
        "content_safe_audit_required": bool(
            runtime_bounds.get("content_safe_audit_required")
        ),
        "contact_value_generation_allowed": bool(
            runtime_bounds.get("contact_value_generation_allowed")
        ),
        "private_phone_harvesting_allowed": bool(
            runtime_bounds.get("private_phone_harvesting_allowed")
        ),
        "personal_address_discovery_allowed": bool(
            runtime_bounds.get("personal_address_discovery_allowed")
        ),
        "raw_provider_payload_as_contact_record_allowed": bool(
            runtime_bounds.get("raw_provider_payload_as_contact_record_allowed")
        ),
        "automatic_db_update_allowed": bool(
            runtime_bounds.get("automatic_db_update_allowed")
        ),
        "memory_writes_allowed": bool(runtime_bounds.get("memory_writes_allowed")),
        "allowed_contact_classes": (
            list(contract.allowed_contact_classes) if contract else []
        ),
    }


def _candidate_merge_summary(artifact: Mapping[str, Any] | None) -> dict[str, Any]:
    provenance = _mapping_value(artifact, "provenance")
    return {
        "artifact_type": _safe_optional_text(_value(artifact, "artifact_type")),
        "merge_executed": _optional_bool(_value(artifact, "merge_executed")),
        "candidate_count": _safe_non_negative_int(
            _value(artifact, "candidate_count")
        ),
        "source_scopes": _safe_text_list(_value(artifact, "source_scopes")),
        "merged_from_artifact_ref_count": _safe_sequence_count(
            _value(artifact, "merged_from_artifact_refs")
        ),
        "duplicate_group_count": _safe_sequence_count(
            _value(artifact, "duplicate_groups")
        ),
        "merge_receipt_count": _safe_sequence_count(
            _value(artifact, "guest_candidate_merge_receipts")
        ),
        "automatic_contact_promotion_performed": _optional_bool(
            _value(provenance, "automatic_contact_promotion_performed")
        ),
        "external_overwrite_performed": _optional_bool(
            _value(provenance, "external_overwrite_performed")
        ),
        "ranking_performed": _optional_bool(_value(provenance, "ranking_performed")),
        "selection_performed": _optional_bool(
            _value(provenance, "selection_performed")
        ),
    }


def _execution_disabled_summary(
    *,
    provider_id: str | None,
    execution_config: Any,
    authorization_status: str,
    live_provider_execution_authorized: bool,
) -> dict[str, Any]:
    reasons: list[str] = []
    if not provider_id:
        reasons.append("missing_provider_id")
    if execution_config is None:
        reasons.append("missing_provider_execution_config")
        return {
            "provider_id": provider_id,
            "config_present": False,
            "execution_mode": None,
            "enabled": False,
            "live_provider_execution_allowed": False,
            "cost_allowed": False,
            "implementation_status": None,
            "execution_disabled": True,
            "disabled_reasons": reasons,
        }
    if execution_config.enabled is not True:
        reasons.append("provider_execution_config_disabled")
    if execution_config.execution_mode != EXECUTION_MODE_ALLOWED:
        reasons.append("provider_execution_mode_not_allowed")
    if execution_config.live_provider_execution_allowed is not True:
        reasons.append("provider_config_disallows_live_execution")
    if execution_config.cost_allowed is not True:
        reasons.append("provider_config_disallows_cost")
    if authorization_status != "allowed" or not live_provider_execution_authorized:
        reasons.append("provider_authorization_not_live_allowed")
    return {
        "provider_id": provider_id,
        "config_present": True,
        "execution_mode": execution_config.execution_mode,
        "enabled": execution_config.enabled,
        "live_provider_execution_allowed": (
            execution_config.live_provider_execution_allowed
        ),
        "cost_allowed": execution_config.cost_allowed,
        "implementation_status": execution_config.implementation_status,
        "execution_disabled": bool(reasons),
        "disabled_reasons": list(dict.fromkeys(reasons)),
    }


def _receipt_refs(
    *,
    merge_artifact: Mapping[str, Any] | None,
    result_artifact: Mapping[str, Any] | None,
    explicit_refs: Sequence[str] | None,
) -> list[str]:
    refs: list[str] = []
    for value in explicit_refs or ():
        _append_ref(refs, value)
    for receipt in _value(merge_artifact, "guest_candidate_merge_receipts") or ():
        if isinstance(receipt, Mapping):
            _append_ref(refs, receipt.get("receipt_ref"))
    for candidate in _value(merge_artifact, "candidates") or ():
        if isinstance(candidate, Mapping):
            for value in candidate.get("merge_receipt_refs") or ():
                _append_ref(refs, value)
    for container in (
        result_artifact,
        _mapping_value(result_artifact, "provenance"),
    ):
        for key in (
            "receipt_refs",
            "execution_receipt_refs",
            "merge_receipt_refs",
        ):
            for value in _value(container, key) or ():
                _append_ref(refs, value)
    return refs


def _append_ref(refs: list[str], value: Any) -> None:
    text = _safe_optional_text(value)
    if text and text not in refs:
        refs.append(text)


def _mapping_value(
    container: Mapping[str, Any] | None,
    key: str,
) -> Mapping[str, Any] | None:
    value = _value(container, key)
    return value if isinstance(value, Mapping) else None


def _value(container: Mapping[str, Any] | None, key: str) -> Any:
    if not isinstance(container, Mapping):
        return None
    return container.get(key)


def _safe_optional_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return " ".join(value.split())[:240]
    return None


def _safe_text_list(value: Any) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    items: list[str] = []
    for item in value:
        text = _safe_optional_text(item)
        if text and text not in items:
            items.append(text)
    return items


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _safe_non_negative_int(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


def _safe_sequence_count(value: Any) -> int:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return len(value)
    return 0


def _forbidden_paths(value: Any, *, prefix: str = "") -> tuple[str, ...]:
    if isinstance(value, Mapping):
        paths: list[str] = []
        for key, item in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if key_text in FORBIDDEN_DIAGNOSTIC_FIELDS:
                paths.append(path)
            paths.extend(_forbidden_paths(item, prefix=path))
        return tuple(paths)
    if isinstance(value, list | tuple):
        paths = []
        for index, item in enumerate(value):
            paths.extend(_forbidden_paths(item, prefix=f"{prefix}[{index}]"))
        return tuple(paths)
    return ()


__all__ = [
    "FORBIDDEN_DIAGNOSTIC_FIELDS",
    "GUEST_CONTACT_RETRIEVAL_DIAGNOSTIC",
    "build_guest_contact_retrieval_diagnostics",
    "validate_guest_contact_retrieval_diagnostics",
]
