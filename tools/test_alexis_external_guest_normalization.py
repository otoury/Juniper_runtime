import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.alexis.normalizers.external_guest_discovery import (  # noqa: E402
    ALEXIS_EXTERNAL_GUEST_NORMALIZATION,
    normalize_external_discovery_to_guest_candidate_list,
)
from runtime.artifacts.external_discovery_result import (  # noqa: E402
    build_external_discovery_result_set,
)
from runtime.workflows.candidate_merge import (  # noqa: E402
    GUEST_CANDIDATE_LIST_ARTIFACT,
)


def _raw_external_discovery_artifact():
    return build_external_discovery_result_set(
        provider_metadata={
            "provider_id": "bounded_fixture",
            "provider_type": "fixture",
            "request_id": "request-123",
        },
        raw_provider_payload={
            "items": [
                {
                    "id": "provider-result-1",
                    "name": "Guest One",
                    "url": "https://example.test/guest-one",
                },
                {
                    "id": "provider-result-2",
                    "name": "Guest Two",
                    "url": "https://example.test/guest-two",
                },
            ]
        },
        raw_results=[
            {
                "provider_result_id": "provider-result-1",
                "display_name": "Guest One",
                "canonical_name": "guest one",
                "source_url": "https://example.test/guest-one",
                "has_email_contact": True,
                "email_refs": ["artifact:contact:guest-one:email"],
                "has_video_presence": True,
                "video_presence_refs": ["artifact:video:guest-one:clip"],
                "contact_confidence": 0.85,
                "on_air_suitability_signals": [
                    "camera_ready",
                    "topic_relevant",
                ],
            },
            {
                "provider_result_id": "provider-result-2",
                "name": "Guest Two",
                "url": "https://example.test/guest-two",
                "has_email_contact": False,
                "has_video_presence": False,
                "contact_confidence": 0.2,
            },
        ],
        source_refs=[
            {
                "source_ref_id": "source-ref-1",
                "provider_result_id": "provider-result-1",
                "source_url": "https://example.test/guest-one",
                "source_type": "web_page",
                "title": "Guest One profile",
            },
            {
                "source_ref_id": "source-ref-2",
                "provider_result_id": "provider-result-2",
                "source_url": "https://example.test/guest-two",
                "source_type": "web_page",
                "title": "Guest Two profile",
            },
        ],
        citations=[
            {
                "citation_id": "citation-1",
                "source_ref_id": "source-ref-1",
                "provider_result_id": "provider-result-1",
                "source_url": "https://example.test/guest-one",
                "quote": "Guest One profile snippet.",
            },
            {
                "citation_id": "citation-2",
                "source_ref_id": "source-ref-2",
                "provider_result_id": "provider-result-2",
                "source_url": "https://example.test/guest-two",
                "quote": "Guest Two profile snippet.",
            },
        ],
    )


def test_normalization_produces_typed_guest_candidate_list():
    result = normalize_external_discovery_to_guest_candidate_list(
        _raw_external_discovery_artifact(),
        artifact_ref="artifact:external_discovery_result_set:fixture",
    )

    artifact = result.artifact
    assert result.materialized is True
    assert result.transition_outcome == "success"
    assert artifact["artifact_type"] == GUEST_CANDIDATE_LIST_ARTIFACT
    assert artifact["source_scope"] == "web"
    assert artifact["candidate_count"] == 2
    assert [candidate["display_name"] for candidate in artifact["candidates"]] == [
        "Guest One",
        "Guest Two",
    ]


def test_provenance_citations_and_source_refs_are_preserved():
    result = normalize_external_discovery_to_guest_candidate_list(
        _raw_external_discovery_artifact(),
        artifact_ref="artifact:external_discovery_result_set:fixture",
    )
    artifact = result.artifact
    candidate = artifact["candidates"][0]

    assert artifact["source_refs"][0]["source_ref_id"] == "source-ref-1"
    assert artifact["citations"][0]["citation_id"] == "citation-1"
    assert artifact["provider_metadata"]["provider_id"] == "bounded_fixture"
    assert artifact["provenance"]["raw_external_discovery_artifact_ref"] == (
        "artifact:external_discovery_result_set:fixture"
    )
    assert candidate["source_refs"][0]["source_ref_id"] == "source-ref-1"
    assert candidate["citations"][0]["citation_id"] == "citation-1"
    assert candidate["provenance"]["raw_result"]["provider_result_id"] == (
        "provider-result-1"
    )
    assert candidate["provenance"]["raw_external_result_provenance"][
        "raw_external_result"
    ] is True


def test_enrichment_metadata_is_preserved():
    artifact = normalize_external_discovery_to_guest_candidate_list(
        _raw_external_discovery_artifact()
    ).artifact
    candidate = artifact["candidates"][0]

    assert candidate["has_email_contact"] is True
    assert candidate["has_video_presence"] is True
    assert candidate["video_presence_refs"] == ["artifact:video:guest-one:clip"]
    assert candidate["contact_confidence"] == 0.85
    assert candidate["on_air_suitability_signals"] == [
        "camera_ready",
        "topic_relevant",
    ]


def test_malformed_raw_artifact_fails_safely():
    result = normalize_external_discovery_to_guest_candidate_list(
        {
            "artifact_type": "external_discovery_result_set",
            "raw_results": "not a list",
        }
    )

    assert result.materialized is False
    assert result.transition_outcome == "failure"
    assert result.artifact["artifact_type"] == GUEST_CANDIDATE_LIST_ARTIFACT
    assert result.artifact["candidate_count"] == 0
    assert result.artifact["provenance"]["normalization_performed"] is False
    assert "invalid_provider_metadata" in result.skipped_reasons
    assert "invalid_object_list" in result.skipped_reasons


def test_malformed_candidate_enrichment_is_skipped_safely():
    raw = _raw_external_discovery_artifact()
    raw["raw_results"][0]["contact_confidence"] = 3

    result = normalize_external_discovery_to_guest_candidate_list(raw)

    assert result.materialized is True
    assert result.artifact["candidate_count"] == 1
    assert result.artifact["candidates"][0]["display_name"] == "Guest Two"
    assert result.skipped_reasons == ("candidate_enrichment_metadata_invalid",)


def test_no_ranking_scoring_or_provider_execution_occurs():
    artifact = normalize_external_discovery_to_guest_candidate_list(
        _raw_external_discovery_artifact()
    ).artifact
    provenance = artifact["provenance"]

    assert "ranked_candidates" not in artifact
    assert "ranking" not in artifact
    assert provenance["normalizer"] == ALEXIS_EXTERNAL_GUEST_NORMALIZATION
    assert provenance["provider_execution_performed"] is False
    assert provenance["provider_executed"] is False
    assert provenance["web_search_executed"] is False
    assert provenance["browser_api_called"] is False
    assert provenance["search_api_called"] is False
    assert provenance["cloud_model_called"] is False
    assert provenance["external_adapter_called"] is False
    assert provenance["ranking_performed"] is False
    assert provenance["scoring_performed"] is False
    assert provenance["selection_performed"] is False
    assert provenance["delivery_performed"] is False

    for candidate in artifact["candidates"]:
        assert "rank" not in candidate
        assert "score" not in candidate
        assert candidate["provenance"]["ranking_performed"] is False
        assert candidate["provenance"]["scoring_performed"] is False


def test_normalizer_module_has_no_execution_paths():
    source = (
        ROOT / "agents" / "alexis" / "normalizers" / "external_guest_discovery.py"
    ).read_text(encoding="utf-8")
    lowered = source.lower()
    forbidden = (
        "requests",
        "urllib",
        "selenium",
        "playwright",
        "beautifulsoup",
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
    )

    assert all(term not in lowered for term in forbidden)


def main():
    test_normalization_produces_typed_guest_candidate_list()
    test_provenance_citations_and_source_refs_are_preserved()
    test_enrichment_metadata_is_preserved()
    test_malformed_raw_artifact_fails_safely()
    test_malformed_candidate_enrichment_is_skipped_safely()
    test_no_ranking_scoring_or_provider_execution_occurs()
    test_normalizer_module_has_no_execution_paths()
    print("PASS alexis external guest normalization")


if __name__ == "__main__":
    main()
