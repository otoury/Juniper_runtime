import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.workflows.adequacy import (  # noqa: E402
    materialize_guest_candidate_adequacy,
)
from runtime.workflows.declarations import resolve_workflow_declaration  # noqa: E402
from runtime.workflows.notification import (  # noqa: E402
    OPERATOR_NOTIFICATION_ACTION,
    materialize_operator_notification,
)
from runtime.workflows.transitions import resolve_workflow_transition  # noqa: E402


def _workflow():
    return resolve_workflow_declaration(
        agent_name="alexis",
        workflow_id="search_db_then_web",
        root=ROOT,
    )


def _step(operation_id):
    for step in _workflow().steps:
        if step.semantic_operation == operation_id:
            return step
    raise AssertionError(f"missing operation {operation_id}")


def _candidate_artifact():
    return {
        "artifact_type": "guest_candidate_list",
        "candidate_count": 2,
        "candidates": [
            {
                "candidate_id": "g1",
                "display_name": "Dr. Ada Stone",
            },
            {
                "candidate_id": "g2",
                "display_name": "Prof. Ben Hale",
            },
        ],
    }


def _adequacy_artifact():
    return materialize_guest_candidate_adequacy(
        candidate_artifact=_candidate_artifact(),
        step=_step("assess_guest_candidate_adequacy"),
        min_required_candidates=3,
    ).artifact


def _notification():
    return materialize_operator_notification(
        step=_step("notify_web_search_fallback"),
        adequacy_artifact=_adequacy_artifact(),
        candidate_artifact=_candidate_artifact(),
        artifact_refs=(
            "artifact:guest_candidate_list:search_db",
            "artifact:guest_candidate_adequacy:search_db",
        ),
    )


def test_notify_and_continue_declaration_includes_message_template():
    step = _step("notify_web_search_fallback")
    template = step.constraints["message_template"]
    assert step.operation_kind == "notify_and_continue"
    assert template["template_id"] == (
        "db_guest_candidates_inadequate_web_fallback_v1"
    )
    assert "candidate_count" in template["placeholders"]
    assert "min_required_candidates" in template["placeholders"]
    assert "candidate_names" in template["placeholders"]


def test_materialization_uses_declared_template_not_invented_prose():
    result = _notification()
    template = _step("notify_web_search_fallback").constraints[
        "message_template"
    ]
    action = result.action
    assert result.materialized is True
    assert action["message"]["template_id"] == template["template_id"]
    assert action["provenance"]["declared_template_used"] is True
    assert action["provenance"]["runtime_prose_invented"] is False
    assert action["message"]["rendered_text"].startswith("I found ")


def test_candidate_count_bound_from_typed_adequacy_result():
    action = _notification().action
    assert action["message"]["bindings"]["candidate_count"] == "2"
    assert "I found 2 database guest candidates" in action["message"]["text"]


def test_min_required_candidates_bound_from_typed_adequacy_result():
    action = _notification().action
    assert action["message"]["bindings"]["min_required_candidates"] == "3"
    assert "minimum of 3" in action["message"]["text"]


def test_candidate_names_from_guest_candidate_list_are_included():
    text = _notification().action["message"]["text"]
    assert "Dr. Ada Stone" in text
    assert "Prof. Ben Hale" in text


def test_notification_action_is_non_blocking_and_non_suspending():
    action = _notification().action
    assert action["action_type"] == OPERATOR_NOTIFICATION_ACTION
    assert action["operation_kind"] == "notify_and_continue"
    assert action["blocking"] is False
    assert action["suspending"] is False
    assert action["notification_prepared"] is True


def test_requires_approval_false():
    assert _notification().action["requires_approval"] is False


def test_notification_sent_false():
    action = _notification().action
    assert action["notification_sent"] is False
    assert action["provenance"]["notification_sent"] is False


def test_no_external_delivery_adapter_imported_or_called():
    source = (ROOT / "runtime" / "workflows" / "notification.py").read_text(
        encoding="utf-8"
    )
    lowered = source.lower()
    forbidden = (
        "telegram",
        "smtp",
        "gmail",
        "mailgun",
        "requests.",
        "urllib",
        "send_email(",
    )
    assert all(term not in lowered for term in forbidden)


def test_workflow_can_continue_to_search_web_declaratively():
    materialized = _notification()
    resolution = resolve_workflow_transition(
        workflow=_workflow(),
        current_operation_id="notify_web_search_fallback",
        result_status=materialized.transition_outcome,
    )
    assert materialized.transition_outcome == "success"
    assert resolution.resolved is True
    assert resolution.next_operation_id == "run_search_web"


def test_web_search_is_still_not_executed():
    action = _notification().action
    assert action["provenance"]["web_search_executed"] is False
    assert action["provenance"]["ranking_performed"] is False
    assert action["provenance"]["draft_generated"] is False
    assert action["provenance"]["delivery_performed"] is False


def test_runtime_remains_domain_neutral_except_typed_field_binding():
    source = (ROOT / "runtime" / "workflows" / "notification.py").read_text(
        encoding="utf-8"
    )
    lowered = source.lower()
    forbidden = (
        "agents.alexis",
        "alexis_guest_db",
        "newsroom",
        "telegram",
        "gateway",
        "smtp",
        "gmail",
        "mailgun",
    )
    assert all(term not in lowered for term in forbidden)


def main():
    test_notify_and_continue_declaration_includes_message_template()
    test_materialization_uses_declared_template_not_invented_prose()
    test_candidate_count_bound_from_typed_adequacy_result()
    test_min_required_candidates_bound_from_typed_adequacy_result()
    test_candidate_names_from_guest_candidate_list_are_included()
    test_notification_action_is_non_blocking_and_non_suspending()
    test_requires_approval_false()
    test_notification_sent_false()
    test_no_external_delivery_adapter_imported_or_called()
    test_workflow_can_continue_to_search_web_declaratively()
    test_web_search_is_still_not_executed()
    test_runtime_remains_domain_neutral_except_typed_field_binding()
    print("PASS notify and continue materialization")


if __name__ == "__main__":
    main()
