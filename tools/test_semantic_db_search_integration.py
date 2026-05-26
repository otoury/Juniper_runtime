import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.alexis.adapters.guest_db.semantic_index import (  # noqa: E402
    build_guest_db_semantic_index,
)
from runtime.registries.provider_binding_registry import (  # noqa: E402
    get_provider_binding,
)
from runtime.workflows.adequacy import (  # noqa: E402
    materialize_guest_candidate_adequacy,
)
from runtime.workflows.candidate_merge import (  # noqa: E402
    materialize_guest_candidate_list_merge,
)
from runtime.workflows.declarations import (  # noqa: E402
    resolve_workflow_declaration,
)
from runtime.workflows.ranking import (  # noqa: E402
    materialize_guest_candidate_ranking,
)
from runtime.workflows.semantic_guest_retrieval import (  # noqa: E402
    materialize_semantic_guest_db_retrieval,
)


def _record(candidate_id, name, title, expertise, notes):
    return {
        "guest_id": candidate_id,
        "display_name": name,
        "title": title,
        "expertise": expertise,
        "booking_notes": notes,
        "source_updated_at": "2026-05-17T00:00:00Z",
    }


def _semantic_candidate_artifact():
    index = build_guest_db_semantic_index(
        rows=[
            _record(
                "guest-001",
                "Mira Chen",
                "AI policy scholar",
                "Artificial intelligence regulation",
                "Can explain state-level model governance.",
            ),
            _record(
                "guest-002",
                "Noah Patel",
                "Hospital administrator",
                "Rural medicine operations",
                "Available for health system logistics segments.",
            ),
        ],
        max_entries=5,
    ).index
    provider_binding = get_provider_binding(
        "alexis_guest_db",
        agent_name="alexis",
        root=ROOT,
    )
    assert provider_binding is not None
    return materialize_semantic_guest_db_retrieval(
        semantic_query={
            "query_text": "AI regulation",
            "max_results": 5,
        },
        guest_semantic_index=index,
        provider_binding_metadata=provider_binding.to_metadata(),
        workflow_id="search_db",
        step_id="db_guest_retrieval",
        artifact_ref="artifact:guest_candidate_list:search_db",
    ).artifact


def _assessment_step():
    workflow = resolve_workflow_declaration(
        agent_name="alexis",
        workflow_id="search_db_then_web",
        root=ROOT,
    )
    for step in workflow.steps:
        if step.semantic_operation == "assess_guest_candidate_adequacy":
            return step
    raise AssertionError("missing adequacy step")


def test_search_db_workflow_allows_local_semantic_retrieval_path():
    workflow = resolve_workflow_declaration(
        agent_name="alexis",
        workflow_id="search_db",
        root=ROOT,
    )
    metadata = workflow.steps[0].constraints["retrieval_mode_metadata"]
    semantic = metadata["supported_modes"]["semantic_lookup"]

    assert metadata["default_mode"] == "semantic_lookup"
    assert workflow.steps[0].constraints["provider_binding_id"] == "alexis_guest_db"
    assert semantic["execution_status"] == "implemented"
    assert semantic["local_only"] is True
    assert semantic["governance"]["enabled"] is True
    assert semantic["governance"]["live_embedding_calls_allowed"] is False
    assert semantic["governance"]["cloud_embedding_calls_allowed"] is False


def test_semantic_db_results_flow_into_adequacy_assessment():
    candidate_artifact = _semantic_candidate_artifact()
    adequacy = materialize_guest_candidate_adequacy(
        candidate_artifact=candidate_artifact,
        step=_assessment_step(),
    ).artifact

    assert candidate_artifact["candidate_count"] == 1
    assert adequacy["candidate_count"] == 1
    assert adequacy["adequate"] is True
    assert adequacy["provenance"]["semantic_retrieval_executed"] is True
    assert adequacy["provenance"]["semantic_records_returned"] == 1
    assert candidate_artifact["provider"]["provider_id"] == "alexis_guest_db"
    assert candidate_artifact["provenance"]["provider_id"] == "alexis_guest_db"


def test_semantic_db_results_flow_into_candidate_merge():
    candidate_artifact = _semantic_candidate_artifact()
    merged = materialize_guest_candidate_list_merge(
        candidate_artifacts=[candidate_artifact],
        artifact_refs=["artifact:guest_candidate_list:search_db"],
    ).artifact
    candidate = merged["candidates"][0]

    assert merged["candidate_count"] == 1
    assert merged["source_scopes"] == ["db"]
    assert candidate["semantic_match_score"] == 1.0
    assert candidate["metadata"]["semantic_match_score"] == 1.0
    assert candidate["source_lineage"][0]["provenance"][
        "artifact_provenance"
    ]["retrieval_boundary"] == "runtime.semantic_retrieval"


def test_semantic_metadata_survives_dedupe_merge_when_later_input_has_it():
    non_semantic = {
        "artifact_type": "guest_candidate_list",
        "source_scope": "db",
        "candidate_count": 1,
        "candidates": [
            {
                "candidate_id": "guest-001",
                "display_name": "Mira Chen",
            }
        ],
        "provenance": {"source_scope": "db"},
    }
    semantic = _semantic_candidate_artifact()
    merged = materialize_guest_candidate_list_merge(
        candidate_artifacts=[non_semantic, semantic],
        artifact_refs=[
            "artifact:guest_candidate_list:bounded_fixture",
            "artifact:guest_candidate_list:semantic_fixture",
        ],
    ).artifact
    candidate = merged["candidates"][0]

    assert merged["candidate_count"] == 1
    assert "semantic_match_score" not in candidate
    assert "matched_terms" not in candidate
    assert "metadata" not in candidate
    assert candidate["merge_receipt_refs"] == ["receipt:guest_candidate_merge:0"]
    receipt = merged["guest_candidate_merge_receipts"][0]
    assert receipt["merge_is_structural"] is True
    assert receipt["semantic_ranking_performed"] is False
    assert receipt["source_weighting_heuristic_performed"] is False


def test_semantic_metadata_survives_deterministic_ranking():
    merged = materialize_guest_candidate_list_merge(
        candidate_artifacts=[_semantic_candidate_artifact()],
        artifact_refs=["artifact:guest_candidate_list:search_db"],
    ).artifact
    ranked = materialize_guest_candidate_ranking(
        candidate_artifact=merged,
        input_artifact_ref="artifact:guest_candidate_list:merged",
    ).artifact
    candidate = ranked["ranked_candidates"][0]

    assert ranked["ranking_policy"]["deterministic"] is True
    assert ranked["provenance"]["cloud_model_called"] is False
    assert ranked["provenance"]["external_adapter_called"] is False
    assert candidate["semantic_match_score"] == 1.0
    assert candidate["metadata"]["matched_terms"] == ["ai", "regulation"]
    assert candidate["provenance"]["ranking_policy_id"]


def test_ranking_remains_deterministic_for_semantic_db_results():
    merged = materialize_guest_candidate_list_merge(
        candidate_artifacts=[_semantic_candidate_artifact()],
        artifact_refs=["artifact:guest_candidate_list:search_db"],
    ).artifact

    first = materialize_guest_candidate_ranking(
        candidate_artifact=merged,
        input_artifact_ref="artifact:guest_candidate_list:merged",
    ).artifact
    second = materialize_guest_candidate_ranking(
        candidate_artifact=merged,
        input_artifact_ref="artifact:guest_candidate_list:merged",
    ).artifact

    assert first == second


def test_no_web_cloud_or_external_execution_is_added():
    artifacts = [
        _semantic_candidate_artifact(),
    ]
    merged = materialize_guest_candidate_list_merge(
        candidate_artifacts=artifacts,
    ).artifact
    ranked = materialize_guest_candidate_ranking(
        candidate_artifact=merged,
    ).artifact
    rendered = repr([*artifacts, merged, ranked]).lower()

    assert "web_search_executed': true" not in rendered
    assert "cloud_model_called': true" not in rendered
    assert "external_adapter_called': true" not in rendered
    assert "delivery_performed': true" not in rendered
    assert "llm_ranking_performed': true" not in rendered


def main():
    test_search_db_workflow_allows_local_semantic_retrieval_path()
    test_semantic_db_results_flow_into_adequacy_assessment()
    test_semantic_db_results_flow_into_candidate_merge()
    test_semantic_metadata_survives_dedupe_merge_when_later_input_has_it()
    test_semantic_metadata_survives_deterministic_ranking()
    test_ranking_remains_deterministic_for_semantic_db_results()
    test_no_web_cloud_or_external_execution_is_added()
    print("PASS semantic db search integration")


if __name__ == "__main__":
    main()
