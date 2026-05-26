from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from runtime.policies.cloud_provider_authorization import (
    CloudProviderAuthorizationInput,
    CloudProviderAuthorizationPolicy,
    evaluate_cloud_provider_authorization,
)
from runtime.execution_classes import (
    EXECUTION_CLASS_PAID_CLOUD_MODEL,
    evaluate_execution_class_dry_run,
)
from runtime.policies.rss_cloud_fallback_eligibility import (
    RSS_CLOUD_FALLBACK_ELIGIBILITY_ARTIFACT,
    validate_rss_cloud_fallback_eligibility,
)
from runtime.registries.external_discovery_provider_registry import (
    ExternalDiscoveryProviderDeclaration,
    get_external_discovery_provider_declaration,
)


RSS_CLOUD_ESCALATION_RESULT_ARTIFACT = "rss_cloud_escalation_result"
ESCALATION_STATUS_NOT_ELIGIBLE = "not_eligible"
ESCALATION_STATUS_BLOCKED = "blocked"
ESCALATION_STATUS_READY = "ready"
ESCALATION_STATUS_EXECUTED = "executed"


@dataclass(frozen=True)
class RssCloudEscalationMaterialization:
    artifact: dict[str, Any]
    materialized: bool
    transition_outcome: str
    skipped_reasons: tuple[str, ...]
    audit_summary: dict[str, Any]

    def to_audit_record(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact.get("artifact_type"),
            "materialized": self.materialized,
            "transition_outcome": self.transition_outcome,
            "skipped_reasons": list(self.skipped_reasons),
            "audit_summary": dict(self.audit_summary),
        }


def materialize_rss_cloud_escalation(
    *,
    adequacy_artifact: Mapping[str, Any],
    workflow_id: str,
    request_query: str,
    agent_id: str | None = None,
    actor_id: str | None = None,
    user_id: str | None = None,
    channel: str | None = None,
    request_source: str | None = None,
    is_test_context: bool = False,
    cloud_dry_run: bool = True,
    authorization_policy: CloudProviderAuthorizationPolicy | None = None,
    provider_declaration: ExternalDiscoveryProviderDeclaration | None = None,
    generated_at: datetime | None = None,
    root: str | None = None,
) -> RssCloudEscalationMaterialization:
    eligibility = (
        adequacy_artifact.get("fallback_eligibility")
        if isinstance(adequacy_artifact, Mapping)
        else None
    )
    skipped_reasons: list[str] = []
    if not validate_rss_cloud_fallback_eligibility(eligibility):
        skipped_reasons.append("fallback_eligibility_contract_failed")

    provider_id = (
        eligibility.get("fallback_provider_id")
        if isinstance(eligibility, Mapping)
        else None
    )
    provider = provider_declaration
    if provider is None and isinstance(provider_id, str) and provider_id.strip():
        provider = get_external_discovery_provider_declaration(
            provider_id.strip(),
            root=root,
        )
    if provider is None:
        skipped_reasons.append("fallback_provider_declaration_missing")
    elif provider.provider_type != "cloud_ai":
        skipped_reasons.append("fallback_provider_type_not_cloud_ai")

    eligible = bool(
        isinstance(eligibility, Mapping)
        and eligibility.get("eligible") is True
        and not skipped_reasons
    )
    authorization = evaluate_cloud_provider_authorization(
        CloudProviderAuthorizationInput(
            provider_id=provider_id if isinstance(provider_id, str) else None,
            agent_id=agent_id,
            channel=channel,
            request_source=request_source,
            actor_id=actor_id,
            user_id=user_id,
            is_test_context=is_test_context,
            cloud_dry_run=cloud_dry_run,
            governance_state=(
                provider.governance_state if provider is not None else None
            ),
        ),
        policy=authorization_policy,
        root=root,
    ).to_metadata()

    if not eligible and "rss_fallback_not_eligible" not in skipped_reasons:
        skipped_reasons.append("rss_fallback_not_eligible")

    if eligible and authorization.get("live_execution_authorized") is not True:
        skipped_reasons.extend(_string_list(authorization.get("skipped_reasons")))
    dry_run_decision = evaluate_execution_class_dry_run(
        EXECUTION_CLASS_PAID_CLOUD_MODEL,
        dry_run=cloud_dry_run,
    )
    if dry_run_decision.allowed is False:
        skipped_reasons.append(dry_run_decision.reason)

    external_call_allowed = bool(
        eligible
        and authorization.get("live_execution_authorized") is True
        and authorization.get("external_call_allowed") is True
        and dry_run_decision.allowed is True
    )
    status = _status(
        eligible=eligible,
        external_call_allowed=external_call_allowed,
        skipped_reasons=tuple(skipped_reasons),
    )
    artifact = {
        "artifact_type": RSS_CLOUD_ESCALATION_RESULT_ARTIFACT,
        "workflow_id": _safe_text(workflow_id, limit=120),
        "source_artifact_type": adequacy_artifact.get("artifact_type"),
        "source_scope": adequacy_artifact.get("source_scope"),
        "generated_at": _timestamp(generated_at),
        "request_query": _safe_text(request_query, limit=500),
        "status": status,
        "execution_class": dry_run_decision.execution_class,
        "dry_run_effect": dry_run_decision.dry_run_effect,
        "execution_class_allowed": dry_run_decision.allowed,
        "execution_class_reason": dry_run_decision.reason,
        "eligible": eligible,
        "execution_allowed": external_call_allowed,
        "external_call_performed": False,
        "cost_incurred": False,
        "delivery_performed": False,
        "fallback_eligibility": dict(eligibility)
        if isinstance(eligibility, Mapping)
        else None,
        "provider": provider.to_metadata() if provider is not None else None,
        "authorization": authorization,
        "skipped_reasons": list(dict.fromkeys(skipped_reasons)),
        "provenance": {
            "kind": "rss_cloud_escalation",
            "source_artifact_type": adequacy_artifact.get("artifact_type"),
            "source_scope": adequacy_artifact.get("source_scope"),
            "fallback_eligibility_artifact_type": (
                eligibility.get("artifact_type")
                if isinstance(eligibility, Mapping)
                else None
            ),
            "cloud_web_fallback_triggered": False,
            "external_call_performed": False,
            "cost_incurred": False,
            "delivery_performed": False,
        },
    }
    materialized = validate_rss_cloud_escalation_result(artifact)
    return RssCloudEscalationMaterialization(
        artifact=artifact,
        materialized=materialized,
        transition_outcome="success" if materialized else "failure",
        skipped_reasons=tuple(artifact["skipped_reasons"]),
        audit_summary=_audit_summary(artifact),
    )


def validate_rss_cloud_escalation_result(artifact: Mapping[str, Any]) -> bool:
    if not isinstance(artifact, Mapping):
        return False
    if artifact.get("artifact_type") != RSS_CLOUD_ESCALATION_RESULT_ARTIFACT:
        return False
    if artifact.get("status") not in {
        ESCALATION_STATUS_NOT_ELIGIBLE,
        ESCALATION_STATUS_BLOCKED,
        ESCALATION_STATUS_READY,
        ESCALATION_STATUS_EXECUTED,
    }:
        return False
    for field in ("workflow_id", "source_artifact_type", "source_scope", "generated_at"):
        if not _safe_text(artifact.get(field), limit=500):
            return False
    if artifact.get("external_call_performed") is not False:
        return False
    if artifact.get("cost_incurred") is not False:
        return False
    if artifact.get("delivery_performed") is not False:
        return False
    if artifact.get("execution_allowed") not in {True, False}:
        return False
    if artifact.get("eligible") not in {True, False}:
        return False
    eligibility = artifact.get("fallback_eligibility")
    if eligibility is not None and not validate_rss_cloud_fallback_eligibility(
        eligibility
    ):
        return False
    authorization = artifact.get("authorization")
    provenance = artifact.get("provenance")
    if not isinstance(authorization, Mapping):
        return False
    if not isinstance(provenance, Mapping):
        return False
    if provenance.get("fallback_eligibility_artifact_type") not in {
        None,
        RSS_CLOUD_FALLBACK_ELIGIBILITY_ARTIFACT,
    }:
        return False
    if provenance.get("cloud_web_fallback_triggered") is not False:
        return False
    if provenance.get("external_call_performed") is not False:
        return False
    return isinstance(artifact.get("skipped_reasons"), list)


def _status(
    *,
    eligible: bool,
    external_call_allowed: bool,
    skipped_reasons: tuple[str, ...],
) -> str:
    if external_call_allowed:
        return ESCALATION_STATUS_READY
    if not eligible:
        return ESCALATION_STATUS_NOT_ELIGIBLE
    if skipped_reasons:
        return ESCALATION_STATUS_BLOCKED
    return ESCALATION_STATUS_BLOCKED


def _audit_summary(artifact: Mapping[str, Any]) -> dict[str, Any]:
    authorization = artifact.get("authorization")
    return {
        "artifact_type": artifact.get("artifact_type"),
        "workflow_id": artifact.get("workflow_id"),
        "status": artifact.get("status"),
        "eligible": artifact.get("eligible"),
        "execution_allowed": artifact.get("execution_allowed"),
        "external_call_performed": artifact.get("external_call_performed"),
        "cost_incurred": artifact.get("cost_incurred"),
        "authorization_status": (
            authorization.get("authorization_status")
            if isinstance(authorization, Mapping)
            else None
        ),
        "skipped_reasons": list(artifact.get("skipped_reasons", [])),
    }


def _timestamp(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def _safe_text(value: Any, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    ]


__all__ = [
    "ESCALATION_STATUS_BLOCKED",
    "ESCALATION_STATUS_EXECUTED",
    "ESCALATION_STATUS_NOT_ELIGIBLE",
    "ESCALATION_STATUS_READY",
    "RSS_CLOUD_ESCALATION_RESULT_ARTIFACT",
    "RssCloudEscalationMaterialization",
    "materialize_rss_cloud_escalation",
    "validate_rss_cloud_escalation_result",
]
