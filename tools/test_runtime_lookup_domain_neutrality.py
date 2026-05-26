import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


RUNTIME_SHARED_LOOKUP_FILES = [
    Path("runtime/lookup/types.py"),
    Path("runtime/lookup/lineage.py"),
    Path("runtime/lookup/lifecycle.py"),
    Path("runtime/lookup/governance.py"),
    Path("runtime/lookup/capability_compatibility.py"),
    Path("runtime/lookup/context.py"),
    Path("runtime/lookup/telemetry.py"),
    Path("runtime/lookup/execution.py"),
    Path("runtime/lookup/execution_policy.py"),
    Path("runtime/lookup/pipeline_telemetry.py"),
    Path("runtime/lookup/pipeline_summary.py"),
    Path("runtime/lookup/policy_validation.py"),
    Path("runtime/lookup/context_materializer.py"),
    Path("runtime/lookup/context_render_gate.py"),
    Path("runtime/lookup/context_renderer.py"),
    Path("runtime/lookup/context_budgeting.py"),
    Path("runtime/lookup/context_injection.py"),
    Path("runtime/lookup/request_planner.py"),
    Path("runtime/registries/exact_entity_lookup_registry.py"),
    Path("runtime/registries/bounded_entity_search_registry.py"),
    Path("runtime/registries/lookup_capability_registry.py"),
    Path("agents/shared/semantics/exact_entity_lookup_contracts.json"),
    Path("agents/shared/contracts/lookup_capability_contracts.json"),
    Path("agents/shared/contracts/lookup_runtime_compatibility.json"),
    Path("agents/shared/contracts/lookup_render_contracts.json"),
    Path("agents/shared/governance/lookup_governance_states.json"),
    Path("agents/shared/policies/lookup_execution.json"),
    Path("planner/contracts/lookup_request_contracts.json"),
]
AGENT_LOCAL_LOOKUP_FILES = [
    Path("agents/alexis/adapters/guest_db/readonly_adapter.py"),
    Path("agents/alexis/adapters/guest_db/exact_entity_lookup_adapter.py"),
]
PLANNER_LOOKUP_METADATA_FILES = [
    Path("planner/lookup_metadata.py"),
]
FORBIDDEN_RUNTIME_TERMS = [
    "guest",
    "guest_id",
    "guest_db",
]
FORBIDDEN_PLANNER_POLICY_TERMS = [
    "guest",
    "source_scope",
]


def test_runtime_shared_lookup_files_are_domain_neutral():
    failures = []

    for relative_path in RUNTIME_SHARED_LOOKUP_FILES:
        text = (ROOT / relative_path).read_text(encoding="utf-8").lower()
        for term in FORBIDDEN_RUNTIME_TERMS:
            if term in text:
                failures.append(f"{relative_path}: {term}")

    assert failures == []


def test_alexis_local_lookup_files_may_use_guest_terms():
    assert all((ROOT / path).exists() for path in AGENT_LOCAL_LOOKUP_FILES)
    combined = "\n".join(
        (ROOT / path).read_text(encoding="utf-8").lower()
        for path in AGENT_LOCAL_LOOKUP_FILES
    )

    assert "guest" in combined


def test_planner_lookup_metadata_has_no_agent_policy_terms():
    failures = []

    for relative_path in PLANNER_LOOKUP_METADATA_FILES:
        text = (ROOT / relative_path).read_text(encoding="utf-8").lower()
        for term in FORBIDDEN_PLANNER_POLICY_TERMS:
            if term in text:
                failures.append(f"{relative_path}: {term}")

    assert failures == []


def main():
    test_runtime_shared_lookup_files_are_domain_neutral()
    test_alexis_local_lookup_files_may_use_guest_terms()
    test_planner_lookup_metadata_has_no_agent_policy_terms()
    print("PASS runtime lookup domain neutrality")


if __name__ == "__main__":
    main()
