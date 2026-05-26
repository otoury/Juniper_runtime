from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from runtime.registries.external_discovery_provider_registry import (
    ExternalDiscoveryProviderDeclaration,
    get_external_discovery_provider_declaration,
)


RSS_CLOUD_FALLBACK_ELIGIBILITY_POLICY_PATH = Path(
    "agents/shared/semantics/rss_cloud_fallback_eligibility_policy.json"
)
RSS_CLOUD_FALLBACK_ELIGIBILITY_ARTIFACT = "rss_cloud_fallback_eligibility"
PREMIUM_CLOUD_WEB_DEEP_FALLBACK_ELIGIBILITY_ARTIFACT = (
    "premium_cloud_web_deep_fallback_eligibility"
)
FALLBACK_EXECUTION_STATUS_DRY_RUN_ELIGIBLE = "dry_run_eligible"
FALLBACK_EXECUTION_STATUS_DRY_RUN_INELIGIBLE = "dry_run_ineligible"
FALLBACK_EXECUTION_STATUS_DRY_RUN_BLOCKED = "dry_run_blocked"
FALLBACK_TIER_RSS_FIRST = "rss_first"
FALLBACK_TIER_SEARCH_API = "search_api"
FALLBACK_TIER_CLOUD_WEB_DEEP_PREMIUM = "cloud_web_deep_premium"


class RssCloudFallbackEligibilityPolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class RssCloudFallbackTier:
    tier_id: str
    order: int
    provider_type: str
    provider_id: str
    requires_prior_inadequacy: tuple[str, ...]
    active_by_default: bool
    execution_allowed: bool
    premium: bool
    metadata: dict[str, Any]


@dataclass(frozen=True)
class RssCloudFallbackEligibilityPolicy:
    policy_id: str
    source_artifact_type: str
    source_scope: str
    fallback_provider_type: str
    fallback_provider_id: str
    fallback_order: tuple[str, ...]
    fallback_tiers: tuple[RssCloudFallbackTier, ...]
    evaluation_mode: str
    execution_allowed: bool
    eligible_outcomes: tuple[str, ...]
    eligible_insufficiency_reasons: tuple[str, ...]
    blocked_outcome_reasons: dict[str, str]


def evaluate_rss_cloud_fallback_eligibility(
    adequacy_artifact: Mapping[str, Any],
    *,
    policy: RssCloudFallbackEligibilityPolicy | None = None,
    provider_declaration: ExternalDiscoveryProviderDeclaration | None = None,
    root: str | Path | None = None,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    active_policy = policy or load_rss_cloud_fallback_eligibility_policy(root)
    provider = provider_declaration or get_external_discovery_provider_declaration(
        active_policy.fallback_provider_id,
        root=root,
    )
    skipped_reasons: list[str] = []

    if not isinstance(adequacy_artifact, Mapping):
        skipped_reasons.append("rss_adequacy_artifact_missing")
        outcome = None
        insufficiency_reason = None
        source_scope = active_policy.source_scope
    else:
        outcome = _safe_optional_text(adequacy_artifact.get("outcome"))
        insufficiency_reason = _safe_optional_text(
            adequacy_artifact.get("insufficiency_reason")
        )
        source_scope = (
            _safe_optional_text(adequacy_artifact.get("source_scope"))
            or active_policy.source_scope
        )
        if adequacy_artifact.get("artifact_type") != active_policy.source_artifact_type:
            skipped_reasons.append("rss_adequacy_artifact_type_mismatch")
        if source_scope != active_policy.source_scope:
            skipped_reasons.append("rss_source_scope_mismatch")

    provider_metadata = provider.to_metadata() if provider is not None else None
    if provider is None:
        skipped_reasons.append("fallback_provider_declaration_missing")
    elif provider.provider_type != active_policy.fallback_provider_type:
        skipped_reasons.append("fallback_provider_type_mismatch")

    eligible = (
        not skipped_reasons
        and outcome in active_policy.eligible_outcomes
        and insufficiency_reason in active_policy.eligible_insufficiency_reasons
    )
    reason = _eligibility_reason(
        policy=active_policy,
        outcome=outcome,
        insufficiency_reason=insufficiency_reason,
        skipped_reasons=tuple(skipped_reasons),
        eligible=eligible,
    )
    execution_status = _execution_status(
        eligible=eligible,
        skipped_reasons=tuple(skipped_reasons),
    )

    return {
        "artifact_type": RSS_CLOUD_FALLBACK_ELIGIBILITY_ARTIFACT,
        "policy_id": active_policy.policy_id,
        "evaluation_mode": active_policy.evaluation_mode,
        "source_artifact_type": active_policy.source_artifact_type,
        "source_scope": source_scope,
        "fallback_provider_type": active_policy.fallback_provider_type,
        "fallback_provider_id": active_policy.fallback_provider_id,
        "fallback_order": list(active_policy.fallback_order),
        "fallback_tiers": [_tier_to_metadata(tier) for tier in active_policy.fallback_tiers],
        "eligible": eligible,
        "reason": reason,
        "eligibility_reason": reason,
        "rss_adequacy_outcome": outcome,
        "rss_insufficiency_reason": insufficiency_reason,
        "execution_status": execution_status,
        "dry_run": True,
        "dry_run_allowed": True,
        "live_allowed": False,
        "execution_allowed": False,
        "fallback_execution_allowed": False,
        "provider_execution_allowed": False,
        "external_call_performed": False,
        "cost_incurred": False,
        "cloud_web_fallback_triggered": False,
        "evaluated_at": _timestamp(evaluated_at),
        "skipped_reasons": skipped_reasons,
        "provider": provider_metadata,
        "provenance": {
            "kind": "rss_cloud_fallback_eligibility",
            "evaluation_mode": active_policy.evaluation_mode,
            "source_artifact_type": active_policy.source_artifact_type,
            "fallback_provider_type": active_policy.fallback_provider_type,
            "fallback_provider_id": active_policy.fallback_provider_id,
            "external_call_performed": False,
            "cost_incurred": False,
            "cloud_web_fallback_triggered": False,
            "delivery_performed": False,
        },
    }


def evaluate_premium_cloud_web_deep_fallback_eligibility(
    *,
    rss_adequacy_artifact: Mapping[str, Any] | None,
    search_api_adequacy_artifact: Mapping[str, Any] | None,
    policy: RssCloudFallbackEligibilityPolicy | None = None,
    provider_declaration: ExternalDiscoveryProviderDeclaration | None = None,
    root: str | Path | None = None,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    active_policy = policy or load_rss_cloud_fallback_eligibility_policy(root)
    tier = _fallback_tier(
        active_policy,
        FALLBACK_TIER_CLOUD_WEB_DEEP_PREMIUM,
    )
    provider = provider_declaration
    if provider is None and tier is not None:
        provider = get_external_discovery_provider_declaration(
            tier.provider_id,
            root=root,
        )

    skipped_reasons: list[str] = []
    if tier is None:
        skipped_reasons.append("premium_fallback_tier_missing")
    elif not _valid_premium_tier(tier):
        skipped_reasons.append("premium_fallback_tier_contract_failed")

    rss_inadequate = _is_inadequate(
        rss_adequacy_artifact,
        artifact_type=active_policy.source_artifact_type,
    )
    search_api_inadequate = _is_inadequate(search_api_adequacy_artifact)
    if not rss_inadequate:
        skipped_reasons.append("rss_inadequacy_required")
    if not search_api_inadequate:
        skipped_reasons.append("search_api_inadequacy_required")

    if provider is None:
        skipped_reasons.append("premium_provider_declaration_missing")
    elif tier is not None and provider.provider_id != tier.provider_id:
        skipped_reasons.append("premium_provider_id_mismatch")
    elif provider.provider_type != "cloud_ai":
        skipped_reasons.append("premium_provider_type_mismatch")

    eligible = not skipped_reasons
    return {
        "artifact_type": PREMIUM_CLOUD_WEB_DEEP_FALLBACK_ELIGIBILITY_ARTIFACT,
        "policy_id": active_policy.policy_id,
        "evaluation_mode": active_policy.evaluation_mode,
        "fallback_tier": FALLBACK_TIER_CLOUD_WEB_DEEP_PREMIUM,
        "fallback_order": list(active_policy.fallback_order),
        "requires_prior_inadequacy": list(
            tier.requires_prior_inadequacy if tier is not None else ()
        ),
        "rss_inadequate": rss_inadequate,
        "search_api_inadequate": search_api_inadequate,
        "prior_inadequacy_satisfied": rss_inadequate and search_api_inadequate,
        "eligible": eligible,
        "execution_status": (
            FALLBACK_EXECUTION_STATUS_DRY_RUN_ELIGIBLE
            if eligible
            else FALLBACK_EXECUTION_STATUS_DRY_RUN_BLOCKED
        ),
        "active_by_default": False,
        "execution_allowed": False,
        "fallback_execution_allowed": False,
        "provider_execution_allowed": False,
        "live_allowed": False,
        "external_call_performed": False,
        "cost_incurred": False,
        "cloud_web_fallback_triggered": False,
        "explicit_governance_required": True,
        "source_fidelity_required": True,
        "source_refs_required": True,
        "citations_required": True,
        "cost_awareness_required": True,
        "source_normalization_required_before_summary": True,
        "provider": provider.to_metadata() if provider is not None else None,
        "evaluated_at": _timestamp(evaluated_at),
        "skipped_reasons": list(dict.fromkeys(skipped_reasons)),
        "provenance": {
            "kind": "premium_cloud_web_deep_fallback_eligibility",
            "evaluation_mode": active_policy.evaluation_mode,
            "fallback_tier": FALLBACK_TIER_CLOUD_WEB_DEEP_PREMIUM,
            "external_call_performed": False,
            "cost_incurred": False,
            "cloud_web_fallback_triggered": False,
            "delivery_performed": False,
        },
    }


def validate_rss_cloud_fallback_eligibility(artifact: Mapping[str, Any]) -> bool:
    if not isinstance(artifact, Mapping):
        return False
    if artifact.get("artifact_type") != RSS_CLOUD_FALLBACK_ELIGIBILITY_ARTIFACT:
        return False
    if artifact.get("evaluation_mode") != "dry_run":
        return False
    if artifact.get("source_artifact_type") != "rss_coverage_adequacy":
        return False
    if artifact.get("fallback_provider_type") not in {"cloud_ai", "search_api"}:
        return False
    if not _safe_optional_text(artifact.get("fallback_provider_id")):
        return False
    if not _valid_fallback_order(artifact.get("fallback_order")):
        return False
    if not _valid_fallback_tier_metadata(artifact.get("fallback_tiers")):
        return False
    if not _safe_optional_text(artifact.get("eligibility_reason")):
        return False
    if artifact.get("eligible") not in {True, False}:
        return False
    if artifact.get("execution_status") not in {
        FALLBACK_EXECUTION_STATUS_DRY_RUN_ELIGIBLE,
        FALLBACK_EXECUTION_STATUS_DRY_RUN_INELIGIBLE,
        FALLBACK_EXECUTION_STATUS_DRY_RUN_BLOCKED,
    }:
        return False
    for key in (
        "execution_allowed",
        "fallback_execution_allowed",
        "provider_execution_allowed",
        "live_allowed",
        "external_call_performed",
        "cost_incurred",
        "cloud_web_fallback_triggered",
    ):
        if artifact.get(key) is not False:
            return False
    if artifact.get("dry_run") is not True:
        return False
    if artifact.get("dry_run_allowed") is not True:
        return False
    provenance = artifact.get("provenance")
    if not isinstance(provenance, Mapping):
        return False
    if provenance.get("cloud_web_fallback_triggered") is not False:
        return False
    if provenance.get("external_call_performed") is not False:
        return False
    return isinstance(artifact.get("skipped_reasons"), list)


def validate_premium_cloud_web_deep_fallback_eligibility(
    artifact: Mapping[str, Any],
) -> bool:
    if not isinstance(artifact, Mapping):
        return False
    if artifact.get("artifact_type") != (
        PREMIUM_CLOUD_WEB_DEEP_FALLBACK_ELIGIBILITY_ARTIFACT
    ):
        return False
    if artifact.get("evaluation_mode") != "dry_run":
        return False
    if artifact.get("fallback_tier") != FALLBACK_TIER_CLOUD_WEB_DEEP_PREMIUM:
        return False
    if not _valid_fallback_order(artifact.get("fallback_order")):
        return False
    if artifact.get("requires_prior_inadequacy") != [
        FALLBACK_TIER_RSS_FIRST,
        FALLBACK_TIER_SEARCH_API,
    ]:
        return False
    if artifact.get("prior_inadequacy_satisfied") != (
        artifact.get("rss_inadequate") is True
        and artifact.get("search_api_inadequate") is True
    ):
        return False
    for key in (
        "active_by_default",
        "execution_allowed",
        "fallback_execution_allowed",
        "provider_execution_allowed",
        "live_allowed",
        "external_call_performed",
        "cost_incurred",
        "cloud_web_fallback_triggered",
    ):
        if artifact.get(key) is not False:
            return False
    for key in (
        "explicit_governance_required",
        "source_fidelity_required",
        "source_refs_required",
        "citations_required",
        "cost_awareness_required",
        "source_normalization_required_before_summary",
    ):
        if artifact.get(key) is not True:
            return False
    provider = artifact.get("provider")
    if provider is not None:
        if not isinstance(provider, Mapping):
            return False
        if provider.get("provider_id") != FALLBACK_TIER_CLOUD_WEB_DEEP_PREMIUM:
            return False
        if provider.get("provider_type") != "cloud_ai":
            return False
        if provider.get("execution_allowed") is not False:
            return False
    provenance = artifact.get("provenance")
    if not isinstance(provenance, Mapping):
        return False
    if provenance.get("external_call_performed") is not False:
        return False
    if provenance.get("cloud_web_fallback_triggered") is not False:
        return False
    return isinstance(artifact.get("skipped_reasons"), list)


@lru_cache(maxsize=None)
def load_rss_cloud_fallback_eligibility_policy(
    root: str | Path | None = None,
) -> RssCloudFallbackEligibilityPolicy:
    try:
        data = json.loads(_policy_path(root).read_text(encoding="utf-8"))
        return _policy_from_data(data)
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        RssCloudFallbackEligibilityPolicyError,
    ):
        return _blocked_policy()


def _policy_path(root: str | Path | None = None) -> Path:
    if root is None:
        return RSS_CLOUD_FALLBACK_ELIGIBILITY_POLICY_PATH
    return Path(root) / RSS_CLOUD_FALLBACK_ELIGIBILITY_POLICY_PATH


def _policy_from_data(data: Any) -> RssCloudFallbackEligibilityPolicy:
    if not isinstance(data, dict) or data.get("version") != 1:
        raise RssCloudFallbackEligibilityPolicyError(
            "RSS cloud fallback eligibility policy version must be 1."
        )
    if data.get("evaluation_mode") != "dry_run":
        raise RssCloudFallbackEligibilityPolicyError(
            "RSS cloud fallback eligibility policy must be dry-run."
        )
    if data.get("execution_allowed") is not False:
        raise RssCloudFallbackEligibilityPolicyError(
            "RSS cloud fallback eligibility policy must not allow execution."
        )
    policy = RssCloudFallbackEligibilityPolicy(
        policy_id=_required_text(data.get("policy_id")),
        source_artifact_type=_required_text(data.get("source_artifact_type")),
        source_scope=_required_text(data.get("source_scope")),
        fallback_provider_type=_required_text(data.get("fallback_provider_type")),
        fallback_provider_id=_required_text(data.get("fallback_provider_id")),
        fallback_order=_fallback_order(data.get("fallback_order")),
        fallback_tiers=_fallback_tiers(data.get("fallback_tiers")),
        evaluation_mode="dry_run",
        execution_allowed=False,
        eligible_outcomes=_text_tuple(data.get("eligible_outcomes")),
        eligible_insufficiency_reasons=_text_tuple(
            data.get("eligible_insufficiency_reasons")
        ),
        blocked_outcome_reasons={
            _required_text(key): _required_text(value)
            for key, value in _object(data.get("blocked_outcome_reasons")).items()
        },
    )
    _validate_fallback_tiers(policy)
    return policy


def _blocked_policy() -> RssCloudFallbackEligibilityPolicy:
    return RssCloudFallbackEligibilityPolicy(
        policy_id="rss_cloud_fallback_eligibility_blocked_fallback",
        source_artifact_type="rss_coverage_adequacy",
        source_scope="rss_metadata_cache",
        fallback_provider_type="search_api",
        fallback_provider_id="search_api",
        fallback_order=(
            FALLBACK_TIER_RSS_FIRST,
            FALLBACK_TIER_SEARCH_API,
            FALLBACK_TIER_CLOUD_WEB_DEEP_PREMIUM,
        ),
        fallback_tiers=(),
        evaluation_mode="dry_run",
        execution_allowed=False,
        eligible_outcomes=(),
        eligible_insufficiency_reasons=(),
        blocked_outcome_reasons={
            "adequate": "rss_coverage_adequate",
            "unknown": "rss_coverage_unknown",
        },
    )


def _fallback_order(value: Any) -> tuple[str, ...]:
    order = _text_tuple(value)
    if order != (
        FALLBACK_TIER_RSS_FIRST,
        FALLBACK_TIER_SEARCH_API,
        FALLBACK_TIER_CLOUD_WEB_DEEP_PREMIUM,
    ):
        raise RssCloudFallbackEligibilityPolicyError(
            "RSS cloud fallback order must be rss_first, search_api, "
            "cloud_web_deep_premium."
        )
    return order


def _fallback_tiers(value: Any) -> tuple[RssCloudFallbackTier, ...]:
    if not isinstance(value, list):
        raise RssCloudFallbackEligibilityPolicyError(
            "RSS cloud fallback tiers must be a list."
        )
    tiers = []
    for item in value:
        data = _object(item)
        tier_id = _required_text(data.get("tier_id"))
        tiers.append(
            RssCloudFallbackTier(
                tier_id=tier_id,
                order=_required_int(data.get("order")),
                provider_type=_required_text(data.get("provider_type")),
                provider_id=_required_text(data.get("provider_id")),
                requires_prior_inadequacy=_text_tuple(
                    data.get("requires_prior_inadequacy")
                ),
                active_by_default=_required_bool(data.get("active_by_default")),
                execution_allowed=_required_bool(data.get("execution_allowed")),
                premium=_required_bool(data.get("premium")),
                metadata={
                    key: value
                    for key, value in data.items()
                    if key
                    not in {
                        "tier_id",
                        "order",
                        "provider_type",
                        "provider_id",
                        "requires_prior_inadequacy",
                        "active_by_default",
                        "execution_allowed",
                        "premium",
                    }
                },
            )
        )
    return tuple(tiers)


def _validate_fallback_tiers(policy: RssCloudFallbackEligibilityPolicy) -> None:
    by_id = {tier.tier_id: tier for tier in policy.fallback_tiers}
    if tuple(by_id) != policy.fallback_order:
        raise RssCloudFallbackEligibilityPolicyError(
            "RSS cloud fallback tiers must match fallback_order."
        )
    expected_prior = {
        FALLBACK_TIER_RSS_FIRST: (),
        FALLBACK_TIER_SEARCH_API: (FALLBACK_TIER_RSS_FIRST,),
        FALLBACK_TIER_CLOUD_WEB_DEEP_PREMIUM: (
            FALLBACK_TIER_RSS_FIRST,
            FALLBACK_TIER_SEARCH_API,
        ),
    }
    for index, tier_id in enumerate(policy.fallback_order, start=1):
        tier = by_id[tier_id]
        if tier.order != index:
            raise RssCloudFallbackEligibilityPolicyError(
                "RSS cloud fallback tier order must be consecutive."
            )
        if tier.requires_prior_inadequacy != expected_prior[tier_id]:
            raise RssCloudFallbackEligibilityPolicyError(
                "RSS cloud fallback tier prior inadequacy chain is invalid."
            )
    search_tier = by_id[FALLBACK_TIER_SEARCH_API]
    if search_tier.provider_type != "search_api" or search_tier.execution_allowed:
        raise RssCloudFallbackEligibilityPolicyError(
            "Search API fallback tier must be non-executing search_api."
        )
    premium_tier = by_id[FALLBACK_TIER_CLOUD_WEB_DEEP_PREMIUM]
    if not _valid_premium_tier(premium_tier):
        raise RssCloudFallbackEligibilityPolicyError(
            "Premium cloud_web_deep fallback tier is missing governance, "
            "source fidelity, citation, or cost requirements."
        )


def _valid_premium_tier(tier: RssCloudFallbackTier) -> bool:
    return (
        tier.provider_type == "cloud_ai"
        and tier.provider_id == FALLBACK_TIER_CLOUD_WEB_DEEP_PREMIUM
        and tier.active_by_default is False
        and tier.execution_allowed is False
        and tier.premium is True
        and tier.metadata.get("provider_capability") == "cloud_web_deep"
        and tier.metadata.get("explicit_governance_required") is True
        and tier.metadata.get("source_fidelity_required") is True
        and tier.metadata.get("source_refs_required") is True
        and tier.metadata.get("citations_required") is True
        and tier.metadata.get("cost_awareness_required") is True
        and tier.metadata.get("source_normalization_required_before_summary") is True
    )


def _fallback_tier(
    policy: RssCloudFallbackEligibilityPolicy,
    tier_id: str,
) -> RssCloudFallbackTier | None:
    for tier in policy.fallback_tiers:
        if tier.tier_id == tier_id:
            return tier
    return None


def _tier_to_metadata(tier: RssCloudFallbackTier) -> dict[str, Any]:
    return {
        "tier_id": tier.tier_id,
        "order": tier.order,
        "provider_type": tier.provider_type,
        "provider_id": tier.provider_id,
        "requires_prior_inadequacy": list(tier.requires_prior_inadequacy),
        "active_by_default": tier.active_by_default,
        "execution_allowed": tier.execution_allowed,
        "premium": tier.premium,
        **dict(tier.metadata),
    }


def _valid_fallback_order(value: Any) -> bool:
    return value == [
        FALLBACK_TIER_RSS_FIRST,
        FALLBACK_TIER_SEARCH_API,
        FALLBACK_TIER_CLOUD_WEB_DEEP_PREMIUM,
    ]


def _valid_fallback_tier_metadata(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 3:
        return False
    by_id = {
        item.get("tier_id"): item
        for item in value
        if isinstance(item, Mapping)
    }
    if set(by_id) != {
        FALLBACK_TIER_RSS_FIRST,
        FALLBACK_TIER_SEARCH_API,
        FALLBACK_TIER_CLOUD_WEB_DEEP_PREMIUM,
    }:
        return False
    premium = by_id[FALLBACK_TIER_CLOUD_WEB_DEEP_PREMIUM]
    return (
        premium.get("active_by_default") is False
        and premium.get("execution_allowed") is False
        and premium.get("premium") is True
        and premium.get("requires_prior_inadequacy")
        == [FALLBACK_TIER_RSS_FIRST, FALLBACK_TIER_SEARCH_API]
        and premium.get("explicit_governance_required") is True
        and premium.get("source_fidelity_required") is True
        and premium.get("source_refs_required") is True
        and premium.get("citations_required") is True
        and premium.get("cost_awareness_required") is True
        and premium.get("source_normalization_required_before_summary") is True
    )


def _is_inadequate(
    value: Mapping[str, Any] | None,
    *,
    artifact_type: str | None = None,
) -> bool:
    if not isinstance(value, Mapping):
        return False
    if artifact_type is not None and value.get("artifact_type") != artifact_type:
        return False
    if value.get("outcome") == "inadequate":
        return True
    if value.get("adequate") is False:
        return True
    return value.get("eligible") is True and value.get("execution_status") in {
        FALLBACK_EXECUTION_STATUS_DRY_RUN_ELIGIBLE,
        "inadequate",
    }


def _eligibility_reason(
    *,
    policy: RssCloudFallbackEligibilityPolicy,
    outcome: str | None,
    insufficiency_reason: str | None,
    skipped_reasons: tuple[str, ...],
    eligible: bool,
) -> str:
    if skipped_reasons:
        return skipped_reasons[0]
    if eligible:
        return insufficiency_reason or "rss_coverage_inadequate"
    if outcome in policy.blocked_outcome_reasons:
        return policy.blocked_outcome_reasons[outcome]
    if outcome in policy.eligible_outcomes:
        return "rss_insufficiency_reason_not_eligible"
    return "rss_coverage_outcome_not_eligible"


def _execution_status(*, eligible: bool, skipped_reasons: tuple[str, ...]) -> str:
    if skipped_reasons:
        return FALLBACK_EXECUTION_STATUS_DRY_RUN_BLOCKED
    if eligible:
        return FALLBACK_EXECUTION_STATUS_DRY_RUN_ELIGIBLE
    return FALLBACK_EXECUTION_STATUS_DRY_RUN_INELIGIBLE


def _timestamp(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def _required_text(value: Any) -> str:
    text = _safe_optional_text(value)
    if not text:
        raise RssCloudFallbackEligibilityPolicyError(
            "RSS cloud fallback eligibility policy text fields must be non-empty."
        )
    return text


def _required_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RssCloudFallbackEligibilityPolicyError(
            "RSS cloud fallback eligibility policy integer fields must be positive."
        )
    return value


def _required_bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise RssCloudFallbackEligibilityPolicyError(
            "RSS cloud fallback eligibility policy boolean fields must be boolean."
        )
    return value


def _safe_optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


def _text_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        _safe_optional_text(item) is None for item in value
    ):
        raise RssCloudFallbackEligibilityPolicyError(
            "RSS cloud fallback eligibility policy lists must contain text."
        )
    return tuple(_required_text(item) for item in value)


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RssCloudFallbackEligibilityPolicyError(
            "RSS cloud fallback eligibility policy objects must be objects."
        )
    return dict(value)


__all__ = [
    "FALLBACK_EXECUTION_STATUS_DRY_RUN_BLOCKED",
    "FALLBACK_EXECUTION_STATUS_DRY_RUN_ELIGIBLE",
    "FALLBACK_EXECUTION_STATUS_DRY_RUN_INELIGIBLE",
    "FALLBACK_TIER_CLOUD_WEB_DEEP_PREMIUM",
    "FALLBACK_TIER_RSS_FIRST",
    "FALLBACK_TIER_SEARCH_API",
    "PREMIUM_CLOUD_WEB_DEEP_FALLBACK_ELIGIBILITY_ARTIFACT",
    "RSS_CLOUD_FALLBACK_ELIGIBILITY_ARTIFACT",
    "RssCloudFallbackTier",
    "RssCloudFallbackEligibilityPolicy",
    "evaluate_premium_cloud_web_deep_fallback_eligibility",
    "evaluate_rss_cloud_fallback_eligibility",
    "load_rss_cloud_fallback_eligibility_policy",
    "validate_premium_cloud_web_deep_fallback_eligibility",
    "validate_rss_cloud_fallback_eligibility",
]
