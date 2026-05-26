from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ALLOWED_WORKFLOW_TYPES = {"semantic_workflow_skeleton"}
ALLOWED_STEP_KINDS = {
    "retrieval",
    "selection",
    "artifact_generation",
    "action_generation",
    "approval_handoff",
    "delivery_placeholder",
    "workflow_call",
}
ALLOWED_OPERATION_KINDS = {
    "retrieval",
    "selection",
    "artifact_generation",
    "action_generation",
    "delivery_preparation",
    "wait_for_approval",
    "notify_and_continue",
    "rank_candidates",
    "draft_artifact",
    "run_workflow",
}
ALLOWED_OUTPUT_TYPES = {
    "lookup_result_set",
    "ranked_entity",
    "artifact",
    "typed_action",
    "approval_request",
    "placeholder",
    "workflow_result",
}
ALLOWED_GOVERNANCE_STATES = {
    "enabled",
    "disabled",
    "audit_only",
}
ALLOWED_RETRIEVAL_MODES = {
    "exact_lookup": "exact_entity_lookup",
    "bounded_lookup": "bounded_entity_search",
    "semantic_lookup": "semantic_entity_search",
}
ALLOWED_RETRIEVAL_EXECUTION_STATUSES = {
    "implemented",
    "declared_only",
    "not_implemented",
}


class WorkflowDeclarationError(ValueError):
    pass


@dataclass(frozen=True)
class WorkflowStepDeclaration:
    step_id: str
    step_kind: str
    semantic_operation: str
    capability: str | None
    output_type: str
    requires_approval: bool
    bounded: bool
    governance_state: str
    constraints: dict[str, Any]
    produces_artifact_type: str | None = None
    action_type: str | None = None
    delivery_performed: bool = False
    placeholder: bool = False
    operation_kind: str | None = None
    on_success: str | None = None
    on_failure: str | None = None
    on_inadequate: str | None = None
    blocking: bool = False
    suspending: bool = False
    workflow_ref: str | None = None
    input_refs: tuple[str, ...] = ()
    input_mapping: dict[str, str] | None = None
    output_ref: str | None = None
    output_mapping: dict[str, str] | None = None


@dataclass(frozen=True)
class WorkflowDeclaration:
    workflow_id: str
    workflow_type: str
    owning_agent: str
    description: str
    governance_state: str
    planner_authority_required: bool
    steps: tuple[WorkflowStepDeclaration, ...]
    non_goals: tuple[str, ...]


@dataclass(frozen=True)
class WorkflowExecutionPlan:
    workflow_id: str
    owning_agent: str
    execution_mode: str
    execution_performed: bool
    steps: tuple[WorkflowStepDeclaration, ...]
    skipped_reasons: tuple[str, ...]

    def to_summary(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "owning_agent": self.owning_agent,
            "execution_mode": self.execution_mode,
            "execution_performed": self.execution_performed,
            "step_count": len(self.steps),
            "ordered_operations": [
                step.semantic_operation for step in self.steps
            ],
            "skipped_reasons": list(self.skipped_reasons),
        }


def load_workflow_declaration(
    path: str | Path,
) -> WorkflowDeclaration:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return workflow_declaration_from_dict(raw)


def load_agent_workflow_declarations(
    *,
    agent_name: str,
    root: str | Path = ".",
) -> dict[str, WorkflowDeclaration]:
    workflow_dir = Path(root) / "agents" / agent_name / "workflows"
    declarations: dict[str, WorkflowDeclaration] = {}

    if not workflow_dir.exists():
        return declarations

    for path in sorted(workflow_dir.glob("*.json")):
        declaration = load_workflow_declaration(path)
        if declaration.owning_agent != agent_name:
            raise WorkflowDeclarationError(
                f"{path}: owning_agent must be {agent_name!r}"
            )
        declarations[declaration.workflow_id] = declaration

    _validate_workflow_reference_graph(declarations)
    return declarations


def resolve_workflow_declaration(
    *,
    agent_name: str,
    workflow_id: str,
    root: str | Path = ".",
) -> WorkflowDeclaration:
    declarations = load_agent_workflow_declarations(
        agent_name=agent_name,
        root=root,
    )
    declaration = declarations.get(workflow_id)

    if declaration is None:
        raise WorkflowDeclarationError(
            f"Unknown workflow declaration: {agent_name}.{workflow_id}"
        )

    return declaration


def build_dry_run_workflow_plan(
    declaration: WorkflowDeclaration,
) -> WorkflowExecutionPlan:
    skipped_reasons: list[str] = []

    if declaration.governance_state != "enabled":
        skipped_reasons.append(
            f"governance_state:{declaration.governance_state}"
        )

    return WorkflowExecutionPlan(
        workflow_id=declaration.workflow_id,
        owning_agent=declaration.owning_agent,
        execution_mode="declaration_only",
        execution_performed=False,
        steps=declaration.steps,
        skipped_reasons=tuple(skipped_reasons),
    )


def workflow_declaration_from_dict(
    data: dict[str, Any],
) -> WorkflowDeclaration:
    _require_object(data, "workflow declaration")

    workflow_id = _require_string(data, "workflow_id")
    workflow_type = _require_enum(
        data,
        "workflow_type",
        ALLOWED_WORKFLOW_TYPES,
    )
    owning_agent = _require_string(data, "owning_agent")
    governance_state = _require_enum(
        data,
        "governance_state",
        ALLOWED_GOVERNANCE_STATES,
    )
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise WorkflowDeclarationError("steps must be a non-empty list")

    parsed_steps = tuple(
        _step_from_dict(step, index=index)
        for index, step in enumerate(steps)
    )
    _validate_transitions(parsed_steps)
    _validate_direct_workflow_refs(workflow_id, parsed_steps)

    return WorkflowDeclaration(
        workflow_id=workflow_id,
        workflow_type=workflow_type,
        owning_agent=owning_agent,
        description=str(data.get("description", "")),
        governance_state=governance_state,
        planner_authority_required=bool(
            data.get("planner_authority_required", True)
        ),
        steps=parsed_steps,
        non_goals=tuple(
            str(item)
            for item in data.get("non_goals", [])
        ),
    )


def _step_from_dict(
    data: dict[str, Any],
    *,
    index: int,
) -> WorkflowStepDeclaration:
    _require_object(data, f"steps[{index}]")
    output_type = _require_enum(
        data,
        "output_type",
        ALLOWED_OUTPUT_TYPES,
    )
    step_kind = _require_enum(data, "step_kind", ALLOWED_STEP_KINDS)
    operation_kind = _operation_kind(data, step_kind=step_kind)
    action_type = data.get("action_type")
    requires_approval = bool(data.get("requires_approval", False))
    delivery_performed = bool(data.get("delivery_performed", False))

    if output_type == "typed_action" and not action_type:
        raise WorkflowDeclarationError(
            f"steps[{index}]: typed_action requires action_type"
        )

    if action_type == "send_email" and not requires_approval:
        raise WorkflowDeclarationError(
            f"steps[{index}]: send_email action must require approval"
        )

    if step_kind == "delivery_placeholder":
        if delivery_performed:
            raise WorkflowDeclarationError(
                f"steps[{index}]: delivery placeholder must not perform delivery"
            )
        if not requires_approval:
            raise WorkflowDeclarationError(
                f"steps[{index}]: delivery placeholder must require approval"
            )

    workflow_ref = _optional_string(data, "workflow_ref")
    if operation_kind == "run_workflow" and not workflow_ref:
        raise WorkflowDeclarationError(
            f"steps[{index}]: run_workflow requires workflow_ref"
        )
    if operation_kind != "run_workflow" and workflow_ref:
        raise WorkflowDeclarationError(
            f"steps[{index}]: workflow_ref requires run_workflow"
        )

    constraints = dict(data.get("constraints", {}))
    if step_kind == "retrieval":
        _validate_retrieval_mode_metadata(constraints, index=index)

    return WorkflowStepDeclaration(
        step_id=_require_string(data, "step_id"),
        step_kind=step_kind,
        semantic_operation=_require_string(data, "semantic_operation"),
        capability=_optional_string(data, "capability"),
        output_type=output_type,
        requires_approval=requires_approval,
        bounded=bool(data.get("bounded", True)),
        governance_state=_require_enum(
            data,
            "governance_state",
            ALLOWED_GOVERNANCE_STATES,
        ),
        constraints=constraints,
        produces_artifact_type=_optional_string(
            data,
            "produces_artifact_type",
        ),
        action_type=_optional_string(data, "action_type"),
        delivery_performed=delivery_performed,
        placeholder=bool(data.get("placeholder", False)),
        operation_kind=operation_kind,
        on_success=_optional_transition(data, "on_success"),
        on_failure=_optional_transition(data, "on_failure"),
        on_inadequate=_optional_transition(data, "on_inadequate"),
        blocking=_is_blocking_operation(operation_kind),
        suspending=_is_suspending_operation(operation_kind),
        workflow_ref=workflow_ref,
        input_refs=_string_tuple(data.get("input_refs")),
        input_mapping=_optional_string_mapping(data, "input_mapping"),
        output_ref=_optional_string(data, "output_ref"),
        output_mapping=_optional_string_mapping(data, "output_mapping"),
    )


def _operation_kind(data: dict[str, Any], *, step_kind: str) -> str:
    raw = data.get("operation_kind")
    if raw is None:
        return _default_operation_kind(step_kind)
    if not isinstance(raw, str) or not raw.strip():
        raise WorkflowDeclarationError(
            "operation_kind must be a non-empty string when present"
        )
    value = raw.strip()
    if value not in ALLOWED_OPERATION_KINDS:
        raise WorkflowDeclarationError(
            f"operation_kind has unsupported value {value!r}"
        )
    return value


def _default_operation_kind(step_kind: str) -> str:
    defaults = {
        "approval_handoff": "wait_for_approval",
        "delivery_placeholder": "delivery_preparation",
        "workflow_call": "run_workflow",
    }
    return defaults.get(step_kind, step_kind)


def _optional_transition(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise WorkflowDeclarationError(
            f"{key} must be a non-empty string when present"
        )
    return value.strip()


def _validate_transitions(
    steps: tuple[WorkflowStepDeclaration, ...],
) -> None:
    operation_ids = {step.semantic_operation for step in steps}
    for index, step in enumerate(steps):
        for field in ("on_success", "on_failure", "on_inadequate"):
            target = getattr(step, field)
            if target is None or target == "__terminate__":
                continue
            if target not in operation_ids:
                raise WorkflowDeclarationError(
                    f"steps[{index}]: {field} targets unknown operation "
                    f"{target!r}"
                )


def _validate_direct_workflow_refs(
    workflow_id: str,
    steps: tuple[WorkflowStepDeclaration, ...],
) -> None:
    for index, step in enumerate(steps):
        if step.workflow_ref is None:
            continue
        if step.workflow_ref == workflow_id:
            raise WorkflowDeclarationError(
                f"steps[{index}]: workflow_ref must not self-reference "
                f"{workflow_id!r}"
            )


def _validate_retrieval_mode_metadata(
    constraints: dict[str, Any],
    *,
    index: int,
) -> None:
    metadata = constraints.get("retrieval_mode_metadata")
    if metadata is None:
        return
    if not isinstance(metadata, dict):
        raise WorkflowDeclarationError(
            f"steps[{index}]: retrieval_mode_metadata must be an object"
        )

    default_mode = metadata.get("default_mode")
    if default_mode not in ALLOWED_RETRIEVAL_MODES:
        raise WorkflowDeclarationError(
            f"steps[{index}]: default retrieval mode is unsupported"
        )

    supported_modes = metadata.get("supported_modes")
    if not isinstance(supported_modes, dict) or not supported_modes:
        raise WorkflowDeclarationError(
            f"steps[{index}]: supported_modes must be a non-empty object"
        )
    if default_mode not in supported_modes:
        raise WorkflowDeclarationError(
            f"steps[{index}]: default retrieval mode must be supported"
        )

    for mode, mode_metadata in supported_modes.items():
        if mode not in ALLOWED_RETRIEVAL_MODES:
            raise WorkflowDeclarationError(
                f"steps[{index}]: retrieval mode {mode!r} is unsupported"
            )
        if not isinstance(mode_metadata, dict):
            raise WorkflowDeclarationError(
                f"steps[{index}]: retrieval mode metadata must be an object"
            )
        _validate_retrieval_mode(
            mode,
            mode_metadata,
            index=index,
        )


def _validate_retrieval_mode(
    mode: str,
    metadata: dict[str, Any],
    *,
    index: int,
) -> None:
    if metadata.get("lookup_type") != ALLOWED_RETRIEVAL_MODES[mode]:
        raise WorkflowDeclarationError(
            f"steps[{index}]: retrieval mode {mode!r} has invalid lookup_type"
        )

    execution_status = metadata.get("execution_status")
    if execution_status not in ALLOWED_RETRIEVAL_EXECUTION_STATUSES:
        raise WorkflowDeclarationError(
            f"steps[{index}]: retrieval mode {mode!r} has invalid "
            "execution_status"
        )

    if mode != "semantic_lookup":
        return

    if metadata.get("local_only") is not True:
        raise WorkflowDeclarationError(
            f"steps[{index}]: semantic_lookup must be local_only"
        )
    governance = metadata.get("governance")
    if not isinstance(governance, dict):
        raise WorkflowDeclarationError(
            f"steps[{index}]: semantic_lookup governance must be declared"
        )
    if not isinstance(governance.get("enabled"), bool):
        raise WorkflowDeclarationError(
            f"steps[{index}]: semantic_lookup enabled governance must be bool"
        )
    if governance.get("live_embedding_calls_allowed") is not False:
        raise WorkflowDeclarationError(
            f"steps[{index}]: semantic_lookup must not allow live embeddings"
        )
    if governance.get("cloud_embedding_calls_allowed") is not False:
        raise WorkflowDeclarationError(
            f"steps[{index}]: semantic_lookup must not allow cloud embeddings"
        )

    backend = governance.get("embedding_index_backend")
    if not isinstance(backend, str) or not backend.strip():
        raise WorkflowDeclarationError(
            f"steps[{index}]: semantic_lookup backend placeholder required"
        )

    threshold = governance.get("similarity_threshold")
    if threshold is not None and (
        not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
        or threshold < 0
        or threshold > 1
    ):
        raise WorkflowDeclarationError(
            f"steps[{index}]: semantic_lookup similarity threshold invalid"
        )

    max_candidates = governance.get("max_semantic_candidates")
    if (
        not isinstance(max_candidates, int)
        or isinstance(max_candidates, bool)
        or max_candidates < 0
    ):
        raise WorkflowDeclarationError(
            f"steps[{index}]: semantic_lookup max candidates invalid"
        )
    if execution_status == "implemented":
        if governance.get("enabled") is not True:
            raise WorkflowDeclarationError(
                f"steps[{index}]: implemented semantic_lookup governance "
                "must be enabled"
            )
        if max_candidates < 1:
            raise WorkflowDeclarationError(
                f"steps[{index}]: implemented semantic_lookup must allow "
                "at least one semantic candidate"
            )


def _validate_workflow_reference_graph(
    declarations: dict[str, WorkflowDeclaration],
) -> None:
    for declaration in declarations.values():
        for step in declaration.steps:
            ref = step.workflow_ref
            if ref is None:
                continue
            if ref not in declarations:
                raise WorkflowDeclarationError(
                    f"{declaration.workflow_id}.{step.step_id}: "
                    f"workflow_ref {ref!r} not found"
                )

    _validate_no_shallow_workflow_cycles(declarations)


def _validate_no_shallow_workflow_cycles(
    declarations: dict[str, WorkflowDeclaration],
) -> None:
    edges = {
        workflow_id: tuple(
            step.workflow_ref
            for step in declaration.steps
            if step.workflow_ref is not None
        )
        for workflow_id, declaration in declarations.items()
    }

    def visit(
        workflow_id: str,
        path: tuple[str, ...],
        visited: set[str],
    ) -> None:
        if workflow_id in path:
            cycle = " -> ".join((*path, workflow_id))
            raise WorkflowDeclarationError(
                f"workflow_ref cycle detected: {cycle}"
            )
        if workflow_id in visited:
            return
        visited.add(workflow_id)
        for child in edges.get(workflow_id, ()):
            visit(child, (*path, workflow_id), visited)

    visited: set[str] = set()
    for workflow_id in declarations:
        visit(workflow_id, (), visited)


def _is_blocking_operation(operation_kind: str | None) -> bool:
    return operation_kind == "wait_for_approval"


def _is_suspending_operation(operation_kind: str | None) -> bool:
    return operation_kind == "wait_for_approval"


def _require_object(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise WorkflowDeclarationError(f"{label} must be an object")


def _require_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise WorkflowDeclarationError(f"{key} must be a non-empty string")
    return value


def _optional_string(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise WorkflowDeclarationError(
            f"{key} must be a non-empty string when present"
        )
    return value


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise WorkflowDeclarationError("input_refs must be a list when present")
    values: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise WorkflowDeclarationError(
                "input_refs items must be non-empty strings"
            )
        values.append(item.strip())
    return tuple(values)


def _optional_string_mapping(
    data: dict[str, Any],
    key: str,
) -> dict[str, str] | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise WorkflowDeclarationError(f"{key} must be an object when present")

    mapping: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise WorkflowDeclarationError(
                f"{key} keys must be non-empty strings"
            )
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise WorkflowDeclarationError(
                f"{key} values must be non-empty strings"
            )
        mapping[raw_key.strip()] = raw_value.strip()
    return mapping


def _require_enum(
    data: dict[str, Any],
    key: str,
    allowed: set[str],
) -> str:
    value = _require_string(data, key)
    if value not in allowed:
        raise WorkflowDeclarationError(
            f"{key} has unsupported value {value!r}"
        )
    return value


__all__ = [
    "WorkflowDeclaration",
    "WorkflowDeclarationError",
    "WorkflowExecutionPlan",
    "WorkflowStepDeclaration",
    "build_dry_run_workflow_plan",
    "load_agent_workflow_declarations",
    "load_workflow_declaration",
    "resolve_workflow_declaration",
    "workflow_declaration_from_dict",
]
