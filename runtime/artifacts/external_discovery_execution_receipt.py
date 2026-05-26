from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


EXTERNAL_DISCOVERY_EXECUTION_RECEIPT_ARTIFACT = (
    "external_discovery_execution_receipt"
)
REQUIRED_RECEIPT_FIELDS = (
    "artifact_type",
    "provider_id",
    "provider_type",
    "action_type",
    "query_plan_ref",
    "result_artifact_ref",
    "dry_run",
    "external_call_performed",
    "cost_incurred",
    "governance_state",
    "execution_allowed",
    "blocked_reason",
    "created_at",
)
FORBIDDEN_CONTENT_FIELDS = (
    "query_plan",
    "raw_provider_payload",
    "raw_results",
    "source_refs",
    "citations",
    "results",
    "candidates",
    "guest_candidate_list",
    "outreach_draft",
    "email_draft",
)


@dataclass(frozen=True)
class ExternalDiscoveryExecutionReceiptValidationError:
    error_code: str
    field: str
    message: str


def build_external_discovery_execution_receipt(
    *,
    provider_id: str | None,
    provider_type: str | None,
    action_type: str | None,
    query_plan_ref: str | None,
    result_artifact_ref: str | None,
    dry_run: bool,
    external_call_performed: bool,
    cost_incurred: bool,
    governance_state: str | None,
    execution_allowed: bool,
    blocked_reason: str | None,
    authorization: dict[str, Any] | None = None,
    created_at: datetime | str | None = None,
) -> dict[str, Any]:
    receipt = {
        "artifact_type": EXTERNAL_DISCOVERY_EXECUTION_RECEIPT_ARTIFACT,
        "provider_id": _optional_string(provider_id),
        "provider_type": _optional_string(provider_type),
        "action_type": _optional_string(action_type),
        "query_plan_ref": _optional_string(query_plan_ref),
        "result_artifact_ref": _optional_string(result_artifact_ref),
        "dry_run": bool(dry_run),
        "external_call_performed": bool(external_call_performed),
        "cost_incurred": bool(cost_incurred),
        "governance_state": _optional_string(governance_state),
        "execution_allowed": bool(execution_allowed),
        "blocked_reason": _optional_string(blocked_reason),
        "created_at": _timestamp(created_at),
    }
    if authorization is not None:
        receipt["authorization"] = deepcopy(authorization)
    return receipt


def validate_external_discovery_execution_receipt(
    receipt: Any,
) -> tuple[ExternalDiscoveryExecutionReceiptValidationError, ...]:
    if not isinstance(receipt, dict):
        return (
            ExternalDiscoveryExecutionReceiptValidationError(
                "invalid_external_discovery_execution_receipt",
                "receipt",
                "external discovery execution receipt must be an object.",
            ),
        )

    errors: list[ExternalDiscoveryExecutionReceiptValidationError] = []
    for field in REQUIRED_RECEIPT_FIELDS:
        if field not in receipt:
            errors.append(
                ExternalDiscoveryExecutionReceiptValidationError(
                    "missing_execution_receipt_field",
                    field,
                    f"{field} must be present on execution receipts.",
                )
            )

    if receipt.get("artifact_type") != EXTERNAL_DISCOVERY_EXECUTION_RECEIPT_ARTIFACT:
        errors.append(
            ExternalDiscoveryExecutionReceiptValidationError(
                "invalid_execution_receipt_artifact_type",
                "artifact_type",
                "artifact_type must be external_discovery_execution_receipt.",
            )
        )

    for field in ("provider_id", "provider_type", "governance_state"):
        value = receipt.get(field)
        if value is not None and not _optional_string(value):
            errors.append(
                ExternalDiscoveryExecutionReceiptValidationError(
                    "invalid_execution_receipt_string",
                    field,
                    f"{field} must be null or a non-empty string.",
                )
            )

    if not _optional_string(receipt.get("action_type")):
        errors.append(
            ExternalDiscoveryExecutionReceiptValidationError(
                "invalid_execution_receipt_string",
                "action_type",
                "action_type must be a non-empty string.",
            )
        )

    for field in ("query_plan_ref", "result_artifact_ref"):
        value = receipt.get(field)
        if value is not None and not _optional_string(value):
            errors.append(
                ExternalDiscoveryExecutionReceiptValidationError(
                    "invalid_execution_receipt_ref",
                    field,
                    f"{field} must be null or a non-empty string.",
                )
            )

    for field in (
        "dry_run",
        "external_call_performed",
        "cost_incurred",
        "execution_allowed",
    ):
        if not isinstance(receipt.get(field), bool):
            errors.append(
                ExternalDiscoveryExecutionReceiptValidationError(
                    "invalid_execution_receipt_boolean",
                    field,
                    f"{field} must be a boolean.",
                )
            )

    execution_allowed = receipt.get("execution_allowed")
    execution_state = receipt.get("execution_state")
    provider_call_implemented = receipt.get("provider_call_implemented")
    live_adapter_execution = (
        receipt.get("dry_run") is False
        and receipt.get("live_authorized") is True
        and provider_call_implemented is True
        and execution_state
        in {
            "live_adapter_executed",
            "live_adapter_failed",
        }
    )
    fake_adapter_execution = (
        execution_allowed is True
        and receipt.get("adapter_kind") == "fake"
        and receipt.get("fake_test_adapter_used") is True
        and receipt.get("external_call_performed") is False
        and receipt.get("cost_incurred") is False
        and receipt.get("dry_run") is False
    )
    live_authorized_without_call = (
        execution_allowed is True
        and execution_state == "live_authorized_not_implemented"
        and provider_call_implemented is False
        and receipt.get("dry_run") is False
    )
    if (
        execution_allowed is not False
        and not live_authorized_without_call
        and not fake_adapter_execution
        and not live_adapter_execution
    ):
        errors.append(
            ExternalDiscoveryExecutionReceiptValidationError(
                "execution_not_allowed",
                "execution_allowed",
                "external discovery execution must be blocked or explicitly authorized without a provider call.",
            )
        )
    if (
        provider_call_implemented is not None
        and provider_call_implemented is not False
        and not fake_adapter_execution
        and not live_adapter_execution
    ):
        errors.append(
            ExternalDiscoveryExecutionReceiptValidationError(
                "provider_call_not_allowed",
                "provider_call_implemented",
                "provider calls are not implemented for this execution stage.",
            )
        )
    if (
        receipt.get("dry_run") is True
        and receipt.get("external_call_performed") is not False
    ):
        errors.append(
            ExternalDiscoveryExecutionReceiptValidationError(
                "external_call_not_allowed",
                "external_call_performed",
                "dry-run external discovery receipts must not record external calls.",
            )
        )
    if receipt.get("dry_run") is True and receipt.get("cost_incurred") is not False:
        errors.append(
            ExternalDiscoveryExecutionReceiptValidationError(
                "cost_not_allowed",
                "cost_incurred",
                "dry-run external discovery receipts must not record incurred cost.",
            )
        )
    if (
        receipt.get("external_call_performed") is True
        and not live_adapter_execution
    ):
        errors.append(
            ExternalDiscoveryExecutionReceiptValidationError(
                "external_call_not_allowed",
                "external_call_performed",
                "external calls require live adapter execution authorization.",
            )
        )
    if receipt.get("cost_incurred") is True and not live_adapter_execution:
        errors.append(
            ExternalDiscoveryExecutionReceiptValidationError(
                "cost_not_allowed",
                "cost_incurred",
                "cost requires live adapter execution authorization.",
            )
        )
    if not _optional_string(receipt.get("blocked_reason")):
        errors.append(
            ExternalDiscoveryExecutionReceiptValidationError(
                "missing_blocked_reason",
                "blocked_reason",
                "blocked_reason must identify why execution did not run.",
            )
        )

    if not _optional_string(receipt.get("created_at")):
        errors.append(
            ExternalDiscoveryExecutionReceiptValidationError(
                "invalid_created_at",
                "created_at",
                "created_at must be an ISO timestamp string.",
            )
        )

    for field in FORBIDDEN_CONTENT_FIELDS:
        if field in receipt:
            errors.append(
                ExternalDiscoveryExecutionReceiptValidationError(
                    "content_field_not_allowed",
                    field,
                    "execution receipts must contain refs and audit metadata only.",
                )
            )

    return tuple(errors)


def _timestamp(value: datetime | str | None) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "EXTERNAL_DISCOVERY_EXECUTION_RECEIPT_ARTIFACT",
    "ExternalDiscoveryExecutionReceiptValidationError",
    "build_external_discovery_execution_receipt",
    "validate_external_discovery_execution_receipt",
]
