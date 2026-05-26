from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXTERNAL_SEARCH_EXECUTION_RECEIPT_ARTIFACT = "external_search_execution_receipt"
EXTERNAL_SEARCH_EXECUTION_RECEIPT_AUDIT_LOG_PATH = Path(
    "logs/external_search_execution_receipts.jsonl"
)
ALLOWED_EXECUTION_STATES = frozenset(
    {
        "provider_execution_disabled",
        "provider_execution_completed",
        "provider_execution_failed",
    }
)
REQUIRED_RECEIPT_FIELDS = (
    "artifact_type",
    "receipt_id",
    "receipt_ref",
    "request_id",
    "search_id",
    "provider_id",
    "provider_type",
    "semantic_type",
    "authorization_decision",
    "execution_state",
    "execution_performed",
    "external_call_performed",
    "cost_incurred",
    "timing",
    "bounds",
    "normalized_result_metadata",
    "failure",
    "result_artifact_ref",
    "created_at",
)
FORBIDDEN_CONTENT_FIELDS = frozenset(
    {
        "api_key",
        "authorization_header",
        "bearer_token",
        "citations",
        "credential",
        "credential_env_var",
        "email_draft",
        "prompt",
        "provider_payload",
        "query",
        "ranking",
        "raw_provider_payload",
        "raw_results",
        "rendered_context",
        "results",
        "secret",
        "source_refs",
        "summary",
        "token",
    }
)


@dataclass(frozen=True)
class ExternalSearchExecutionReceiptValidationError:
    error_code: str
    field: str
    message: str


def build_external_search_execution_receipt(
    *,
    request_id: str,
    search_id: str,
    provider_id: str | None,
    provider_type: str | None,
    authorization_decision: dict[str, Any],
    execution_state: str,
    execution_performed: bool,
    external_call_performed: bool,
    cost_incurred: bool,
    timing: dict[str, Any],
    bounds: dict[str, Any],
    normalized_result_metadata: dict[str, Any] | None = None,
    failure: dict[str, Any] | None = None,
    result_artifact_ref: str | None = None,
    created_at: datetime | str | None = None,
) -> dict[str, Any]:
    created = _timestamp(created_at)
    safe_provider_id = _optional_string(provider_id)
    safe_request_id = _required_string(request_id)
    receipt_id = (
        f"external-search-execution:{safe_request_id}:"
        f"{safe_provider_id or 'provider-unknown'}:{created}"
    )
    receipt = {
        "artifact_type": EXTERNAL_SEARCH_EXECUTION_RECEIPT_ARTIFACT,
        "receipt_id": receipt_id,
        "receipt_ref": f"receipt:{receipt_id}",
        "request_id": safe_request_id,
        "search_id": _required_string(search_id),
        "provider_id": safe_provider_id,
        "provider_type": _optional_string(provider_type),
        "semantic_type": "external_search",
        "authorization_decision": _safe_authorization_decision(
            authorization_decision
        ),
        "execution_state": _required_string(execution_state),
        "execution_performed": bool(execution_performed),
        "external_call_performed": bool(external_call_performed),
        "cost_incurred": bool(cost_incurred),
        "timing": _safe_timing(timing),
        "bounds": _safe_bounds(bounds),
        "normalized_result_metadata": _safe_result_metadata(
            normalized_result_metadata
        ),
        "failure": _safe_failure(failure),
        "result_artifact_ref": _optional_string(result_artifact_ref),
        "created_at": created,
    }
    return receipt


def validate_external_search_execution_receipt(
    receipt: Any,
) -> tuple[ExternalSearchExecutionReceiptValidationError, ...]:
    if not isinstance(receipt, dict):
        return (
            ExternalSearchExecutionReceiptValidationError(
                "invalid_external_search_execution_receipt",
                "receipt",
                "external search execution receipt must be an object.",
            ),
        )

    errors: list[ExternalSearchExecutionReceiptValidationError] = []
    for field in REQUIRED_RECEIPT_FIELDS:
        if field not in receipt:
            errors.append(
                ExternalSearchExecutionReceiptValidationError(
                    "missing_execution_receipt_field",
                    field,
                    f"{field} must be present on execution receipts.",
                )
            )

    if receipt.get("artifact_type") != EXTERNAL_SEARCH_EXECUTION_RECEIPT_ARTIFACT:
        errors.append(
            ExternalSearchExecutionReceiptValidationError(
                "invalid_execution_receipt_artifact_type",
                "artifact_type",
                "artifact_type must be external_search_execution_receipt.",
            )
        )
    for field in ("receipt_id", "receipt_ref", "request_id", "search_id"):
        if not _optional_string(receipt.get(field)):
            errors.append(
                ExternalSearchExecutionReceiptValidationError(
                    "invalid_execution_receipt_string",
                    field,
                    f"{field} must be a non-empty string.",
                )
            )
    for field in ("provider_id", "provider_type", "result_artifact_ref"):
        value = receipt.get(field)
        if value is not None and not _optional_string(value):
            errors.append(
                ExternalSearchExecutionReceiptValidationError(
                    "invalid_execution_receipt_string",
                    field,
                    f"{field} must be null or a non-empty string.",
                )
            )
    if receipt.get("semantic_type") != "external_search":
        errors.append(
            ExternalSearchExecutionReceiptValidationError(
                "invalid_semantic_type",
                "semantic_type",
                "semantic_type must be external_search.",
            )
        )
    if receipt.get("execution_state") not in ALLOWED_EXECUTION_STATES:
        errors.append(
            ExternalSearchExecutionReceiptValidationError(
                "invalid_execution_state",
                "execution_state",
                "execution_state must be a known provider execution state.",
            )
        )
    for field in ("execution_performed", "external_call_performed", "cost_incurred"):
        if not isinstance(receipt.get(field), bool):
            errors.append(
                ExternalSearchExecutionReceiptValidationError(
                    "invalid_execution_receipt_boolean",
                    field,
                    f"{field} must be a boolean.",
                )
            )

    _validate_timing(receipt.get("timing"), errors)
    _validate_bounds(receipt.get("bounds"), errors)
    _validate_result_metadata(receipt.get("normalized_result_metadata"), errors)
    _validate_failure(receipt.get("failure"), receipt.get("execution_state"), errors)
    _validate_authorization_decision(receipt.get("authorization_decision"), errors)

    for path in _forbidden_content_paths(receipt):
        errors.append(
            ExternalSearchExecutionReceiptValidationError(
                "content_field_not_allowed",
                path,
                "execution receipts must contain refs and audit metadata only.",
            )
        )
    return tuple(errors)


def append_external_search_execution_receipt_audit_record(
    receipt: dict[str, Any],
    *,
    audit_path: str | Path = EXTERNAL_SEARCH_EXECUTION_RECEIPT_AUDIT_LOG_PATH,
) -> None:
    errors = validate_external_search_execution_receipt(receipt)
    if errors:
        fields = ", ".join(error.field for error in errors)
        raise ValueError(f"invalid external search execution receipt: {fields}")
    path = Path(audit_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, sort_keys=True) + "\n")


def load_external_search_execution_receipt_audit_records(
    audit_path: str | Path = EXTERNAL_SEARCH_EXECUTION_RECEIPT_AUDIT_LOG_PATH,
) -> tuple[dict[str, Any], ...]:
    path = Path(audit_path)
    if not path.exists():
        return ()
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            records.append(value)
    return tuple(records)


def _validate_timing(
    value: Any,
    errors: list[ExternalSearchExecutionReceiptValidationError],
) -> None:
    if not isinstance(value, dict):
        errors.append(
            ExternalSearchExecutionReceiptValidationError(
                "invalid_timing",
                "timing",
                "timing must be an object.",
            )
        )
        return
    for field in ("started_at", "completed_at"):
        if not _optional_string(value.get(field)):
            errors.append(
                ExternalSearchExecutionReceiptValidationError(
                    "invalid_timing",
                    f"timing.{field}",
                    f"timing.{field} must be a timestamp string.",
                )
            )
    duration = value.get("duration_ms")
    if not isinstance(duration, int) or isinstance(duration, bool) or duration < 0:
        errors.append(
            ExternalSearchExecutionReceiptValidationError(
                "invalid_timing",
                "timing.duration_ms",
                "timing.duration_ms must be a non-negative integer.",
            )
        )


def _validate_bounds(
    value: Any,
    errors: list[ExternalSearchExecutionReceiptValidationError],
) -> None:
    if not isinstance(value, dict):
        errors.append(
            ExternalSearchExecutionReceiptValidationError(
                "invalid_bounds",
                "bounds",
                "bounds must be an object.",
            )
        )
        return
    for field in ("requested_max_results", "normalized_max_results", "timeout_ms"):
        item = value.get(field)
        if item is not None and (
            not isinstance(item, int) or isinstance(item, bool) or item < 0
        ):
            errors.append(
                ExternalSearchExecutionReceiptValidationError(
                    "invalid_bounds",
                    f"bounds.{field}",
                    f"bounds.{field} must be null or a non-negative integer.",
                )
            )
    for field in (
        "freshness_policy_present",
        "source_policy_present",
        "result_bounds_present",
    ):
        if not isinstance(value.get(field), bool):
            errors.append(
                ExternalSearchExecutionReceiptValidationError(
                    "invalid_bounds",
                    f"bounds.{field}",
                    f"bounds.{field} must be a boolean.",
                )
            )


def _validate_result_metadata(
    value: Any,
    errors: list[ExternalSearchExecutionReceiptValidationError],
) -> None:
    if not isinstance(value, dict):
        errors.append(
            ExternalSearchExecutionReceiptValidationError(
                "invalid_normalized_result_metadata",
                "normalized_result_metadata",
                "normalized_result_metadata must be an object.",
            )
        )
        return
    for field in (
        "raw_result_count",
        "source_ref_count",
        "citation_count",
        "rejected_result_count",
    ):
        item = value.get(field)
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            errors.append(
                ExternalSearchExecutionReceiptValidationError(
                    "invalid_normalized_result_metadata",
                    f"normalized_result_metadata.{field}",
                    f"normalized_result_metadata.{field} must be a non-negative integer.",
                )
            )


def _validate_failure(
    value: Any,
    execution_state: Any,
    errors: list[ExternalSearchExecutionReceiptValidationError],
) -> None:
    if not isinstance(value, dict):
        errors.append(
            ExternalSearchExecutionReceiptValidationError(
                "invalid_failure",
                "failure",
                "failure must be an object.",
            )
        )
        return
    failed = execution_state in {
        "provider_execution_disabled",
        "provider_execution_failed",
    }
    if not isinstance(value.get("failed"), bool):
        errors.append(
            ExternalSearchExecutionReceiptValidationError(
                "invalid_failure",
                "failure.failed",
                "failure.failed must be a boolean.",
            )
        )
    if failed and value.get("failed") is not True:
        errors.append(
            ExternalSearchExecutionReceiptValidationError(
                "failure_state_hidden",
                "failure.failed",
                "failed execution states must be explicit.",
            )
        )
    if execution_state == "provider_execution_failed" and not _optional_string(
        value.get("error_class")
    ):
        errors.append(
            ExternalSearchExecutionReceiptValidationError(
                "missing_error_class",
                "failure.error_class",
                "provider execution failures must record a safe error class.",
            )
        )


def _validate_authorization_decision(
    value: Any,
    errors: list[ExternalSearchExecutionReceiptValidationError],
) -> None:
    if not isinstance(value, dict):
        errors.append(
            ExternalSearchExecutionReceiptValidationError(
                "invalid_authorization_decision",
                "authorization_decision",
                "authorization_decision must be an object.",
            )
        )
        return
    required = (
        "authorization_state",
        "authorization_status",
        "live_provider_execution_authorized",
        "external_call_allowed",
        "cost_allowed",
        "audit_required",
        "fail_closed",
    )
    for field in required:
        if field not in value:
            errors.append(
                ExternalSearchExecutionReceiptValidationError(
                    "missing_authorization_decision_field",
                    f"authorization_decision.{field}",
                    f"authorization_decision.{field} is required.",
                )
            )


def _safe_authorization_decision(value: dict[str, Any]) -> dict[str, Any]:
    allowed_fields = {
        "provider_id",
        "resource_id",
        "semantic_type",
        "authorization_state",
        "authorization_status",
        "live_provider_execution_authorized",
        "external_call_allowed",
        "cost_allowed",
        "audit_required",
        "fail_closed",
        "policy_id",
        "governance_id",
        "binding_id",
        "contract_id",
        "skipped_reasons",
    }
    if not isinstance(value, dict):
        return {}
    return {
        key: deepcopy(item)
        for key, item in value.items()
        if key in allowed_fields and key not in FORBIDDEN_CONTENT_FIELDS
    }


def _safe_timing(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"started_at": None, "completed_at": None, "duration_ms": 0}
    return {
        "started_at": _optional_string(value.get("started_at")),
        "completed_at": _optional_string(value.get("completed_at")),
        "duration_ms": _safe_non_negative_int(value.get("duration_ms")),
    }


def _safe_bounds(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    return {
        "requested_max_results": _safe_optional_non_negative_int(
            value.get("requested_max_results")
        ),
        "normalized_max_results": _safe_optional_non_negative_int(
            value.get("normalized_max_results")
        ),
        "timeout_ms": _safe_optional_non_negative_int(value.get("timeout_ms")),
        "freshness_policy_present": bool(value.get("freshness_policy_present")),
        "source_policy_present": bool(value.get("source_policy_present")),
        "result_bounds_present": bool(value.get("result_bounds_present")),
    }


def _safe_result_metadata(value: dict[str, Any] | None) -> dict[str, int]:
    if not isinstance(value, dict):
        value = {}
    return {
        "raw_result_count": _safe_non_negative_int(value.get("raw_result_count")),
        "source_ref_count": _safe_non_negative_int(value.get("source_ref_count")),
        "citation_count": _safe_non_negative_int(value.get("citation_count")),
        "rejected_result_count": _safe_non_negative_int(
            value.get("rejected_result_count")
        ),
    }


def _safe_failure(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"failed": False, "failure_reasons": [], "error_class": None}
    reasons = value.get("failure_reasons")
    safe_reasons = [
        item.strip()
        for item in reasons
        if isinstance(item, str) and item.strip()
    ] if isinstance(reasons, list) else []
    return {
        "failed": bool(value.get("failed")),
        "failure_reasons": safe_reasons,
        "error_class": _optional_string(value.get("error_class")),
    }


def _forbidden_content_paths(value: Any, *, prefix: str = "") -> tuple[str, ...]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if key_text.lower() in FORBIDDEN_CONTENT_FIELDS:
                paths.append(path)
            paths.extend(_forbidden_content_paths(item, prefix=path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            paths.extend(_forbidden_content_paths(item, prefix=f"{prefix}[{index}]"))
    return tuple(paths)


def _timestamp(value: datetime | str | None) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def _safe_optional_non_negative_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _safe_non_negative_int(value: Any) -> int:
    normalized = _safe_optional_non_negative_int(value)
    return normalized if normalized is not None else 0


def _required_string(value: Any) -> str:
    normalized = _optional_string(value)
    if normalized is None:
        raise ValueError("receipt string required")
    return normalized


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "EXTERNAL_SEARCH_EXECUTION_RECEIPT_ARTIFACT",
    "EXTERNAL_SEARCH_EXECUTION_RECEIPT_AUDIT_LOG_PATH",
    "ExternalSearchExecutionReceiptValidationError",
    "append_external_search_execution_receipt_audit_record",
    "build_external_search_execution_receipt",
    "load_external_search_execution_receipt_audit_records",
    "validate_external_search_execution_receipt",
]
