from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping


GUEST_CANDIDATE_MERGE_RECEIPT_CONTRACTS_PATH = Path(
    "agents/shared/contracts/guest_candidate_merge_receipt_contracts.json"
)
GUEST_CANDIDATE_MERGE_RECEIPT_ARTIFACT = "guest_candidate_merge_receipt"
GUEST_CANDIDATE_MERGE_POLICY_ID = (
    "declared_identity_structural_guest_candidate_merge_v1"
)


class GuestCandidateMergeReceiptContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class GuestCandidateMergeReceiptContract:
    id: str
    semantic_type: str
    artifact_type: str
    merge_policy_id: str
    allowed_candidate_origins: tuple[str, ...]
    allowed_contact_verification_states: tuple[str, ...]
    required_fields: tuple[str, ...]
    required_false_fields: tuple[str, ...]
    forbidden_fields: tuple[str, ...]
    semantic_authority: dict[str, bool]
    fail_closed: dict[str, bool]


@dataclass(frozen=True)
class GuestCandidateMergeReceiptValidationError:
    error_code: str
    field: str
    message: str


def validate_guest_candidate_merge_receipt(
    receipt: Any,
    *,
    root: str | Path | None = None,
) -> tuple[GuestCandidateMergeReceiptValidationError, ...]:
    contract = load_guest_candidate_merge_receipt_contract(root)
    if contract is None:
        return (
            _error(
                "missing_contract",
                "contract",
                "guest candidate merge receipt contract is unavailable.",
            ),
        )
    if not isinstance(receipt, Mapping):
        return (
            _error(
                "invalid_receipt",
                "receipt",
                "guest candidate merge receipt must be an object.",
            ),
        )

    errors: list[GuestCandidateMergeReceiptValidationError] = []
    for field in contract.required_fields:
        if field not in receipt:
            errors.append(
                _error(
                    "missing_required_field",
                    field,
                    f"required receipt field '{field}' is missing.",
                )
            )

    if receipt.get("artifact_type") != contract.artifact_type:
        errors.append(
            _error(
                "invalid_artifact_type",
                "artifact_type",
                "receipt artifact_type must be guest_candidate_merge_receipt.",
            )
        )
    if receipt.get("merge_policy_id") != contract.merge_policy_id:
        errors.append(
            _error(
                "invalid_merge_policy_id",
                "merge_policy_id",
                "receipt merge_policy_id does not match the contract.",
            )
        )
    if receipt.get("merge_is_structural") is not True:
        errors.append(
            _error(
                "merge_not_structural",
                "merge_is_structural",
                "guest candidate merge receipts must be structural.",
            )
        )

    _validate_string_list(
        receipt,
        "candidate_refs",
        errors,
        non_empty=True,
    )
    _validate_string_list(
        receipt,
        "candidate_origins",
        errors,
        allowed=set(contract.allowed_candidate_origins),
        non_empty=True,
        invalid_code="invalid_candidate_origin",
    )
    _validate_string_list(
        receipt,
        "contact_verification_states",
        errors,
        allowed=set(contract.allowed_contact_verification_states),
        non_empty=True,
        invalid_code="invalid_contact_verification_state",
    )

    for field in contract.required_false_fields:
        if receipt.get(field) is not False:
            errors.append(
                _error(
                    "required_false_field_enabled",
                    field,
                    f"receipt field '{field}' must be false.",
                )
            )

    forbidden = sorted(set(contract.forbidden_fields) & set(receipt))
    for field in forbidden:
        errors.append(
            _error(
                "forbidden_field_present",
                field,
                f"receipt field '{field}' is forbidden by contract.",
            )
        )

    declared_identity_policy = receipt.get("declared_identity_policy")
    if not isinstance(declared_identity_policy, Mapping):
        errors.append(
            _error(
                "invalid_declared_identity_policy",
                "declared_identity_policy",
                "declared_identity_policy must be an object.",
            )
        )
    elif declared_identity_policy.get("hidden_dedup_inference_performed") is not False:
        errors.append(
            _error(
                "hidden_dedup_inference_performed",
                "declared_identity_policy.hidden_dedup_inference_performed",
                "hidden dedup inference must not be performed.",
            )
        )

    for field in ("identity_evidence", "provenance_refs"):
        value = receipt.get(field)
        if not isinstance(value, list) or not all(
            isinstance(item, Mapping) for item in value
        ):
            errors.append(
                _error(
                    "invalid_object_list",
                    field,
                    f"receipt field '{field}' must be a list of objects.",
                )
            )

    return tuple(errors)


@lru_cache(maxsize=None)
def load_guest_candidate_merge_receipt_contract(
    root: str | Path | None = None,
) -> GuestCandidateMergeReceiptContract | None:
    try:
        data = _read_json(GUEST_CANDIDATE_MERGE_RECEIPT_CONTRACTS_PATH, root)
        if data.get("version") != 1:
            raise GuestCandidateMergeReceiptContractError("contract version invalid")
        contracts = data.get("contracts")
        if not isinstance(contracts, list) or len(contracts) != 1:
            raise GuestCandidateMergeReceiptContractError("contract list invalid")
        entry = contracts[0]
        if not isinstance(entry, dict):
            raise GuestCandidateMergeReceiptContractError("contract entry invalid")

        contract = GuestCandidateMergeReceiptContract(
            id=_required_string(entry.get("id")),
            semantic_type=_required_string(entry.get("semantic_type")),
            artifact_type=_required_string(entry.get("artifact_type")),
            merge_policy_id=_required_string(entry.get("merge_policy_id")),
            allowed_candidate_origins=_string_tuple(
                entry.get("allowed_candidate_origins")
            ),
            allowed_contact_verification_states=_string_tuple(
                entry.get("allowed_contact_verification_states")
            ),
            required_fields=_string_tuple(entry.get("required_fields")),
            required_false_fields=_string_tuple(entry.get("required_false_fields")),
            forbidden_fields=_string_tuple(entry.get("forbidden_fields")),
            semantic_authority=_bool_object(entry.get("semantic_authority")),
            fail_closed=_bool_object(entry.get("fail_closed")),
        )
        _validate_contract(contract)
        return contract
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        GuestCandidateMergeReceiptContractError,
    ):
        return None


def _validate_contract(contract: GuestCandidateMergeReceiptContract) -> None:
    if contract.id != GUEST_CANDIDATE_MERGE_RECEIPT_ARTIFACT:
        raise GuestCandidateMergeReceiptContractError("contract id invalid")
    if contract.semantic_type != GUEST_CANDIDATE_MERGE_RECEIPT_ARTIFACT:
        raise GuestCandidateMergeReceiptContractError("semantic type invalid")
    if contract.artifact_type != GUEST_CANDIDATE_MERGE_RECEIPT_ARTIFACT:
        raise GuestCandidateMergeReceiptContractError("artifact type invalid")
    if contract.merge_policy_id != GUEST_CANDIDATE_MERGE_POLICY_ID:
        raise GuestCandidateMergeReceiptContractError("merge policy invalid")
    if not contract.allowed_candidate_origins:
        raise GuestCandidateMergeReceiptContractError("candidate origins missing")
    if not contract.allowed_contact_verification_states:
        raise GuestCandidateMergeReceiptContractError(
            "contact verification states missing"
        )
    if any(value is not False for value in contract.semantic_authority.values()):
        raise GuestCandidateMergeReceiptContractError("contract grants authority")
    if any(value is not True for value in contract.fail_closed.values()):
        raise GuestCandidateMergeReceiptContractError("contract does not fail closed")


def _validate_string_list(
    receipt: Mapping[str, Any],
    field: str,
    errors: list[GuestCandidateMergeReceiptValidationError],
    *,
    allowed: set[str] | None = None,
    non_empty: bool = False,
    invalid_code: str = "invalid_string_list_item",
) -> None:
    value = receipt.get(field)
    if not isinstance(value, list) or (
        non_empty and not value
    ) or any(not isinstance(item, str) or not item.strip() for item in value):
        errors.append(
            _error(
                "invalid_string_list",
                field,
                f"receipt field '{field}' must be a list of non-empty strings.",
            )
        )
        return

    if allowed is None:
        return

    for item in value:
        if item not in allowed:
            errors.append(
                _error(
                    invalid_code,
                    field,
                    f"receipt field '{field}' contains unsupported value '{item}'.",
                )
            )


def _read_json(path: Path, root: str | Path | None) -> dict[str, Any]:
    resolved = path if root is None else Path(root) / path
    return json.loads(resolved.read_text(encoding="utf-8"))


def _required_string(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GuestCandidateMergeReceiptContractError("required string invalid")
    return value.strip()


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise GuestCandidateMergeReceiptContractError("string list invalid")
    result = tuple(
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    )
    if len(result) != len(value):
        raise GuestCandidateMergeReceiptContractError("string list invalid")
    return result


def _bool_object(value: Any) -> dict[str, bool]:
    if not isinstance(value, dict) or not value:
        raise GuestCandidateMergeReceiptContractError("bool object invalid")
    if any(not isinstance(item, bool) for item in value.values()):
        raise GuestCandidateMergeReceiptContractError("bool object invalid")
    return dict(value)


def _error(
    error_code: str,
    field: str,
    message: str,
) -> GuestCandidateMergeReceiptValidationError:
    return GuestCandidateMergeReceiptValidationError(
        error_code=error_code,
        field=field,
        message=message,
    )


__all__ = [
    "GUEST_CANDIDATE_MERGE_RECEIPT_ARTIFACT",
    "GUEST_CANDIDATE_MERGE_RECEIPT_CONTRACTS_PATH",
    "GuestCandidateMergeReceiptContract",
    "GuestCandidateMergeReceiptValidationError",
    "load_guest_candidate_merge_receipt_contract",
    "validate_guest_candidate_merge_receipt",
]
