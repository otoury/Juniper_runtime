import json
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.registries.external_discovery_provider_registry import (  # noqa: E402
    ALLOWED_EXECUTION_MODES,
    EXTERNAL_DISCOVERY_PROVIDER_CONTRACTS_PATH,
    FORBIDDEN_DECLARATION_FIELDS,
    REQUIRED_DECLARATION_FIELDS,
    get_external_discovery_provider_declaration,
    load_external_discovery_provider_contracts,
    load_external_discovery_provider_declarations,
)


def _clear_caches():
    load_external_discovery_provider_contracts.cache_clear()
    load_external_discovery_provider_declarations.cache_clear()


def _base_registry(**declaration_overrides):
    declaration = {
        "provider_id": "cloud_web_ai",
        "provider_type": "cloud_ai",
        "execution_mode": "declaration_only",
        "governance_state": "audit_only",
        "external": True,
        "cost_bearing": True,
        "governed": True,
        "non_executing": True,
        "governance": {
            "live_execution_allowed": False,
            "network_calls_allowed": False,
            "delivery_allowed": False,
            "dry_run_or_mock_required": True,
        },
        "cost_policy": {
            "cost_bearing": True,
            "free_tier_available": False,
            "free_tier": {
                "queries_per_period": None,
                "period": None,
                "notes": "No shared free-tier assumption.",
            },
            "cost_tracking_required": True,
        },
        "supported_output_types": [
            "external_discovery_result_set",
            "external_discovery_source_reference",
        ],
        "max_queries": 3,
        "max_results": 25,
        "max_cost": {
            "currency": "USD",
            "amount": None,
            "period": "per_discovery_request",
        },
        "execution_bounds": {
            "max_queries": 3,
            "max_results": 25,
            "timeout_ms": 30000,
            "connect_timeout_ms": 5000,
            "read_timeout_ms": 25000,
            "max_retries": 0,
        },
        "source_requirements": {
            "source_refs_required": True,
            "provider_result_id_required": True,
            "source_url_required": True,
            "raw_results_required": True,
            "allowed_source_types": ["web_page"],
            "disallowed_source_types": [],
            "primary_sources_required": None,
            "freshness_policy": None,
        },
        "citation_requirements": {
            "citations_required": True,
            "minimum_citations": None,
            "source_url_required": True,
        },
    }
    declaration.update(declaration_overrides)
    return {
        "version": 1,
        "contracts": [
            {
                "id": "external_discovery_provider",
                "contract_version": 1,
                "required_declaration_fields": sorted(REQUIRED_DECLARATION_FIELDS),
                "allowed_provider_types": [
                    "cloud_ai",
                    "search_api",
                ],
                "allowed_execution_modes": sorted(ALLOWED_EXECUTION_MODES),
                "allowed_governance_states": [
                    "enabled",
                    "audit_only",
                    "disabled",
                ],
                "allowed_output_types": [
                    "external_discovery_result_set",
                    "external_discovery_source_reference",
                ],
                "execution_policy": {
                    "execution_allowed": False,
                    "network_calls_allowed": False,
                    "cloud_model_calls_allowed": False,
                    "normalization_allowed": False,
                    "delivery_allowed": False,
                },
                "forbidden_declaration_fields": sorted(FORBIDDEN_DECLARATION_FIELDS),
            }
        ],
        "provider_declarations": [declaration],
    }


def _with_temp_registry(data):
    root = Path(tempfile.mkdtemp())
    path = root / EXTERNAL_DISCOVERY_PROVIDER_CONTRACTS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    _clear_caches()
    return root


def _cleanup(root):
    shutil.rmtree(root)
    _clear_caches()


def test_shared_provider_contract_loads():
    contracts = load_external_discovery_provider_contracts(ROOT)

    assert len(contracts) == 1
    contract = contracts[0]
    assert contract.id == "external_discovery_provider"
    assert set(contract.required_declaration_fields) == REQUIRED_DECLARATION_FIELDS
    assert contract.execution_policy["execution_allowed"] is False
    assert contract.execution_policy["network_calls_allowed"] is False
    assert contract.execution_policy["cloud_model_calls_allowed"] is False
    assert contract.execution_policy["normalization_allowed"] is False


def test_cloud_web_ai_provider_declaration_loads():
    declaration = get_external_discovery_provider_declaration(
        "cloud_web_ai",
        root=ROOT,
    )

    assert declaration is not None
    assert declaration.provider_type == "cloud_ai"
    assert declaration.execution_mode == "declaration_only"
    assert declaration.governance_state == "audit_only"
    assert declaration.external is True
    assert declaration.cost_bearing is True
    assert declaration.governed is True
    assert declaration.non_executing is True
    assert declaration.governance["live_execution_allowed"] is False
    assert declaration.governance["dry_run_or_mock_required"] is True
    assert declaration.cost_policy["free_tier_available"] is False
    assert declaration.max_queries == 3
    assert declaration.max_results == 25
    assert declaration.max_cost["currency"] == "USD"
    assert declaration.max_cost["amount"] is None
    assert declaration.execution_bounds["timeout_ms"] == 30000
    assert declaration.source_requirements["source_refs_required"] is True
    assert declaration.source_requirements["allowed_source_types"] == ["web_page"]
    assert declaration.citation_requirements["citations_required"] is True


def test_search_api_provider_declaration_loads():
    declaration = get_external_discovery_provider_declaration(
        "search_api",
        root=ROOT,
    )

    assert declaration is not None
    assert declaration.provider_type == "search_api"
    assert declaration.execution_mode == "declaration_only"
    assert declaration.governance_state == "audit_only"
    assert declaration.external is True
    assert declaration.cost_bearing is True
    assert declaration.governed is True
    assert declaration.non_executing is True
    assert declaration.governance["network_calls_allowed"] is False
    assert declaration.cost_policy["free_tier_available"] is True
    assert isinstance(declaration.cost_policy["free_tier"], dict)
    assert declaration.max_queries == 5
    assert declaration.max_results == 25
    assert declaration.max_cost["currency"] == "USD"
    assert declaration.execution_bounds["timeout_ms"] == 15000
    assert declaration.execution_bounds["max_queries"] == declaration.max_queries
    assert declaration.source_requirements["source_refs_required"] is True
    assert declaration.source_requirements["provider_result_id_required"] is True
    assert declaration.source_requirements["source_url_required"] is True
    assert declaration.source_requirements["freshness_policy"] is None
    assert declaration.citation_requirements["source_url_required"] is True


def test_cloud_web_deep_premium_provider_declaration_loads():
    declaration = get_external_discovery_provider_declaration(
        "cloud_web_deep_premium",
        root=ROOT,
    )

    assert declaration is not None
    assert declaration.provider_type == "cloud_ai"
    assert declaration.execution_mode == "declaration_only"
    assert declaration.governance_state == "audit_only"
    assert declaration.external is True
    assert declaration.cost_bearing is True
    assert declaration.governed is True
    assert declaration.non_executing is True
    assert declaration.governance["live_execution_allowed"] is False
    assert declaration.governance["network_calls_allowed"] is False
    assert declaration.governance["dry_run_or_mock_required"] is True
    assert declaration.cost_policy["free_tier_available"] is False
    assert declaration.cost_policy["cost_tracking_required"] is True
    assert declaration.max_queries == 1
    assert declaration.max_results == 25
    assert declaration.execution_bounds["max_queries"] == declaration.max_queries
    assert declaration.source_requirements["source_refs_required"] is True
    assert declaration.source_requirements["raw_results_required"] is True
    assert declaration.citation_requirements["citations_required"] is True
    assert declaration.citation_requirements["minimum_citations"] == 1
    assert "model" not in declaration.raw_data
    assert "prompt" not in declaration.raw_data


def test_providers_remain_non_executing():
    declarations = load_external_discovery_provider_declarations(ROOT)

    assert {item.provider_id for item in declarations} == {
        "cloud_web_ai",
        "cloud_web_deep_premium",
        "search_api",
    }
    assert all(item.execution_allowed is False for item in declarations)
    assert all(item.execution_mode == "declaration_only" for item in declarations)
    assert all(item.governance_state in {"audit_only", "disabled"} for item in declarations)
    assert all(item.non_executing is True for item in declarations)
    assert all(
        item.to_metadata()["execution_allowed"] is False
        for item in declarations
    )


def test_agent_owned_provider_is_not_shared_declaration():
    assert (
        get_external_discovery_provider_declaration(
            "alexis_guest_db",
            root=ROOT,
        )
        is None
    )


def test_malformed_provider_declaration_fails_closed():
    root = _with_temp_registry(
        _base_registry(
            provider_id="unapproved_provider",
        )
    )

    try:
        assert load_external_discovery_provider_declarations(root) == ()
        assert (
            get_external_discovery_provider_declaration(
                "unapproved_provider",
                root=root,
            )
            is None
        )
    finally:
        _cleanup(root)


def test_enabled_provider_declaration_fails_closed():
    root = _with_temp_registry(
        _base_registry(
            governance_state="enabled",
        )
    )

    try:
        assert load_external_discovery_provider_declarations(root) == ()
    finally:
        _cleanup(root)


def test_governance_metadata_is_required():
    registry = _base_registry()
    del registry["provider_declarations"][0]["source_requirements"]
    root = _with_temp_registry(registry)

    try:
        assert load_external_discovery_provider_declarations(root) == ()
    finally:
        _cleanup(root)


def test_search_api_source_refs_are_required():
    registry = _base_registry(
        provider_id="search_api",
        provider_type="search_api",
        max_queries=5,
        execution_bounds={
            "max_queries": 5,
            "max_results": 25,
            "timeout_ms": 15000,
            "connect_timeout_ms": 3000,
            "read_timeout_ms": 12000,
            "max_retries": 0,
        },
    )
    registry["provider_declarations"][0]["source_requirements"][
        "source_refs_required"
    ] = False
    root = _with_temp_registry(registry)

    try:
        assert load_external_discovery_provider_declarations(root) == ()
    finally:
        _cleanup(root)


def test_provider_execution_bounds_are_required():
    registry = _base_registry()
    registry["provider_declarations"][0]["execution_bounds"]["timeout_ms"] = 0
    root = _with_temp_registry(registry)

    try:
        assert load_external_discovery_provider_declarations(root) == ()
    finally:
        _cleanup(root)


def test_free_tier_cost_metadata_is_required():
    registry = _base_registry()
    del registry["provider_declarations"][0]["cost_policy"]["free_tier"]
    root = _with_temp_registry(registry)

    try:
        assert load_external_discovery_provider_declarations(root) == ()
    finally:
        _cleanup(root)


def test_search_api_is_not_cloud_web_semantics():
    declaration = get_external_discovery_provider_declaration(
        "search_api",
        root=ROOT,
    )

    assert declaration is not None
    metadata = declaration.to_metadata()
    assert metadata["provider_type"] == "search_api"
    assert metadata["provider_id"] != "cloud_web_ai"
    assert "model" not in declaration.raw_data
    assert "prompt" not in declaration.raw_data
    assert "normalizer" not in declaration.raw_data


def test_execution_fields_fail_closed():
    root = _with_temp_registry(
        _base_registry(
            execute=True,
        )
    )

    try:
        assert load_external_discovery_provider_declarations(root) == ()
    finally:
        _cleanup(root)


def test_registry_exposes_no_provider_execution_path():
    runtime_text = (
        ROOT
        / "runtime"
        / "registries"
        / "external_discovery_provider_registry.py"
    ).read_text(encoding="utf-8")
    forbidden_imports = (
        "requests",
        "urllib",
        "http.client",
        "aiohttp",
        "openai",
        "anthropic",
        "google.generativeai",
    )
    forbidden_callables = (
        "def execute_",
        "def run_",
        "def call_",
        "def fetch_",
        "def search_",
    )

    assert all(term not in runtime_text for term in forbidden_imports)
    assert all(term not in runtime_text for term in forbidden_callables)


def test_runtime_provider_contract_remains_domain_neutral():
    shared_text = (
        ROOT / EXTERNAL_DISCOVERY_PROVIDER_CONTRACTS_PATH
    ).read_text(encoding="utf-8").lower()
    runtime_text = (
        ROOT
        / "runtime"
        / "registries"
        / "external_discovery_provider_registry.py"
    ).read_text(encoding="utf-8").lower()
    combined = f"{shared_text}\n{runtime_text}"

    forbidden = (
        "guest",
        "alexis",
        "booking",
        "newsroom",
        "candidate",
        "send_email",
    )
    assert all(term not in combined for term in forbidden)


def main():
    test_shared_provider_contract_loads()
    test_cloud_web_ai_provider_declaration_loads()
    test_search_api_provider_declaration_loads()
    test_cloud_web_deep_premium_provider_declaration_loads()
    test_providers_remain_non_executing()
    test_agent_owned_provider_is_not_shared_declaration()
    test_malformed_provider_declaration_fails_closed()
    test_enabled_provider_declaration_fails_closed()
    test_governance_metadata_is_required()
    test_search_api_source_refs_are_required()
    test_provider_execution_bounds_are_required()
    test_free_tier_cost_metadata_is_required()
    test_search_api_is_not_cloud_web_semantics()
    test_execution_fields_fail_closed()
    test_registry_exposes_no_provider_execution_path()
    test_runtime_provider_contract_remains_domain_neutral()
    print("PASS external discovery provider contracts")


if __name__ == "__main__":
    main()
