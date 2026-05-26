import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.workflows.adequacy import (  # noqa: E402
    GUEST_CANDIDATE_ADEQUACY_ARTIFACT,
    materialize_guest_candidate_adequacy,
)
from runtime.workflows.declarations import resolve_workflow_declaration  # noqa: E402
from runtime.workflows.transitions import resolve_workflow_transition  # noqa: E402


def _workflow():
    return resolve_workflow_declaration(
        agent_name="alexis",
        workflow_id="search_db_then_web",
        root=ROOT,
    )


def _assessment_step():
    for step in _workflow().steps:
        if step.semantic_operation == "assess_guest_candidate_adequacy":
            return step
    raise AssertionError("missing adequacy assessment step")


def _candidate_artifact(count, candidates=None):
    if candidates is None:
        candidates = [
            {
                "candidate_id": f"guest-{index}",
                "display_name": f"Guest {index}",
            }
            for index in range(count)
        ]
    return {
        "artifact_type": "guest_candidate_list",
        "workflow_id": "search_db",
        "step_id": "db_guest_retrieval",
        "candidate_count": count,
        "candidates": candidates,
        "provenance": {
            "retrieval_executed": False,
        },
    }


def test_accepts_typed_guest_candidate_list_artifact():
    result = materialize_guest_candidate_adequacy(
        candidate_artifact=_candidate_artifact(1),
        step=_assessment_step(),
    )
    assert result.materialized is True
    assert result.artifact["artifact_type"] == GUEST_CANDIDATE_ADEQUACY_ARTIFACT
    assert result.artifact["candidate_count"] == 1


def test_candidate_count_at_or_above_minimum_is_adequate():
    result = materialize_guest_candidate_adequacy(
        candidate_artifact=_candidate_artifact(2),
        step=_assessment_step(),
        min_required_candidates=2,
    )
    assert result.artifact["adequate"] is True
    assert result.artifact["outcome"] == "adequate"
    assert result.transition_outcome == "success"


def test_candidate_count_below_minimum_is_inadequate():
    result = materialize_guest_candidate_adequacy(
        candidate_artifact=_candidate_artifact(1),
        step=_assessment_step(),
        min_required_candidates=2,
    )
    assert result.artifact["adequate"] is False
    assert result.artifact["outcome"] == "inadequate"
    assert result.transition_outcome == "inadequate"


def test_empty_candidate_list_is_inadequate():
    result = materialize_guest_candidate_adequacy(
        candidate_artifact=_candidate_artifact(0, candidates=[]),
        step=_assessment_step(),
    )
    assert result.artifact["candidate_count"] == 0
    assert result.artifact["adequate"] is False
    assert result.artifact["outcome"] == "inadequate"


def test_malformed_or_missing_artifact_fails_safely_unknown():
    missing = materialize_guest_candidate_adequacy(
        candidate_artifact=None,
        step=_assessment_step(),
    )
    malformed = materialize_guest_candidate_adequacy(
        candidate_artifact={"artifact_type": "email_draft"},
        step=_assessment_step(),
    )
    assert missing.materialized is False
    assert missing.artifact["outcome"] == "unknown"
    assert missing.artifact["adequate"] is None
    assert missing.transition_outcome == "failure"
    assert malformed.materialized is False
    assert malformed.skipped_reasons == ("unexpected_candidate_artifact_type",)


def test_result_artifact_type_is_guest_candidate_adequacy():
    artifact = materialize_guest_candidate_adequacy(
        candidate_artifact=_candidate_artifact(1),
        step=_assessment_step(),
    ).artifact
    assert artifact["artifact_type"] == "guest_candidate_adequacy"
    assert artifact["result_type"] == "guest_candidate_adequacy"


def test_result_is_structured_not_prose():
    artifact = materialize_guest_candidate_adequacy(
        candidate_artifact=_candidate_artifact(1),
        step=_assessment_step(),
    ).artifact
    assert isinstance(artifact, dict)
    assert not isinstance(artifact, str)
    assert "Subject:" not in repr(artifact)
    assert "Hi " not in repr(artifact)
    assert "draft_text" not in repr(artifact)


def test_required_and_future_email_video_signals_preserved_not_scored():
    artifact = materialize_guest_candidate_adequacy(
        candidate_artifact=_candidate_artifact(1),
        step=_assessment_step(),
    ).artifact
    assert artifact["required_signals"] == [
        "has_email_contact",
        "has_video_presence",
    ]
    assert set(artifact["future_enrichment_signals"]) == {
        "has_email_contact",
        "email_refs",
        "has_video_presence",
        "video_presence_refs",
        "contact_confidence",
        "on_air_suitability_signals",
    }
    assert artifact["provenance"]["required_signals_scored"] is False
    assert artifact["provenance"]["ranking_performed"] is False


def test_inadequate_outcome_maps_to_on_inadequate_transition_path():
    materialized = materialize_guest_candidate_adequacy(
        candidate_artifact=_candidate_artifact(0),
        step=_assessment_step(),
    )
    resolution = resolve_workflow_transition(
        workflow=_workflow(),
        current_operation_id="assess_guest_candidate_adequacy",
        result_status=materialized.transition_outcome,
    )
    assert materialized.transition_outcome == "inadequate"
    assert resolution.resolved is True
    assert resolution.next_operation_id == "notify_web_search_fallback"


def test_no_web_ranking_draft_or_delivery_execution_occurs():
    result = materialize_guest_candidate_adequacy(
        candidate_artifact=_candidate_artifact(0),
        step=_assessment_step(),
    )
    artifact = result.artifact
    assert artifact["provenance"]["web_search_executed"] is False
    assert artifact["provenance"]["ranking_performed"] is False
    assert artifact["provenance"]["selection_performed"] is False
    assert artifact["provenance"]["draft_generated"] is False
    assert artifact["provenance"]["delivery_performed"] is False


def test_runtime_remains_domain_neutral_without_alexis_imports():
    source = (ROOT / "runtime" / "workflows" / "adequacy.py").read_text(
        encoding="utf-8"
    )
    lowered = source.lower()
    forbidden = (
        "agents.alexis",
        "alexis_guest_db",
        "telegram",
        "gateway",
        "smtp",
        "gmail",
        "mailgun",
        "send_email(",
        "web_search(",
    )
    assert all(term not in lowered for term in forbidden)


def main():
    test_accepts_typed_guest_candidate_list_artifact()
    test_candidate_count_at_or_above_minimum_is_adequate()
    test_candidate_count_below_minimum_is_inadequate()
    test_empty_candidate_list_is_inadequate()
    test_malformed_or_missing_artifact_fails_safely_unknown()
    test_result_artifact_type_is_guest_candidate_adequacy()
    test_result_is_structured_not_prose()
    test_required_and_future_email_video_signals_preserved_not_scored()
    test_inadequate_outcome_maps_to_on_inadequate_transition_path()
    test_no_web_ranking_draft_or_delivery_execution_occurs()
    test_runtime_remains_domain_neutral_without_alexis_imports()
    print("PASS guest candidate adequacy materialization")


if __name__ == "__main__":
    main()
