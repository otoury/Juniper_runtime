from __future__ import annotations

from dataclasses import replace
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from runtime.policies.cloud_provider_authorization import (
    AUTHORIZATION_MODE_BLOCKED,
    CloudProviderAuthorizationDecision,
    CloudProviderAuthorizationInput,
    CloudProviderAuthorizationPolicy,
    evaluate_cloud_provider_authorization,
    load_cloud_provider_authorization_policy,
)
from runtime.registries.cloud_provider_pilot_registry import (
    CloudProviderPilotBinding,
    get_cloud_provider_pilot,
)


def evaluate_cloud_provider_pilot_authorization(
    request: CloudProviderAuthorizationInput,
    *,
    policy: CloudProviderAuthorizationPolicy | None = None,
    pilot: CloudProviderPilotBinding | None = None,
    root: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> CloudProviderAuthorizationDecision:
    if policy is not None:
        return evaluate_cloud_provider_authorization(
            request,
            policy=policy,
            root=root,
            environ=environ,
        )

    active_pilot = pilot or get_cloud_provider_pilot(
        agent_id=request.agent_id,
        provider_id=request.provider_id,
        channel=request.channel,
        root=root,
    )
    if active_pilot is None:
        return evaluate_cloud_provider_authorization(
            request,
            root=root,
            environ=environ,
        )

    base_policy = load_cloud_provider_authorization_policy(root)
    pilot_policy = replace(
        base_policy,
        provider_policies={
            **base_policy.provider_policies,
            active_pilot.provider_id: {
                "mode": active_pilot.authorization_mode,
                "allowlisted_telegram_user_ids": (),
            },
        },
    )
    pilot_request = replace(
        request,
        governance_state=active_pilot.governance_state,
    )
    return evaluate_cloud_provider_authorization(
        pilot_request,
        policy=pilot_policy,
        root=root,
        environ=environ,
    )


def evaluate_cloud_provider_pilot_authorization_metadata(
    request: CloudProviderAuthorizationInput,
    *,
    policy: CloudProviderAuthorizationPolicy | None = None,
    root: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if policy is not None:
        return evaluate_cloud_provider_authorization(
            request,
            policy=policy,
            root=root,
            environ=environ,
        ).to_metadata()

    pilot = get_cloud_provider_pilot(
        agent_id=request.agent_id,
        provider_id=request.provider_id,
        channel=request.channel,
        root=root,
    )
    decision = evaluate_cloud_provider_pilot_authorization(
        request,
        pilot=pilot,
        root=root,
        environ=environ,
    )
    metadata = decision.to_metadata()
    if pilot is None:
        metadata["pilot_authorization_applied"] = False
        metadata["pilot_authorization_mode"] = AUTHORIZATION_MODE_BLOCKED
        return metadata

    metadata["pilot_authorization_applied"] = True
    metadata["pilot"] = pilot.to_metadata()
    metadata["pilot_authorization_mode"] = pilot.authorization_mode
    metadata["pilot_max_queries"] = pilot.max_queries
    metadata["pilot_max_results"] = pilot.max_results
    metadata["pilot_engine_policy_ref"] = pilot.engine_policy_ref
    return metadata


__all__ = [
    "evaluate_cloud_provider_pilot_authorization",
    "evaluate_cloud_provider_pilot_authorization_metadata",
]
