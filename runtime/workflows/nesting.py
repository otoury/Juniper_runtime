from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.workflows.declarations import WorkflowDeclaration
from runtime.workflows.trust_inheritance import (
    BOUNDARY_NESTED_WORKFLOW,
    build_trust_inheritance_decision,
    build_workflow_step_trust_lineage,
)


@dataclass(frozen=True)
class NestedWorkflowGraph:
    root_workflow_id: str
    workflow_ids: tuple[str, ...]
    nodes: tuple[dict[str, Any], ...]
    edges: tuple[dict[str, Any], ...]
    expanded: bool
    execution_performed: bool
    skipped_reasons: tuple[str, ...]

    def to_audit_record(self) -> dict[str, Any]:
        return {
            "root_workflow_id": self.root_workflow_id,
            "workflow_ids": list(self.workflow_ids),
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "expanded": self.expanded,
            "execution_performed": self.execution_performed,
            "skipped_reasons": list(self.skipped_reasons),
        }


def build_nested_workflow_graph(
    *,
    root_workflow_id: str,
    declarations: dict[str, WorkflowDeclaration],
    max_depth: int = 4,
) -> NestedWorkflowGraph:
    root = declarations.get(root_workflow_id)
    if root is None:
        return _closed(
            root_workflow_id=root_workflow_id,
            skipped_reasons=("workflow_not_found",),
        )

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_nodes: set[tuple[str, str]] = set()
    workflow_ids: set[str] = set()

    def visit(workflow: WorkflowDeclaration, depth: int) -> None:
        workflow_ids.add(workflow.workflow_id)
        if depth > max_depth:
            return

        for step in workflow.steps:
            node_key = (workflow.workflow_id, step.semantic_operation)
            if node_key not in seen_nodes:
                seen_nodes.add(node_key)
                nodes.append(
                    {
                        "workflow_id": workflow.workflow_id,
                        "operation_id": step.semantic_operation,
                        "operation_kind": step.operation_kind,
                        "workflow_ref": step.workflow_ref,
                        "blocking": step.blocking,
                        "suspending": step.suspending,
                    }
                )

            if step.workflow_ref is None:
                continue

            child = declarations.get(step.workflow_ref)
            edges.append(
                {
                    "parent_workflow_id": workflow.workflow_id,
                    "operation_id": step.semantic_operation,
                    "child_workflow_id": step.workflow_ref,
                    "edge_type": "workflow_ref",
                    "trust_inheritance": _nested_trust_inheritance(
                        parent=workflow,
                        child=child,
                        step=step,
                    ),
                    "execution_performed": False,
                }
            )
            if child is not None:
                visit(child, depth + 1)

    visit(root, 0)
    return NestedWorkflowGraph(
        root_workflow_id=root.workflow_id,
        workflow_ids=tuple(sorted(workflow_ids)),
        nodes=tuple(nodes),
        edges=tuple(edges),
        expanded=True,
        execution_performed=False,
        skipped_reasons=(),
    )


def _closed(
    *,
    root_workflow_id: str,
    skipped_reasons: tuple[str, ...],
) -> NestedWorkflowGraph:
    return NestedWorkflowGraph(
        root_workflow_id=root_workflow_id,
        workflow_ids=(),
        nodes=(),
        edges=(),
        expanded=False,
        execution_performed=False,
        skipped_reasons=skipped_reasons,
    )


def _nested_trust_inheritance(
    *,
    parent: WorkflowDeclaration,
    child: WorkflowDeclaration | None,
    step: Any,
) -> dict[str, Any]:
    parent_lineage = build_workflow_step_trust_lineage(
        owning_agent=parent.owning_agent,
        workflow_id=parent.workflow_id,
        workflow_type=parent.workflow_type,
        step_id=getattr(step, "step_id", None),
        capability=getattr(step, "capability", None),
        action_type=getattr(step, "action_type", None),
    )
    child_step = child.steps[0] if child is not None and child.steps else None
    child_lineage = build_workflow_step_trust_lineage(
        owning_agent=getattr(child, "owning_agent", None),
        workflow_id=getattr(child, "workflow_id", None),
        workflow_type=getattr(child, "workflow_type", None),
        step_id=getattr(child_step, "step_id", None),
        capability=getattr(child_step, "capability", None),
        action_type=getattr(child_step, "action_type", None),
    )
    return build_trust_inheritance_decision(
        boundary_type=BOUNDARY_NESTED_WORKFLOW,
        prior_trust_state="workflow_call_boundary",
        prior_trust_lineage=parent_lineage,
        current_trust_lineage=child_lineage,
    ).to_record()


__all__ = [
    "NestedWorkflowGraph",
    "build_nested_workflow_graph",
]
