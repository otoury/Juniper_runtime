import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.registries.scheduled_task_registry import (  # noqa: E402
    audit_agent_scheduled_task_declarations,
    audit_scheduled_task_declarations,
    audit_scheduled_task_declarations_from_path,
    load_scheduled_task_contracts,
    load_scheduled_task_declarations,
    validate_scheduled_task_declaration,
)


def valid_declaration():
    return {
        "id": "neutral_daily_workflow_check",
        "contract_id": "scheduled_workflow_task",
        "task_type": "scheduled_workflow_task",
        "schedule": {
            "type": "cron",
            "expression": "0 9 * * *",
            "timezone": "UTC",
        },
        "binding": {
            "agent": "neutral_agent",
            "workflow": "daily_check",
            "binding_id": "daily_check_binding",
        },
        "semantic_operation": {
            "operation_type": "WORKFLOW_MAINTENANCE",
            "capability_id": "neutral_daily_check",
            "produces_artifact": False,
            "external_side_effects_allowed": False,
            "memory_write_allowed": False,
            "requires_approval": False,
        },
        "governance_state": "audit_only",
        "execution_constraints": {
            "max_runtime_ms": 1000,
            "max_concurrent_runs": 1,
            "retry_policy": {
                "type": "none",
            },
        },
        "provenance_audit": {
            "required": True,
        },
        "fail_closed": {
            "missing_schedule": True,
            "missing_binding_reference": True,
            "unknown_governance_state": True,
            "forbidden_autonomous_fields": True,
        },
    }


def write_registry(root, declarations):
    source = ROOT / "agents/shared/semantics/scheduled_task_contracts.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    data["task_declarations"] = declarations
    path = Path(root) / "agents/shared/semantics/scheduled_task_contracts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def test_valid_scheduled_task_contract_loads():
    contracts = load_scheduled_task_contracts(root=ROOT)

    assert len(contracts) == 1
    contract = contracts[0]
    assert contract.id == "scheduled_workflow_task"
    assert contract.task_type == "scheduled_workflow_task"
    assert set(contract.schedule_types) == {"cron", "interval"}
    assert set(contract.governance_states) == {
        "enabled",
        "disabled",
        "audit_only",
    }


def test_valid_scheduled_task_declaration_loads():
    with TemporaryDirectory() as tmp:
        write_registry(tmp, [valid_declaration()])
        declarations, errors = audit_scheduled_task_declarations(root=tmp)

    assert errors == ()
    assert len(declarations) == 1
    metadata = declarations[0].to_metadata()
    assert metadata["task_type"] == "scheduled_workflow_task"
    assert metadata["schedule_type"] == "cron"
    assert metadata["agent"] == "neutral_agent"
    assert metadata["workflow"] == "daily_check"
    assert metadata["semantic_operation"] == {
        "operation_type": "WORKFLOW_MAINTENANCE",
        "capability_id": "neutral_daily_check",
        "produces_artifact": False,
        "external_side_effects_allowed": False,
        "memory_write_allowed": False,
        "requires_approval": False,
    }
    assert metadata["governance_state"] == "audit_only"
    assert metadata["retry_policy"] == "none"


def test_missing_schedule_fails_closed():
    declaration = valid_declaration()
    del declaration["schedule"]

    errors = validate_scheduled_task_declaration(declaration)

    assert errors
    assert any(error.field == "schedule" for error in errors)


def test_missing_agent_workflow_binding_fails_closed():
    declaration = valid_declaration()
    del declaration["binding"]

    errors = validate_scheduled_task_declaration(declaration)

    assert errors
    assert any(error.field == "binding" for error in errors)


def test_unknown_governance_state_fails_closed():
    declaration = valid_declaration()
    declaration["governance_state"] = "shadow"

    errors = validate_scheduled_task_declaration(declaration)

    assert errors
    assert any(error.field == "governance_state" for error in errors)


def test_missing_semantic_operation_metadata_fails_closed():
    declaration = valid_declaration()
    del declaration["semantic_operation"]

    errors = validate_scheduled_task_declaration(declaration)

    assert errors
    assert any(error.field == "semantic_operation" for error in errors)


def test_unknown_semantic_operation_type_fails_closed():
    declaration = valid_declaration()
    declaration["semantic_operation"]["operation_type"] = "BACKGROUND_PROMPT"

    errors = validate_scheduled_task_declaration(declaration)

    assert errors
    assert any(
        error.field == "semantic_operation.operation_type"
        for error in errors
    )


def test_semantic_side_effect_flags_are_validated():
    declaration = valid_declaration()
    declaration["semantic_operation"]["external_side_effects_allowed"] = "false"

    errors = validate_scheduled_task_declaration(declaration)

    assert errors
    assert any(
        error.field
        == "semantic_operation.external_side_effects_allowed"
        for error in errors
    )


def test_hidden_autonomous_and_self_mutating_fields_are_rejected():
    declaration = valid_declaration()
    declaration["autonomous_task_creation"] = True
    declaration["schedule"]["self_mutating_schedule"] = True
    declaration["binding"]["hidden_prompt"] = "prompt"

    errors = validate_scheduled_task_declaration(declaration)
    fields = {error.field for error in errors}

    assert "autonomous_task_creation" in fields
    assert "schedule.self_mutating_schedule" in fields
    assert "binding.hidden_prompt" in fields


def test_registry_validation_is_domain_neutral():
    source = (
        ROOT / "runtime/registries/scheduled_task_registry.py"
    ).read_text(encoding="utf-8")
    lowered = source.lower()

    forbidden = ("guest", "booking", "alexis_guest", "guest_db")
    assert all(term not in lowered for term in forbidden)


def test_no_job_execution_occurs():
    declaration = valid_declaration()
    declaration["execution_callable"] = "run_anything"

    with TemporaryDirectory() as tmp:
        write_registry(tmp, [declaration])
        declarations = load_scheduled_task_declarations(root=tmp)
        audited, errors = audit_scheduled_task_declarations(root=tmp)

    assert declarations == ()
    assert audited == ()
    assert errors
    assert any(error.field == "execution_callable" for error in errors)


def test_alexis_scheduled_task_declarations_validate():
    declarations, errors = audit_agent_scheduled_task_declarations(
        "alexis",
        root=ROOT,
    )

    assert errors == ()
    assert len(declarations) == 4
    assert {
        declaration.id
        for declaration in declarations
    } == {
        "alexis_daily_news_briefing",
        "alexis_rss_feed_check",
        "alexis_guest_db_freshness_audit",
        "alexis_booking_workflow_smoke_check",
    }
    assert all(
        declaration.task_type == "scheduled_workflow_task"
        for declaration in declarations
    )
    assert all(declaration.agent == "alexis" for declaration in declarations)
    assert all(declaration.max_concurrent_runs == 1 for declaration in declarations)
    assert all(declaration.retry_policy == "none" for declaration in declarations)
    assert {
        declaration.id: declaration.semantic_operation["operation_type"]
        for declaration in declarations
    } == {
        "alexis_daily_news_briefing": "NEWS_INGESTION",
        "alexis_rss_feed_check": "NEWS_INGESTION",
        "alexis_guest_db_freshness_audit": "DATABASE_AUDIT",
        "alexis_booking_workflow_smoke_check": "SMOKE_CHECK",
    }
    assert all(
        declaration.semantic_operation["external_side_effects_allowed"] is False
        for declaration in declarations
    )
    assert all(
        declaration.semantic_operation["memory_write_allowed"] is False
        for declaration in declarations
    )


def test_alexis_rss_newsroom_interval_resolves_declared_workflow_binding():
    declarations, errors = audit_agent_scheduled_task_declarations(
        "alexis",
        root=ROOT,
    )

    assert errors == ()
    rss_task = next(
        declaration for declaration in declarations
        if declaration.id == "alexis_rss_feed_check"
    )
    assert rss_task.governance_state == "enabled"
    assert rss_task.schedule_type == "interval"
    assert rss_task.schedule["every_ms"] == 1800000
    assert rss_task.agent == "alexis"
    assert rss_task.workflow == "alexis_rss_feed_check"
    assert rss_task.binding_id == "alexis_rss_feed_check"
    assert rss_task.semantic_operation == {
        "operation_type": "NEWS_INGESTION",
        "capability_id": "alexis_rss_feed_check",
        "produces_artifact": False,
        "external_side_effects_allowed": False,
        "memory_write_allowed": False,
        "requires_approval": False,
    }


def test_disabled_and_audit_only_tasks_do_not_imply_execution():
    declarations, errors = audit_agent_scheduled_task_declarations(
        "alexis",
        root=ROOT,
    )

    assert errors == ()
    assert {
        declaration.governance_state
        for declaration in declarations
    } == {"disabled", "audit_only", "enabled"}
    assert all(
        declaration.governance_state in {"disabled", "audit_only", "enabled"}
        for declaration in declarations
    )
    assert {
        declaration.id for declaration in declarations
        if declaration.governance_state == "enabled"
    } == {"alexis_rss_feed_check"}
    assert all("execution_callable" not in declaration.raw_data for declaration in declarations)
    assert all("runner" not in declaration.raw_data for declaration in declarations)


def test_alexis_missing_workflow_binding_fails_closed():
    source = ROOT / "agents/alexis/scheduled_tasks.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    del data["task_declarations"][0]["binding"]["workflow"]

    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "agents/alexis/scheduled_tasks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        _declarations, errors = audit_scheduled_task_declarations_from_path(
            path,
            root=ROOT,
        )

    assert errors
    assert any(error.field == "binding.workflow" for error in errors)


def test_no_scheduled_runner_or_executor_exists_or_is_invoked():
    import runtime.registries.scheduled_task_registry as registry

    public_callables = {
        name
        for name in dir(registry)
        if not name.startswith("_") and callable(getattr(registry, name))
    }
    forbidden_public_callables = {
        "execute_scheduled_task",
        "run_scheduled_task",
        "start_scheduler",
        "dispatch_scheduled_task",
    }
    source = (
        ROOT / "runtime/registries/scheduled_task_registry.py"
    ).read_text(encoding="utf-8")

    assert public_callables.isdisjoint(forbidden_public_callables)
    assert "subprocess" not in source
    assert "requests" not in source
    assert "feedparser" not in source
    assert "telegram" not in source.lower()


def main():
    test_valid_scheduled_task_contract_loads()
    test_valid_scheduled_task_declaration_loads()
    test_missing_schedule_fails_closed()
    test_missing_agent_workflow_binding_fails_closed()
    test_unknown_governance_state_fails_closed()
    test_missing_semantic_operation_metadata_fails_closed()
    test_unknown_semantic_operation_type_fails_closed()
    test_semantic_side_effect_flags_are_validated()
    test_hidden_autonomous_and_self_mutating_fields_are_rejected()
    test_registry_validation_is_domain_neutral()
    test_no_job_execution_occurs()
    test_alexis_scheduled_task_declarations_validate()
    test_alexis_rss_newsroom_interval_resolves_declared_workflow_binding()
    test_disabled_and_audit_only_tasks_do_not_imply_execution()
    test_alexis_missing_workflow_binding_fails_closed()
    test_no_scheduled_runner_or_executor_exists_or_is_invoked()
    print("PASS scheduled task contracts")


if __name__ == "__main__":
    main()
