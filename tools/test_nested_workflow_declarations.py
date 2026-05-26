import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.workflows.declarations import (  # noqa: E402
    WorkflowDeclarationError,
    load_agent_workflow_declarations,
    resolve_workflow_declaration,
)
from runtime.workflows.nesting import build_nested_workflow_graph  # noqa: E402
from runtime.workflows.transitions import (  # noqa: E402
    TERMINAL_OPERATION_ID,
    resolve_workflow_transition,
)


AGENT = "neutral_agent"


def _base_workflow(workflow_id, steps):
    return {
        "workflow_id": workflow_id,
        "workflow_type": "semantic_workflow_skeleton",
        "owning_agent": AGENT,
        "description": f"{workflow_id} fixture",
        "governance_state": "enabled",
        "planner_authority_required": True,
        "steps": steps,
        "non_goals": [
            "no web execution",
            "no ranking execution",
            "no draft generation",
            "no delivery execution",
        ],
    }


def _retrieval_step(step_id, operation_id, **extra):
    step = {
        "step_id": step_id,
        "step_kind": "retrieval",
        "semantic_operation": operation_id,
        "capability": "lookup",
        "output_type": "lookup_result_set",
        "requires_approval": False,
        "bounded": True,
        "governance_state": "audit_only",
        "constraints": {},
    }
    step.update(extra)
    return step


def _workflow_call_step(step_id, operation_id, workflow_ref, **extra):
    step = {
        "step_id": step_id,
        "step_kind": "workflow_call",
        "operation_kind": "run_workflow",
        "semantic_operation": operation_id,
        "capability": "workflow_runtime",
        "output_type": "workflow_result",
        "workflow_ref": workflow_ref,
        "input_refs": ["artifact:query:seed"],
        "output_ref": f"artifact:workflow_result:{operation_id}",
        "requires_approval": False,
        "bounded": True,
        "governance_state": "enabled",
        "constraints": {},
    }
    step.update(extra)
    return step


def _assessment_step(**extra):
    step = {
        "step_id": "assess_adequacy",
        "step_kind": "selection",
        "semantic_operation": "assess_adequacy",
        "capability": "assess_result",
        "output_type": "workflow_result",
        "requires_approval": False,
        "bounded": True,
        "governance_state": "enabled",
        "constraints": {
            "assessment_basis": "declared_result_status",
        },
        "on_success": TERMINAL_OPERATION_ID,
        "on_inadequate": "run_search_web",
    }
    step.update(extra)
    return step


def _write_workflow(root, workflow):
    workflow_dir = root / "agents" / workflow["owning_agent"] / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    (workflow_dir / f"{workflow['workflow_id']}.json").write_text(
        json.dumps(workflow, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_search_fixtures(root):
    _write_workflow(
        root,
        _base_workflow(
            "search_db",
            [
                _retrieval_step(
                    "search_db_sources",
                    "search_db_sources",
                    on_success=TERMINAL_OPERATION_ID,
                )
            ],
        ),
    )
    _write_workflow(
        root,
        _base_workflow(
            "search_web",
            [
                _retrieval_step(
                    "search_web_sources",
                    "search_web_sources",
                    on_success=TERMINAL_OPERATION_ID,
                )
            ],
        ),
    )
    _write_workflow(
        root,
        _base_workflow(
            "search_db_then_web",
            [
                _workflow_call_step(
                    "run_search_db",
                    "run_search_db",
                    "search_db",
                    on_success="assess_adequacy",
                    on_failure=TERMINAL_OPERATION_ID,
                ),
                _assessment_step(),
                _workflow_call_step(
                    "run_search_web",
                    "run_search_web",
                    "search_web",
                    on_success=TERMINAL_OPERATION_ID,
                ),
            ],
        ),
    )


def test_existing_guest_booking_outreach_still_loads():
    workflow = resolve_workflow_declaration(
        agent_name="alexis",
        workflow_id="guest_booking_outreach",
        root=ROOT,
    )
    assert workflow.workflow_id == "guest_booking_outreach"
    assert workflow.steps[-1].semantic_operation == "future_delivery_placeholder"


def test_simple_child_workflow_reference_validates():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_search_fixtures(root)
        declarations = load_agent_workflow_declarations(
            agent_name=AGENT,
            root=root,
        )

    parent = declarations["search_db_then_web"]
    call = parent.steps[0]
    assert call.operation_kind == "run_workflow"
    assert call.workflow_ref == "search_db"
    assert call.input_refs == ("artifact:query:seed",)
    assert call.output_ref == "artifact:workflow_result:run_search_db"


def test_missing_child_workflow_reference_fails_safely():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_workflow(
            root,
            _base_workflow(
                "parent_missing_child",
                [
                    _workflow_call_step(
                        "run_missing",
                        "run_missing",
                        "missing_child",
                    )
                ],
            ),
        )
        try:
            load_agent_workflow_declarations(agent_name=AGENT, root=root)
        except WorkflowDeclarationError as exc:
            message = str(exc)
        else:
            raise AssertionError("missing child workflow should fail")

    assert "workflow_ref 'missing_child' not found" in message


def test_missing_workflow_ref_field_fails_safely():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        step = _workflow_call_step(
            "run_missing_ref",
            "run_missing_ref",
            "temporary_child",
        )
        del step["workflow_ref"]
        _write_workflow(
            root,
            _base_workflow(
                "parent_missing_ref_field",
                [step],
            ),
        )
        try:
            load_agent_workflow_declarations(agent_name=AGENT, root=root)
        except WorkflowDeclarationError as exc:
            message = str(exc)
        else:
            raise AssertionError("missing workflow_ref should fail")

    assert "run_workflow requires workflow_ref" in message


def test_direct_self_reference_fails_safely():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_workflow(
            root,
            _base_workflow(
                "self_parent",
                [
                    _workflow_call_step(
                        "run_self",
                        "run_self",
                        "self_parent",
                    )
                ],
            ),
        )
        try:
            load_agent_workflow_declarations(agent_name=AGENT, root=root)
        except WorkflowDeclarationError as exc:
            message = str(exc)
        else:
            raise AssertionError("direct self-reference should fail")

    assert "workflow_ref must not self-reference" in message


def test_nested_workflow_graph_includes_parent_and_child_workflow_ids():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_search_fixtures(root)
        declarations = load_agent_workflow_declarations(
            agent_name=AGENT,
            root=root,
        )
        graph = build_nested_workflow_graph(
            root_workflow_id="search_db_then_web",
            declarations=declarations,
        )

    assert graph.expanded is True
    assert graph.execution_performed is False
    assert graph.workflow_ids == (
        "search_db",
        "search_db_then_web",
        "search_web",
    )
    assert {
        edge["child_workflow_id"]
        for edge in graph.edges
    } == {"search_db", "search_web"}


def test_search_db_then_web_declares_db_assessment_then_web_fallback():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_search_fixtures(root)
        workflow = load_agent_workflow_declarations(
            agent_name=AGENT,
            root=root,
        )["search_db_then_web"]

    operations = [step.semantic_operation for step in workflow.steps]
    assert operations == [
        "run_search_db",
        "assess_adequacy",
        "run_search_web",
    ]
    assert workflow.steps[0].workflow_ref == "search_db"
    assert workflow.steps[1].on_inadequate == "run_search_web"
    assert workflow.steps[2].workflow_ref == "search_web"


def test_transition_resolver_moves_from_child_node_to_assessment_node():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_search_fixtures(root)
        workflow = load_agent_workflow_declarations(
            agent_name=AGENT,
            root=root,
        )["search_db_then_web"]
        resolution = resolve_workflow_transition(
            workflow=workflow,
            current_operation_id="run_search_db",
            result_status="success",
        )

    assert resolution.resolved is True
    assert resolution.next_operation_id == "assess_adequacy"
    assert resolution.blocking is False
    assert resolution.suspending is False


def test_no_child_workflow_execution_web_ranking_draft_or_delivery_occurs():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_search_fixtures(root)
        declarations = load_agent_workflow_declarations(
            agent_name=AGENT,
            root=root,
        )
        graph = build_nested_workflow_graph(
            root_workflow_id="search_db_then_web",
            declarations=declarations,
        )

    rendered = repr(graph).lower()
    assert graph.execution_performed is False
    assert all(edge["execution_performed"] is False for edge in graph.edges)
    assert "ranked_entity" not in rendered
    assert "email_draft" not in rendered
    assert "delivery_performed" not in rendered


def test_nested_workflow_code_remains_domain_neutral():
    sources = [
        ROOT / "runtime" / "workflows" / "declarations.py",
        ROOT / "runtime" / "workflows" / "nesting.py",
    ]
    lowered = "\n".join(
        source.read_text(encoding="utf-8").lower()
        for source in sources
    )
    forbidden = (
        "agents.alexis",
        "newsroom",
        "telegram",
        "gateway",
        "smtp",
        "gmail",
        "mailgun",
        "web_search",
        "send_email(",
    )
    assert all(term not in lowered for term in forbidden)


def main():
    test_existing_guest_booking_outreach_still_loads()
    test_simple_child_workflow_reference_validates()
    test_missing_child_workflow_reference_fails_safely()
    test_missing_workflow_ref_field_fails_safely()
    test_direct_self_reference_fails_safely()
    test_nested_workflow_graph_includes_parent_and_child_workflow_ids()
    test_search_db_then_web_declares_db_assessment_then_web_fallback()
    test_transition_resolver_moves_from_child_node_to_assessment_node()
    test_no_child_workflow_execution_web_ranking_draft_or_delivery_occurs()
    test_nested_workflow_code_remains_domain_neutral()
    print("PASS nested workflow declarations")


if __name__ == "__main__":
    main()
