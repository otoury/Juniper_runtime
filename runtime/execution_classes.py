from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


EXECUTION_CLASS_LOCAL_CACHE_READ = "local_cache_read"
EXECUTION_CLASS_LOCAL_CACHE_SYNTHESIS = "local_cache_synthesis"
EXECUTION_CLASS_EXTERNAL_NETWORK_FETCH = "external_network_fetch"
EXECUTION_CLASS_PAID_CLOUD_MODEL = "paid_cloud_model"
EXECUTION_CLASS_PAID_EXTERNAL_PROVIDER = "paid_external_provider"
EXECUTION_CLASS_SIDE_EFFECTFUL_ACTION = "side_effectful_action"
EXECUTION_CLASS_WRITE_OPERATION = "write_operation"

DRY_RUN_BLOCKED_EXECUTION_CLASSES = frozenset(
    {
        EXECUTION_CLASS_EXTERNAL_NETWORK_FETCH,
        EXECUTION_CLASS_PAID_CLOUD_MODEL,
        EXECUTION_CLASS_PAID_EXTERNAL_PROVIDER,
        EXECUTION_CLASS_SIDE_EFFECTFUL_ACTION,
        EXECUTION_CLASS_WRITE_OPERATION,
    }
)

DRY_RUN_ALLOWED_EXECUTION_CLASSES = frozenset(
    {
        EXECUTION_CLASS_LOCAL_CACHE_READ,
        EXECUTION_CLASS_LOCAL_CACHE_SYNTHESIS,
    }
)

ALL_EXECUTION_CLASSES = (
    EXECUTION_CLASS_LOCAL_CACHE_READ,
    EXECUTION_CLASS_LOCAL_CACHE_SYNTHESIS,
    EXECUTION_CLASS_EXTERNAL_NETWORK_FETCH,
    EXECUTION_CLASS_PAID_CLOUD_MODEL,
    EXECUTION_CLASS_PAID_EXTERNAL_PROVIDER,
    EXECUTION_CLASS_SIDE_EFFECTFUL_ACTION,
    EXECUTION_CLASS_WRITE_OPERATION,
)


@dataclass(frozen=True)
class ExecutionClassDryRunDecision:
    execution_class: str
    dry_run: bool
    allowed: bool
    dry_run_effect: str
    reason: str

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "execution_class": self.execution_class,
            "dry_run": self.dry_run,
            "dry_run_effect": self.dry_run_effect,
            "allowed": self.allowed,
            "reason": self.reason,
            "planner_semantic_authority": False,
            "semantic_reinterpretation_performed": False,
        }


def dry_run_requested(environ: Mapping[str, str] | None = None) -> bool:
    source = environ if environ is not None else os.environ
    return _env_truthy(source.get("CLOUD_DRY_RUN")) or _env_truthy(
        source.get("JUNIPER_DRY_RUN")
    )


def evaluate_execution_class_dry_run(
    execution_class: str,
    *,
    dry_run: bool,
) -> ExecutionClassDryRunDecision:
    normalized = _normalize_execution_class(execution_class)
    if not dry_run:
        return ExecutionClassDryRunDecision(
            execution_class=normalized,
            dry_run=False,
            allowed=True,
            dry_run_effect="not_applicable",
            reason="dry_run_not_requested",
        )
    if normalized in DRY_RUN_ALLOWED_EXECUTION_CLASSES:
        return ExecutionClassDryRunDecision(
            execution_class=normalized,
            dry_run=True,
            allowed=True,
            dry_run_effect="allowed_local_free_execution",
            reason=f"{normalized}_allowed_under_dry_run",
        )
    return ExecutionClassDryRunDecision(
        execution_class=normalized,
        dry_run=True,
        allowed=False,
        dry_run_effect="blocked",
        reason=f"{normalized}_blocked_by_dry_run",
    )


def _normalize_execution_class(value: str) -> str:
    if value in ALL_EXECUTION_CLASSES:
        return value
    return EXECUTION_CLASS_SIDE_EFFECTFUL_ACTION


def _env_truthy(value: object) -> bool:
    return isinstance(value, str) and value.lower() in {"1", "true", "yes", "on"}


__all__ = [
    "ALL_EXECUTION_CLASSES",
    "DRY_RUN_ALLOWED_EXECUTION_CLASSES",
    "DRY_RUN_BLOCKED_EXECUTION_CLASSES",
    "EXECUTION_CLASS_EXTERNAL_NETWORK_FETCH",
    "EXECUTION_CLASS_LOCAL_CACHE_READ",
    "EXECUTION_CLASS_LOCAL_CACHE_SYNTHESIS",
    "EXECUTION_CLASS_PAID_CLOUD_MODEL",
    "EXECUTION_CLASS_PAID_EXTERNAL_PROVIDER",
    "EXECUTION_CLASS_SIDE_EFFECTFUL_ACTION",
    "EXECUTION_CLASS_WRITE_OPERATION",
    "ExecutionClassDryRunDecision",
    "dry_run_requested",
    "evaluate_execution_class_dry_run",
]
