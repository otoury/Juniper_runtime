import sys
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_runtime_root_no_longer_contains_flat_feature_modules():
    runtime_root = ROOT / "runtime"
    forbidden_patterns = (
        "lookup_*.py",
        "scheduled_workflow_*.py",
        "source_ingestion_*.py",
    )
    forbidden = []
    for pattern in forbidden_patterns:
        forbidden.extend(runtime_root.glob(pattern))
    forbidden.extend(runtime_root.glob("source_item_store.py"))

    assert forbidden == []


def test_runtime_feature_packages_exist():
    for package in (
        ROOT / "runtime" / "lookup",
        ROOT / "runtime" / "scheduling",
        ROOT / "runtime" / "ingestion",
        ROOT / "runtime" / "actions",
        ROOT / "runtime" / "contracts",
        ROOT / "runtime" / "policies",
        ROOT / "runtime" / "workflows",
    ):
        assert package.is_dir()
        assert (package / "__init__.py").is_file()


def test_runtime_feature_modules_moved_to_packages():
    expected = (
        ROOT / "runtime" / "lookup" / "execution.py",
        ROOT / "runtime" / "lookup" / "request_planner.py",
        ROOT / "runtime" / "lookup" / "context_materializer.py",
        ROOT / "runtime" / "lookup" / "context_renderer.py",
        ROOT / "runtime" / "lookup" / "context_injection.py",
        ROOT / "runtime" / "lookup" / "context_budgeting.py",
        ROOT / "runtime" / "lookup" / "context_render_gate.py",
        ROOT / "runtime" / "lookup" / "lifecycle.py",
        ROOT / "runtime" / "lookup" / "lineage.py",
        ROOT / "runtime" / "lookup" / "governance.py",
        ROOT / "runtime" / "lookup" / "policy_validation.py",
        ROOT / "runtime" / "lookup" / "pipeline_summary.py",
        ROOT / "runtime" / "lookup" / "pipeline_telemetry.py",
        ROOT / "runtime" / "lookup" / "execution_policy.py",
        ROOT / "runtime" / "lookup" / "capability_compatibility.py",
        ROOT / "runtime" / "lookup" / "types.py",
        ROOT / "runtime" / "lookup" / "telemetry.py",
        ROOT / "runtime" / "lookup" / "context.py",
        ROOT / "runtime" / "scheduling" / "workflow_orchestration.py",
        ROOT / "runtime" / "scheduling" / "workflow_executor.py",
        ROOT / "runtime" / "scheduling" / "workflow_audit.py",
        ROOT / "runtime" / "scheduling" / "workflow_loop.py",
        ROOT / "runtime" / "scheduling" / "workflow_locking.py",
        ROOT / "runtime" / "ingestion" / "source_execution.py",
        ROOT / "runtime" / "ingestion" / "source_audit.py",
        ROOT / "runtime" / "ingestion" / "source_item_store.py",
        ROOT / "runtime" / "actions" / "capabilities.py",
        ROOT / "runtime" / "actions" / "contracts.py",
        ROOT / "runtime" / "actions" / "detector.py",
        ROOT / "runtime" / "actions" / "executor.py",
        ROOT / "runtime" / "actions" / "parser.py",
        ROOT / "runtime" / "actions" / "queue.py",
        ROOT / "runtime" / "actions" / "registry.py",
        ROOT / "runtime" / "actions" / "types.py",
    )

    assert all(path.is_file() for path in expected)


def test_top_level_actions_package_does_not_reappear():
    actions_root = ROOT / "actions"

    assert not actions_root.exists()


def test_top_level_router_package_does_not_reappear():
    router_root = ROOT / "router"

    assert not router_root.exists()


def test_gateway_routing_package_exists():
    routing_root = ROOT / "gateway" / "routing"

    assert routing_root.is_dir()
    assert (routing_root / "__init__.py").is_file()
    assert (routing_root / "juniper.py").is_file()


def test_empty_learning_package_does_not_reappear():
    learning_root = ROOT / "learning"

    assert not learning_root.exists()


def test_top_level_runtime_trace_package_does_not_reappear():
    runtime_trace_root = ROOT / "runtime_trace"

    assert not runtime_trace_root.exists()


def test_runtime_trace_package_exists():
    trace_root = ROOT / "runtime" / "trace"

    assert trace_root.is_dir()
    assert (trace_root / "__init__.py").is_file()
    assert (trace_root / "store.py").is_file()


def test_top_level_workflow_package_is_retired():
    workflow_root = ROOT / "workflow"

    if workflow_root.exists():
        assert not (workflow_root / "__init__.py").exists()
        assert not (workflow_root / "store.py").exists()


def test_runtime_workflow_store_exists():
    store_path = ROOT / "runtime" / "workflows" / "store.py"

    assert store_path.is_file()


def test_top_level_workspace_has_no_python_package_ownership():
    workspace_root = ROOT / "workspace"
    if workspace_root.exists():
        assert workspace_root.is_dir()
        assert not (workspace_root / "__init__.py").exists()
        assert not any(workspace_root.rglob("*.py"))


def test_top_level_system_package_does_not_reappear():
    system_root = ROOT / "system"

    assert not system_root.exists()


def test_gateway_system_package_exists():
    system_root = ROOT / "gateway" / "system"

    assert system_root.is_dir()
    assert (system_root / "__init__.py").is_file()
    assert (system_root / "analytics.py").is_file()
    assert (system_root / "status.py").is_file()


def test_top_level_ui_package_does_not_reappear():
    ui_root = ROOT / "ui"

    assert not ui_root.exists()


def test_top_level_policies_package_does_not_reappear():
    policies_root = ROOT / "policies"

    assert not policies_root.exists()


def test_runtime_policies_package_exists():
    policies_root = ROOT / "runtime" / "policies"

    assert policies_root.is_dir()
    assert (policies_root / "__init__.py").is_file()
    assert (policies_root / "model_registry.py").is_file()
    assert (policies_root / "model_selector.py").is_file()
    assert (policies_root / "escalation.py").is_file()


def test_runner_ui_package_exists():
    ui_root = ROOT / "runner" / "ui"

    assert ui_root.is_dir()
    assert (ui_root / "__init__.py").is_file()
    assert (ui_root / "dashboard.py").is_file()


def test_runtime_summary_modules_are_domain_neutral():
    forbidden_terms = (
        "news_summary",
        "latest_news",
        "newsroom",
    )
    runtime_sources = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "runtime").rglob("*.py")
    ]

    assert all(
        all(term not in path for term in forbidden_terms)
        for path in runtime_sources
    )


def test_runtime_diagnostic_modules_are_domain_neutral():
    forbidden_terms = (
        "alexis",
        "contact",
        "guest",
        "latest_news",
        "newsroom",
    )
    runtime_diagnostic_sources = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "runtime").rglob("*diagnostic*.py")
    ]

    assert all(
        all(term not in path for term in forbidden_terms)
        for path in runtime_diagnostic_sources
    )


def test_shared_context_placeholder_registries_do_not_reappear():
    removed_shared_files = (
        ROOT / "agents" / "shared" / "semantics" / "context_sources.json",
        ROOT / "agents" / "shared" / "semantics" / "context_adapters.json",
        ROOT / "agents" / "shared" / "semantics" / "context_injections.json",
    )

    assert all(not path.exists() for path in removed_shared_files)


def test_alexis_binding_declarations_not_under_context():
    forbidden_context_binding_files = (
        ROOT / "agents" / "alexis" / "context" / "adapters.json",
        ROOT / "agents" / "alexis" / "context" / "bindings.json",
        ROOT / "agents" / "alexis" / "context" / "injections.json",
    )

    assert all(not path.exists() for path in forbidden_context_binding_files)


def test_alexis_binding_declarations_exist_under_bindings():
    expected_binding_files = (
        ROOT / "agents" / "alexis" / "bindings" / "adapters.json",
        ROOT / "agents" / "alexis" / "bindings" / "resources.json",
        ROOT / "agents" / "alexis" / "bindings" / "context_injections.json",
        ROOT / "agents" / "alexis" / "bindings" / "capabilities.json",
    )

    assert all(path.is_file() for path in expected_binding_files)


def test_alexis_mixed_capability_binding_file_does_not_reappear():
    mixed_path = ROOT / "agents" / "alexis" / "capabilities" / "bindings.json"

    assert not mixed_path.exists()


def test_alexis_capability_authority_split_files_exist():
    expected = (
        ROOT / "agents" / "alexis" / "bindings" / "capabilities.json",
        ROOT / "agents" / "alexis" / "policies" / "lookup_execution.json",
        ROOT / "agents" / "alexis" / "policies" / "context_rendering.json",
        ROOT / "agents" / "alexis" / "policies" / "context_injection.json",
        ROOT / "agents" / "alexis" / "policies" / "context_assembly.json",
        ROOT / "agents" / "alexis" / "governance" / "lookup_capabilities.json",
        ROOT
        / "agents"
        / "alexis"
        / "contracts"
        / "lookup_runtime_compatibility.json",
    )

    assert all(path.is_file() for path in expected)


def test_alexis_capability_bindings_are_binding_only():
    path = ROOT / "agents" / "alexis" / "bindings" / "capabilities.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    allowed_fields = {"shared_capability", "skills", "resources"}
    forbidden_fields = {
        "lookup_capability_governance",
        "lookup_capability_compatibility",
        "lookup_execution_policy",
        "lookup_request_policy",
        "lookup_context_materialization_policy",
        "lookup_context_render_policy",
        "lookup_context_injection_policy",
        "tone",
        "context_policy",
    }

    for binding in data["bindings"].values():
        assert set(binding) <= allowed_fields
        assert not (set(binding) & forbidden_fields)


def test_obsolete_context_binding_registry_module_names_do_not_reappear():
    obsolete_registry_modules = (
        ROOT / "runtime" / "registries" / "context_source_registry.py",
        ROOT / "runtime" / "registries" / "context_adapter_registry.py",
        ROOT / "runtime" / "registries" / "context_injection_registry.py",
    )

    assert all(not path.exists() for path in obsolete_registry_modules)


def test_binding_registry_modules_exist():
    binding_registry_modules = (
        ROOT / "runtime" / "registries" / "resource_binding_registry.py",
        ROOT / "runtime" / "registries" / "adapter_binding_registry.py",
        ROOT
        / "runtime"
        / "registries"
        / "context_injection_binding_registry.py",
    )

    assert all(path.is_file() for path in binding_registry_modules)


def test_artifact_ontology_does_not_contain_runtime_policy_fields():
    path = ROOT / "agents" / "shared" / "artifacts" / "artifacts.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    forbidden_fields = {
        "persist_as_artifact",
        "preferred_engine",
        "fallback_engines",
        "reasoning_depth",
        "style_sensitivity",
        "latency_preference",
        "formatting_constraints",
        "transforms",
        "extract_fields",
    }

    for config in data.values():
        assert not (set(config) & forbidden_fields)


def test_artifact_policy_file_exists():
    path = (
        ROOT
        / "agents"
        / "shared"
        / "artifacts"
        / "artifact_policies.json"
    )

    assert path.is_file()


def test_semantic_taxonomy_file_does_not_reappear():
    taxonomy_path = ROOT / "config" / "semantic_taxonomy.json"

    assert not taxonomy_path.exists()


def test_semantic_ontology_excludes_context_resolver_and_examples():
    ontology_paths = (
        ROOT / "semantics" / "interaction_modes.json",
        ROOT / "semantics" / "operations.json",
    )

    for path in ontology_paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "context_resolver" not in data
        assert "transform_intents" not in data


def test_semantic_taxonomy_split_files_exist():
    expected = (
        ROOT / "semantics" / "interaction_modes.json",
        ROOT / "semantics" / "operations.json",
        ROOT / "planner" / "policies" / "artifact_attachment.json",
        ROOT / "semantics" / "transform_guidance.json",
        ROOT / "semantics" / "transform_examples.json",
        ROOT / "planner" / "policies" / "context_resolution.json",
    )

    assert all(path.is_file() for path in expected)


def test_shared_lookup_capability_contract_semantics_file_does_not_reappear():
    path = ROOT / "agents/shared/semantics/lookup_capability_contracts.json"

    assert not path.exists()


def test_shared_lookup_contract_authority_split_files_exist():
    expected = (
        ROOT / "agents/shared/contracts/lookup_capability_contracts.json",
        ROOT / "agents/shared/contracts/lookup_runtime_compatibility.json",
        ROOT / "agents/shared/contracts/lookup_render_contracts.json",
        ROOT / "agents/shared/governance/lookup_governance_states.json",
        ROOT / "agents/shared/policies/lookup_execution.json",
        ROOT / "planner/contracts/lookup_request_contracts.json",
    )

    assert all(path.is_file() for path in expected)


def test_shared_lookup_capability_contract_excludes_policy_governance_and_planner_fields():
    path = ROOT / "agents/shared/contracts/lookup_capability_contracts.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    forbidden_fields = {
        "contract_version",
        "runtime_compatibility_version",
        "governance_states",
        "cancellation_behaviors",
        "policy_sections",
        "render_modes",
        "context_types",
        "content_types",
        "truncation_modes",
        "planner_contract",
    }

    for contract in data["contracts"]:
        assert not (set(contract) & forbidden_fields)


def test_attachment_policy_lives_under_planner_policies():
    path = ROOT / "planner" / "policies" / "artifact_attachment.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    assert set(data) == {"attachment"}


def test_transform_guidance_lives_under_semantics():
    path = ROOT / "semantics" / "transform_guidance.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    assert set(data) == {"transform_intents"}
    assert set(data["transform_intents"]) == {"guidance"}


def test_root_config_directory_is_retired():
    assert not (ROOT / "config").exists()


def test_root_contracts_directory_is_retired():
    assert not (ROOT / "contracts").exists()


def test_planner_contracts_live_under_planner_contracts():
    expected = (
        ROOT / "planner/contracts/request_gate.json",
        ROOT / "planner/contracts/execution_planner.json",
        ROOT / "planner/contracts/lookup_request_contracts.json",
    )

    assert all(path.is_file() for path in expected)


def test_runtime_contract_utilities_and_repair_contract_live_under_runtime_contracts():
    expected = (
        ROOT / "runtime/contracts/__init__.py",
        ROOT / "runtime/contracts/base_validator.py",
        ROOT / "runtime/contracts/exceptions.py",
        ROOT / "runtime/contracts/result.py",
        ROOT / "runtime/contracts/schema_validator.py",
        ROOT / "runtime/contracts/semantic_validation.py",
        ROOT / "runtime/contracts/artifact_repair.json",
    )

    assert all(path.is_file() for path in expected)


def main():
    test_runtime_root_no_longer_contains_flat_feature_modules()
    test_runtime_feature_packages_exist()
    test_runtime_feature_modules_moved_to_packages()
    test_top_level_actions_package_does_not_reappear()
    test_top_level_router_package_does_not_reappear()
    test_gateway_routing_package_exists()
    test_empty_learning_package_does_not_reappear()
    test_top_level_runtime_trace_package_does_not_reappear()
    test_runtime_trace_package_exists()
    test_top_level_workflow_package_is_retired()
    test_runtime_workflow_store_exists()
    test_top_level_workspace_has_no_python_package_ownership()
    test_top_level_system_package_does_not_reappear()
    test_gateway_system_package_exists()
    test_top_level_ui_package_does_not_reappear()
    test_top_level_policies_package_does_not_reappear()
    test_runtime_policies_package_exists()
    test_runner_ui_package_exists()
    test_runtime_summary_modules_are_domain_neutral()
    test_shared_context_placeholder_registries_do_not_reappear()
    test_alexis_binding_declarations_not_under_context()
    test_alexis_binding_declarations_exist_under_bindings()
    test_alexis_mixed_capability_binding_file_does_not_reappear()
    test_alexis_capability_authority_split_files_exist()
    test_alexis_capability_bindings_are_binding_only()
    test_obsolete_context_binding_registry_module_names_do_not_reappear()
    test_binding_registry_modules_exist()
    test_artifact_ontology_does_not_contain_runtime_policy_fields()
    test_artifact_policy_file_exists()
    test_semantic_taxonomy_file_does_not_reappear()
    test_semantic_ontology_excludes_context_resolver_and_examples()
    test_semantic_taxonomy_split_files_exist()
    test_shared_lookup_capability_contract_semantics_file_does_not_reappear()
    test_shared_lookup_contract_authority_split_files_exist()
    test_shared_lookup_capability_contract_excludes_policy_governance_and_planner_fields()
    test_attachment_policy_lives_under_planner_policies()
    test_transform_guidance_lives_under_semantics()
    test_root_config_directory_is_retired()
    test_root_contracts_directory_is_retired()
    test_planner_contracts_live_under_planner_contracts()
    test_runtime_contract_utilities_and_repair_contract_live_under_runtime_contracts()
    print("PASS runtime topology")


if __name__ == "__main__":
    main()
