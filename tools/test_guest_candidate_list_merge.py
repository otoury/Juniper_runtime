import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.workflows.candidate_merge import (  # noqa: E402
    GUEST_CANDIDATE_LIST_ARTIFACT,
    materialize_guest_candidate_list_merge,
)


def _artifact(source_scope, candidates, *, artifact_ref=None):
    artifact = {
        "artifact_type": GUEST_CANDIDATE_LIST_ARTIFACT,
        "source_scope": source_scope,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "provenance": {
            "source_scope": source_scope,
            "retrieval_executed": source_scope == "db",
            "web_search_executed": False,
        },
    }
    if artifact_ref is not None:
        artifact["artifact_ref"] = artifact_ref
    return artifact


def _db_candidate(candidate_id, name, *, email=None, canonical_name=None):
    candidate = {
        "candidate_id": candidate_id,
        "display_name": name,
        "source_record_id": f"db:{candidate_id}",
        "provenance": {"adapter_id": "local_fixture"},
    }
    if email is not None:
        candidate["email"] = email
    if canonical_name is not None:
        candidate["canonical_name"] = canonical_name
    return candidate


def _web_candidate(name, *, email=None, canonical_name=None, url=None):
    candidate = {
        "display_name": name,
        "source_url": url or f"https://example.invalid/{name}",
        "provenance": {"discovery_executed": False},
    }
    if email is not None:
        candidate["email"] = email
    if canonical_name is not None:
        candidate["canonical_name"] = canonical_name
    return candidate


def test_db_only_candidate_list_merges_safely():
    result = materialize_guest_candidate_list_merge(
        candidate_artifacts=[
            _artifact(
                "db",
                [_db_candidate("g1", "Guest One")],
                artifact_ref="artifact:guest_candidate_list:search_db",
            )
        ]
    )
    artifact = result.artifact
    assert result.materialized is True
    assert artifact["artifact_type"] == GUEST_CANDIDATE_LIST_ARTIFACT
    assert artifact["candidate_count"] == 1
    assert artifact["source_scopes"] == ["db"]
    assert artifact["merge_executed"] is True


def test_guest_db_alias_is_normalized_to_db_boundary_scope():
    artifact = materialize_guest_candidate_list_merge(
        candidate_artifacts=[_artifact("guest_db", [_db_candidate("g1", "Guest One")])]
    ).artifact
    assert artifact["source_scopes"] == ["db"]
    assert artifact["candidates"][0]["source_scope"] == "db"


def test_web_only_candidate_list_merges_safely():
    result = materialize_guest_candidate_list_merge(
        candidate_artifacts=[
            _artifact(
                "web",
                [_web_candidate("Guest Web", canonical_name="guest web")],
                artifact_ref="artifact:guest_candidate_list:search_web",
            )
        ]
    )
    artifact = result.artifact
    assert result.materialized is True
    assert artifact["candidate_count"] == 1
    assert artifact["source_scopes"] == ["web"]
    assert artifact["provenance"]["web_search_executed"] is False


def test_db_plus_web_candidate_lists_merge_into_one_typed_artifact():
    artifact = materialize_guest_candidate_list_merge(
        candidate_artifacts=[
            _artifact("db", [_db_candidate("g1", "Guest One")]),
            _artifact("web", [_web_candidate("Guest Two", email="two@example.test")]),
        ],
        artifact_refs=(
            "artifact:guest_candidate_list:search_db",
            "artifact:guest_candidate_list:search_web",
        ),
    ).artifact
    assert artifact["artifact_type"] == GUEST_CANDIDATE_LIST_ARTIFACT
    assert artifact["candidate_count"] == 2
    assert artifact["source_scopes"] == ["db", "web"]
    assert artifact["merged_from_artifact_refs"] == [
        "artifact:guest_candidate_list:search_db",
        "artifact:guest_candidate_list:search_web",
    ]


def test_duplicate_candidate_merges_preserve_provenance_and_evidence():
    artifact = materialize_guest_candidate_list_merge(
        candidate_artifacts=[
            _artifact(
                "db",
                [
                    _db_candidate(
                        "g1",
                        "Guest One",
                        email="guest@example.test",
                        canonical_name="guest one",
                    )
                ],
            ),
            _artifact(
                "web",
                [
                    _web_candidate(
                        "Guest One",
                        email="GUEST@example.test",
                        canonical_name="Guest One",
                    )
                ],
            ),
        ],
        artifact_refs=(
            "artifact:guest_candidate_list:search_db",
            "artifact:guest_candidate_list:search_web",
        ),
    ).artifact
    assert artifact["candidate_count"] == 1
    assert len(artifact["duplicate_groups"]) == 1
    candidate = artifact["candidates"][0]
    assert candidate["source_scopes"] == ["db", "web"]
    assert candidate["artifact_refs"] == [
        "artifact:guest_candidate_list:search_db",
        "artifact:guest_candidate_list:search_web",
    ]
    assert len(candidate["source_lineage"]) == 2
    assert len(candidate["duplicate_evidence"]) == 2
    assert candidate["provenance"]["source_lineage"][0]["source_scope"] == "db"


def test_duplicate_candidate_merges_preserve_enrichment_metadata():
    artifact = materialize_guest_candidate_list_merge(
        candidate_artifacts=[
            _artifact(
                "db",
                [
                    _db_candidate(
                        "g1",
                        "Guest One",
                        email="guest@example.test",
                        canonical_name="guest one",
                    )
                ],
            ),
            _artifact(
                "web",
                [
                    {
                        **_web_candidate(
                            "Guest One",
                            email="GUEST@example.test",
                            canonical_name="Guest One",
                        ),
                        "has_email_contact": True,
                        "email_refs": ["artifact:contact:guest-one:email"],
                        "has_video_presence": True,
                        "video_presence_refs": ["artifact:video:guest-one:clip"],
                        "contact_confidence": 0.7,
                        "on_air_suitability_signals": ["camera_ready"],
                    }
                ],
            ),
        ],
    ).artifact
    candidate = artifact["candidates"][0]
    assert "has_email_contact" not in candidate
    assert "email_refs" not in candidate
    assert "has_video_presence" not in candidate
    assert "video_presence_refs" not in candidate
    assert "contact_confidence" not in candidate
    assert "on_air_suitability_signals" not in candidate
    assert candidate["merge_receipt_refs"] == ["receipt:guest_candidate_merge:0"]
    receipt = artifact["guest_candidate_merge_receipts"][0]
    assert receipt["automatic_contact_promotion_performed"] is False
    assert receipt["external_overwrote_local_db"] is False
    assert artifact["provenance"]["ranking_performed"] is False


def test_malformed_enrichment_metadata_is_not_merged():
    artifact = materialize_guest_candidate_list_merge(
        candidate_artifacts=[
            _artifact(
                "web",
                [
                    {
                        **_web_candidate("Guest Web"),
                        "has_email_contact": "yes",
                    }
                ],
            )
        ]
    ).artifact
    assert artifact["candidate_count"] == 0
    assert artifact["provenance"]["skipped_reasons"] == [
        "candidate_enrichment_metadata_invalid"
    ]


def test_candidate_order_is_stable_and_not_ranking_based():
    artifact = materialize_guest_candidate_list_merge(
        candidate_artifacts=[
            _artifact(
                "db",
                [
                    _db_candidate("g2", "Second"),
                    _db_candidate("g1", "First"),
                ],
            ),
            _artifact(
                "web",
                [
                    _web_candidate("Third", canonical_name="third"),
                ],
            ),
        ]
    ).artifact
    assert [candidate["display_name"] for candidate in artifact["candidates"]] == [
        "Second",
        "First",
        "Third",
    ]
    assert artifact["provenance"]["ranking_performed"] is False
    assert artifact["provenance"]["scoring_performed"] is False


def test_no_ranking_web_draft_notification_or_delivery_execution_occurs():
    artifact = materialize_guest_candidate_list_merge(
        candidate_artifacts=[_artifact("web", [_web_candidate("Guest Web")])]
    ).artifact
    provenance = artifact["provenance"]
    assert provenance["ranking_performed"] is False
    assert provenance["scoring_performed"] is False
    assert provenance["selection_performed"] is False
    assert provenance["web_search_executed"] is False
    assert provenance["browser_api_called"] is False
    assert provenance["search_api_called"] is False
    assert provenance["cloud_model_called"] is False
    assert provenance["draft_generated"] is False
    assert provenance["notification_performed"] is False
    assert provenance["delivery_performed"] is False


def test_runtime_merge_module_has_no_alexis_imports_or_external_calls():
    source = (ROOT / "runtime" / "workflows" / "candidate_merge.py").read_text(
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


def main():
    test_db_only_candidate_list_merges_safely()
    test_guest_db_alias_is_normalized_to_db_boundary_scope()
    test_web_only_candidate_list_merges_safely()
    test_db_plus_web_candidate_lists_merge_into_one_typed_artifact()
    test_duplicate_candidate_merges_preserve_provenance_and_evidence()
    test_duplicate_candidate_merges_preserve_enrichment_metadata()
    test_malformed_enrichment_metadata_is_not_merged()
    test_candidate_order_is_stable_and_not_ranking_based()
    test_no_ranking_web_draft_notification_or_delivery_execution_occurs()
    test_runtime_merge_module_has_no_alexis_imports_or_external_calls()
    print("PASS guest candidate list merge")


if __name__ == "__main__":
    main()
