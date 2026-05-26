import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.workflows.candidate_merge import (  # noqa: E402
    ENRICHMENT_METADATA_FIELDS,
    GUEST_CANDIDATE_LIST_ARTIFACT,
    materialize_guest_candidate_list_merge,
    validate_guest_candidate_enrichment_metadata,
)


def _artifact(candidate):
    return {
        "artifact_type": GUEST_CANDIDATE_LIST_ARTIFACT,
        "source_scope": "web",
        "candidate_count": 1,
        "candidates": [candidate],
        "provenance": {
            "web_search_executed": False,
            "cloud_model_called": False,
        },
    }


def test_candidate_without_enrichment_metadata_remains_valid():
    candidate = {
        "candidate_id": "guest-1",
        "display_name": "Guest One",
    }
    assert validate_guest_candidate_enrichment_metadata(candidate) == ()


def test_candidate_with_email_contact_metadata_validates():
    candidate = {
        "candidate_id": "guest-1",
        "display_name": "Guest One",
        "has_email_contact": True,
        "email_refs": ["artifact:contact:guest-1:email"],
        "contact_confidence": 0.8,
    }
    assert validate_guest_candidate_enrichment_metadata(candidate) == ()


def test_candidate_with_video_presence_metadata_validates():
    candidate = {
        "candidate_id": "guest-1",
        "display_name": "Guest One",
        "has_video_presence": True,
        "video_presence_refs": ["artifact:video:guest-1:clip"],
        "on_air_suitability_signals": ["camera_ready", "topic_relevant"],
    }
    assert validate_guest_candidate_enrichment_metadata(candidate) == ()


def test_malformed_enrichment_metadata_fails_safely():
    malformed = {
        "candidate_id": "guest-1",
        "display_name": "Guest One",
        "has_email_contact": "yes",
        "email_refs": "artifact:contact:guest-1:email",
        "has_video_presence": 1,
        "video_presence_refs": [""],
        "contact_confidence": 2,
        "on_air_suitability_signals": ["camera_ready", 7],
    }
    errors = validate_guest_candidate_enrichment_metadata(malformed)
    assert errors == (
        "has_email_contact_not_boolean",
        "has_video_presence_not_boolean",
        "email_refs_not_string_list",
        "video_presence_refs_not_string_list",
        "contact_confidence_not_unit_interval",
        "on_air_suitability_signals_not_string_list",
    )

    result = materialize_guest_candidate_list_merge(
        candidate_artifacts=[_artifact(malformed)]
    )
    assert result.materialized is True
    assert result.artifact["candidate_count"] == 0
    assert result.skipped_reasons == ("candidate_enrichment_metadata_invalid",)


def test_enrichment_metadata_schema_fields_are_declared():
    assert ENRICHMENT_METADATA_FIELDS == (
        "has_email_contact",
        "email_refs",
        "has_video_presence",
        "video_presence_refs",
        "contact_confidence",
        "on_air_suitability_signals",
    )


def test_no_external_calls_occur_for_enrichment_validation():
    source = (ROOT / "runtime" / "workflows" / "candidate_merge.py").read_text(
        encoding="utf-8"
    )
    lowered = source.lower()
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
        "search_web(",
    )
    assert all(term not in lowered for term in forbidden)


def main():
    test_candidate_without_enrichment_metadata_remains_valid()
    test_candidate_with_email_contact_metadata_validates()
    test_candidate_with_video_presence_metadata_validates()
    test_malformed_enrichment_metadata_fails_safely()
    test_enrichment_metadata_schema_fields_are_declared()
    test_no_external_calls_occur_for_enrichment_validation()
    print("PASS guest candidate enrichment metadata")


if __name__ == "__main__":
    main()
