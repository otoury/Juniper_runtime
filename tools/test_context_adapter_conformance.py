import sys
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.registries.adapter_binding_registry import (  # noqa: E402
    ContextAdapterContract,
    load_context_adapter_registry_strict,
)
from tools.context_adapter_conformance import (  # noqa: E402
    KNOWN_ADAPTER_CONFORMANCE,
)


def conformance_errors(
    adapters: list[ContextAdapterContract],
) -> list[str]:
    errors: list[str] = []

    for adapter in adapters:
        if not adapter.enabled:
            continue

        conformance = KNOWN_ADAPTER_CONFORMANCE.get(adapter.adapter_id)

        if conformance is None:
            errors.append(
                f"{adapter.adapter_id}: missing conformance coverage"
            )
            continue

        if adapter.adapter_type != conformance["adapter_type"]:
            errors.append(
                f"{adapter.adapter_id}: adapter_type mismatch "
                f"{adapter.adapter_type} != {conformance['adapter_type']}"
            )

        if adapter.execution_mode != conformance["execution_mode"]:
            errors.append(
                f"{adapter.adapter_id}: execution_mode mismatch "
                f"{adapter.execution_mode} != "
                f"{conformance['execution_mode']}"
            )

    return errors


def sample_contract(**overrides):
    contract = ContextAdapterContract(
        adapter_id="synthetic_guest_context",
        source_contract_id="alexis_guest_db",
        enabled=True,
        adapter_type="synthetic",
        execution_mode="synthetic_only",
        external_reads_allowed=False,
        read_scope=None,
        read_target=None,
        max_records=None,
        writes_allowed=None,
        raw_data={},
    )

    if not overrides:
        return contract

    return replace(contract, **overrides)


def test_current_synthetic_adapter_has_conformance_coverage():
    adapters = list(load_context_adapter_registry_strict(ROOT))
    errors = conformance_errors(adapters)

    assert errors == []
    assert (
        KNOWN_ADAPTER_CONFORMANCE["synthetic_guest_context"]["test_command"]
        == "python tools/test_synthetic_context_adapter.py"
    )


def test_missing_conformance_record_fails():
    errors = conformance_errors([
        sample_contract(adapter_id="unknown_adapter"),
    ])

    assert errors == ["unknown_adapter: missing conformance coverage"]


def test_adapter_type_mismatch_fails():
    errors = conformance_errors([
        sample_contract(adapter_type="unexpected"),
    ])

    assert errors == [
        "synthetic_guest_context: adapter_type mismatch "
        "unexpected != synthetic"
    ]


def test_execution_mode_mismatch_fails():
    errors = conformance_errors([
        sample_contract(execution_mode="live"),
    ])

    assert errors == [
        "synthetic_guest_context: execution_mode mismatch "
        "live != synthetic_only"
    ]


def test_disabled_adapter_mapping_is_inert():
    errors = conformance_errors([
        sample_contract(
            adapter_id="unknown_disabled_adapter",
            enabled=False,
            adapter_type="unknown",
            execution_mode="unknown",
        ),
    ])

    assert errors == []


def main():
    test_current_synthetic_adapter_has_conformance_coverage()
    test_missing_conformance_record_fails()
    test_adapter_type_mismatch_fails()
    test_execution_mode_mismatch_fails()
    test_disabled_adapter_mapping_is_inert()
    print("PASS context adapter conformance")


if __name__ == "__main__":
    main()
