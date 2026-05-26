import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.artifacts.search_api_result import (  # noqa: E402
    SEARCH_API_RESULT_SET_ARTIFACT,
    build_search_api_result_set,
    normalize_search_api_result_set_to_summary_source_items,
    validate_search_api_result_set,
)
from runtime.artifacts.summary import (  # noqa: E402
    build_summary_artifact,
    validate_summary_artifact,
)
from runtime.registries.artifacts import (  # noqa: E402
    get_artifact_config,
    load_artifact_registry,
)


def _valid_live_artifact():
    return build_search_api_result_set(
        provider_id="tavily",
        provider_type="search_api",
        query="AI governance source attribution",
        results=[
            {
                "provider_result_id": "result-1",
                "source_ref_id": "source-1",
                "title": "Example source",
                "url": "https://example.test/source",
                "snippet": "Provider snippet.",
                "raw_item": {
                    "title": "Example source",
                    "url": "https://example.test/source",
                    "content": "Provider snippet.",
                },
            }
        ],
        source_refs=[
            {
                "source_ref_id": "source-1",
                "provider_result_id": "result-1",
                "source_url": "https://example.test/source",
                "source_type": "web_page",
                "title": "Example source",
            }
        ],
        citations=[
            {
                "citation_id": "citation-1",
                "source_ref_id": "source-1",
                "provider_result_id": "result-1",
                "source_url": "https://example.test/source",
            }
        ],
        raw_provider_payload={
            "results": [
                {
                    "title": "Example source",
                    "url": "https://example.test/source",
                    "content": "Provider snippet.",
                }
            ]
        },
        external_call_performed=True,
        dry_run=False,
        cost_incurred=False,
    )


def test_search_api_result_artifact_is_registered():
    load_artifact_registry.cache_clear()
    config = get_artifact_config(SEARCH_API_RESULT_SET_ARTIFACT)

    assert config["semantic_class"] == "search_api_raw_result"
    assert config["bounded"] is True
    assert config["persist_as_artifact"] is True
    assert config["formatting_constraints"]["summarization_allowed"] is False
    assert config["formatting_constraints"]["domain_normalization_allowed"] is False
    assert config["formatting_constraints"]["delivery_allowed"] is False


def test_valid_live_search_api_result_artifact_validates():
    artifact = _valid_live_artifact()

    assert artifact["artifact_type"] == SEARCH_API_RESULT_SET_ARTIFACT
    assert artifact["result_type"] == SEARCH_API_RESULT_SET_ARTIFACT
    assert artifact["provider_id"] == "tavily"
    assert artifact["provider_type"] == "search_api"
    assert artifact["external_call_performed"] is True
    assert artifact["dry_run"] is False
    assert artifact["provenance"]["raw_search_api_result"] is True
    assert validate_search_api_result_set(artifact) == ()


def test_invalid_search_api_result_requires_urls_and_source_refs():
    artifact = _valid_live_artifact()
    artifact["results"][0].pop("url")
    artifact["results"][0].pop("source_ref_id")
    artifact["source_refs"] = []

    errors = validate_search_api_result_set(artifact)
    codes = {error.error_code for error in errors}

    assert "accepted_result_missing_url" in codes
    assert "accepted_result_missing_source_ref" in codes
    assert "invalid_object_list" in codes


def test_raw_search_api_result_stays_separate_from_summary_artifacts():
    artifact = _valid_live_artifact()
    artifact["sourced_summary"] = "A derived summary is not raw output."
    artifact["news_briefing"] = {"items": []}
    artifact["telegram_text"] = "Final Telegram prose must be produced downstream."
    artifact["provenance"]["summary_generated"] = True

    errors = validate_search_api_result_set(artifact)
    fields = {error.field for error in errors}

    assert "sourced_summary" in fields
    assert "news_briefing" in fields
    assert "telegram_text" in fields
    assert "provenance.summary_generated" in fields


def test_dry_run_search_api_artifact_allows_empty_results_without_live_call():
    artifact = build_search_api_result_set(
        provider_id="tavily",
        provider_type="search_api",
        query="AI governance source attribution",
        results=[],
        source_refs=[],
        citations=[],
        raw_provider_payload={
            "dry_run": True,
            "external_call_performed": False,
        },
        external_call_performed=False,
        dry_run=True,
        cost_incurred=False,
        provenance={
            "execution_state": "dry_run_no_live_call",
        },
    )

    assert artifact["results"] == []
    assert artifact["source_refs"] == []
    assert artifact["citations"] == []
    assert artifact["external_call_performed"] is False
    assert artifact["dry_run"] is True
    assert artifact["cost_incurred"] is False
    assert validate_search_api_result_set(artifact) == ()


def test_cost_and_execution_flags_must_match_provenance():
    artifact = _valid_live_artifact()
    artifact["provenance"]["cost_incurred"] = True
    artifact["provenance"]["external_call_performed"] = False

    errors = validate_search_api_result_set(artifact)
    fields = {error.field for error in errors}

    assert "provenance.cost_incurred" in fields
    assert "provenance.external_call_performed" in fields


def test_search_api_result_set_normalizes_to_summary_source_items():
    artifact = _valid_live_artifact()
    artifact["results"][0]["source_metadata"] = {
        "published_date": "2026-05-20T09:30:00+00:00"
    }

    source_items = normalize_search_api_result_set_to_summary_source_items(artifact)

    assert len(source_items) == 1
    assert source_items[0]["item_id"] == "result-1"
    assert source_items[0]["provider_result_id"] == "result-1"
    assert source_items[0]["source_ref_id"] == "source-1"
    assert source_items[0]["source_id"] == "tavily:result-1"
    assert source_items[0]["title"] == "Example source"
    assert source_items[0]["link"] == "https://example.test/source"
    assert source_items[0]["snippet"] == "Provider snippet."
    assert source_items[0]["published"] == "2026-05-20T09:30:00+00:00"
    assert source_items[0]["provider_metadata"]["provider_id"] == "tavily"
    assert source_items[0]["provider_metadata"]["provider_type"] == "search_api"
    assert source_items[0]["source_ref"]["source_url"] == "https://example.test/source"


def test_search_api_summary_artifact_preserves_refs_and_provider_metadata():
    artifact = _valid_live_artifact()
    source_items = normalize_search_api_result_set_to_summary_source_items(artifact)
    seen_by_model_summary = []

    summary_artifact = build_summary_artifact(
        source_items=source_items,
        summary_kind="source_grounded_briefing_input",
        tone="neutral",
        provenance="search_api_source_normalization",
        summary_text_builder=lambda item: seen_by_model_summary.append(
            (
                item["source_ref_id"],
                item.get("snippet", ""),
                item.get("provider_metadata", {}).get("provider_type", ""),
            )
        )
        or f"{item['title']} - {item.get('snippet', '')}",
    )

    assert summary_artifact is not None
    assert validate_summary_artifact(summary_artifact)
    assert summary_artifact["source_items"][0]["source_ref_id"] == "source-1"
    assert summary_artifact["source_items"][0]["snippet"] == "Provider snippet."
    assert (
        summary_artifact["source_items"][0]["provider_metadata"]["provider_type"]
        == "search_api"
    )
    assert summary_artifact["source_refs"][0]["source_ref_id"] == "source-1"
    assert summary_artifact["source_refs"][0]["link"] == "https://example.test/source"
    assert summary_artifact["summary_blocks"][0]["source_ref_id"] == "source-1"
    assert summary_artifact["summary_blocks"][0]["citation_id"] == (
        summary_artifact["citations"][0]["citation_id"]
    )
    assert seen_by_model_summary == [
        ("source-1", "Provider snippet.", "search_api")
    ]


def test_search_api_normalization_does_not_accept_provider_final_prose():
    artifact = _valid_live_artifact()
    artifact["raw_provider_payload"]["answer"] = (
        "Telegram-ready provider prose must not be promoted by normalization."
    )
    artifact["final_answer"] = artifact["raw_provider_payload"]["answer"]

    errors = validate_search_api_result_set(artifact)
    source_items = normalize_search_api_result_set_to_summary_source_items(artifact)

    assert any(error.field == "final_answer" for error in errors)
    assert source_items == ()


def main():
    test_search_api_result_artifact_is_registered()
    test_valid_live_search_api_result_artifact_validates()
    test_invalid_search_api_result_requires_urls_and_source_refs()
    test_raw_search_api_result_stays_separate_from_summary_artifacts()
    test_dry_run_search_api_artifact_allows_empty_results_without_live_call()
    test_cost_and_execution_flags_must_match_provenance()
    test_search_api_result_set_normalizes_to_summary_source_items()
    test_search_api_summary_artifact_preserves_refs_and_provider_metadata()
    test_search_api_normalization_does_not_accept_provider_final_prose()
    print("PASS search_api result artifact")


if __name__ == "__main__":
    main()
