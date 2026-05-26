from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from collections.abc import Mapping

from runtime.governance.operational_controls import (
    OperationalControlDecision,
    evaluate_cloud_execution_control,
)


CLOUD_PROVIDER_AUTHORIZATION_POLICY_PATH = Path(
    "agents/shared/governance/cloud_provider_authorization_policy.json"
)
AUTHORIZATION_MODE_BLOCKED = "blocked"
AUTHORIZATION_MODE_ALL_TELEGRAM_USERS = "all_telegram_users"
AUTHORIZATION_MODE_ALLOWLISTED_TELEGRAM_USER_IDS = (
    "allowlisted_telegram_user_ids"
)
AUTHORIZATION_STATUS_ALLOWED = "allowed"
AUTHORIZATION_STATUS_BLOCKED = "blocked"
AUTHORIZATION_STATUS_DRY_RUN_FORCED = "dry_run_forced"
ALLOWED_AUTHORIZATION_MODES = frozenset(
    {
        AUTHORIZATION_MODE_BLOCKED,
        AUTHORIZATION_MODE_ALL_TELEGRAM_USERS,
        AUTHORIZATION_MODE_ALLOWLISTED_TELEGRAM_USER_IDS,
    }
)


class CloudProviderAuthorizationPolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class CloudProviderAuthorizationPolicy:
    default_mode: str
    live_governance_states: tuple[str, ...]
    dry_run_forced_when_cloud_dry_run: bool
    blocked_channels: tuple[str, ...]
    blocked_request_sources: tuple[str, ...]
    test_context_blocked: bool
    recognized_channels: tuple[str, ...]
    provider_policies: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class CloudProviderAuthorizationInput:
    provider_id: str | None
    agent_id: str | None = None
    channel: str | None = None
    request_source: str | None = None
    actor_id: str | None = None
    user_id: str | None = None
    is_test_context: bool = False
    cloud_dry_run: bool = False
    governance_state: str | None = None


@dataclass(frozen=True)
class CloudProviderAuthorizationDecision:
    provider_id: str | None
    agent_id: str | None
    channel: str | None
    request_source: str | None
    actor_id: str | None
    user_id: str | None
    is_test_context: bool
    cloud_dry_run: bool
    governance_state: str | None
    mode: str
    authorization_status: str
    live_execution_authorized: bool
    dry_run_required: bool
    external_call_allowed: bool
    cost_allowed: bool
    skipped_reasons: tuple[str, ...]
    operational_control: OperationalControlDecision | None = None

    def to_metadata(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "agent_id": self.agent_id,
            "channel": self.channel,
            "request_source": self.request_source,
            "actor_id": self.actor_id,
            "user_id": self.user_id,
            "is_test_context": self.is_test_context,
            "cloud_dry_run": self.cloud_dry_run,
            "governance_state": self.governance_state,
            "authorization_mode": self.mode,
            "authorization_status": self.authorization_status,
            "live_execution_authorized": self.live_execution_authorized,
            "dry_run_required": self.dry_run_required,
            "external_call_allowed": self.external_call_allowed,
            "cost_allowed": self.cost_allowed,
            "actor_authorization_checked": True,
            "channel_authorization_checked": True,
            "operational_control": (
                self.operational_control.to_diagnostics()
                if self.operational_control is not None
                else None
            ),
            "skipped_reasons": list(self.skipped_reasons),
        }


def evaluate_cloud_provider_authorization(
    request: CloudProviderAuthorizationInput,
    *,
    policy: CloudProviderAuthorizationPolicy | None = None,
    root: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> CloudProviderAuthorizationDecision:
    active_policy = policy or load_cloud_provider_authorization_policy(root)
    provider_id = _safe_optional_string(request.provider_id)
    channel = _normalized_optional_string(request.channel)
    request_source = _normalized_optional_string(request.request_source)
    actor_id = _safe_optional_string(request.actor_id)
    user_id = _safe_optional_string(request.user_id) or actor_id
    governance_state = _safe_optional_string(request.governance_state)
    mode = _provider_mode(active_policy, provider_id)

    skipped_reasons: list[str] = []
    dry_run_required = False
    operational_control = (
        evaluate_cloud_execution_control(root=root, environ=environ)
    )
    if operational_control is not None and not operational_control.allowed:
        skipped_reasons.extend(operational_control.reason_codes)

    dry_run_has_bootstrap_authority = bool(
        operational_control is not None
        and operational_control.source.startswith("bootstrap_env:")
    )
    if (
        request.cloud_dry_run
        and active_policy.dry_run_forced_when_cloud_dry_run
        and dry_run_has_bootstrap_authority
    ):
        dry_run_required = True
        skipped_reasons.append("cloud_dry_run_forced")

    if request.is_test_context and active_policy.test_context_blocked:
        skipped_reasons.append("test_context_blocked")

    if channel in active_policy.blocked_channels:
        skipped_reasons.append("blocked_channel")

    if request_source in active_policy.blocked_request_sources:
        skipped_reasons.append("blocked_request_source")

    if governance_state not in active_policy.live_governance_states:
        skipped_reasons.append("governance_state_not_live_enabled")

    if mode == AUTHORIZATION_MODE_BLOCKED:
        skipped_reasons.append("authorization_mode_blocked")
    elif mode == AUTHORIZATION_MODE_ALL_TELEGRAM_USERS:
        if channel != "telegram":
            skipped_reasons.append(_channel_block_reason(channel, active_policy))
    elif mode == AUTHORIZATION_MODE_ALLOWLISTED_TELEGRAM_USER_IDS:
        if channel != "telegram":
            skipped_reasons.append(_channel_block_reason(channel, active_policy))
        elif user_id not in _provider_allowlist(active_policy, provider_id):
            skipped_reasons.append("telegram_user_id_not_allowlisted")
    else:
        skipped_reasons.append("authorization_mode_invalid")

    live_authorized = not skipped_reasons
    if dry_run_required:
        status = AUTHORIZATION_STATUS_DRY_RUN_FORCED
    elif live_authorized:
        status = AUTHORIZATION_STATUS_ALLOWED
    else:
        status = AUTHORIZATION_STATUS_BLOCKED

    return CloudProviderAuthorizationDecision(
        provider_id=provider_id,
        agent_id=_safe_optional_string(request.agent_id),
        channel=channel,
        request_source=request_source,
        actor_id=actor_id,
        user_id=user_id,
        is_test_context=bool(request.is_test_context),
        cloud_dry_run=bool(request.cloud_dry_run),
        governance_state=governance_state,
        mode=mode,
        authorization_status=status,
        live_execution_authorized=live_authorized,
        dry_run_required=dry_run_required,
        external_call_allowed=live_authorized,
        cost_allowed=live_authorized,
        skipped_reasons=tuple(dict.fromkeys(skipped_reasons)),
        operational_control=operational_control,
    )


@lru_cache(maxsize=None)
def load_cloud_provider_authorization_policy(
    root: str | Path | None = None,
) -> CloudProviderAuthorizationPolicy:
    try:
        data = json.loads(_policy_path(root).read_text(encoding="utf-8"))
        return _policy_from_data(data)
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        CloudProviderAuthorizationPolicyError,
    ):
        return _blocked_fallback_policy()


def _policy_path(root: str | Path | None = None) -> Path:
    if root is None:
        return CLOUD_PROVIDER_AUTHORIZATION_POLICY_PATH
    return Path(root) / CLOUD_PROVIDER_AUTHORIZATION_POLICY_PATH


def _policy_from_data(data: Any) -> CloudProviderAuthorizationPolicy:
    if not isinstance(data, dict) or data.get("version") != 1:
        raise CloudProviderAuthorizationPolicyError(
            "Cloud provider authorization policy version must be 1."
        )

    allowed_modes = _string_tuple(data.get("allowed_modes"))
    if set(allowed_modes) != set(ALLOWED_AUTHORIZATION_MODES):
        raise CloudProviderAuthorizationPolicyError(
            "Cloud provider authorization policy has unsupported modes."
        )

    default_mode = _required_mode(data.get("default_mode"))
    blocked_contexts = data.get("blocked_contexts")
    if not isinstance(blocked_contexts, dict):
        raise CloudProviderAuthorizationPolicyError(
            "Cloud provider authorization policy blocked_contexts must be an object."
        )

    provider_policies: dict[str, dict[str, Any]] = {}
    raw_provider_policies = data.get("provider_policies")
    if not isinstance(raw_provider_policies, list):
        raise CloudProviderAuthorizationPolicyError(
            "Cloud provider authorization policy provider_policies must be a list."
        )
    for entry in raw_provider_policies:
        if not isinstance(entry, dict):
            raise CloudProviderAuthorizationPolicyError(
                "Cloud provider authorization policy entries must be objects."
            )
        provider_id = _required_string(entry.get("provider_id"))
        mode = _required_mode(entry.get("mode"))
        provider_policies[provider_id] = {
            "mode": mode,
            "allowlisted_telegram_user_ids": _string_tuple(
                entry.get("allowlisted_telegram_user_ids", [])
            ),
        }

    return CloudProviderAuthorizationPolicy(
        default_mode=default_mode,
        live_governance_states=_string_tuple(data.get("live_governance_states")),
        dry_run_forced_when_cloud_dry_run=bool(
            data.get("dry_run_forced_when_cloud_dry_run") is True
        ),
        blocked_channels=_normalized_string_tuple(blocked_contexts.get("channels")),
        blocked_request_sources=_normalized_string_tuple(
            blocked_contexts.get("request_sources")
        ),
        test_context_blocked=bool(blocked_contexts.get("test_context") is True),
        recognized_channels=_normalized_string_tuple(data.get("recognized_channels")),
        provider_policies=provider_policies,
    )


def _blocked_fallback_policy() -> CloudProviderAuthorizationPolicy:
    return CloudProviderAuthorizationPolicy(
        default_mode=AUTHORIZATION_MODE_BLOCKED,
        live_governance_states=("enabled",),
        dry_run_forced_when_cloud_dry_run=True,
        blocked_channels=("cli", "dev", "test"),
        blocked_request_sources=("cli", "dev", "test"),
        test_context_blocked=True,
        recognized_channels=("telegram",),
        provider_policies={},
    )


def _provider_mode(
    policy: CloudProviderAuthorizationPolicy,
    provider_id: str | None,
) -> str:
    if provider_id is None:
        return policy.default_mode
    provider_policy = policy.provider_policies.get(provider_id)
    if provider_policy is None:
        return policy.default_mode
    mode = provider_policy.get("mode")
    if mode in ALLOWED_AUTHORIZATION_MODES:
        return str(mode)
    return AUTHORIZATION_MODE_BLOCKED


def _provider_allowlist(
    policy: CloudProviderAuthorizationPolicy,
    provider_id: str | None,
) -> tuple[str, ...]:
    if provider_id is None:
        return ()
    provider_policy = policy.provider_policies.get(provider_id)
    if provider_policy is None:
        return ()
    value = provider_policy.get("allowlisted_telegram_user_ids")
    if isinstance(value, tuple):
        return value
    return ()


def _channel_block_reason(
    channel: str | None,
    policy: CloudProviderAuthorizationPolicy,
) -> str:
    if channel is None:
        return "channel_missing"
    if channel not in policy.recognized_channels:
        return "unknown_channel"
    return "channel_not_authorized_for_mode"


def _required_mode(value: Any) -> str:
    mode = _required_string(value)
    if mode not in ALLOWED_AUTHORIZATION_MODES:
        raise CloudProviderAuthorizationPolicyError(
            "Cloud provider authorization mode is unsupported."
        )
    return mode


def _required_string(value: Any) -> str:
    normalized = _safe_optional_string(value)
    if normalized is None:
        raise CloudProviderAuthorizationPolicyError(
            "Cloud provider authorization policy requires non-empty strings."
        )
    return normalized


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        _safe_optional_string(item) is None for item in value
    ):
        raise CloudProviderAuthorizationPolicyError(
            "Cloud provider authorization policy lists must contain strings."
        )
    return tuple(str(item).strip() for item in value)


def _normalized_string_tuple(value: Any) -> tuple[str, ...]:
    return tuple(item.lower() for item in _string_tuple(value))


def _normalized_optional_string(value: Any) -> str | None:
    normalized = _safe_optional_string(value)
    if normalized is None:
        return None
    return normalized.lower()


def _safe_optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "AUTHORIZATION_MODE_ALLOWLISTED_TELEGRAM_USER_IDS",
    "AUTHORIZATION_MODE_ALL_TELEGRAM_USERS",
    "AUTHORIZATION_MODE_BLOCKED",
    "AUTHORIZATION_STATUS_ALLOWED",
    "AUTHORIZATION_STATUS_BLOCKED",
    "AUTHORIZATION_STATUS_DRY_RUN_FORCED",
    "CLOUD_PROVIDER_AUTHORIZATION_POLICY_PATH",
    "CloudProviderAuthorizationDecision",
    "CloudProviderAuthorizationInput",
    "CloudProviderAuthorizationPolicy",
    "CloudProviderAuthorizationPolicyError",
    "evaluate_cloud_provider_authorization",
    "load_cloud_provider_authorization_policy",
]
