import json
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.registries.resource_binding_registry import (  # noqa: E402
    get_context_source_contract,
    get_context_source_token_budget,
    list_context_source_contracts,
    list_context_sources_for_capability,
    load_context_source_registry,
)


REGISTRY_RELATIVE_PATH = Path(
    "agents/alexis/bindings/resources.json"
)


def write_registry(root: Path, data):
    path = root / REGISTRY_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data),
        encoding="utf-8",
    )
    load_context_source_registry.cache_clear()


def with_temp_root(data):
    temp_root = Path(tempfile.mkdtemp())
    write_registry(temp_root, data)
    return temp_root


def valid_registry(*, enabled=False):
    return {
        "version": 1,
        "bindings": [
            {
                "binding_id": "alexis_guest_db",
                "adapter_type": "structured_database",
                "enabled": enabled,
                "allowed_capabilities": ["draft_email"],
                "requires_provenance_validation": True,
                "max_injection_tokens": 256,
                "execution_mode": "manual_future",
                "description": "Structured guest booking database.",
            }
        ],
    }


def cleanup(root: Path):
    shutil.rmtree(root)
    load_context_source_registry.cache_clear()


def test_registry_loads_successfully():
    contracts = list_context_source_contracts(root=ROOT)

    assert len(contracts) == 1
    assert contracts[0].binding_id == "alexis_guest_db"
    assert contracts[0].adapter_type == "structured_database"


def test_disabled_source_remains_inert():
    contract = get_context_source_contract(
        "alexis_guest_db",
        root=ROOT,
    )

    assert contract is not None
    assert contract.enabled is False
    assert contract.execution_mode == "manual_future"


def test_invalid_registry_shape_fails_closed():
    root = with_temp_root(
        {
            "version": 1,
            "bindings": [
                {
                    "binding_id": "broken_source",
                    "adapter_type": "structured_database",
                    "enabled": "yes",
                }
            ],
        }
    )

    try:
        assert list_context_source_contracts(root=root) == []
        assert get_context_source_contract("broken_source", root=root) is None
    finally:
        cleanup(root)


def test_missing_registry_fails_closed():
    root = Path(tempfile.mkdtemp())
    load_context_source_registry.cache_clear()

    try:
        assert list_context_source_contracts(root=root) == []
    finally:
        cleanup(root)


def test_unknown_source_lookup_returns_none():
    assert get_context_source_contract(
        "unknown_source",
        root=ROOT,
    ) is None


def test_capability_scoping_metadata_resolves():
    draft_sources = list_context_sources_for_capability(
        "draft_email",
        root=ROOT,
    )
    send_sources = list_context_sources_for_capability(
        "send_email",
        root=ROOT,
    )

    assert [source.id for source in draft_sources] == ["alexis_guest_db"]
    assert send_sources == []


def test_token_budget_metadata_resolves():
    assert get_context_source_token_budget(
        "alexis_guest_db",
        root=ROOT,
    ) == 256
    assert get_context_source_token_budget(
        "unknown_source",
        root=ROOT,
    ) is None


def main():
    test_registry_loads_successfully()
    test_disabled_source_remains_inert()
    test_invalid_registry_shape_fails_closed()
    test_missing_registry_fails_closed()
    test_unknown_source_lookup_returns_none()
    test_capability_scoping_metadata_resolves()
    test_token_budget_metadata_resolves()
    print("PASS context source registry")


if __name__ == "__main__":
    main()
