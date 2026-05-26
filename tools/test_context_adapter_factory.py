import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.alexis.adapters.guest_db.fixture_adapter import (  # noqa: E402
    GuestDbReadonlyFixtureAdapter,
)
from agents.alexis.adapters.guest_db.readonly_adapter import (  # noqa: E402
    AlexisGuestDbReadonlyAdapter,
)
from runtime.adapters.synthetic_guest_context_adapter import (  # noqa: E402
    SyntheticGuestContextAdapter,
)
from runtime.context_adapter_factory import (  # noqa: E402
    create_context_adapter,
    get_context_adapter_factory,
)
from runtime.context_composer import compose_bounded_context  # noqa: E402
from runtime.context_micro_injection import MICRO_BLOCK  # noqa: E402
from runtime.registries.context_injection_binding_registry import (  # noqa: E402
    list_context_injection_contracts,
)
from runtime.registries.adapter_binding_registry import (  # noqa: E402
    ContextAdapterContract,
)


class Env:
    def __init__(self, **values):
        self.values = values
        self.previous = {}

    def __enter__(self):
        for key, value in self.values.items():
            self.previous[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def __exit__(self, exc_type, exc, tb):
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def contract():
    return list_context_injection_contracts(ROOT)[0]


def adapter_contract(adapter_id):
    return ContextAdapterContract(
        adapter_id=adapter_id,
        source_contract_id="alexis_guest_db",
        enabled=True,
        adapter_type=(
            "synthetic"
            if adapter_id == "synthetic_guest_context"
            else "structured_database"
        ),
        execution_mode=(
            "synthetic_only"
            if adapter_id == "synthetic_guest_context"
            else "read_only_fixed_id"
        ),
        external_reads_allowed=adapter_id != "synthetic_guest_context",
        read_scope=(
            None
            if adapter_id == "synthetic_guest_context"
            else "declared_local_database"
        ),
        read_target=(
            None
            if adapter_id == "synthetic_guest_context"
            else (
                "agents/alexis/adapters/guest_db/resources/canonical/"
                "GUESTS_CANONICAL.csv"
            )
        ),
        max_records=None if adapter_id == "synthetic_guest_context" else 1,
        writes_allowed=(
            None if adapter_id == "synthetic_guest_context" else False
        ),
        raw_data={},
    )


def test_factory_resolves_synthetic_guest_context():
    factory = get_context_adapter_factory("synthetic_guest_context")
    adapter = create_context_adapter(
        "synthetic_guest_context",
        contract(),
        adapter_contract("synthetic_guest_context"),
    )

    assert factory is not None
    assert isinstance(adapter, SyntheticGuestContextAdapter)


def test_factory_resolves_guest_db_readonly_fixture():
    factory = get_context_adapter_factory("guest_db_readonly_fixture")
    fixture_contract = adapter_contract("guest_db_readonly_fixture")
    fixture_contract = ContextAdapterContract(
        **{
            **fixture_contract.__dict__,
            "execution_mode": "read_only_fixture",
            "read_scope": "local_fixture_file",
            "read_target": "tools/fixtures/guest_db_readonly_fixture.json",
        }
    )
    adapter = create_context_adapter(
        "guest_db_readonly_fixture",
        contract(),
        fixture_contract,
    )

    assert factory is not None
    assert isinstance(adapter, GuestDbReadonlyFixtureAdapter)


def test_factory_resolves_guest_db_readonly():
    factory = get_context_adapter_factory("guest_db_readonly")
    adapter = create_context_adapter(
        "guest_db_readonly",
        contract(),
        adapter_contract("guest_db_readonly"),
    )

    assert factory is not None
    assert isinstance(adapter, AlexisGuestDbReadonlyAdapter)


def test_unknown_adapter_returns_none():
    assert get_context_adapter_factory("unknown_adapter") is None
    assert create_context_adapter(
        "unknown_adapter",
        contract(),
        adapter_contract("guest_db_readonly"),
    ) is None


def test_composer_uses_factory_path_and_behavior_unchanged():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
        JUNIPER_ENABLE_EXTERNAL_CONTEXT_READS=None,
    ):
        result = compose_bounded_context(
            request_id="req_context_adapter_factory",
            agent="alexis",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    assert result.injection_performed is True
    assert result.rendered_blocks == [MICRO_BLOCK]
    assert (
        result.trace_payload["adapter_trace"]["adapter_id"]
        == "synthetic_guest_context"
    )


def test_context_composer_does_not_import_agents_alexis_directly():
    source = (ROOT / "runtime" / "context_composer.py").read_text()

    assert "agents.alexis" not in source


def main():
    test_factory_resolves_synthetic_guest_context()
    test_factory_resolves_guest_db_readonly_fixture()
    test_factory_resolves_guest_db_readonly()
    test_unknown_adapter_returns_none()
    test_composer_uses_factory_path_and_behavior_unchanged()
    test_context_composer_does_not_import_agents_alexis_directly()
    print("PASS context adapter factory")


if __name__ == "__main__":
    main()
