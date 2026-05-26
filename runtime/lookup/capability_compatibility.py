from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


LOOKUP_CAPABILITY_CONTRACT_VERSION = 1
LOOKUP_RUNTIME_COMPATIBILITY_VERSION = 1
SUPPORTED_LOOKUP_CAPABILITY_FEATURES = frozenset(
    {
        "exact_entity_lookup",
        "bounded_entity_search",
        "bounded_context_materialization",
        "structured_fact_rendering",
        "audited_context_injection",
        "lineage",
        "governance",
        "execution_timeout",
        "bounded_concurrency",
    }
)


@dataclass(frozen=True)
class LookupCapabilityCompatibility:
    contract_version: int
    min_runtime_version: int
    max_runtime_version: int
    required_features: tuple[str, ...]

    def to_metadata(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "min_runtime_version": self.min_runtime_version,
            "max_runtime_version": self.max_runtime_version,
            "required_features": list(self.required_features),
        }


def normalize_lookup_capability_compatibility(
    policy: dict[str, Any] | None,
    *,
    supported_features: Iterable[str] = SUPPORTED_LOOKUP_CAPABILITY_FEATURES,
) -> LookupCapabilityCompatibility | None:
    if not isinstance(policy, dict):
        return None

    contract_version = policy.get("contract_version")
    min_runtime_version = policy.get("min_runtime_version")
    max_runtime_version = policy.get("max_runtime_version")
    required_features = policy.get("required_features", [])
    supported = frozenset(supported_features)

    if not _positive_int(contract_version):
        return None

    if contract_version != LOOKUP_CAPABILITY_CONTRACT_VERSION:
        return None

    if not _positive_int(min_runtime_version) or not _positive_int(
        max_runtime_version
    ):
        return None

    if min_runtime_version > max_runtime_version:
        return None

    if not (
        min_runtime_version
        <= LOOKUP_RUNTIME_COMPATIBILITY_VERSION
        <= max_runtime_version
    ):
        return None

    if (
        not isinstance(required_features, list)
        or any(not _non_empty_string(feature) for feature in required_features)
    ):
        return None

    normalized_features = tuple(feature.strip() for feature in required_features)
    if len(normalized_features) != len(set(normalized_features)):
        return None

    if any(feature not in supported for feature in normalized_features):
        return None

    return LookupCapabilityCompatibility(
        contract_version=contract_version,
        min_runtime_version=min_runtime_version,
        max_runtime_version=max_runtime_version,
        required_features=normalized_features,
    )


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


__all__ = [
    "LOOKUP_CAPABILITY_CONTRACT_VERSION",
    "LOOKUP_RUNTIME_COMPATIBILITY_VERSION",
    "SUPPORTED_LOOKUP_CAPABILITY_FEATURES",
    "LookupCapabilityCompatibility",
    "normalize_lookup_capability_compatibility",
]
