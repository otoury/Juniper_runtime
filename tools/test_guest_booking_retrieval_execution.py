import sys
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.alexis.adapters.guest_db.bounded_entity_search_adapter import (  # noqa: E402
    execute_alexis_guest_bounded_entity_search,
)
from runtime.lookup.governance import LookupGovernancePolicy  # noqa: E402
from runtime.registries.lookup_capability_registry import (  # noqa: E402
    resolve_lookup_capability,
)
from runtime.workflows.declarations import resolve_workflow_declaration  # noqa: E402
from runtime.workflows.execution import execute_retrieval_action  # noqa: E402
from runtime.workflows.materialization import (  # noqa: E402
    GUEST_CANDIDATE_LIST_ARTIFACT,
    materialize_retrieval_action,
)


WORKFLOW_ID = "guest_booking_outreach"


class CountingGuestLookupAgent:
    def __init__(self):
        self.calls = 0

    def get_lookup_executor(self, lookup_request, lookup_capability=None):
        assert lookup_capability is not None
        assert "guest_db" in lookup_capability["adapter_owners"]
        assert lookup_request["source_scope"] in lookup_capability[
            "source_scopes"
        ]

        def _execute(request):
            self.calls += 1
            return execute_alexis_guest_bounded_entity_search(request)

        return _execute


class FailingLookupAgent:
    def __init__(self):
        self.calls = 0

    def get_lookup_executor(self, lookup_request, lookup_capability=None):
        self.calls += 1
        raise AssertionError("adapter should not be called")


def _workflow():
    return resolve_workflow_declaration(
        agent_name="alexis",
        workflow_id=WORKFLOW_ID,
        root=ROOT,
    )


def _action(**planner_overrides):
    planner_lookup = {
        "search_topic": "Family Practice Physician",
    }
    planner_lookup.update(planner_overrides)
    materialized = materialize_retrieval_action(
        workflow=_workflow(),
        planner_lookup=planner_lookup,
        root=ROOT,
    )
    assert materialized.action is not None
    return materialized.action


def _resolved_capability(state):
    resolved = resolve_lookup_capability(
        agent="alexis",
        shared_capability="discover_entities",
        root=ROOT,
    )
    assert not isinstance(resolved, Exception)
    return replace(
        resolved,
        governance=LookupGovernancePolicy(state=state),
    )


def test_disabled_retrieval_fails_closed_without_adapter_call():
    agent = FailingLookupAgent()
    receipt = execute_retrieval_action(
        action=_action(),
        agent=agent,
        root=ROOT,
        resolved_capability=_resolved_capability("disabled"),
    )
    assert receipt.execution_status == "closed"
    assert receipt.retrieval_executed is False
    assert receipt.execution_allowed is False
    assert receipt.artifact["candidate_count"] == 0
    assert agent.calls == 0


def test_audit_only_retrieval_does_not_execute_by_default():
    agent = FailingLookupAgent()
    receipt = execute_retrieval_action(
        action=_action(),
        agent=agent,
        root=ROOT,
    )
    assert receipt.execution_status == "closed"
    assert receipt.retrieval_executed is False
    assert receipt.execution_allowed is False
    assert "lookup_capability_audit_only" in receipt.skipped_reasons
    assert agent.calls == 0


def test_enabled_retrieval_calls_declared_lookup_adapter_path():
    agent = CountingGuestLookupAgent()
    receipt = execute_retrieval_action(
        action=_action(),
        agent=agent,
        root=ROOT,
        resolved_capability=_resolved_capability("enabled"),
    )
    assert agent.calls == 1
    assert receipt.execution_status == "executed"
    assert receipt.retrieval_executed is True
    assert receipt.execution_allowed is True
    assert receipt.artifact["artifact_type"] == GUEST_CANDIDATE_LIST_ARTIFACT
    assert receipt.artifact["candidate_count"] >= 1


def test_max_results_is_enforced_at_execution_boundary():
    agent = CountingGuestLookupAgent()
    receipt = execute_retrieval_action(
        action=_action(max_results=50),
        agent=agent,
        root=ROOT,
        resolved_capability=_resolved_capability("enabled"),
    )
    assert receipt.artifact["max_results"] == 5
    assert receipt.artifact["candidate_count"] <= 5


def test_artifact_contains_structured_candidates_not_prose():
    receipt = execute_retrieval_action(
        action=_action(),
        agent=CountingGuestLookupAgent(),
        root=ROOT,
        resolved_capability=_resolved_capability("enabled"),
    )
    artifact = receipt.artifact
    assert isinstance(artifact, dict)
    assert artifact["artifact_type"] == GUEST_CANDIDATE_LIST_ARTIFACT
    assert isinstance(artifact["candidates"], list)
    assert artifact["candidates"]
    assert isinstance(artifact["candidates"][0], dict)
    assert "display_name" in artifact["candidates"][0]
    assert not isinstance(artifact["candidates"], str)


def test_provenance_includes_workflow_action_source_and_governance():
    receipt = execute_retrieval_action(
        action=_action(),
        agent=CountingGuestLookupAgent(),
        root=ROOT,
        resolved_capability=_resolved_capability("enabled"),
    )
    provenance = receipt.provenance
    assert provenance["workflow_id"] == WORKFLOW_ID
    assert provenance["operation_id"] == "guest_retrieval"
    assert provenance["action_type"] == "bounded_guest_retrieval"
    assert provenance["source_binding_id"] == "alexis_guest_db"
    assert provenance["resource_id"] == "guest_db"
    assert provenance["adapter_id"] == "synthetic_guest_context"
    assert provenance["retrieval_executed"] is True
    assert provenance["execution_allowed"] is True
    assert provenance["governance_state"] == "enabled"


def test_no_ranking_draft_approval_or_delivery_executes():
    receipt = execute_retrieval_action(
        action=_action(),
        agent=CountingGuestLookupAgent(),
        root=ROOT,
        resolved_capability=_resolved_capability("enabled"),
    )
    assert receipt.step_id == "guest_retrieval"
    assert receipt.action_type == "bounded_guest_retrieval"
    assert receipt.artifact["artifact_type"] != "email_draft"
    assert all("ranking" not in key for key in receipt.artifact.keys())
    assert all("delivery" not in key for key in receipt.artifact.keys())


def test_runtime_workflow_execution_code_remains_domain_neutral():
    source = (ROOT / "runtime" / "workflows" / "execution.py").read_text(
        encoding="utf-8"
    )
    assert "agents.alexis" not in source
    assert "GUESTS_CANONICAL.csv" not in source
    assert "newsroom" not in source.lower()


def main():
    test_disabled_retrieval_fails_closed_without_adapter_call()
    test_audit_only_retrieval_does_not_execute_by_default()
    test_enabled_retrieval_calls_declared_lookup_adapter_path()
    test_max_results_is_enforced_at_execution_boundary()
    test_artifact_contains_structured_candidates_not_prose()
    test_provenance_includes_workflow_action_source_and_governance()
    test_no_ranking_draft_approval_or_delivery_executes()
    test_runtime_workflow_execution_code_remains_domain_neutral()
    print("PASS guest booking retrieval execution")


if __name__ == "__main__":
    main()
