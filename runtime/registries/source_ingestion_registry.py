from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


SOURCE_INGESTION_CONTRACTS_PATH = Path(
    "agents/shared/semantics/source_ingestion_contracts.json"
)
AGENT_SOURCE_FEEDS_FILENAME = "source_feeds.json"
ALLOWED_SOURCE_TYPES = {"rss_feed"}
ALLOWED_GOVERNANCE_STATES = {"enabled", "disabled", "audit_only"}
ALLOWED_REFRESH_POLICY_TYPES = {"manual", "scheduled"}
ALLOWED_PRIORITY_LEVELS = {"low", "normal", "high", "critical"}
PLACEHOLDER_DOMAINS = {"example.com", "example.org", "example.net"}
FORBIDDEN_DECLARATION_FIELDS = {
    "autonomous",
    "autonomous_source_creation",
    "background_retrieval",
    "fetch",
    "fetch_callable",
    "hidden_prompt",
    "hidden_prompt_injection",
    "memory_write",
    "memory_writes",
    "runner",
    "telegram_delivery",
}


class SourceIngestionRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceIngestionContract:
    id: str
    contract_version: int
    source_type: str
    governance_states: tuple[str, ...]
    forbidden_declaration_fields: tuple[str, ...]
    raw_data: dict[str, Any]


@dataclass(frozen=True)
class SourceIngestionDeclaration:
    source_id: str
    contract_id: str
    source_type: str
    url: str
    owning_agent: str
    governance_state: str
    refresh_policy: dict[str, Any]
    source_category: dict[str, Any]
    priority_policy: dict[str, Any]
    provenance_policy: dict[str, Any]
    provenance_audit: dict[str, Any]
    content_safety: dict[str, bool]
    storage_policy: dict[str, bool]
    manifest_path: Path
    raw_data: dict[str, Any]

    def to_metadata(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "contract_id": self.contract_id,
            "source_type": self.source_type,
            "url": self.url,
            "owning_agent": self.owning_agent,
            "governance_state": self.governance_state,
            "refresh_policy": dict(self.refresh_policy),
            "source_category": dict(self.source_category),
            "priority_policy": dict(self.priority_policy),
            "provenance_policy": dict(self.provenance_policy),
            "provenance_audit": dict(self.provenance_audit),
            "content_safety": dict(self.content_safety),
            "storage_policy": dict(self.storage_policy),
            "manifest_path": str(self.manifest_path),
        }


@dataclass(frozen=True)
class SourceIngestionValidationError:
    error_code: str
    field: str
    message: str


def _registry_path(root: str | Path | None = None) -> Path:
    if root is None:
        return SOURCE_INGESTION_CONTRACTS_PATH
    return Path(root) / SOURCE_INGESTION_CONTRACTS_PATH


def _require_string(entry: dict[str, Any], key: str, *, entry_id: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SourceIngestionRegistryError(
            f"Source ingestion entry '{entry_id}' field '{key}' must be a "
            "non-empty string."
        )
    return value.strip()


def _require_int(
    entry: dict[str, Any],
    key: str,
    *,
    entry_id: str,
    minimum: int = 1,
) -> int:
    value = entry.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise SourceIngestionRegistryError(
            f"Source ingestion entry '{entry_id}' field '{key}' must be an "
            f"integer greater than or equal to {minimum}."
        )
    return value


def _require_object(
    entry: dict[str, Any],
    key: str,
    *,
    entry_id: str,
) -> dict[str, Any]:
    value = entry.get(key)
    if not isinstance(value, dict):
        raise SourceIngestionRegistryError(
            f"Source ingestion entry '{entry_id}' field '{key}' must be an "
            "object."
        )
    return dict(value)


def _require_string_list(
    entry: dict[str, Any],
    key: str,
    *,
    entry_id: str,
) -> tuple[str, ...]:
    value = entry.get(key)
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise SourceIngestionRegistryError(
            f"Source ingestion entry '{entry_id}' field '{key}' must be a "
            "list of non-empty strings."
        )
    return tuple(item.strip() for item in value)


def _forbidden_field_paths(value: Any, *, prefix: str = "") -> tuple[str, ...]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, item in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if key_text in FORBIDDEN_DECLARATION_FIELDS:
                paths.append(path)
            paths.extend(_forbidden_field_paths(item, prefix=path))
        return tuple(paths)
    if isinstance(value, list):
        paths = []
        for index, item in enumerate(value):
            paths.extend(_forbidden_field_paths(item, prefix=f"{prefix}[{index}]"))
        return tuple(paths)
    return ()


def _contract_from_entry(entry: Any) -> SourceIngestionContract:
    if not isinstance(entry, dict):
        raise SourceIngestionRegistryError(
            "Source ingestion contract entries must be objects."
        )

    entry_id = _require_string(entry, "id", entry_id="<unknown>")
    contract_version = _require_int(entry, "contract_version", entry_id=entry_id)
    if contract_version != 1:
        raise SourceIngestionRegistryError(
            f"Source ingestion contract '{entry_id}' has unsupported version."
        )

    source_type = _require_string(entry, "source_type", entry_id=entry_id)
    if source_type not in ALLOWED_SOURCE_TYPES:
        raise SourceIngestionRegistryError(
            f"Source ingestion contract '{entry_id}' has unsupported source_type."
        )

    fields = set(
        _require_string_list(
            _require_object(entry, "declaration_fields", entry_id=entry_id),
            "required_fields",
            entry_id=entry_id,
        )
    )
    expected_fields = {
        "source_id",
        "contract_id",
        "source_type",
        "url",
        "owning_agent",
        "governance_state",
        "refresh_policy",
        "source_category",
        "priority_policy",
        "provenance_policy",
        "provenance_audit",
        "content_safety",
        "storage_policy",
    }
    if fields != expected_fields:
        raise SourceIngestionRegistryError(
            f"Source ingestion contract '{entry_id}' has incomplete fields."
        )

    governance = _require_object(entry, "governance", entry_id=entry_id)
    governance_states = _require_string_list(
        governance,
        "allowed_states",
        entry_id=entry_id,
    )
    if set(governance_states) != ALLOWED_GOVERNANCE_STATES:
        raise SourceIngestionRegistryError(
            f"Source ingestion contract '{entry_id}' has unsupported governance."
        )

    refresh_policy = _require_object(entry, "refresh_policy", entry_id=entry_id)
    if refresh_policy.get("static_declaration_required") is not True:
        raise SourceIngestionRegistryError(
            f"Source ingestion contract '{entry_id}' must require static refresh."
        )
    if (
        set(
            _require_string_list(
                refresh_policy,
                "allowed_types",
                entry_id=entry_id,
            )
        )
        != ALLOWED_REFRESH_POLICY_TYPES
    ):
        raise SourceIngestionRegistryError(
            f"Source ingestion contract '{entry_id}' has unsupported refresh."
        )

    source_category = _require_object(entry, "source_category", entry_id=entry_id)
    if source_category.get("required") is not True:
        raise SourceIngestionRegistryError(
            f"Source ingestion contract '{entry_id}' must require category tags."
        )
    priority_policy = _require_object(entry, "priority_policy", entry_id=entry_id)
    if priority_policy.get("required") is not True:
        raise SourceIngestionRegistryError(
            f"Source ingestion contract '{entry_id}' must require priority policy."
        )
    provenance_policy = _require_object(
        entry,
        "provenance_policy",
        entry_id=entry_id,
    )
    if provenance_policy.get("required") is not True:
        raise SourceIngestionRegistryError(
            f"Source ingestion contract '{entry_id}' must require provenance policy."
        )

    content_safety = _require_object(entry, "content_safety", entry_id=entry_id)
    if content_safety.get("required") is not True:
        raise SourceIngestionRegistryError(
            f"Source ingestion contract '{entry_id}' must require content safety."
        )
    storage_policy = _require_object(entry, "storage_policy", entry_id=entry_id)
    if storage_policy.get("required") is not True:
        raise SourceIngestionRegistryError(
            f"Source ingestion contract '{entry_id}' must require storage policy."
        )
    fail_closed = _require_object(entry, "fail_closed", entry_id=entry_id)
    if any(value is not True for value in fail_closed.values()):
        raise SourceIngestionRegistryError(
            f"Source ingestion contract '{entry_id}' fail_closed must be true."
        )

    forbidden_fields = _require_string_list(
        entry,
        "forbidden_declaration_fields",
        entry_id=entry_id,
    )
    if not FORBIDDEN_DECLARATION_FIELDS.issubset(set(forbidden_fields)):
        raise SourceIngestionRegistryError(
            f"Source ingestion contract '{entry_id}' must forbid execution fields."
        )

    return SourceIngestionContract(
        id=entry_id,
        contract_version=contract_version,
        source_type=source_type,
        governance_states=governance_states,
        forbidden_declaration_fields=forbidden_fields,
        raw_data=dict(entry),
    )


def validate_source_ingestion_declaration(
    declaration: Any,
    *,
    contracts: tuple[SourceIngestionContract, ...] | None = None,
    manifest_path: Path | None = None,
) -> list[SourceIngestionValidationError]:
    manifest = manifest_path or SOURCE_INGESTION_CONTRACTS_PATH
    if not isinstance(declaration, dict):
        return [
            SourceIngestionValidationError(
                error_code="invalid_source_ingestion_declaration",
                field="declaration",
                message="declaration must be an object.",
            )
        ]

    errors: list[SourceIngestionValidationError] = []
    for path in _forbidden_field_paths(declaration):
        errors.append(
            SourceIngestionValidationError(
                error_code="forbidden_source_ingestion_field",
                field=path,
                message="field is not allowed in source ingestion declarations.",
            )
        )

    contract_by_id = {
        contract.id: contract
        for contract in (contracts or load_source_ingestion_contracts())
    }
    contract_id = declaration.get("contract_id")
    contract = contract_by_id.get(contract_id) if isinstance(contract_id, str) else None
    if contract is None:
        errors.append(
            SourceIngestionValidationError(
                error_code="invalid_source_ingestion_declaration",
                field="contract_id",
                message="contract_id must reference a registered contract.",
            )
        )

    source_id = declaration.get("source_id")
    if not isinstance(source_id, str) or not source_id.strip():
        errors.append(
            SourceIngestionValidationError(
                error_code="missing_source_id",
                field="source_id",
                message="source_id must be a non-empty string.",
            )
        )

    source_type = declaration.get("source_type")
    if source_type not in ALLOWED_SOURCE_TYPES:
        errors.append(
            SourceIngestionValidationError(
                error_code="unknown_source_type",
                field="source_type",
                message="source_type must be rss_feed.",
            )
        )
    elif contract is not None and source_type != contract.source_type:
        errors.append(
            SourceIngestionValidationError(
                error_code="unknown_source_type",
                field="source_type",
                message="source_type must match the contract.",
            )
        )

    url = declaration.get("url")
    if not isinstance(url, str) or not url.strip():
        errors.append(
            SourceIngestionValidationError(
                error_code="missing_source_url",
                field="url",
                message="url must be a non-empty string.",
            )
        )
    elif not (url.startswith("https://") or url.startswith("http://")):
        errors.append(
            SourceIngestionValidationError(
                error_code="invalid_source_url",
                field="url",
                message="url must be an HTTP(S) URL.",
            )
        )

    owning_agent = declaration.get("owning_agent")
    if not isinstance(owning_agent, str) or not owning_agent.strip():
        errors.append(
            SourceIngestionValidationError(
                error_code="invalid_source_owner",
                field="owning_agent",
                message="owning_agent must be a non-empty string.",
            )
        )

    governance_state = declaration.get("governance_state")
    if governance_state not in ALLOWED_GOVERNANCE_STATES:
        errors.append(
            SourceIngestionValidationError(
                error_code="unknown_source_governance_state",
                field="governance_state",
                message="governance_state must be enabled, disabled, or audit_only.",
            )
        )

    _validate_refresh_policy(declaration.get("refresh_policy"), errors)
    _validate_source_category(declaration.get("source_category"), errors)
    _validate_priority_policy(declaration.get("priority_policy"), errors)
    _validate_provenance_policy(declaration.get("provenance_policy"), errors)
    _validate_provenance(
        declaration.get("provenance_audit"),
        errors,
        manifest=manifest,
    )
    _validate_content_safety(declaration.get("content_safety"), errors)
    _validate_storage_policy(declaration.get("storage_policy"), errors)
    return errors


def validate_source_ingestion_readiness(
    declaration: Any,
    *,
    contracts: tuple[SourceIngestionContract, ...] | None = None,
    manifest_path: Path | None = None,
) -> list[SourceIngestionValidationError]:
    errors = validate_source_ingestion_declaration(
        declaration,
        contracts=contracts,
        manifest_path=manifest_path,
    )
    if not isinstance(declaration, dict):
        return errors

    source_id = declaration.get("source_id")
    if isinstance(source_id, str):
        normalized_source_id = source_id.lower()
        if "example" in normalized_source_id or "placeholder" in normalized_source_id:
            errors.append(
                SourceIngestionValidationError(
                    error_code="placeholder_source_declaration",
                    field="source_id",
                    message="source_id must not be an example or placeholder.",
                )
            )

    url = declaration.get("url")
    if isinstance(url, str):
        hostname = _source_url_hostname(url)
        if hostname in PLACEHOLDER_DOMAINS or hostname.endswith(".example.com"):
            errors.append(
                SourceIngestionValidationError(
                    error_code="placeholder_source_declaration",
                    field="url",
                    message="production source URL must not use example domains.",
                )
            )
    return errors


def _source_url_hostname(url: str) -> str:
    if "://" not in url:
        return ""
    remainder = url.split("://", 1)[1]
    authority = remainder.split("/", 1)[0]
    hostname = authority.rsplit("@", 1)[-1].split(":", 1)[0]
    return hostname.lower()


def _validate_refresh_policy(
    value: Any,
    errors: list[SourceIngestionValidationError],
) -> None:
    if not isinstance(value, dict):
        errors.append(
            SourceIngestionValidationError(
                error_code="malformed_refresh_policy",
                field="refresh_policy",
                message="refresh_policy must be an object.",
            )
        )
        return
    if value.get("type") not in ALLOWED_REFRESH_POLICY_TYPES:
        errors.append(
            SourceIngestionValidationError(
                error_code="malformed_refresh_policy",
                field="refresh_policy.type",
                message="refresh_policy.type must be manual or scheduled.",
            )
        )


def _validate_source_category(
    value: Any,
    errors: list[SourceIngestionValidationError],
) -> None:
    if not isinstance(value, dict):
        errors.append(
            SourceIngestionValidationError(
                error_code="malformed_source_category",
                field="source_category",
                message="source_category must be an object.",
            )
        )
        return
    category = value.get("category")
    if not isinstance(category, str) or not category.strip():
        errors.append(
            SourceIngestionValidationError(
                error_code="malformed_source_category",
                field="source_category.category",
                message="source_category.category must be a non-empty string.",
            )
        )
    _validate_non_empty_string_list(
        value.get("topic_tags"),
        errors,
        field="source_category.topic_tags",
        error_code="malformed_source_category",
    )


def _validate_priority_policy(
    value: Any,
    errors: list[SourceIngestionValidationError],
) -> None:
    if not isinstance(value, dict):
        errors.append(
            SourceIngestionValidationError(
                error_code="malformed_priority_policy",
                field="priority_policy",
                message="priority_policy must be an object.",
            )
        )
        return
    if value.get("level") not in ALLOWED_PRIORITY_LEVELS:
        errors.append(
            SourceIngestionValidationError(
                error_code="malformed_priority_policy",
                field="priority_policy.level",
                message="priority_policy.level must be low, normal, high, or critical.",
            )
        )
    rationale = value.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        errors.append(
            SourceIngestionValidationError(
                error_code="malformed_priority_policy",
                field="priority_policy.rationale",
                message="priority_policy.rationale must be a non-empty string.",
            )
        )


def _validate_provenance_policy(
    value: Any,
    errors: list[SourceIngestionValidationError],
) -> None:
    if not isinstance(value, dict):
        errors.append(
            SourceIngestionValidationError(
                error_code="malformed_provenance_policy",
                field="provenance_policy",
                message="provenance_policy must be an object.",
            )
        )
        return
    required_true = (
        "citation_required",
        "source_url_required",
        "attribution_required",
    )
    for key in required_true:
        if value.get(key) is not True:
            errors.append(
                SourceIngestionValidationError(
                    error_code="malformed_provenance_policy",
                    field=f"provenance_policy.{key}",
                    message=f"provenance_policy.{key} must be true.",
                )
            )
    if value.get("prose_only_output_allowed") is not False:
        errors.append(
            SourceIngestionValidationError(
                error_code="malformed_provenance_policy",
                field="provenance_policy.prose_only_output_allowed",
                message="provenance_policy.prose_only_output_allowed must be false.",
            )
        )


def _validate_non_empty_string_list(
    value: Any,
    errors: list[SourceIngestionValidationError],
    *,
    field: str,
    error_code: str,
) -> None:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        errors.append(
            SourceIngestionValidationError(
                error_code=error_code,
                field=field,
                message=f"{field} must be a list of non-empty strings.",
            )
        )


def _validate_provenance(
    value: Any,
    errors: list[SourceIngestionValidationError],
    *,
    manifest: Path,
) -> None:
    if not isinstance(value, dict):
        errors.append(
            SourceIngestionValidationError(
                error_code="missing_provenance_audit",
                field="provenance_audit",
                message="provenance_audit must be an object.",
            )
        )
        return
    if value.get("required") is not True:
        errors.append(
            SourceIngestionValidationError(
                error_code="missing_provenance_audit",
                field="provenance_audit.required",
                message="provenance audit must be required.",
            )
        )
    if value.get("manifest_path") not in (None, str(manifest)):
        errors.append(
            SourceIngestionValidationError(
                error_code="missing_provenance_audit",
                field="provenance_audit.manifest_path",
                message="manifest_path must match the loaded declaration.",
            )
        )


def _validate_content_safety(
    value: Any,
    errors: list[SourceIngestionValidationError],
) -> None:
    required_false = (
        "raw_content_storage_allowed",
        "prompt_injection_surface_allowed",
        "summary_generation_allowed",
    )
    _validate_false_policy(value, errors, "content_safety", required_false)


def _validate_storage_policy(
    value: Any,
    errors: list[SourceIngestionValidationError],
) -> None:
    required_false = {
        "memory_write_allowed",
        "article_storage_allowed",
    }
    optional_bool = {"metadata_storage_allowed"}
    _validate_false_policy(value, errors, "storage_policy", required_false)
    if isinstance(value, dict):
        for key in optional_bool:
            if not isinstance(value.get(key), bool):
                errors.append(
                    SourceIngestionValidationError(
                        error_code="malformed_storage_policy",
                        field=f"storage_policy.{key}",
                        message=f"storage_policy.{key} must be boolean.",
                    )
                )


def _validate_false_policy(
    value: Any,
    errors: list[SourceIngestionValidationError],
    field: str,
    keys: set[str] | tuple[str, ...],
) -> None:
    if not isinstance(value, dict):
        errors.append(
            SourceIngestionValidationError(
                error_code=f"malformed_{field}",
                field=field,
                message=f"{field} must be an object.",
            )
        )
        return
    for key in keys:
        if value.get(key) is not False:
            errors.append(
                SourceIngestionValidationError(
                    error_code=f"malformed_{field}",
                    field=f"{field}.{key}",
                    message=f"{field}.{key} must be false for contract stage.",
                )
            )


def _declaration_from_entry(
    entry: dict[str, Any],
    *,
    contracts: tuple[SourceIngestionContract, ...],
    manifest_path: Path,
) -> SourceIngestionDeclaration:
    errors = validate_source_ingestion_declaration(
        entry,
        contracts=contracts,
        manifest_path=manifest_path,
    )
    if errors:
        first_error = errors[0]
        raise SourceIngestionRegistryError(
            f"Source ingestion declaration error at {first_error.field}: "
            f"{first_error.message}"
        )
    return SourceIngestionDeclaration(
        source_id=_require_string(entry, "source_id", entry_id="<unknown>"),
        contract_id=_require_string(entry, "contract_id", entry_id=entry["source_id"]),
        source_type=_require_string(entry, "source_type", entry_id=entry["source_id"]),
        url=_require_string(entry, "url", entry_id=entry["source_id"]),
        owning_agent=_require_string(
            entry,
            "owning_agent",
            entry_id=entry["source_id"],
        ),
        governance_state=_require_string(
            entry,
            "governance_state",
            entry_id=entry["source_id"],
        ),
        refresh_policy=dict(entry["refresh_policy"]),
        source_category=dict(entry["source_category"]),
        priority_policy=dict(entry["priority_policy"]),
        provenance_policy=dict(entry["provenance_policy"]),
        provenance_audit=dict(entry["provenance_audit"]),
        content_safety={
            key: bool(value)
            for key, value in dict(entry["content_safety"]).items()
        },
        storage_policy={
            key: bool(value)
            for key, value in dict(entry["storage_policy"]).items()
        },
        manifest_path=manifest_path,
        raw_data=dict(entry),
    )


def _load_registry_strict(
    root: str | Path | None = None,
) -> tuple[
    tuple[SourceIngestionContract, ...],
    tuple[SourceIngestionDeclaration, ...],
]:
    path = _registry_path(root)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise SourceIngestionRegistryError(
            "Source ingestion registry version must be 1."
        )
    raw_contracts = data.get("contracts")
    if not isinstance(raw_contracts, list):
        raise SourceIngestionRegistryError(
            "Source ingestion registry 'contracts' must be a list."
        )
    contracts = tuple(_contract_from_entry(entry) for entry in raw_contracts)
    raw_declarations = data.get("source_declarations", [])
    if not isinstance(raw_declarations, list):
        raise SourceIngestionRegistryError(
            "Source ingestion registry 'source_declarations' must be a list."
        )
    declarations = tuple(
        _declaration_from_entry(
            entry,
            contracts=contracts,
            manifest_path=path,
        )
        for entry in raw_declarations
    )
    return contracts, declarations


def _load_declaration_manifest(
    manifest_path: Path,
    *,
    contracts: tuple[SourceIngestionContract, ...],
) -> tuple[
    tuple[SourceIngestionDeclaration, ...],
    tuple[SourceIngestionValidationError, ...],
]:
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            return (), (
                SourceIngestionValidationError(
                    error_code="invalid_source_manifest",
                    field="version",
                    message="source manifest version must be 1.",
                ),
            )
        raw_declarations = data.get("source_declarations", [])
        if not isinstance(raw_declarations, list):
            return (), (
                SourceIngestionValidationError(
                    error_code="invalid_source_manifest",
                    field="source_declarations",
                    message="source_declarations must be a list.",
                ),
            )

        declarations: list[SourceIngestionDeclaration] = []
        errors: list[SourceIngestionValidationError] = []
        for entry in raw_declarations:
            entry_errors = validate_source_ingestion_declaration(
                entry,
                contracts=contracts,
                manifest_path=manifest_path,
            )
            if entry_errors:
                errors.extend(entry_errors)
                continue
            declarations.append(
                _declaration_from_entry(
                    entry,
                    contracts=contracts,
                    manifest_path=manifest_path,
                )
            )
        source_ids = [declaration.source_id for declaration in declarations]
        if len(source_ids) != len(set(source_ids)):
            errors.append(
                SourceIngestionValidationError(
                    error_code="invalid_source_manifest",
                    field="source_declarations.source_id",
                    message="source IDs must be unique.",
                )
            )
            return (), tuple(errors)
        return tuple(declarations), tuple(errors)
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        SourceIngestionRegistryError,
    ) as exc:
        return (), (
            SourceIngestionValidationError(
                error_code="invalid_source_manifest",
                field="manifest",
                message=str(exc),
            ),
        )


@lru_cache(maxsize=None)
def load_source_ingestion_contracts(
    root: str | Path | None = None,
) -> tuple[SourceIngestionContract, ...]:
    try:
        contracts, _declarations = _load_registry_strict(root)
        return contracts
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        SourceIngestionRegistryError,
    ):
        return ()


@lru_cache(maxsize=None)
def load_source_ingestion_declarations(
    root: str | Path | None = None,
) -> tuple[SourceIngestionDeclaration, ...]:
    try:
        _contracts, declarations = _load_registry_strict(root)
        return declarations
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        SourceIngestionRegistryError,
    ):
        return ()


def audit_source_ingestion_declarations(
    *,
    root: str | Path | None = None,
) -> tuple[
    tuple[SourceIngestionDeclaration, ...],
    tuple[SourceIngestionValidationError, ...],
]:
    path = _registry_path(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            return (), (
                SourceIngestionValidationError(
                    error_code="invalid_source_registry",
                    field="version",
                    message="source ingestion registry version must be 1.",
                ),
            )
        contracts = tuple(
            _contract_from_entry(entry)
            for entry in data.get("contracts", [])
        )
        raw_declarations = data.get("source_declarations", [])
        if not isinstance(raw_declarations, list):
            return (), (
                SourceIngestionValidationError(
                    error_code="invalid_source_registry",
                    field="source_declarations",
                    message="source_declarations must be a list.",
                ),
            )
        declarations: list[SourceIngestionDeclaration] = []
        errors: list[SourceIngestionValidationError] = []
        for entry in raw_declarations:
            entry_errors = validate_source_ingestion_declaration(
                entry,
                contracts=contracts,
                manifest_path=path,
            )
            if entry_errors:
                errors.extend(entry_errors)
                continue
            declarations.append(
                _declaration_from_entry(
                    entry,
                    contracts=contracts,
                    manifest_path=path,
                )
            )
        return tuple(declarations), tuple(errors)
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        SourceIngestionRegistryError,
    ) as exc:
        return (), (
            SourceIngestionValidationError(
                error_code="invalid_source_registry",
                field="registry",
                message=str(exc),
            ),
        )


def audit_source_ingestion_declarations_from_path(
    manifest_path: str | Path,
    *,
    root: str | Path | None = None,
) -> tuple[
    tuple[SourceIngestionDeclaration, ...],
    tuple[SourceIngestionValidationError, ...],
]:
    contracts = load_source_ingestion_contracts(root=root)
    if not contracts:
        return (), (
            SourceIngestionValidationError(
                error_code="invalid_source_registry",
                field="contracts",
                message="source ingestion contracts must be registered.",
            ),
        )
    return _load_declaration_manifest(Path(manifest_path), contracts=contracts)


def audit_agent_source_ingestion_declarations(
    agent: str,
    *,
    root: str | Path | None = None,
) -> tuple[
    tuple[SourceIngestionDeclaration, ...],
    tuple[SourceIngestionValidationError, ...],
]:
    agent_name = str(agent or "").strip()
    if not agent_name:
        return (), (
            SourceIngestionValidationError(
                error_code="invalid_source_manifest",
                field="agent",
                message="agent must be a non-empty string.",
            ),
        )
    root_path = Path(root) if root is not None else Path(".")
    manifest_path = root_path / "agents" / agent_name / AGENT_SOURCE_FEEDS_FILENAME
    return audit_source_ingestion_declarations_from_path(
        manifest_path,
        root=root,
    )


__all__ = [
    "AGENT_SOURCE_FEEDS_FILENAME",
    "ALLOWED_GOVERNANCE_STATES",
    "ALLOWED_REFRESH_POLICY_TYPES",
    "ALLOWED_SOURCE_TYPES",
    "FORBIDDEN_DECLARATION_FIELDS",
    "SOURCE_INGESTION_CONTRACTS_PATH",
    "SourceIngestionContract",
    "SourceIngestionDeclaration",
    "SourceIngestionRegistryError",
    "SourceIngestionValidationError",
    "audit_agent_source_ingestion_declarations",
    "audit_source_ingestion_declarations",
    "audit_source_ingestion_declarations_from_path",
    "load_source_ingestion_contracts",
    "load_source_ingestion_declarations",
    "validate_source_ingestion_declaration",
]
