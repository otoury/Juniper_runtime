from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SUMMARY_CONTRACT_PATH = Path("agents/shared/skills/summarize/contract.json")
ALLOWED_ARTIFACT_TYPES = {"summary"}


@dataclass(frozen=True)
class SummaryContract:
    contract_id: str
    artifact_type: str
    max_items: int
    max_words: int | None
    max_summary_blocks: int
    max_summary_chars_per_block: int
    required_source_item_fields: tuple[str, ...]
    raw_data: dict[str, Any]


@dataclass(frozen=True)
class SummaryContractError:
    field: str
    message: str


def load_summary_contracts(
    path: str | Path = SUMMARY_CONTRACT_PATH,
) -> tuple[tuple[SummaryContract, ...], tuple[SummaryContractError, ...]]:
    manifest_path = Path(path)
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return (), (SummaryContractError("manifest", str(exc)),)

    contracts = data.get("contracts")
    if not isinstance(contracts, list):
        return (), (SummaryContractError("contracts", "contracts must be a list."),)

    loaded = []
    errors = []
    for index, entry in enumerate(contracts):
        if not isinstance(entry, dict):
            errors.append(
                SummaryContractError(
                    f"contracts[{index}]",
                    "contract entry must be an object.",
                )
            )
            continue
        contract, contract_errors = _validate_contract(entry, index=index)
        if contract_errors:
            errors.extend(contract_errors)
        elif contract is not None:
            loaded.append(contract)
    return tuple(loaded), tuple(errors)


def get_summary_contract(
    contract_id: str = "summarize_metadata_items",
    *,
    path: str | Path = SUMMARY_CONTRACT_PATH,
) -> SummaryContract | None:
    contracts, errors = load_summary_contracts(path)
    if errors:
        return None
    for contract in contracts:
        if contract.contract_id == contract_id:
            return contract
    return None


def _validate_contract(
    entry: dict[str, Any],
    *,
    index: int,
) -> tuple[SummaryContract | None, tuple[SummaryContractError, ...]]:
    errors = []
    prefix = f"contracts[{index}]"

    contract_id = _required_string(entry, "contract_id", errors, prefix)
    artifact_type = _required_string(entry, "artifact_type", errors, prefix)
    max_items = _required_positive_int(entry, "max_items", errors, prefix)
    max_words = _optional_positive_int(entry, "max_words", errors, prefix)

    if artifact_type and artifact_type not in ALLOWED_ARTIFACT_TYPES:
        errors.append(
            SummaryContractError(
                f"{prefix}.artifact_type",
                "unsupported artifact_type.",
            )
        )
    if max_items and max_items > 10:
        errors.append(
            SummaryContractError(
                f"{prefix}.max_items",
                "max_items must be bounded at 10 or fewer.",
            )
        )

    summary_kind_policy = _required_object(
        entry,
        "summary_kind_policy",
        errors,
        prefix,
    )
    tone_policy = _required_object(entry, "tone_policy", errors, prefix)
    source_grounding = _required_object(entry, "source_grounding", errors, prefix)
    bounded_output = _required_object(entry, "bounded_output", errors, prefix)
    safety = _required_object(entry, "safety", errors, prefix)

    for name, policy in (
        ("summary_kind_policy", summary_kind_policy),
        ("tone_policy", tone_policy),
    ):
        if policy and policy.get("required") is not True:
            errors.append(
                SummaryContractError(
                    f"{prefix}.{name}.required",
                    f"{name} must be required.",
                )
            )

    required_fields = ()
    if source_grounding:
        if source_grounding.get("required") is not True:
            errors.append(
                SummaryContractError(
                    f"{prefix}.source_grounding.required",
                    "source grounding is required.",
                )
            )
        required_fields = _string_tuple(
            source_grounding.get("required_source_item_fields")
        )
        if not required_fields:
            errors.append(
                SummaryContractError(
                    f"{prefix}.source_grounding.required_source_item_fields",
                    "required source item fields must be declared.",
                )
            )

    max_blocks = 0
    max_chars = 0
    if bounded_output:
        if bounded_output.get("required") is not True:
            errors.append(
                SummaryContractError(
                    f"{prefix}.bounded_output.required",
                    "bounded output is required.",
                )
            )
        max_blocks = _required_positive_int(
            bounded_output,
            "max_summary_blocks",
            errors,
            f"{prefix}.bounded_output",
        )
        max_chars = _required_positive_int(
            bounded_output,
            "max_summary_chars_per_block",
            errors,
            f"{prefix}.bounded_output",
        )

    if safety:
        for field in (
            "source_expansion_allowed",
            "live_fetch_allowed",
            "memory_write_allowed",
            "model_chaining_allowed",
            "embedding_allowed",
            "autonomous_topic_expansion_allowed",
            "hidden_context_injection_allowed",
        ):
            if safety.get(field) is not False:
                errors.append(
                    SummaryContractError(
                        f"{prefix}.safety.{field}",
                        f"{field} must be false.",
                    )
                )

    if errors:
        return None, tuple(errors)

    return (
        SummaryContract(
            contract_id=contract_id,
            artifact_type=artifact_type,
            max_items=max_items,
            max_words=max_words,
            max_summary_blocks=max_blocks,
            max_summary_chars_per_block=max_chars,
            required_source_item_fields=required_fields,
            raw_data=dict(entry),
        ),
        (),
    )


def _required_string(
    value: dict[str, Any],
    field: str,
    errors: list[SummaryContractError],
    prefix: str,
) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item.strip():
        errors.append(
            SummaryContractError(
                f"{prefix}.{field}",
                f"{field} must be a non-empty string.",
            )
        )
        return ""
    return item.strip()


def _required_positive_int(
    value: dict[str, Any],
    field: str,
    errors: list[SummaryContractError],
    prefix: str,
) -> int:
    item = value.get(field)
    if not isinstance(item, int) or isinstance(item, bool) or item < 1:
        errors.append(
            SummaryContractError(
                f"{prefix}.{field}",
                f"{field} must be a positive integer.",
            )
        )
        return 0
    return item


def _optional_positive_int(
    value: dict[str, Any],
    field: str,
    errors: list[SummaryContractError],
    prefix: str,
) -> int | None:
    item = value.get(field)
    if item is None:
        return None
    if not isinstance(item, int) or isinstance(item, bool) or item < 1:
        errors.append(
            SummaryContractError(
                f"{prefix}.{field}",
                f"{field} must be null or a positive integer.",
            )
        )
        return None
    return item


def _required_object(
    value: dict[str, Any],
    field: str,
    errors: list[SummaryContractError],
    prefix: str,
) -> dict[str, Any]:
    item = value.get(field)
    if not isinstance(item, dict):
        errors.append(
            SummaryContractError(
                f"{prefix}.{field}",
                f"{field} must be an object.",
            )
        )
        return {}
    return item


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    )


__all__ = [
    "SUMMARY_CONTRACT_PATH",
    "SummaryContract",
    "SummaryContractError",
    "get_summary_contract",
    "load_summary_contracts",
]
