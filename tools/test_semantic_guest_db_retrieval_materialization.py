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
from runtime.workflows.semantic_guest_retrieval import (  # noqa: E402
    GUEST_CANDIDATE_LIST_ARTIFACT,
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


def _index():
    result = build_guest_db_semantic_index(
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
            _record(
                "guest-003",
                "Iris Gomez",
                "Technology attorney",
                "AI liability and privacy law",
                "Good on regulatory enforcement questions.",
            ),
        ],
        max_entries=5,
    )
    assert result.records_indexed == 3
    return result.index


def _materialize(query=None):
    provider_binding = get_provider_binding(
        "alexis_guest_db",
        agent_name="alexis",
        root=ROOT,
    )
    assert provider_binding is not None
    return materialize_semantic_guest_db_retrieval(
        semantic_query=query or {
            "query_text": "AI regulation",
            "max_results": 5,
        },
        guest_semantic_index=_index(),
        provider_binding_metadata=provider_binding.to_metadata(),
        workflow_id="search_db",
        step_id="db_guest_retrieval",
        artifact_ref="artifact:guest_candidate_list:search_db",
    )


def test_semantic_retrieval_returns_typed_guest_candidate_list():
    result = _materialize()
    artifact = result.artifact

    assert result.materialized is True
    assert artifact["artifact_type"] == GUEST_CANDIDATE_LIST_ARTIFACT
    assert artifact["source_scope"] == "db"
    assert artifact["candidate_count"] == 2
    assert [item["candidate_id"] for item in artifact["candidates"]] == [
        "guest-001",
        "guest-003",
    ]


def test_alexis_guest_db_provider_binding_validates():
    provider_binding = get_provider_binding(
        "alexis_guest_db",
        agent_name="alexis",
        root=ROOT,
    )

    assert provider_binding is not None
    assert provider_binding.provider_id == "alexis_guest_db"
    assert provider_binding.provider_contract_id == "external_discovery_provider"
    assert provider_binding.provider_type == "local_agent_owned_database"
    assert provider_binding.owner_agent == "alexis"
    assert provider_binding.resource_binding_id == "alexis_guest_db"
    assert provider_binding.resource_id == "guest_db"
    assert provider_binding.supported_output_types == (GUEST_CANDIDATE_LIST_ARTIFACT,)
    assert provider_binding.local_only is True
    assert provider_binding.execution_policy["network_calls_allowed"] is False
    assert provider_binding.execution_policy["cloud_model_calls_allowed"] is False
    assert provider_binding.execution_policy["delivery_allowed"] is False


def test_semantic_metadata_is_preserved_on_candidates():
    artifact = _materialize().artifact
    candidate = artifact["candidates"][0]

    assert candidate["semantic_match_score"] == 1.0
    assert candidate["semantic_match_reasons"] == [
        "semantic_text_term_overlap",
        "semantic_tag_term_overlap",
        "semantic_category_term_overlap",
    ]
    assert candidate["matched_terms"] == ["ai", "regulation"]
    assert candidate["metadata"]["source_scope"] == "db"
    assert candidate["provenance"]["source_scope"] == "db"
    assert candidate["provenance"]["source_record_id"] == "guest-001"


def test_artifact_provenance_records_local_semantic_boundary():
    artifact = _materialize().artifact
    provenance = artifact["provenance"]

    assert provenance["materialization_boundary"] == (
        "runtime.workflows.semantic_guest_retrieval"
    )
    assert provenance["retrieval_boundary"] == "runtime.semantic_retrieval"
    assert provenance["source_scope"] == "db"
    assert provenance["deterministic"] is True
    assert provenance["external_calls_executed"] is False
    assert provenance["cloud_model_called"] is False
    assert provenance["llm_ranking_performed"] is False
    assert provenance["web_search_executed"] is False
    assert provenance["delivery_performed"] is False
    assert provenance["provider_id"] == "alexis_guest_db"
    assert provenance["provider_contract_id"] == "external_discovery_provider"
    assert provenance["resource_binding_id"] == "alexis_guest_db"
    assert provenance["resource_id"] == "guest_db"
    assert provenance["semantic_owner"] == "alexis"


def test_provider_metadata_is_preserved_on_artifact():
    artifact = _materialize().artifact
    provider = artifact["provider"]

    assert provider["provider_id"] == "alexis_guest_db"
    assert provider["provider_contract_id"] == "external_discovery_provider"
    assert provider["execution_mode"] == "local_only"
    assert provider["semantic_retrieval_path"] == (
        "runtime.workflows.semantic_guest_retrieval"
    )
    assert provider["local_only"] is True
    assert provider["execution_policy"]["network_calls_allowed"] is False
    assert provider["execution_policy"]["cloud_model_calls_allowed"] is False


def test_malformed_query_fails_safely():
    result = materialize_semantic_guest_db_retrieval(
        semantic_query={"query_text": " "},
        guest_semantic_index=_index(),
    )

    assert result.materialized is False
    assert result.transition_outcome == "failure"
    assert result.skipped_reasons == ("missing_semantic_query_text",)
    assert result.artifact["artifact_type"] == GUEST_CANDIDATE_LIST_ARTIFACT
    assert result.artifact["candidate_count"] == 0
    assert result.artifact["candidates"] == []


def test_deterministic_retrieval_behavior():
    first = _materialize().artifact
    second = _materialize().artifact

    assert first == second
    assert [item["candidate_id"] for item in first["candidates"]] == [
        "guest-001",
        "guest-003",
    ]


def test_no_external_calls_are_added():
    sources = [
        ROOT / "runtime" / "semantic_retrieval.py",
        ROOT / "runtime" / "workflows" / "semantic_guest_retrieval.py",
    ]
    forbidden = (
        "requests",
        "urllib",
        "selenium",
        "playwright",
        "openai",
        "anthropic",
        "browser.search",
        "webbrowser",
        "telegram",
        "gateway",
        "smtp",
        "gmail",
        "mailgun",
        "send_email(",
        "delivery_performed = true",
    )
    for path in sources:
        lowered = path.read_text(encoding="utf-8").lower()
        assert all(term not in lowered for term in forbidden)


def main():
    test_semantic_retrieval_returns_typed_guest_candidate_list()
    test_alexis_guest_db_provider_binding_validates()
    test_semantic_metadata_is_preserved_on_candidates()
    test_artifact_provenance_records_local_semantic_boundary()
    test_provider_metadata_is_preserved_on_artifact()
    test_malformed_query_fails_safely()
    test_deterministic_retrieval_behavior()
    test_no_external_calls_are_added()
    print("PASS semantic guest db retrieval materialization")


if __name__ == "__main__":
    main()
