import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.workflows.declarations import (  # noqa: E402
    WorkflowDeclarationError,
    load_agent_workflow_declarations,
    resolve_workflow_declaration,
    workflow_declaration_from_dict,
)
from runtime.workflows.nesting import build_nested_workflow_graph  # noqa: E402
from runtime.workflows.transitions import resolve_workflow_transition  # noqa: E402


def _declarations():
    return load_agent_workflow_declarations(agent_name="alexis", root=ROOT)


def _workflow(workflow_id):
    return resolve_workflow_declaration(
        agent_name="alexis",
        workflow_id=workflow_id,
        root=ROOT,
    )


def _step(workflow, operation_id):
    for step in workflow.steps:
        if step.semantic_operation == operation_id:
            return step
    raise AssertionError(f"missing operation {operation_id}")


def test_search_db_workflow_loads():
    workflow = _workflow("search_db")
    step = workflow.steps[0]
    assert workflow.workflow_id == "search_db"
    assert step.semantic_operation == "db_guest_retrieval"
    assert step.constraints["source_scope"] == "guest_db"
    assert step.constraints["resource_binding_id"] == "alexis_guest_db"
    assert step.constraints["output_artifact_type"] == "guest_candidate_list"


def test_search_db_declares_retrieval_modes():
    workflow = _workflow("search_db")
    metadata = workflow.steps[0].constraints["retrieval_mode_metadata"]
    modes = metadata["supported_modes"]

    assert metadata["default_mode"] == "semantic_lookup"
    assert set(modes) == {
        "exact_lookup",
        "bounded_lookup",
        "semantic_lookup",
    }
    assert modes["exact_lookup"]["lookup_type"] == "exact_entity_lookup"
    assert modes["bounded_lookup"]["lookup_type"] == "bounded_entity_search"
    assert modes["bounded_lookup"]["execution_status"] == "implemented"


def test_search_db_semantic_lookup_policy_is_local_only_and_local_executing():
    workflow = _workflow("search_db")
    semantic = workflow.steps[0].constraints["retrieval_mode_metadata"][
        "supported_modes"
    ]["semantic_lookup"]
    governance = semantic["governance"]

    assert semantic["lookup_type"] == "semantic_entity_search"
    assert semantic["execution_status"] == "implemented"
    assert semantic["local_only"] is True
    assert governance["enabled"] is True
    assert governance["embedding_index_backend"] == (
        "alexis_guest_db_semantic_index_v1"
    )
    assert "similarity_threshold" in governance
    assert governance["max_semantic_candidates"] == 5
    assert governance["live_embedding_calls_allowed"] is False
    assert governance["cloud_embedding_calls_allowed"] is False


def test_semantic_lookup_mode_declaration_validates():
    workflow = workflow_declaration_from_dict(
        {
            "workflow_id": "semantic_lookup_fixture",
            "workflow_type": "semantic_workflow_skeleton",
            "owning_agent": "neutral_agent",
            "description": "Semantic lookup declaration fixture.",
            "governance_state": "enabled",
            "planner_authority_required": True,
            "steps": [
                {
                    "step_id": "lookup",
                    "step_kind": "retrieval",
                    "semantic_operation": "lookup",
                    "capability": "discover_entities",
                    "output_type": "lookup_result_set",
                    "requires_approval": False,
                    "bounded": True,
                    "governance_state": "audit_only",
                    "constraints": {
                        "retrieval_mode_metadata": {
                            "default_mode": "semantic_lookup",
                            "supported_modes": {
                                "semantic_lookup": {
                                    "lookup_type": "semantic_entity_search",
                                    "execution_status": "not_implemented",
                                    "local_only": True,
                                    "governance": {
                                        "enabled": False,
                                        "embedding_index_backend": (
                                            "local_fixture_backend"
                                        ),
                                        "similarity_threshold": None,
                                        "max_semantic_candidates": 0,
                                        "live_embedding_calls_allowed": False,
                                        "cloud_embedding_calls_allowed": False,
                                    },
                                },
                            },
                        },
                    },
                },
            ],
            "non_goals": ["no live retrieval execution"],
        }
    )

    assert workflow.steps[0].constraints["retrieval_mode_metadata"][
        "default_mode"
    ] == "semantic_lookup"


def test_implemented_semantic_lookup_mode_declaration_validates():
    workflow = workflow_declaration_from_dict(
        {
            "workflow_id": "implemented_semantic_lookup_fixture",
            "workflow_type": "semantic_workflow_skeleton",
            "owning_agent": "neutral_agent",
            "description": "Implemented semantic lookup declaration fixture.",
            "governance_state": "enabled",
            "planner_authority_required": True,
            "steps": [
                {
                    "step_id": "lookup",
                    "step_kind": "retrieval",
                    "semantic_operation": "lookup",
                    "capability": "discover_entities",
                    "output_type": "lookup_result_set",
                    "requires_approval": False,
                    "bounded": True,
                    "governance_state": "audit_only",
                    "constraints": {
                        "retrieval_mode_metadata": {
                            "default_mode": "semantic_lookup",
                            "supported_modes": {
                                "semantic_lookup": {
                                    "lookup_type": "semantic_entity_search",
                                    "execution_status": "implemented",
                                    "local_only": True,
                                    "governance": {
                                        "enabled": True,
                                        "embedding_index_backend": (
                                            "local_fixture_backend"
                                        ),
                                        "similarity_threshold": None,
                                        "max_semantic_candidates": 2,
                                        "live_embedding_calls_allowed": False,
                                        "cloud_embedding_calls_allowed": False,
                                    },
                                },
                            },
                        },
                    },
                },
            ],
            "non_goals": ["no external retrieval execution"],
        }
    )

    assert workflow.steps[0].constraints["retrieval_mode_metadata"][
        "supported_modes"
    ]["semantic_lookup"]["execution_status"] == "implemented"


def test_semantic_lookup_rejects_cloud_embedding_execution():
    try:
        workflow_declaration_from_dict(
            {
                "workflow_id": "bad_semantic_lookup_fixture",
                "workflow_type": "semantic_workflow_skeleton",
                "owning_agent": "neutral_agent",
                "description": "Bad semantic lookup declaration fixture.",
                "governance_state": "enabled",
                "planner_authority_required": True,
                "steps": [
                    {
                        "step_id": "lookup",
                        "step_kind": "retrieval",
                        "semantic_operation": "lookup",
                        "capability": "discover_entities",
                        "output_type": "lookup_result_set",
                        "requires_approval": False,
                        "bounded": True,
                        "governance_state": "audit_only",
                        "constraints": {
                            "retrieval_mode_metadata": {
                                "default_mode": "semantic_lookup",
                                "supported_modes": {
                                    "semantic_lookup": {
                                        "lookup_type": "semantic_entity_search",
                                        "execution_status": "not_implemented",
                                        "local_only": True,
                                        "governance": {
                                            "enabled": False,
                                            "embedding_index_backend": (
                                                "local_fixture_backend"
                                            ),
                                            "similarity_threshold": None,
                                            "max_semantic_candidates": 0,
                                            "live_embedding_calls_allowed": (
                                                False
                                            ),
                                            "cloud_embedding_calls_allowed": (
                                                True
                                            ),
                                        },
                                    },
                                },
                            },
                        },
                    },
                ],
                "non_goals": ["no live retrieval execution"],
            }
        )
    except WorkflowDeclarationError as exc:
        message = str(exc)
    else:
        raise AssertionError("cloud semantic lookup should fail")

    assert "cloud embeddings" in message


def test_search_web_workflow_loads_but_does_not_execute():
    workflow = _workflow("search_web")
    step = workflow.steps[0]
    assert workflow.workflow_id == "search_web"
    assert step.semantic_operation == "web_guest_discovery_placeholder"
    assert step.governance_state == "audit_only"
    assert step.placeholder is True
    assert step.constraints["source_scope"] == "web"
    assert step.constraints["web_search_execution_allowed"] is False
    assert step.constraints["declaration_only"] is True


def test_search_db_then_web_loads_as_nested_workflow():
    workflow = _workflow("search_db_then_web")
    graph = build_nested_workflow_graph(
        root_workflow_id="search_db_then_web",
        declarations=_declarations(),
    )
    assert workflow.workflow_id == "search_db_then_web"
    assert graph.expanded is True
    assert graph.execution_performed is False
    assert graph.workflow_ids == (
        "search_db",
        "search_db_then_web",
        "search_web",
    )


def test_no_canonical_workflow_id_remains_search_local():
    declarations = _declarations()
    assert "search_local" not in declarations
    assert "search_local_then_web" not in declarations
    for workflow in declarations.values():
        assert workflow.workflow_id not in {
            "search_local",
            "search_local_then_web",
        }
        for step in workflow.steps:
            assert step.workflow_ref not in {
                "search_local",
                "search_local_then_web",
            }


def test_search_db_then_web_calls_search_db_first():
    workflow = _workflow("search_db_then_web")
    first = workflow.steps[0]
    assert first.semantic_operation == "run_search_db"
    assert first.operation_kind == "run_workflow"
    assert first.workflow_ref == "search_db"
    assert first.constraints["child_source_scope"] == "guest_db"


def test_adequacy_assessment_exists_as_typed_placeholder():
    workflow = _workflow("search_db_then_web")
    assessment = _step(workflow, "assess_guest_candidate_adequacy")
    assert assessment.step_kind == "selection"
    assert assessment.output_type == "workflow_result"
    assert assessment.placeholder is True
    assert assessment.constraints["typed_placeholder"] is True
    assert assessment.constraints["logic_implemented"] is False
    assert assessment.constraints["assessment_type"] == "guest_candidate_adequacy"


def test_adequacy_assessment_references_typed_guest_candidate_list_input():
    assessment = _step(
        _workflow("search_db_then_web"),
        "assess_guest_candidate_adequacy",
    )
    assert assessment.input_refs == ("artifact:guest_candidate_list:search_db",)
    assert assessment.output_ref == "artifact:guest_candidate_adequacy:search_db"
    assert assessment.constraints["input_artifact_type"] == "guest_candidate_list"
    assert assessment.constraints["raw_prose_inspection_allowed"] is False


def test_inadequate_transition_leads_to_notify_and_continue():
    workflow = _workflow("search_db_then_web")
    resolution = resolve_workflow_transition(
        workflow=workflow,
        current_operation_id="assess_guest_candidate_adequacy",
        result_status="inadequate",
    )
    notify = _step(workflow, "notify_web_search_fallback")
    assert resolution.resolved is True
    assert resolution.next_operation_id == "notify_web_search_fallback"
    assert notify.operation_kind == "notify_and_continue"
    assert notify.blocking is False
    assert notify.suspending is False


def test_notify_and_continue_leads_to_search_web():
    workflow = _workflow("search_db_then_web")
    resolution = resolve_workflow_transition(
        workflow=workflow,
        current_operation_id="notify_web_search_fallback",
        result_status="success",
    )
    web = _step(workflow, "run_search_web")
    assert resolution.resolved is True
    assert resolution.next_operation_id == "run_search_web"
    assert web.workflow_ref == "search_web"
    assert web.constraints["web_search_execution_allowed"] is False


def test_search_web_is_governed_declaration_only_and_non_executing():
    declarations = _declarations()
    graph = build_nested_workflow_graph(
        root_workflow_id="search_db_then_web",
        declarations=declarations,
    )
    web = _workflow("search_web").steps[0]
    rendered = repr(graph).lower()
    assert web.governance_state == "audit_only"
    assert web.constraints["declaration_only"] is True
    assert graph.execution_performed is False
    assert all(edge["execution_performed"] is False for edge in graph.edges)
    assert "web_search_result" not in rendered


def test_source_scope_metadata_is_represented():
    db = _workflow("search_db").steps[0]
    web = _workflow("search_web").steps[0]
    combined = _workflow("search_db_then_web")
    assert db.constraints["source_scope"] == "guest_db"
    assert web.constraints["source_scope"] == "web"
    assert all(
        step.constraints["source_scope"] == "db_then_web"
        for step in combined.steps
    )


def test_adequacy_result_shape_is_typed_not_prose():
    assessment = _step(
        _workflow("search_db_then_web"),
        "assess_guest_candidate_adequacy",
    )
    shape = assessment.constraints["adequacy_result_shape"]
    assert shape["artifact_type"] == "guest_candidate_adequacy"
    assert shape["adequate"] is None
    assert shape["outcome"] == "unknown"
    assert shape["candidate_count"] == 0
    assert shape["min_required_candidates"] == 1
    assert isinstance(shape["required_signals"], list)
    assert isinstance(shape["missing_signals"], list)
    assert shape["provenance"]["assessment_executed"] is False
    assert "Subject:" not in repr(shape)
    assert "Hi " not in repr(shape)


def test_future_enrichment_placeholders_do_not_become_ranking_logic():
    expected = {
        "has_email_contact",
        "email_refs",
        "has_video_presence",
        "video_presence_refs",
        "contact_confidence",
        "on_air_suitability_signals",
    }
    db = _workflow("search_db").steps[0]
    web = _workflow("search_web").steps[0]
    assessment = _step(
        _workflow("search_db_then_web"),
        "assess_guest_candidate_adequacy",
    )
    for step in (db, web, assessment):
        assert set(step.constraints["future_enrichment_signals"]) == expected
        assert step.constraints["ranking_performed"] is False


def test_runtime_remains_domain_neutral_and_alexis_declarations_are_scoped():
    runtime_sources = [
        ROOT / "runtime" / "workflows" / "declarations.py",
        ROOT / "runtime" / "workflows" / "nesting.py",
        ROOT / "runtime" / "workflows" / "transitions.py",
    ]
    runtime_text = "\n".join(
        source.read_text(encoding="utf-8").lower()
        for source in runtime_sources
    )
    forbidden = (
        "agents.alexis",
        "alexis_guest_db",
        "newsroom",
        "telegram",
        "gateway",
        "smtp",
        "gmail",
        "mailgun",
        "send_email(",
    )
    assert all(term not in runtime_text for term in forbidden)
    for name in ("search_db", "search_web", "search_db_then_web"):
        assert (
            ROOT / "agents" / "alexis" / "workflows" / f"{name}.json"
        ).exists()


def main():
    test_search_db_workflow_loads()
    test_search_db_declares_retrieval_modes()
    test_search_db_semantic_lookup_policy_is_local_only_and_local_executing()
    test_semantic_lookup_mode_declaration_validates()
    test_implemented_semantic_lookup_mode_declaration_validates()
    test_semantic_lookup_rejects_cloud_embedding_execution()
    test_search_web_workflow_loads_but_does_not_execute()
    test_search_db_then_web_loads_as_nested_workflow()
    test_no_canonical_workflow_id_remains_search_local()
    test_search_db_then_web_calls_search_db_first()
    test_adequacy_assessment_exists_as_typed_placeholder()
    test_adequacy_assessment_references_typed_guest_candidate_list_input()
    test_inadequate_transition_leads_to_notify_and_continue()
    test_notify_and_continue_leads_to_search_web()
    test_search_web_is_governed_declaration_only_and_non_executing()
    test_source_scope_metadata_is_represented()
    test_adequacy_result_shape_is_typed_not_prose()
    test_future_enrichment_placeholders_do_not_become_ranking_logic()
    test_runtime_remains_domain_neutral_and_alexis_declarations_are_scoped()
    print("PASS alexis guest search workflow decomposition")


if __name__ == "__main__":
    main()
