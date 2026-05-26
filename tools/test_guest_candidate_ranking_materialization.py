import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.workflows.ranking import (  # noqa: E402
    GUEST_CANDIDATE_LIST_ARTIFACT,
    RANKED_GUEST_CANDIDATE_LIST_ARTIFACT,
    materialize_guest_candidate_ranking,
)


def _candidate(name, **metadata):
    return {
        "candidate_id": f"guest:{name}",
        "display_name": name,
        **metadata,
    }


def _artifact(candidates):
    return {
        "artifact_type": GUEST_CANDIDATE_LIST_ARTIFACT,
        "workflow_id": "fixture_workflow",
        "step_id": "fixture_candidates",
        "candidate_count": len(candidates),
        "candidates": candidates,
        "provenance": {
            "web_search_executed": False,
            "cloud_model_called": False,
        },
    }


def _ranked_names(candidates):
    result = materialize_guest_candidate_ranking(
        candidate_artifact=_artifact(candidates)
    )
    return [
        candidate["display_name"]
        for candidate in result.artifact["ranked_candidates"]
    ]


def test_output_artifact_is_ranked_guest_candidate_list():
    result = materialize_guest_candidate_ranking(
        candidate_artifact=_artifact([_candidate("One")])
    )
    artifact = result.artifact
    assert result.materialized is True
    assert artifact["artifact_type"] == RANKED_GUEST_CANDIDATE_LIST_ARTIFACT
    assert artifact["ranking_executed"] is True
    assert artifact["candidate_count"] == 1
    assert "ranked_candidates" in artifact
    assert "ranking_policy" in artifact
    assert "rank_reason_codes" in artifact
    assert "provenance" in artifact


def test_candidates_with_email_or_contact_rank_before_candidates_without_email_contact():
    names = _ranked_names(
        [
            _candidate("No Contact"),
            _candidate("Email Field", email="guest@example.test"),
            _candidate("Contact Metadata", has_email_contact=True),
            _candidate("Email Ref", email_refs=["artifact:contact:email"]),
        ]
    )
    assert names == [
        "Email Field",
        "Contact Metadata",
        "Email Ref",
        "No Contact",
    ]


def test_candidates_with_video_presence_rank_before_email_only_candidates():
    names = _ranked_names(
        [
            _candidate("Email Only", has_email_contact=True),
            _candidate(
                "Email And Video",
                has_email_contact=True,
                has_video_presence=True,
            ),
            _candidate(
                "Email And Video Ref",
                has_email_contact=True,
                video_presence_refs=["artifact:video:clip"],
            ),
            _candidate("Video Only", has_video_presence=True),
        ]
    )
    assert names == [
        "Email And Video",
        "Email And Video Ref",
        "Video Only",
        "Email Only",
    ]


def test_email_contact_improves_ranking_after_video_presence():
    names = _ranked_names(
        [
            _candidate("Video Only", has_video_presence=True),
            _candidate(
                "Video And Email",
                has_video_presence=True,
                has_email_contact=True,
            ),
            _candidate("No Contact"),
            _candidate("Email Only", has_email_contact=True),
        ]
    )
    assert names == [
        "Video And Email",
        "Video Only",
        "Email Only",
        "No Contact",
    ]


def test_stable_ordering_is_preserved_when_signals_are_equal():
    names = _ranked_names(
        [
            _candidate("First", has_email_contact=True),
            _candidate("Second", has_email_contact=True),
            _candidate("Third"),
            _candidate("Fourth"),
        ]
    )
    assert names == ["First", "Second", "Third", "Fourth"]


def test_rank_reason_codes_are_emitted_without_prose_explanations():
    artifact = materialize_guest_candidate_ranking(
        candidate_artifact=_artifact(
            [
                _candidate("One", has_email_contact=True),
                _candidate("Two"),
            ]
        )
    ).artifact
    assert artifact["rank_reason_codes"] == [
        "video_presence_present",
        "video_presence_absent",
        "email_contact_present",
        "email_contact_absent",
        "contact_confidence_present",
        "contact_confidence_absent",
        "on_air_suitability_signals_present",
        "on_air_suitability_signals_absent",
        "semantic_match_score_present",
        "semantic_match_score_absent",
        "stable_input_order",
    ]
    for candidate in artifact["ranked_candidates"]:
        assert "rank_reason_codes" in candidate
        assert "rank_explanation" not in candidate
        assert "explanation" not in candidate
        assert all("_" in code for code in candidate["rank_reason_codes"])
    assert artifact["provenance"]["prose_explanation_generated"] is False
    assert artifact["ranking_policy"]["prose_explanations_allowed"] is False


def test_enrichment_score_is_deterministic_and_metadata_only():
    artifact = materialize_guest_candidate_ranking(
        candidate_artifact=_artifact(
            [
                _candidate(
                    "Video Only",
                    has_video_presence=True,
                ),
                _candidate(
                    "Email Strong Metadata",
                    has_email_contact=True,
                    contact_confidence=1.0,
                    on_air_suitability_signals=["clear", "concise"],
                    semantic_match_score=1.0,
                ),
                _candidate(
                    "Video And Email",
                    has_video_presence=True,
                    has_email_contact=True,
                    contact_confidence=0.5,
                ),
            ]
        )
    ).artifact

    names = [candidate["display_name"] for candidate in artifact["ranked_candidates"]]
    assert names == ["Video And Email", "Video Only", "Email Strong Metadata"]
    assert artifact["ranking_policy"]["ordering"][0]["signal"] == "enrichment_score"
    assert artifact["ranking_policy"]["scoring"]["implemented"] is True
    assert artifact["provenance"]["scoring_performed"] is True

    first = artifact["ranked_candidates"][0]
    assert first["enrichment_score"] == 80
    assert first["provenance"]["scoring_performed"] is True
    assert first["provenance"]["scoring_policy_id"] == (
        "deterministic_guest_enrichment_score_v1"
    )
    assert "enrichment_score_components" in first


def test_no_external_calls_or_drafts_occur():
    artifact = materialize_guest_candidate_ranking(
        candidate_artifact=_artifact([_candidate("One")])
    ).artifact
    provenance = artifact["provenance"]
    assert provenance["web_search_executed"] is False
    assert provenance["browser_api_called"] is False
    assert provenance["search_api_called"] is False
    assert provenance["cloud_model_called"] is False
    assert provenance["external_adapter_called"] is False
    assert provenance["draft_generated"] is False
    assert provenance["notification_performed"] is False
    assert provenance["delivery_performed"] is False


def test_runtime_ranking_module_remains_domain_neutral():
    source = (ROOT / "runtime" / "workflows" / "ranking.py").read_text(
        encoding="utf-8"
    )
    lowered = source.lower()
    forbidden = (
        "agents.alexis",
        "alexis_guest_db",
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
        "search_web(",
    )
    assert all(term not in lowered for term in forbidden)


def test_malformed_input_fails_closed_without_ranking_execution():
    result = materialize_guest_candidate_ranking(candidate_artifact=None)
    assert result.materialized is False
    assert result.transition_outcome == "failure"
    assert result.artifact["ranking_executed"] is False
    assert result.skipped_reasons == ("candidate_artifact_missing",)


def main():
    test_output_artifact_is_ranked_guest_candidate_list()
    test_candidates_with_email_or_contact_rank_before_candidates_without_email_contact()
    test_candidates_with_video_presence_rank_before_email_only_candidates()
    test_email_contact_improves_ranking_after_video_presence()
    test_stable_ordering_is_preserved_when_signals_are_equal()
    test_rank_reason_codes_are_emitted_without_prose_explanations()
    test_enrichment_score_is_deterministic_and_metadata_only()
    test_no_external_calls_or_drafts_occur()
    test_runtime_ranking_module_remains_domain_neutral()
    test_malformed_input_fails_closed_without_ranking_execution()
    print("PASS guest candidate ranking materialization")


if __name__ == "__main__":
    main()
