# runtime/recovery_policy.py

from __future__ import annotations

from runtime.policies.model_registry import ENGINES


DEFAULT_ARTIFACT_RECOVERY_ORDER = [
    "local_reasoner_fallback",
    "cloud_fast",
    "cloud_deep",
]


def build_artifact_retry_engines(
    failed_engine: str | None,
    recovery_order: list[str] | None = None,
) -> list[str]:
    """
    Build retry engines for failed artifact generation.

    Runtime policy:
    - prefer local recovery first
    - never retry into the engine that just failed
    - never use dry-run engines for real recovery
    """

    order = recovery_order or DEFAULT_ARTIFACT_RECOVERY_ORDER

    retry_engines = [
        engine
        for engine in order
        if engine != failed_engine
    ]

    retry_engines = [
        engine
        for engine in retry_engines
        if not ENGINES.get(engine, {}).get("dry_run", False)
    ]

    return retry_engines


__all__ = [
    "build_artifact_retry_engines",
]
