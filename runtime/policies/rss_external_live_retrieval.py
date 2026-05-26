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


RSS_EXTERNAL_LIVE_RETRIEVAL_POLICY_PATH = Path(
    "agents/shared/governance/rss_external_live_retrieval_policy.json"
)
RSS_EXTERNAL_LIVE_RETRIEVAL_GOVERNANCE_ARTIFACT = (
    "rss_external_live_retrieval_governance"
)
LIVE_RETRIEVAL_STATUS_ALLOWED = "live_allowed"
LIVE_RETRIEVAL_STATUS_BLOCKED = "blocked"
LIVE_RETRIEVAL_STATUS_NOT_APPLICABLE = "not_applicable"
AUTHORIZATION_MODE_BLOCKED = "blocked"
AUTHORIZATION_MODE_ALL_TELEGRAM_USERS = "all_telegram_users"
AUTHORIZATION_MODE_ALLOWLISTED_TELEGRAM_USER_IDS = (
    "allowlisted_telegram_user_ids"
)
ALLOWED_AUTHORIZATION_MODES = {
    AUTHORIZATION_MODE_BLOCKED,
    AUTHORIZATION_MODE_ALL_TELEGRAM_USERS,
    AUTHORIZATION_MODE_ALLOWLISTED_TELEGRAM_USER_IDS,
}


class RssExternalLiveRetrievalPolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class RssExternalLiveRetrievalPolicy:
    policy_id: str
    source_artifact_type: str
    source_scope: str
    default_mode: str
    recognized_channels: tuple[str, ...]
    blocked_channels: tuple[str, ...]
    blocked_request_sources: tuple[str, ...]
    test_context_blocked: bool
    dry_run_forced_when_cloud_dry_run: bool
    require_explicit_live_request: bool
    require_rss_inadequacy: bool
    require_fallback_eligibility: bool
    require_provider_live_governance: bool
    require_source_refs: bool
    require_citations: bool
    require_cost_awareness: bool
    provider_policies: dict[str, dict[str, Any]]


def evaluate_rss_external_live_retrieval_governance(
    *,
    adequacy_artifact: Mapping[str, Any] | None,
    fallback_eligibility: Mapping[str, Any] | None = None,
    provider_declaration: ExternalDiscoveryProviderDeclaration | None = None,
    policy: RssExternalLiveRetrievalPolicy | None = None,
    root: str | Path | None = None,
    channel: str | None = None,
    request_source: str | None = None,
    actor_id: str | None = None,
    user_id: str | None = None,
    is_test_context: bool = False,
    cloud_dry_run: bool = False,
    workflow_dry_run: bool = False,
    explicit_live_request: bool = False,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    active_policy = policy or load_rss_external_live_retrieval_policy(root)
    eligibility = (
        fallback_eligibility
        if isinstance(fallback_eligibility, Mapping)
        else (
            adequacy_artifact.get("fallback_eligibility")
            if isinstance(adequacy_artifact, Mapping)
            else None
        )
    )
    provider_id = (
        _safe_optional_text(eligibility.get("fallback_provider_id"))
        if isinstance(eligibility, Mapping)
        else None
    )
    provider = provider_declaration
    if provider is None and provider_id:
        provider = get_external_discovery_provider_declaration(
            provider_id,
            root=root,
        )

    normalized_channel = _normalized_optional_text(channel)
    normalized_request_source = _normalized_optional_text(request_source)
    normalized_user_id = _safe_optional_text(user_id) or _safe_optional_text(actor_id)
    mode = _provider_mode(active_policy, provider_id)
    skipped_reasons: list[str] = []

    source_scope = (
        _safe_optional_text(adequacy_artifact.get("source_scope"))
        if isinstance(adequacy_artifact, Mapping)
        else active_policy.source_scope
    ) or active_policy.source_scope
    rss_inadequate = _rss_inadequate(
        adequacy_artifact,
        source_artifact_type=active_policy.source_artifact_type,
        source_scope=active_policy.source_scope,
    )

    if active_policy.require_rss_inadequacy and not rss_inadequate:
        skipped_reasons.append("rss_inadequacy_required")
    if active_policy.require_fallback_eligibility and not (
        isinstance(eligibility, Mapping) and eligibility.get("eligible") is True
    ):
        skipped_reasons.append("fallback_eligibility_required")
    if active_policy.require_explicit_live_request and not explicit_live_request:
        skipped_reasons.append("explicit_live_request_required")
    if cloud_dry_run and active_policy.dry_run_forced_when_cloud_dry_run:
        skipped_reasons.append("cloud_dry_run_forced")
    if workflow_dry_run:
        skipped_reasons.append("workflow_dry_run_forced")
    if is_test_context and active_policy.test_context_blocked:
        skipped_reasons.append("test_context_blocked")
    if normalized_channel in active_policy.blocked_channels:
        skipped_reasons.append("blocked_channel")
    if normalized_request_source in active_policy.blocked_request_sources:
        skipped_reasons.append("blocked_request_source")

    if mode == AUTHORIZATION_MODE_BLOCKED:
        skipped_reasons.append("authorization_mode_blocked")
    elif mode == AUTHORIZATION_MODE_ALL_TELEGRAM_USERS:
        if normalized_channel != "telegram":
            skipped_reasons.append(_channel_block_reason(normalized_channel))
    elif mode == AUTHORIZATION_MODE_ALLOWLISTED_TELEGRAM_USER_IDS:
        if normalized_channel != "telegram":
            skipped_reasons.append(_channel_block_reason(normalized_channel))
        elif normalized_user_id not in _provider_allowlist(active_policy, provider_id):
            skipped_reasons.append("telegram_user_id_not_allowlisted")
    else:
        skipped_reasons.append("authorization_mode_invalid")

    provider_metadata = provider.to_metadata() if provider is not None else None
    if provider is None:
        skipped_reasons.append("fallback_provider_declaration_missing")
    else:
        if provider.external is not True or provider.governed is not True:
            skipped_reasons.append("fallback_provider_not_governed_external")
        if active_policy.require_provider_live_governance:
            governance = provider.governance
            if governance.get("live_execution_allowed") is not True:
                skipped_reasons.append("provider_live_governance_not_enabled")
            if provider.execution_allowed is not True:
                skipped_reasons.append("provider_execution_not_enabled")
        if active_policy.require_source_refs and (
            provider.source_requirements.get("source_refs_required") is not True
        ):
            skipped_reasons.append("source_refs_not_required_by_provider")
        if active_policy.require_citations and (
            provider.citation_requirements.get("citations_required") is not True
        ):
            skipped_reasons.append("citations_not_required_by_provider")
        if active_policy.require_cost_awareness and (
            provider.cost_policy.get("cost_tracking_required") is not True
        ):
            skipped_reasons.append("cost_awareness_not_required_by_provider")

    skipped_reasons = list(dict.fromkeys(skipped_reasons))
    live_allowed = not skipped_reasons
    status = (
        LIVE_RETRIEVAL_STATUS_ALLOWED
        if live_allowed
        else (
            LIVE_RETRIEVAL_STATUS_BLOCKED
            if rss_inadequate
            else LIVE_RETRIEVAL_STATUS_NOT_APPLICABLE
        )
    )
    return {
        "artifact_type": RSS_EXTERNAL_LIVE_RETRIEVAL_GOVERNANCE_ARTIFACT,
        "policy_id": active_policy.policy_id,
        "source_artifact_type": active_policy.source_artifact_type,
        "source_scope": source_scope,
        "fallback_provider_id": provider_id,
        "fallback_provider_type": (
            eligibility.get("fallback_provider_type")
            if isinstance(eligibility, Mapping)
            else None
        ),
        "status": status,
        "live_allowed": live_allowed,
        "external_call_allowed": live_allowed,
        "external_call_performed": False,
        "cost_allowed": live_allowed,
        "cost_incurred": False,
        "delivery_allowed": False,
        "delivery_performed": False,
        "explicit_live_request": bool(explicit_live_request),
        "rss_inadequate": rss_inadequate,
        "fallback_eligible": (
            eligibility.get("eligible") is True
            if isinstance(eligibility, Mapping)
            else False
        ),
        "authorization_mode": mode,
        "channel": normalized_channel,
        "request_source": normalized_request_source,
        "actor_id": _safe_optional_text(actor_id),
        "user_id": normalized_user_id,
        "cloud_dry_run": bool(cloud_dry_run),
        "workflow_dry_run": bool(workflow_dry_run),
        "is_test_context": bool(is_test_context),
        "provider": provider_metadata,
        "source_refs_required": active_policy.require_source_refs,
        "citations_required": active_policy.require_citations,
        "cost_awareness_required": active_policy.require_cost_awareness,
        "source_normalization_required_before_summary": True,
        "evaluated_at": _timestamp(evaluated_at),
        "skipped_reasons": skipped_reasons,
        "provenance": {
            "kind": "rss_external_live_retrieval_governance",
            "source_artifact_type": active_policy.source_artifact_type,
            "source_scope": source_scope,
            "fallback_provider_id": provider_id,
            "external_call_performed": False,
            "cost_incurred": False,
            "delivery_performed": False,
        },
    }


def validate_rss_external_live_retrieval_governance(
    artifact: Mapping[str, Any],
) -> bool:
    if not isinstance(artifact, Mapping):
        return False
    if artifact.get("artifact_type") != RSS_EXTERNAL_LIVE_RETRIEVAL_GOVERNANCE_ARTIFACT:
        return False
    if artifact.get("status") not in {
        LIVE_RETRIEVAL_STATUS_ALLOWED,
        LIVE_RETRIEVAL_STATUS_BLOCKED,
        LIVE_RETRIEVAL_STATUS_NOT_APPLICABLE,
    }:
        return False
    if artifact.get("live_allowed") not in {True, False}:
        return False
    if artifact.get("external_call_allowed") != artifact.get("live_allowed"):
        return False
    if artifact.get("cost_allowed") != artifact.get("live_allowed"):
        return False
    for key in ("external_call_performed", "cost_incurred", "delivery_performed"):
        if artifact.get(key) is not False:
            return False
    if artifact.get("delivery_allowed") is not False:
        return False
    for key in (
        "source_refs_required",
        "citations_required",
        "cost_awareness_required",
        "source_normalization_required_before_summary",
    ):
        if artifact.get(key) is not True:
            return False
    if not isinstance(artifact.get("skipped_reasons"), list):
        return False
    if artifact.get("live_allowed") is True and artifact.get("skipped_reasons"):
        return False
    provenance = artifact.get("provenance")
    if not isinstance(provenance, Mapping):
        return False
    if provenance.get("external_call_performed") is not False:
        return False
    if provenance.get("delivery_performed") is not False:
        return False
    return True


@lru_cache(maxsize=None)
def load_rss_external_live_retrieval_policy(
    root: str | Path | None = None,
) -> RssExternalLiveRetrievalPolicy:
    try:
        data = json.loads(_policy_path(root).read_text(encoding="utf-8"))
        return _policy_from_data(data)
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        RssExternalLiveRetrievalPolicyError,
    ):
        return _blocked_policy()


def _policy_path(root: str | Path | None = None) -> Path:
    if root is None:
        return RSS_EXTERNAL_LIVE_RETRIEVAL_POLICY_PATH
    return Path(root) / RSS_EXTERNAL_LIVE_RETRIEVAL_POLICY_PATH


def _policy_from_data(data: Any) -> RssExternalLiveRetrievalPolicy:
    if not isinstance(data, dict) or data.get("version") != 1:
        raise RssExternalLiveRetrievalPolicyError(
            "RSS external live retrieval policy version must be 1."
        )
    allowed_modes = _text_tuple(data.get("allowed_modes"))
    if set(allowed_modes) != ALLOWED_AUTHORIZATION_MODES:
        raise RssExternalLiveRetrievalPolicyError(
            "RSS external live retrieval policy has unsupported modes."
        )
    blocked_contexts = _object(data.get("blocked_contexts"))
    provider_policies: dict[str, dict[str, Any]] = {}
    for entry in _list(data.get("provider_policies")):
        item = _object(entry)
        provider_id = _required_text(item.get("provider_id"))
        provider_policies[provider_id] = {
            "mode": _required_mode(item.get("mode")),
            "allowlisted_telegram_user_ids": _text_tuple(
                item.get("allowlisted_telegram_user_ids", [])
            ),
        }
    return RssExternalLiveRetrievalPolicy(
        policy_id=_required_text(data.get("policy_id")),
        source_artifact_type=_required_text(data.get("source_artifact_type")),
        source_scope=_required_text(data.get("source_scope")),
        default_mode=_required_mode(data.get("default_mode")),
        recognized_channels=_normalized_text_tuple(data.get("recognized_channels")),
        blocked_channels=_normalized_text_tuple(blocked_contexts.get("channels")),
        blocked_request_sources=_normalized_text_tuple(
            blocked_contexts.get("request_sources")
        ),
        test_context_blocked=_required_bool(blocked_contexts.get("test_context")),
        dry_run_forced_when_cloud_dry_run=_required_bool(
            data.get("dry_run_forced_when_cloud_dry_run")
        ),
        require_explicit_live_request=_required_bool(
            data.get("require_explicit_live_request")
        ),
        require_rss_inadequacy=_required_bool(data.get("require_rss_inadequacy")),
        require_fallback_eligibility=_required_bool(
            data.get("require_fallback_eligibility")
        ),
        require_provider_live_governance=_required_bool(
            data.get("require_provider_live_governance")
        ),
        require_source_refs=_required_bool(data.get("require_source_refs")),
        require_citations=_required_bool(data.get("require_citations")),
        require_cost_awareness=_required_bool(data.get("require_cost_awareness")),
        provider_policies=provider_policies,
    )


def _blocked_policy() -> RssExternalLiveRetrievalPolicy:
    return RssExternalLiveRetrievalPolicy(
        policy_id="rss_external_live_retrieval_blocked_fallback",
        source_artifact_type="rss_coverage_adequacy",
        source_scope="rss_metadata_cache",
        default_mode=AUTHORIZATION_MODE_BLOCKED,
        recognized_channels=("telegram",),
        blocked_channels=("cli", "dev", "test", "runtime"),
        blocked_request_sources=("cli", "dev", "test", "runtime"),
        test_context_blocked=True,
        dry_run_forced_when_cloud_dry_run=True,
        require_explicit_live_request=True,
        require_rss_inadequacy=True,
        require_fallback_eligibility=True,
        require_provider_live_governance=True,
        require_source_refs=True,
        require_citations=True,
        require_cost_awareness=True,
        provider_policies={},
    )


def _rss_inadequate(
    artifact: Mapping[str, Any] | None,
    *,
    source_artifact_type: str,
    source_scope: str,
) -> bool:
    return (
        isinstance(artifact, Mapping)
        and artifact.get("artifact_type") == source_artifact_type
        and artifact.get("source_scope") == source_scope
        and artifact.get("outcome") == "inadequate"
        and artifact.get("adequate") is False
    )


def _provider_mode(
    policy: RssExternalLiveRetrievalPolicy,
    provider_id: str | None,
) -> str:
    if provider_id is None:
        return policy.default_mode
    return str(
        policy.provider_policies.get(provider_id, {}).get(
            "mode",
            policy.default_mode,
        )
    )


def _provider_allowlist(
    policy: RssExternalLiveRetrievalPolicy,
    provider_id: str | None,
) -> tuple[str, ...]:
    if provider_id is None:
        return ()
    value = policy.provider_policies.get(provider_id, {}).get(
        "allowlisted_telegram_user_ids",
        (),
    )
    return value if isinstance(value, tuple) else ()


def _channel_block_reason(channel: str | None) -> str:
    if channel is None:
        return "channel_missing"
    return "channel_not_authorized"


def _timestamp(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def _required_mode(value: Any) -> str:
    text = _required_text(value)
    if text not in ALLOWED_AUTHORIZATION_MODES:
        raise RssExternalLiveRetrievalPolicyError(
            "RSS external live retrieval policy mode is unsupported."
        )
    return text


def _required_text(value: Any) -> str:
    text = _safe_optional_text(value)
    if not text:
        raise RssExternalLiveRetrievalPolicyError(
            "RSS external live retrieval policy text fields must be non-empty."
        )
    return text


def _required_bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise RssExternalLiveRetrievalPolicyError(
            "RSS external live retrieval policy boolean fields must be boolean."
        )
    return value


def _safe_optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


def _normalized_optional_text(value: Any) -> str | None:
    text = _safe_optional_text(value)
    return text.lower() if text else None


def _text_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise RssExternalLiveRetrievalPolicyError(
            "RSS external live retrieval policy lists must be lists."
        )
    return tuple(_required_text(item) for item in value)


def _normalized_text_tuple(value: Any) -> tuple[str, ...]:
    return tuple(item.lower() for item in _text_tuple(value))


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RssExternalLiveRetrievalPolicyError(
            "RSS external live retrieval policy objects must be objects."
        )
    return dict(value)


def _list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise RssExternalLiveRetrievalPolicyError(
            "RSS external live retrieval policy provider_policies must be a list."
        )
    return list(value)


__all__ = [
    "LIVE_RETRIEVAL_STATUS_ALLOWED",
    "LIVE_RETRIEVAL_STATUS_BLOCKED",
    "LIVE_RETRIEVAL_STATUS_NOT_APPLICABLE",
    "RSS_EXTERNAL_LIVE_RETRIEVAL_GOVERNANCE_ARTIFACT",
    "RssExternalLiveRetrievalPolicy",
    "evaluate_rss_external_live_retrieval_governance",
    "load_rss_external_live_retrieval_policy",
    "validate_rss_external_live_retrieval_governance",
]
