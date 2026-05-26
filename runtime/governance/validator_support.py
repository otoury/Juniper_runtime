from __future__ import annotations

from typing import Any, Mapping, Sequence


VALIDATOR_SUPPORT_VERSION = "stage170_validator_support_v1"


def safe_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def unique_values(values: Sequence[str]) -> list[str]:
    found: list[str] = []
    for value in values:
        text = safe_string(value)
        if text and text not in found:
            found.append(text)
    return found


def matching_paths(
    value: Any,
    fields: frozenset[str],
    *,
    prefix: str = "",
    allow_false: bool = False,
    false_allowed_fields: frozenset[str] = frozenset(),
) -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            path = f"{prefix}.{key}" if prefix else key
            if key in fields and not (
                item is False and (allow_false or key in false_allowed_fields)
            ):
                paths.append(path)
            paths.extend(
                matching_paths(
                    item,
                    fields,
                    prefix=path,
                    allow_false=allow_false,
                    false_allowed_fields=false_allowed_fields,
                )
            )
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            paths.extend(
                matching_paths(
                    item,
                    fields,
                    prefix=f"{prefix}[{index}]",
                    allow_false=allow_false,
                    false_allowed_fields=false_allowed_fields,
                )
            )
    return paths


def validator_lineage(
    *,
    owner: str,
    validator: str,
    contract_id: str,
    source: str | None = None,
    parent_validators: Sequence[str] | None = None,
    child_validators: Sequence[str] | None = None,
) -> dict[str, Any]:
    owner_id = safe_string(owner) or "runtime"
    validator_id = safe_string(validator) or "unknown_validator"
    lineage: dict[str, Any] = {
        "support_version": VALIDATOR_SUPPORT_VERSION,
        "owner": owner_id,
        "validator": validator_id,
        "contract_id": safe_string(contract_id),
        "source": safe_string(source),
        "explicit_validator_owner": True,
        "hidden_orchestration_performed": False,
        "semantic_reinterpretation_performed": False,
        "memory_write_performed": False,
        "parent_validators": unique_values(list(parent_validators or [])),
        "child_validators": unique_values(list(child_validators or [])),
    }
    lineage["lineage_path"] = unique_values(
        [
            *lineage["parent_validators"],
            f"{owner_id}.{validator_id}",
            *lineage["child_validators"],
        ]
    )
    return lineage


__all__ = [
    "VALIDATOR_SUPPORT_VERSION",
    "matching_paths",
    "safe_string",
    "unique_values",
    "validator_lineage",
]
