from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from runtime.adapters.external_search_provider_execution import (
    EXECUTION_MODE_ALLOWED,
    get_external_search_provider_execution_config,
)
from runtime.policies.external_search_provider_authorization import (
    ExternalSearchProviderAuthorizationInput,
    evaluate_external_search_provider_authorization,
)
from runtime.governance.visibility_isolation import (
    validate_diagnostic_visibility_surface,
)


LATEST_NEWS_RETRIEVAL_DIAGNOSTIC = "latest_news_retrieval_decision"
FORBIDDEN_DIAGNOSTIC_FIELDS = frozenset(
    {
        "api_key",
        "article_body",
        "authorization_header",
        "bearer_token",
        "citations",
        "credential",
        "credential_env_var",
        "link",
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


def build_latest_news_retrieval_diagnostics(
    *,
    adequacy_artifact: Mapping[str, Any] | None,
    result_artifact: Mapping[str, Any] | None = None,
    execution_receipt_refs: Sequence[str] | None = None,
    root: str | None = None,
) -> dict[str, Any]:
    fallback = _mapping_value(adequacy_artifact, "fallback_eligibility")
    governance = _mapping_value(adequacy_artifact, "external_live_retrieval_governance")
    handoff = _mapping_value(adequacy_artifact, "external_search_handoff")
    provider_id = _safe_optional_text(
        _first_present(
            _value(fallback, "fallback_provider_id"),
            _value(governance, "fallback_provider_id"),
        )
    )
    authorization = evaluate_external_search_provider_authorization(
        ExternalSearchProviderAuthorizationInput(provider_id=provider_id),
        root=root,
    )
    execution_config = (
        get_external_search_provider_execution_config(provider_id, root=root)
        if provider_id
        else None
    )
    receipt_refs = _receipt_refs(
        result_artifact=result_artifact,
        explicit_refs=execution_receipt_refs,
    )

    return {
        "diagnostic_type": LATEST_NEWS_RETRIEVAL_DIAGNOSTIC,
        "workflow_id": _safe_optional_text(_value(adequacy_artifact, "workflow_id")),
        "semantic_boundary": "rss_first_then_governed_external_search",
        "operator_report": True,
        "observational_only": True,
        "retrieval_executed": False,
        "external_call_performed": False,
        "artifact_mutation_performed": False,
        "workflow_state_mutation_performed": False,
        "hidden_context_injection_performed": False,
        "planner_semantic_authority": False,
        "rss_adequacy": _rss_adequacy_summary(adequacy_artifact),
        "escalation_governance": _escalation_summary(
            fallback=fallback,
            governance=governance,
        ),
        "handoff": _handoff_summary(handoff),
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
            provider_id=provider_id,
            execution_config=execution_config,
            authorization_status=authorization.authorization_status,
            live_provider_execution_authorized=(
                authorization.live_provider_execution_authorized
            ),
        ),
        "receipt_refs": receipt_refs,
        "content_safety": {
            "content_fields_suppressed": True,
            "query_suppressed": True,
            "raw_results_suppressed": True,
            "source_refs_suppressed": True,
            "citations_suppressed": True,
            "receipt_refs_allowed": True,
        },
    }


def validate_latest_news_retrieval_diagnostics(payload: Any) -> bool:
    if not isinstance(payload, Mapping):
        return False
    if payload.get("diagnostic_type") != LATEST_NEWS_RETRIEVAL_DIAGNOSTIC:
        return False
    for field in (
        "observational_only",
        "content_safety",
    ):
        if field not in payload:
            return False
    for field in (
        "retrieval_executed",
        "external_call_performed",
        "artifact_mutation_performed",
        "workflow_state_mutation_performed",
        "hidden_context_injection_performed",
        "planner_semantic_authority",
    ):
        if payload.get(field) is not False:
            return False
    if payload.get("observational_only") is not True:
        return False
    if _forbidden_paths(payload):
        return False
    if validate_diagnostic_visibility_surface(payload)["allowed"] is not True:
        return False
    for field in (
        "rss_adequacy",
        "escalation_governance",
        "handoff",
        "provider_authorization",
        "execution_disabled_state",
        "content_safety",
    ):
        if not isinstance(payload.get(field), Mapping):
            return False
    if not isinstance(payload.get("receipt_refs"), list):
        return False
    return True


def _rss_adequacy_summary(
    adequacy_artifact: Mapping[str, Any] | None,
) -> dict[str, Any]:
    metrics = _mapping_value(adequacy_artifact, "metrics")
    return {
        "artifact_type": _safe_optional_text(_value(adequacy_artifact, "artifact_type")),
        "outcome": _safe_optional_text(_value(adequacy_artifact, "outcome")),
        "adequate": _optional_bool(_value(adequacy_artifact, "adequate")),
        "source_scope": _safe_optional_text(_value(adequacy_artifact, "source_scope")),
        "insufficiency_reason": _safe_optional_text(
            _value(adequacy_artifact, "insufficiency_reason")
        ),
        "fresh_item_count": _safe_non_negative_int(
            _value(metrics, "fresh_item_count")
        ),
        "candidate_item_count": _safe_non_negative_int(
            _value(metrics, "candidate_item_count")
        ),
        "topic_matched_item_count": _safe_non_negative_int(
            _value(metrics, "topic_matched_item_count")
        ),
        "source_count": _safe_non_negative_int(_value(metrics, "source_count")),
        "source_ref_count": _safe_sequence_count(
            _value(adequacy_artifact, "source_refs")
        ),
    }


def _escalation_summary(
    *,
    fallback: Mapping[str, Any] | None,
    governance: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "fallback_eligible": _optional_bool(_value(fallback, "eligible")),
        "fallback_execution_status": _safe_optional_text(
            _value(fallback, "execution_status")
        ),
        "fallback_provider_type": _safe_optional_text(
            _value(fallback, "fallback_provider_type")
        ),
        "fallback_provider_id": _safe_optional_text(
            _value(fallback, "fallback_provider_id")
        ),
        "fallback_live_allowed": _optional_bool(_value(fallback, "live_allowed")),
        "governance_status": _safe_optional_text(_value(governance, "status")),
        "governance_live_allowed": _optional_bool(_value(governance, "live_allowed")),
        "governance_external_call_allowed": _optional_bool(
            _value(governance, "external_call_allowed")
        ),
        "explicit_live_request": _optional_bool(
            _value(governance, "explicit_live_request")
        ),
        "governance_skipped_reasons": _safe_text_list(
            _value(governance, "skipped_reasons")
        ),
    }


def _handoff_summary(handoff: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        "status": _safe_optional_text(_value(handoff, "status")),
        "eligible": _optional_bool(_value(handoff, "handoff_eligible")),
        "reason_codes": _safe_text_list(_value(handoff, "reason_codes")),
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
    result_artifact: Mapping[str, Any] | None,
    explicit_refs: Sequence[str] | None,
) -> list[str]:
    refs: list[str] = []
    for value in explicit_refs or ():
        text = _safe_optional_text(value)
        if text and text not in refs:
            refs.append(text)
    for container in (
        result_artifact,
        _mapping_value(result_artifact, "provenance"),
    ):
        for value in _value(container, "execution_receipt_refs") or ():
            text = _safe_optional_text(value)
            if text and text not in refs:
                refs.append(text)
    return refs


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


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


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
    "LATEST_NEWS_RETRIEVAL_DIAGNOSTIC",
    "build_latest_news_retrieval_diagnostics",
    "validate_latest_news_retrieval_diagnostics",
]
