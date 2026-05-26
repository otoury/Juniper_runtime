import sys
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.workflows.declarations import resolve_workflow_declaration  # noqa: E402
from runtime.workflows.external_discovery import (  # noqa: E402
    EXTERNAL_GUEST_DISCOVERY_ACTION,
    GUEST_CANDIDATE_LIST_ARTIFACT,
    materialize_external_guest_discovery,
)
from runtime.workflows.transitions import resolve_workflow_transition  # noqa: E402


def _workflow(workflow_id):
    return resolve_workflow_declaration(
        agent_name="alexis",
        workflow_id=workflow_id,
        root=ROOT,
    )


def _web_step():
    return _workflow("search_web").steps[0]


def _combined_step(operation_id):
    for step in _workflow("search_db_then_web").steps:
        if step.semantic_operation == operation_id:
            return step
    raise AssertionError(f"missing operation {operation_id}")


def _materialized(step=None, governance_state=None):
    return materialize_external_guest_discovery(
        workflow_id="search_web",
        step=step or _web_step(),
        governance_state=governance_state,
        artifact_refs=(
            "artifact:guest_search_request:active",
            "artifact:guest_candidate_list:search_db",
            "artifact:guest_candidate_adequacy:search_db",
        ),
        action_refs=("action:operator_notification:web_fallback",),
    )


def test_search_web_materializes_typed_discovery_descriptor():
    result = _materialized()
    action = result.action
    assert result.materialized is True
    assert action["action_type"] == EXTERNAL_GUEST_DISCOVERY_ACTION
    assert action["workflow_id"] == "search_web"
    assert action["operation_id"] == "web_guest_discovery_placeholder"
    assert action["governance_state"] == "audit_only"


def test_descriptor_source_scope_is_web():
    assert _materialized().action["source_scope"] == "web"


def test_descriptor_never_executes_discovery():
    action = _materialized().action
    assert action["discovery_executed"] is False
    assert action["provenance"]["web_search_executed"] is False
    assert action["provenance"]["browser_api_called"] is False
    assert action["provenance"]["search_api_called"] is False
    assert action["provenance"]["cloud_model_called"] is False


def test_disabled_or_blocked_governance_fails_closed():
    disabled = _materialized(step=replace(_web_step(), governance_state="disabled"))
    blocked = _materialized(governance_state="blocked")
    assert disabled.materialized is False
    assert disabled.action is None
    assert disabled.skipped_reasons == ("web_discovery_governance_closed",)
    assert blocked.materialized is False
    assert blocked.action is None


def test_audit_only_materializes_planning_descriptor_without_execution():
    action = _materialized(governance_state="audit_only").action
    assert action["governance_state"] == "audit_only"
    assert action["execution_allowed"] is False
    assert action["discovery_executed"] is False


def test_enabled_governance_materializes_but_still_does_not_execute():
    action = _materialized(governance_state="enabled").action
    assert action["governance_state"] == "enabled"
    assert action["execution_allowed"] is False
    assert action["discovery_executed"] is False
    assert action["provenance"]["external_adapter_called"] is False


def test_expected_output_artifact_is_typed_web_candidate_list():
    artifact = _materialized().expected_output_artifact
    assert artifact["artifact_type"] == GUEST_CANDIDATE_LIST_ARTIFACT
    assert artifact["source_scope"] == "web"
    assert artifact["candidates"] == []
    assert artifact["discovery_executed"] is False
    assert artifact["provenance"]["web_search_executed"] is False


def test_future_signal_placeholders_are_metadata_only():
    action = _materialized().action
    expected = {
        "has_email_contact",
        "email_refs",
        "has_video_presence",
        "video_presence_refs",
        "contact_confidence",
        "on_air_suitability_signals",
    }
    assert set(action["metadata"]["future_enrichment_signals"]) == expected
    assert action["metadata"]["signal_placeholders_only"] is True
    assert action["metadata"]["ranking_performed"] is False
    assert action["metadata"]["selection_performed"] is False


def test_no_browser_search_cloud_or_external_adapter_imports_or_calls():
    source = (ROOT / "runtime" / "workflows" / "external_discovery.py").read_text(
        encoding="utf-8"
    )
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
        "google",
        "bing",
        "duckduckgo",
        "telegram",
        "smtp",
        "gmail",
        "mailgun",
        "send_email(",
    )
    assert all(term not in lowered for term in forbidden)


def test_search_db_then_web_reaches_search_web_without_execution():
    workflow = _workflow("search_db_then_web")
    resolution = resolve_workflow_transition(
        workflow=workflow,
        current_operation_id="notify_web_search_fallback",
        result_status="success",
    )
    run_web = _combined_step("run_search_web")
    web_descriptor = _materialized()
    assert resolution.resolved is True
    assert resolution.next_operation_id == "run_search_web"
    assert run_web.workflow_ref == "search_web"
    assert web_descriptor.action["discovery_executed"] is False


def test_runtime_remains_domain_neutral_without_alexis_imports():
    source = (ROOT / "runtime" / "workflows" / "external_discovery.py").read_text(
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
    test_search_web_materializes_typed_discovery_descriptor()
    test_descriptor_source_scope_is_web()
    test_descriptor_never_executes_discovery()
    test_disabled_or_blocked_governance_fails_closed()
    test_audit_only_materializes_planning_descriptor_without_execution()
    test_enabled_governance_materializes_but_still_does_not_execute()
    test_expected_output_artifact_is_typed_web_candidate_list()
    test_future_signal_placeholders_are_metadata_only()
    test_no_browser_search_cloud_or_external_adapter_imports_or_calls()
    test_search_db_then_web_reaches_search_web_without_execution()
    test_runtime_remains_domain_neutral_without_alexis_imports()
    print("PASS web guest discovery materialization")


if __name__ == "__main__":
    main()
