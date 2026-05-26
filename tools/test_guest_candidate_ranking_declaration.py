import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.workflows.declarations import (  # noqa: E402
    build_dry_run_workflow_plan,
    resolve_workflow_declaration,
)


WORKFLOW_PATH = (
    ROOT / "agents" / "alexis" / "workflows" / "guest_booking_outreach.json"
)


def _workflow():
    return resolve_workflow_declaration(
        agent_name="alexis",
        workflow_id="guest_booking_outreach",
        root=ROOT,
    )


def _ranking_step():
    for step in _workflow().steps:
        if step.semantic_operation == "rank_guest_candidates":
            return step
    raise AssertionError("missing rank_guest_candidates operation")


def _raw_ranking_step():
    data = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    for step in data["steps"]:
        if step.get("operation_id") == "rank_guest_candidates":
            return step
    raise AssertionError("missing raw rank_guest_candidates operation")


def test_ranking_operation_declaration_loads():
    step = _ranking_step()
    assert step.step_kind == "selection"
    assert step.operation_kind == "rank_candidates"
    assert step.semantic_operation == "rank_guest_candidates"
    assert step.placeholder is False
    assert step.governance_state == "audit_only"


def test_declares_expected_operation_id_and_kind():
    raw = _raw_ranking_step()
    assert raw["operation_id"] == "rank_guest_candidates"
    assert raw["operation_kind"] == "rank_candidates"
    assert raw["semantic_operation"] == "rank_guest_candidates"


def test_input_artifact_ref_is_guest_candidate_list():
    step = _ranking_step()
    assert step.input_refs == ("artifact:guest_candidate_list:guest_retrieval",)
    assert step.constraints["input_artifact_type"] == "guest_candidate_list"


def test_output_artifact_ref_is_ranked_guest_candidate_list():
    step = _ranking_step()
    assert step.output_ref == "artifact:ranked_guest_candidate_list:rank_guest_candidates"
    assert step.output_type == "artifact"
    assert step.produces_artifact_type == "ranked_guest_candidate_list"
    assert step.constraints["output_artifact_type"] == "ranked_guest_candidate_list"


def test_ranking_signals_are_declarative_metadata_only():
    constraints = _ranking_step().constraints
    signals = constraints["ranking_signals"]
    signal_ids = {signal["signal_id"] for signal in signals}
    ordered_signal_ids = [signal["signal_id"] for signal in signals]
    assert constraints["signals_declarative_metadata_only"] is True
    assert all(signal["metadata_only"] is True for signal in signals)
    assert "has_email_contact" in signal_ids
    assert "email_refs" in signal_ids
    assert "has_video_presence" in signal_ids
    assert "video_presence_refs" in signal_ids
    assert "on_air_suitability_signals" in signal_ids
    assert ordered_signal_ids[:3] == [
        "has_video_presence",
        "video_presence_refs",
        "on_air_suitability_signals",
    ]


def test_bounded_deterministic_ranking_execution_is_declared():
    step = _ranking_step()
    plan = build_dry_run_workflow_plan(_workflow())
    assert plan.execution_performed is False
    assert step.constraints["declaration_only"] is False
    assert step.constraints["ranking_execution_allowed"] is True
    assert step.constraints["ranking_logic_implemented"] is True
    assert step.constraints["scoring_implemented"] is True
    assert step.constraints["ranking_policy"] == {
        "policy_id": "deterministic_guest_enrichment_score_v1",
        "version": "v1",
        "deterministic": True,
        "external_calls_allowed": False,
        "prose_explanations_allowed": False,
    }


def test_no_web_draft_or_delivery_execution_occurs():
    step = _ranking_step()
    serialized = repr(step.constraints).lower()
    assert "web_search" not in serialized
    assert "draft_generated" not in serialized
    assert "delivery_performed" not in serialized
    assert "send_email" not in serialized
    assert step.requires_approval is False


def test_runtime_parser_stays_domain_neutral():
    source = (ROOT / "runtime" / "workflows" / "declarations.py").read_text(
        encoding="utf-8"
    )
    lowered = source.lower()
    forbidden = (
        "agents.alexis",
        "alexis_guest_db",
        "rank_guest_candidates",
        "guest_candidate_list",
        "ranked_guest_candidate_list",
        "telegram",
        "gateway",
        "smtp",
        "gmail",
        "mailgun",
        "send_email(",
    )
    assert all(term not in lowered for term in forbidden)


def main():
    test_ranking_operation_declaration_loads()
    test_declares_expected_operation_id_and_kind()
    test_input_artifact_ref_is_guest_candidate_list()
    test_output_artifact_ref_is_ranked_guest_candidate_list()
    test_ranking_signals_are_declarative_metadata_only()
    test_bounded_deterministic_ranking_execution_is_declared()
    test_no_web_draft_or_delivery_execution_occurs()
    test_runtime_parser_stays_domain_neutral()
    print("PASS guest candidate ranking declaration")


if __name__ == "__main__":
    main()
