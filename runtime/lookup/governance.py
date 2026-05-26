from __future__ import annotations

from dataclasses import dataclass
from typing import Any


GOVERNANCE_ENABLED = "enabled"
GOVERNANCE_DISABLED = "disabled"
GOVERNANCE_AUDIT_ONLY = "audit_only"
GOVERNANCE_BLOCKED = "blocked"

LOOKUP_GOVERNANCE_STATES = frozenset(
    {
        GOVERNANCE_ENABLED,
        GOVERNANCE_DISABLED,
        GOVERNANCE_AUDIT_ONLY,
        GOVERNANCE_BLOCKED,
    }
)


@dataclass(frozen=True)
class LookupGovernancePolicy:
    state: str

    @property
    def request_allowed(self) -> bool:
        return self.state in {GOVERNANCE_ENABLED, GOVERNANCE_AUDIT_ONLY}

    @property
    def execution_allowed(self) -> bool:
        return self.state == GOVERNANCE_ENABLED

    @property
    def context_allowed(self) -> bool:
        return self.state == GOVERNANCE_ENABLED


def normalize_lookup_governance_policy(
    policy: dict[str, Any] | None,
) -> LookupGovernancePolicy | None:
    if policy is None:
        return LookupGovernancePolicy(state=GOVERNANCE_ENABLED)

    if not isinstance(policy, dict):
        return None

    state = policy.get("state", GOVERNANCE_ENABLED)
    if not isinstance(state, str) or state not in LOOKUP_GOVERNANCE_STATES:
        return None

    return LookupGovernancePolicy(state=state)


def governance_block_reason(state: str) -> str:
    if state == GOVERNANCE_DISABLED:
        return "lookup_capability_disabled"

    if state == GOVERNANCE_AUDIT_ONLY:
        return "lookup_capability_audit_only"

    if state == GOVERNANCE_BLOCKED:
        return "lookup_capability_blocked"

    return "lookup_capability_governance_invalid"


__all__ = [
    "GOVERNANCE_AUDIT_ONLY",
    "GOVERNANCE_BLOCKED",
    "GOVERNANCE_DISABLED",
    "GOVERNANCE_ENABLED",
    "LOOKUP_GOVERNANCE_STATES",
    "LookupGovernancePolicy",
    "governance_block_reason",
    "normalize_lookup_governance_policy",
]
