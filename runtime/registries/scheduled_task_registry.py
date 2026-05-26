from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


SCHEDULED_TASK_CONTRACTS_PATH = Path(
    "agents/shared/semantics/scheduled_task_contracts.json"
)
AGENT_SCHEDULED_TASKS_FILENAME = "scheduled_tasks.json"
ALLOWED_SCHEDULE_TYPES = {"cron", "interval"}
ALLOWED_GOVERNANCE_STATES = {"enabled", "disabled", "audit_only"}
ALLOWED_RETRY_POLICIES = {"none"}
ALLOWED_SEMANTIC_OPERATION_TYPES = {
    "WORKFLOW_MAINTENANCE",
    "NEWS_INGESTION",
    "SMOKE_CHECK",
    "DATABASE_AUDIT",
}
SEMANTIC_OPERATION_BOOL_FIELDS = {
    "produces_artifact",
    "external_side_effects_allowed",
    "memory_write_allowed",
    "requires_approval",
}
FORBIDDEN_DECLARATION_FIELDS = {
    "autonomous",
    "autonomous_task_creation",
    "self_mutating_schedule",
    "self_modifying_schedule",
    "hidden_prompt",
    "hidden_prompt_execution",
    "memory_write",
    "memory_writes",
    "background_retrieval",
    "execution_callable",
    "runner",
}


class ScheduledTaskRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScheduledTaskContract:
    id: str
    contract_version: int
    task_type: str
    schedule_types: tuple[str, ...]
    governance_states: tuple[str, ...]
    forbidden_declaration_fields: tuple[str, ...]
    raw_data: dict[str, Any]


@dataclass(frozen=True)
class ScheduledTaskDeclaration:
    id: str
    contract_id: str
    task_type: str
    schedule_type: str
    schedule: dict[str, Any]
    agent: str
    workflow: str
    binding_id: str
    semantic_operation: dict[str, Any]
    governance_state: str
    max_runtime_ms: int
    max_concurrent_runs: int
    retry_policy: str
    provenance_audit: dict[str, Any]
    fail_closed: dict[str, bool]
    manifest_path: Path
    raw_data: dict[str, Any]

    def to_metadata(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "contract_id": self.contract_id,
            "task_type": self.task_type,
            "schedule_type": self.schedule_type,
            "agent": self.agent,
            "workflow": self.workflow,
            "binding_id": self.binding_id,
            "semantic_operation": dict(self.semantic_operation),
            "governance_state": self.governance_state,
            "max_runtime_ms": self.max_runtime_ms,
            "max_concurrent_runs": self.max_concurrent_runs,
            "retry_policy": self.retry_policy,
            "manifest_path": str(self.manifest_path),
        }


@dataclass(frozen=True)
class ScheduledTaskValidationError:
    error_code: str
    field: str
    message: str


def _registry_path(root: str | Path | None = None) -> Path:
    if root is None:
        return SCHEDULED_TASK_CONTRACTS_PATH

    return Path(root) / SCHEDULED_TASK_CONTRACTS_PATH


def _require_string(
    entry: dict[str, Any],
    key: str,
    *,
    entry_id: str,
) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ScheduledTaskRegistryError(
            f"Scheduled task entry '{entry_id}' field '{key}' must be a "
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
        raise ScheduledTaskRegistryError(
            f"Scheduled task entry '{entry_id}' field '{key}' must be an "
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
        raise ScheduledTaskRegistryError(
            f"Scheduled task entry '{entry_id}' field '{key}' must be an "
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
        raise ScheduledTaskRegistryError(
            f"Scheduled task entry '{entry_id}' field '{key}' must be a "
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
            path = f"{prefix}[{index}]"
            paths.extend(_forbidden_field_paths(item, prefix=path))
        return tuple(paths)
    return ()


def _contract_from_entry(entry: Any) -> ScheduledTaskContract:
    if not isinstance(entry, dict):
        raise ScheduledTaskRegistryError(
            "Scheduled task contract entries must be objects."
        )

    entry_id = _require_string(entry, "id", entry_id="<unknown>")
    contract_version = _require_int(
        entry,
        "contract_version",
        entry_id=entry_id,
    )
    if contract_version != 1:
        raise ScheduledTaskRegistryError(
            f"Scheduled task contract '{entry_id}' uses unsupported "
            f"contract_version '{contract_version}'."
        )

    task_type = _require_string(entry, "task_type", entry_id=entry_id)
    if task_type != "scheduled_workflow_task":
        raise ScheduledTaskRegistryError(
            f"Scheduled task contract '{entry_id}' uses unsupported "
            f"task_type '{task_type}'."
        )

    schedule_expression = _require_object(
        entry,
        "schedule_expression",
        entry_id=entry_id,
    )
    schedule_types = _require_string_list(
        schedule_expression,
        "allowed_types",
        entry_id=entry_id,
    )
    if set(schedule_types) != ALLOWED_SCHEDULE_TYPES:
        raise ScheduledTaskRegistryError(
            f"Scheduled task contract '{entry_id}' must allow cron and "
            "interval schedules only."
        )
    if schedule_expression.get("static_declaration_required") is not True:
        raise ScheduledTaskRegistryError(
            f"Scheduled task contract '{entry_id}' must require static "
            "schedule declarations."
        )
    if schedule_expression.get("runtime_interpretation_allowed") is not False:
        raise ScheduledTaskRegistryError(
            f"Scheduled task contract '{entry_id}' must disallow runtime "
            "schedule reinterpretation."
        )

    binding_reference = _require_object(
        entry,
        "binding_reference",
        entry_id=entry_id,
    )
    required_binding_fields = set(
        _require_string_list(
            binding_reference,
            "required_fields",
            entry_id=entry_id,
        )
    )
    if required_binding_fields != {"agent", "workflow", "binding_id"}:
        raise ScheduledTaskRegistryError(
            f"Scheduled task contract '{entry_id}' must require agent, "
            "workflow, and binding_id."
        )

    semantic_operation = _require_object(
        entry,
        "semantic_operation",
        entry_id=entry_id,
    )
    if semantic_operation.get("required") is not True:
        raise ScheduledTaskRegistryError(
            f"Scheduled task contract '{entry_id}' must require semantic "
            "operation metadata."
        )
    allowed_operation_types = set(
        _require_string_list(
            semantic_operation,
            "allowed_operation_types",
            entry_id=entry_id,
        )
    )
    if allowed_operation_types != ALLOWED_SEMANTIC_OPERATION_TYPES:
        raise ScheduledTaskRegistryError(
            f"Scheduled task contract '{entry_id}' has unsupported semantic "
            "operation types."
        )
    required_semantic_fields = set(
        _require_string_list(
            semantic_operation,
            "required_fields",
            entry_id=entry_id,
        )
    )
    expected_semantic_fields = {
        "operation_type",
        "capability_id",
        *SEMANTIC_OPERATION_BOOL_FIELDS,
    }
    if required_semantic_fields != expected_semantic_fields:
        raise ScheduledTaskRegistryError(
            f"Scheduled task contract '{entry_id}' must require complete "
            "semantic operation metadata."
        )
    side_effect_flags = set(
        _require_string_list(
            semantic_operation,
            "side_effect_flags",
            entry_id=entry_id,
        )
    )
    if side_effect_flags != SEMANTIC_OPERATION_BOOL_FIELDS:
        raise ScheduledTaskRegistryError(
            f"Scheduled task contract '{entry_id}' has unsupported semantic "
            "side-effect flags."
        )

    governance = _require_object(entry, "governance", entry_id=entry_id)
    governance_states = _require_string_list(
        governance,
        "allowed_states",
        entry_id=entry_id,
    )
    if set(governance_states) != ALLOWED_GOVERNANCE_STATES:
        raise ScheduledTaskRegistryError(
            f"Scheduled task contract '{entry_id}' has unsupported "
            "governance states."
        )

    fail_closed = _require_object(entry, "fail_closed", entry_id=entry_id)
    if any(value is not True for value in fail_closed.values()):
        raise ScheduledTaskRegistryError(
            f"Scheduled task contract '{entry_id}' fail_closed values must "
            "all be true."
        )

    forbidden_fields = _require_string_list(
        entry,
        "forbidden_declaration_fields",
        entry_id=entry_id,
    )
    if not FORBIDDEN_DECLARATION_FIELDS.issubset(set(forbidden_fields)):
        raise ScheduledTaskRegistryError(
            f"Scheduled task contract '{entry_id}' must forbid autonomous "
            "and execution fields."
        )

    return ScheduledTaskContract(
        id=entry_id,
        contract_version=contract_version,
        task_type=task_type,
        schedule_types=schedule_types,
        governance_states=governance_states,
        forbidden_declaration_fields=forbidden_fields,
        raw_data=dict(entry),
    )


def validate_scheduled_task_declaration(
    declaration: Any,
    *,
    contracts: tuple[ScheduledTaskContract, ...] | None = None,
    manifest_path: Path | None = None,
) -> list[ScheduledTaskValidationError]:
    manifest = manifest_path or SCHEDULED_TASK_CONTRACTS_PATH
    if not isinstance(declaration, dict):
        return [
            ScheduledTaskValidationError(
                error_code="invalid_scheduled_task_declaration",
                field="declaration",
                message="declaration must be an object.",
            )
        ]

    task_id = declaration.get("id")
    entry_id = task_id if isinstance(task_id, str) and task_id.strip() else "<unknown>"
    errors: list[ScheduledTaskValidationError] = []

    forbidden_paths = _forbidden_field_paths(declaration)
    for path in forbidden_paths:
        errors.append(
            ScheduledTaskValidationError(
                error_code="forbidden_scheduled_task_field",
                field=path,
                message="field is not allowed in scheduled task declarations.",
            )
        )

    contract_id = declaration.get("contract_id")
    contract_by_id = {
        contract.id: contract
        for contract in (contracts or load_scheduled_task_contracts())
    }
    contract = (
        contract_by_id.get(contract_id)
        if isinstance(contract_id, str)
        else None
    )
    if contract is None:
        errors.append(
            ScheduledTaskValidationError(
                error_code="invalid_scheduled_task_declaration",
                field="contract_id",
                message="contract_id must reference a registered contract.",
            )
        )

    if not isinstance(task_id, str) or not task_id.strip():
        errors.append(
            ScheduledTaskValidationError(
                error_code="invalid_scheduled_task_declaration",
                field="id",
                message="id must be a non-empty string.",
            )
        )

    task_type = declaration.get("task_type")
    expected_task_type = contract.task_type if contract is not None else None
    if (
        not isinstance(task_type, str)
        or not task_type.strip()
        or (
            expected_task_type is not None
            and task_type.strip() != expected_task_type
        )
    ):
        errors.append(
            ScheduledTaskValidationError(
                error_code="invalid_scheduled_task_declaration",
                field="task_type",
                message="task_type must match the scheduled task contract.",
            )
        )

    schedule = declaration.get("schedule")
    if not isinstance(schedule, dict):
        errors.append(
            ScheduledTaskValidationError(
                error_code="missing_scheduled_task_schedule",
                field="schedule",
                message="schedule must be declared statically.",
            )
        )
    else:
        schedule_type = schedule.get("type")
        if schedule_type not in ALLOWED_SCHEDULE_TYPES:
            errors.append(
                ScheduledTaskValidationError(
                    error_code="invalid_scheduled_task_schedule",
                    field="schedule.type",
                    message="schedule type must be cron or interval.",
                )
            )
        elif schedule_type == "cron":
            expression = schedule.get("expression")
            timezone = schedule.get("timezone")
            if not isinstance(expression, str) or not expression.strip():
                errors.append(
                    ScheduledTaskValidationError(
                        error_code="invalid_scheduled_task_schedule",
                        field="schedule.expression",
                        message="cron schedule requires expression.",
                    )
                )
            if not isinstance(timezone, str) or not timezone.strip():
                errors.append(
                    ScheduledTaskValidationError(
                        error_code="invalid_scheduled_task_schedule",
                        field="schedule.timezone",
                        message="cron schedule requires timezone.",
                    )
                )
        elif schedule_type == "interval":
            every_ms = schedule.get("every_ms")
            if (
                not isinstance(every_ms, int)
                or isinstance(every_ms, bool)
                or every_ms < 1
            ):
                errors.append(
                    ScheduledTaskValidationError(
                        error_code="invalid_scheduled_task_schedule",
                        field="schedule.every_ms",
                        message="interval schedule requires positive every_ms.",
                    )
                )

    binding = declaration.get("binding")
    if not isinstance(binding, dict):
        errors.append(
            ScheduledTaskValidationError(
                error_code="missing_scheduled_task_binding",
                field="binding",
                message="agent workflow binding must be declared.",
            )
        )
    else:
        for key in ("agent", "workflow", "binding_id"):
            value = binding.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(
                    ScheduledTaskValidationError(
                        error_code="missing_scheduled_task_binding",
                        field=f"binding.{key}",
                        message=f"binding.{key} must be a non-empty string.",
                    )
                )

    errors.extend(
        validate_scheduled_task_semantic_operation(
            declaration.get("semantic_operation")
        )
    )

    governance_state = declaration.get("governance_state")
    if governance_state not in ALLOWED_GOVERNANCE_STATES:
        errors.append(
            ScheduledTaskValidationError(
                error_code="unknown_scheduled_task_governance_state",
                field="governance_state",
                message="governance_state must be enabled, disabled, or audit_only.",
            )
        )

    constraints = declaration.get("execution_constraints")
    if not isinstance(constraints, dict):
        errors.append(
            ScheduledTaskValidationError(
                error_code="invalid_scheduled_task_execution_constraints",
                field="execution_constraints",
                message="execution_constraints must be an object.",
            )
        )
    else:
        max_runtime_ms = constraints.get("max_runtime_ms")
        if (
            not isinstance(max_runtime_ms, int)
            or isinstance(max_runtime_ms, bool)
            or max_runtime_ms < 1
        ):
            errors.append(
                ScheduledTaskValidationError(
                    error_code="invalid_scheduled_task_execution_constraints",
                    field="execution_constraints.max_runtime_ms",
                    message="max_runtime_ms must be a positive integer.",
                )
            )
        max_concurrent_runs = constraints.get("max_concurrent_runs")
        if (
            not isinstance(max_concurrent_runs, int)
            or isinstance(max_concurrent_runs, bool)
            or max_concurrent_runs < 1
        ):
            errors.append(
                ScheduledTaskValidationError(
                    error_code="invalid_scheduled_task_execution_constraints",
                    field="execution_constraints.max_concurrent_runs",
                    message="max_concurrent_runs must be a positive integer.",
                )
            )
        retry_policy = constraints.get("retry_policy", {"type": "none"})
        if not isinstance(retry_policy, dict):
            errors.append(
                ScheduledTaskValidationError(
                    error_code="invalid_scheduled_task_execution_constraints",
                    field="execution_constraints.retry_policy",
                    message="retry_policy must be an object when present.",
                )
            )
        elif retry_policy.get("type", "none") not in ALLOWED_RETRY_POLICIES:
            errors.append(
                ScheduledTaskValidationError(
                    error_code="invalid_scheduled_task_execution_constraints",
                    field="execution_constraints.retry_policy.type",
                    message="retry_policy.type must be none.",
                )
            )

    provenance_audit = declaration.get("provenance_audit")
    if not isinstance(provenance_audit, dict):
        errors.append(
            ScheduledTaskValidationError(
                error_code="invalid_scheduled_task_provenance",
                field="provenance_audit",
                message="provenance_audit must be an object.",
            )
        )
    else:
        if provenance_audit.get("required") is not True:
            errors.append(
                ScheduledTaskValidationError(
                    error_code="invalid_scheduled_task_provenance",
                    field="provenance_audit.required",
                    message="provenance auditing must be required.",
                )
            )
        if provenance_audit.get("manifest_path") not in (None, str(manifest)):
            errors.append(
                ScheduledTaskValidationError(
                    error_code="invalid_scheduled_task_provenance",
                    field="provenance_audit.manifest_path",
                    message="manifest_path must match the loaded declaration.",
                )
            )

    fail_closed = declaration.get("fail_closed")
    if not isinstance(fail_closed, dict) or any(
        value is not True for value in fail_closed.values()
    ):
        errors.append(
            ScheduledTaskValidationError(
                error_code="invalid_scheduled_task_fail_closed",
                field="fail_closed",
                message="fail_closed must be an object with true values.",
            )
        )

    return errors


def validate_scheduled_task_semantic_operation(
    value: Any,
) -> list[ScheduledTaskValidationError]:
    if not isinstance(value, dict):
        return [
            ScheduledTaskValidationError(
                error_code="missing_scheduled_task_semantic_operation",
                field="semantic_operation",
                message="semantic_operation must be declared.",
            )
        ]

    errors: list[ScheduledTaskValidationError] = []
    expected_fields = {
        "operation_type",
        "capability_id",
        *SEMANTIC_OPERATION_BOOL_FIELDS,
    }
    extra_fields = set(value) - expected_fields
    for field in sorted(extra_fields):
        errors.append(
            ScheduledTaskValidationError(
                error_code="invalid_scheduled_task_semantic_operation",
                field=f"semantic_operation.{field}",
                message="semantic_operation contains unsupported fields.",
            )
        )

    operation_type = value.get("operation_type")
    if operation_type not in ALLOWED_SEMANTIC_OPERATION_TYPES:
        errors.append(
            ScheduledTaskValidationError(
                error_code="unknown_scheduled_task_semantic_operation_type",
                field="semantic_operation.operation_type",
                message="operation_type must be a registered semantic operation type.",
            )
        )

    capability_id = value.get("capability_id")
    if not isinstance(capability_id, str) or not capability_id.strip():
        errors.append(
            ScheduledTaskValidationError(
                error_code="invalid_scheduled_task_semantic_operation",
                field="semantic_operation.capability_id",
                message="capability_id must be a non-empty string.",
            )
        )

    for field in sorted(SEMANTIC_OPERATION_BOOL_FIELDS):
        if not isinstance(value.get(field), bool):
            errors.append(
                ScheduledTaskValidationError(
                    error_code="invalid_scheduled_task_semantic_operation",
                    field=f"semantic_operation.{field}",
                    message=f"semantic_operation.{field} must be boolean.",
                )
            )

    return errors


def _declaration_from_entry(
    entry: dict[str, Any],
    *,
    contracts: tuple[ScheduledTaskContract, ...],
    manifest_path: Path,
) -> ScheduledTaskDeclaration:
    errors = validate_scheduled_task_declaration(
        entry,
        contracts=contracts,
        manifest_path=manifest_path,
    )
    if errors:
        first_error = errors[0]
        raise ScheduledTaskRegistryError(
            f"Scheduled task declaration error at {first_error.field}: "
            f"{first_error.message}"
        )

    schedule = dict(entry["schedule"])
    binding = dict(entry["binding"])
    constraints = dict(entry["execution_constraints"])
    retry_policy = constraints.get("retry_policy", {"type": "none"})

    return ScheduledTaskDeclaration(
        id=_require_string(entry, "id", entry_id="<unknown>"),
        contract_id=_require_string(entry, "contract_id", entry_id=entry["id"]),
        task_type=_require_string(entry, "task_type", entry_id=entry["id"]),
        schedule_type=_require_string(schedule, "type", entry_id=entry["id"]),
        schedule=schedule,
        agent=_require_string(binding, "agent", entry_id=entry["id"]),
        workflow=_require_string(binding, "workflow", entry_id=entry["id"]),
        binding_id=_require_string(
            binding,
            "binding_id",
            entry_id=entry["id"],
        ),
        semantic_operation=dict(entry["semantic_operation"]),
        governance_state=_require_string(
            entry,
            "governance_state",
            entry_id=entry["id"],
        ),
        max_runtime_ms=_require_int(
            constraints,
            "max_runtime_ms",
            entry_id=entry["id"],
        ),
        max_concurrent_runs=_require_int(
            constraints,
            "max_concurrent_runs",
            entry_id=entry["id"],
        ),
        retry_policy=str(retry_policy.get("type", "none")),
        provenance_audit=dict(entry["provenance_audit"]),
        fail_closed={
            key: bool(value)
            for key, value in dict(entry["fail_closed"]).items()
        },
        manifest_path=manifest_path,
        raw_data=dict(entry),
    )


def _load_registry_strict(
    root: str | Path | None = None,
) -> tuple[
    tuple[ScheduledTaskContract, ...],
    tuple[ScheduledTaskDeclaration, ...],
]:
    path = _registry_path(root)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ScheduledTaskRegistryError(
            "Scheduled task registry must be an object."
        )
    if data.get("version") != 1:
        raise ScheduledTaskRegistryError(
            "Scheduled task registry version must be 1."
        )

    raw_contracts = data.get("contracts")
    if not isinstance(raw_contracts, list):
        raise ScheduledTaskRegistryError(
            "Scheduled task registry 'contracts' must be a list."
        )
    contracts = tuple(_contract_from_entry(entry) for entry in raw_contracts)
    contract_ids = [contract.id for contract in contracts]
    if len(contract_ids) != len(set(contract_ids)):
        raise ScheduledTaskRegistryError(
            "Scheduled task registry contains duplicate contract IDs."
        )

    raw_declarations = data.get("task_declarations", [])
    if not isinstance(raw_declarations, list):
        raise ScheduledTaskRegistryError(
            "Scheduled task registry 'task_declarations' must be a list."
        )
    declarations = tuple(
        _declaration_from_entry(
            entry,
            contracts=contracts,
            manifest_path=path,
        )
        for entry in raw_declarations
    )
    declaration_ids = [declaration.id for declaration in declarations]
    if len(declaration_ids) != len(set(declaration_ids)):
        raise ScheduledTaskRegistryError(
            "Scheduled task registry contains duplicate task declaration IDs."
        )

    return contracts, declarations


def _load_declaration_manifest(
    manifest_path: Path,
    *,
    contracts: tuple[ScheduledTaskContract, ...],
) -> tuple[
    tuple[ScheduledTaskDeclaration, ...],
    tuple[ScheduledTaskValidationError, ...],
]:
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            return (
                (),
                (
                    ScheduledTaskValidationError(
                        error_code="invalid_scheduled_task_manifest",
                        field="version",
                        message="scheduled task manifest version must be 1.",
                    ),
                ),
            )
        raw_declarations = data.get("task_declarations", [])
        if not isinstance(raw_declarations, list):
            return (
                (),
                (
                    ScheduledTaskValidationError(
                        error_code="invalid_scheduled_task_manifest",
                        field="task_declarations",
                        message="task_declarations must be a list.",
                    ),
                ),
            )

        declarations: list[ScheduledTaskDeclaration] = []
        errors: list[ScheduledTaskValidationError] = []
        for entry in raw_declarations:
            entry_errors = validate_scheduled_task_declaration(
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

        declaration_ids = [declaration.id for declaration in declarations]
        if len(declaration_ids) != len(set(declaration_ids)):
            errors.append(
                ScheduledTaskValidationError(
                    error_code="invalid_scheduled_task_manifest",
                    field="task_declarations.id",
                    message="task declaration IDs must be unique.",
                )
            )
            return (), tuple(errors)

        return tuple(declarations), tuple(errors)
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        ScheduledTaskRegistryError,
    ) as exc:
        return (
            (),
            (
                ScheduledTaskValidationError(
                    error_code="invalid_scheduled_task_manifest",
                    field="manifest",
                    message=str(exc),
                ),
            ),
        )


@lru_cache(maxsize=None)
def load_scheduled_task_contracts(
    root: str | Path | None = None,
) -> tuple[ScheduledTaskContract, ...]:
    try:
        contracts, _declarations = _load_registry_strict(root)
        return contracts
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        ScheduledTaskRegistryError,
    ):
        return ()


@lru_cache(maxsize=None)
def load_scheduled_task_declarations(
    root: str | Path | None = None,
) -> tuple[ScheduledTaskDeclaration, ...]:
    try:
        _contracts, declarations = _load_registry_strict(root)
        return declarations
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        ScheduledTaskRegistryError,
    ):
        return ()


def audit_scheduled_task_declarations(
    *,
    root: str | Path | None = None,
) -> tuple[
    tuple[ScheduledTaskDeclaration, ...],
    tuple[ScheduledTaskValidationError, ...],
]:
    path = _registry_path(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            return (
                (),
                (
                    ScheduledTaskValidationError(
                        error_code="invalid_scheduled_task_registry",
                        field="version",
                        message="scheduled task registry version must be 1.",
                    ),
                ),
            )
        contracts = tuple(
            _contract_from_entry(entry)
            for entry in data.get("contracts", [])
        )
        declarations: list[ScheduledTaskDeclaration] = []
        errors: list[ScheduledTaskValidationError] = []
        raw_declarations = data.get("task_declarations", [])
        if not isinstance(raw_declarations, list):
            return (
                (),
                (
                    ScheduledTaskValidationError(
                        error_code="invalid_scheduled_task_registry",
                        field="task_declarations",
                        message="task_declarations must be a list.",
                    ),
                ),
            )

        for entry in raw_declarations:
            entry_errors = validate_scheduled_task_declaration(
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
        ScheduledTaskRegistryError,
    ) as exc:
        return (
            (),
            (
                ScheduledTaskValidationError(
                    error_code="invalid_scheduled_task_registry",
                    field="registry",
                    message=str(exc),
                ),
            ),
        )


def audit_scheduled_task_declarations_from_path(
    manifest_path: str | Path,
    *,
    root: str | Path | None = None,
) -> tuple[
    tuple[ScheduledTaskDeclaration, ...],
    tuple[ScheduledTaskValidationError, ...],
]:
    contracts = load_scheduled_task_contracts(root=root)
    if not contracts:
        return (
            (),
            (
                ScheduledTaskValidationError(
                    error_code="invalid_scheduled_task_registry",
                    field="contracts",
                    message="scheduled task contracts must be registered.",
                ),
            ),
        )
    return _load_declaration_manifest(Path(manifest_path), contracts=contracts)


def audit_agent_scheduled_task_declarations(
    agent: str,
    *,
    root: str | Path | None = None,
) -> tuple[
    tuple[ScheduledTaskDeclaration, ...],
    tuple[ScheduledTaskValidationError, ...],
]:
    agent_name = str(agent or "").strip()
    if not agent_name:
        return (
            (),
            (
                ScheduledTaskValidationError(
                    error_code="invalid_scheduled_task_manifest",
                    field="agent",
                    message="agent must be a non-empty string.",
                ),
            ),
        )
    root_path = Path(root) if root is not None else Path(".")
    manifest_path = (
        root_path / "agents" / agent_name / AGENT_SCHEDULED_TASKS_FILENAME
    )
    return audit_scheduled_task_declarations_from_path(
        manifest_path,
        root=root,
    )


__all__ = [
    "ALLOWED_GOVERNANCE_STATES",
    "ALLOWED_RETRY_POLICIES",
    "ALLOWED_SCHEDULE_TYPES",
    "ALLOWED_SEMANTIC_OPERATION_TYPES",
    "AGENT_SCHEDULED_TASKS_FILENAME",
    "FORBIDDEN_DECLARATION_FIELDS",
    "SCHEDULED_TASK_CONTRACTS_PATH",
    "SEMANTIC_OPERATION_BOOL_FIELDS",
    "ScheduledTaskContract",
    "ScheduledTaskDeclaration",
    "ScheduledTaskRegistryError",
    "ScheduledTaskValidationError",
    "audit_agent_scheduled_task_declarations",
    "audit_scheduled_task_declarations",
    "audit_scheduled_task_declarations_from_path",
    "load_scheduled_task_contracts",
    "load_scheduled_task_declarations",
    "validate_scheduled_task_declaration",
    "validate_scheduled_task_semantic_operation",
]
