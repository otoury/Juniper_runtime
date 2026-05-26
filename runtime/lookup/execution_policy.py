from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_LOOKUP_TIMEOUT_MS = 3000
MAX_LOOKUP_TIMEOUT_MS = 60000
DEFAULT_MAX_CONCURRENT_LOOKUPS = 1
MAX_CONCURRENT_LOOKUPS_LIMIT = 16
LOOKUP_CANCELLATION_FAIL_CLOSED = "fail_closed"
LOOKUP_CANCELLATION_BEHAVIORS = frozenset({LOOKUP_CANCELLATION_FAIL_CLOSED})


@dataclass(frozen=True)
class LookupExecutionPolicy:
    timeout_ms: int
    cancellation_behavior: str
    max_concurrent_lookups: int

    def to_metadata(self) -> dict[str, Any]:
        return {
            "timeout_ms": self.timeout_ms,
            "cancellation_behavior": self.cancellation_behavior,
            "max_concurrent_lookups": self.max_concurrent_lookups,
        }


DEFAULT_LOOKUP_EXECUTION_POLICY = LookupExecutionPolicy(
    timeout_ms=DEFAULT_LOOKUP_TIMEOUT_MS,
    cancellation_behavior=LOOKUP_CANCELLATION_FAIL_CLOSED,
    max_concurrent_lookups=DEFAULT_MAX_CONCURRENT_LOOKUPS,
)


def normalize_lookup_execution_policy(
    policy: dict[str, Any] | None,
) -> LookupExecutionPolicy | None:
    if policy is None:
        return DEFAULT_LOOKUP_EXECUTION_POLICY

    if not isinstance(policy, dict):
        return None

    timeout_ms = policy.get("timeout_ms")
    if (
        not isinstance(timeout_ms, int)
        or isinstance(timeout_ms, bool)
        or timeout_ms <= 0
        or timeout_ms > MAX_LOOKUP_TIMEOUT_MS
    ):
        return None

    cancellation_behavior = policy.get("cancellation_behavior")
    if cancellation_behavior not in LOOKUP_CANCELLATION_BEHAVIORS:
        return None

    max_concurrent_lookups = policy.get(
        "max_concurrent_lookups",
        DEFAULT_MAX_CONCURRENT_LOOKUPS,
    )
    if (
        not isinstance(max_concurrent_lookups, int)
        or isinstance(max_concurrent_lookups, bool)
        or max_concurrent_lookups <= 0
        or max_concurrent_lookups > MAX_CONCURRENT_LOOKUPS_LIMIT
    ):
        return None

    return LookupExecutionPolicy(
        timeout_ms=timeout_ms,
        cancellation_behavior=cancellation_behavior,
        max_concurrent_lookups=max_concurrent_lookups,
    )


__all__ = [
    "DEFAULT_LOOKUP_EXECUTION_POLICY",
    "DEFAULT_MAX_CONCURRENT_LOOKUPS",
    "DEFAULT_LOOKUP_TIMEOUT_MS",
    "LOOKUP_CANCELLATION_BEHAVIORS",
    "LOOKUP_CANCELLATION_FAIL_CLOSED",
    "LookupExecutionPolicy",
    "MAX_CONCURRENT_LOOKUPS_LIMIT",
    "MAX_LOOKUP_TIMEOUT_MS",
    "normalize_lookup_execution_policy",
]
