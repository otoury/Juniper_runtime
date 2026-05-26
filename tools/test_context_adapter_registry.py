import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runtime.context_composer as composer  # noqa: E402
from runtime.context_composer import compose_bounded_context  # noqa: E402
from runtime.context_micro_injection import MICRO_BLOCK  # noqa: E402
from runtime.registries.adapter_binding_registry import (  # noqa: E402
    ContextAdapterContract,
    get_context_adapter_for_source,
    list_context_adapter_contracts,
    load_context_adapter_registry,
    load_context_adapter_registry_strict,
)
from tools.test_context_trace_payload import (  # noqa: E402
    forbidden_keys_in_payload,
)


REGISTRY_PATH = Path("agents/alexis/bindings/adapters.json")


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


def clear_cache():
    load_context_adapter_registry.cache_clear()


def adapter_entry(**overrides):
    data = {
        "adapter_id": "synthetic_guest_context",
        "source_contract_id": "alexis_guest_db",
        "enabled": True,
        "adapter_type": "synthetic",
        "execution_mode": "synthetic_only",
        "external_reads_allowed": False,
    }
    data.update(overrides)
    return data


def fixture_adapter_entry(**overrides):
    data = {
        "adapter_id": "guest_db_readonly_fixture",
        "source_contract_id": "alexis_guest_db",
        "enabled": False,
        "adapter_type": "structured_database",
        "execution_mode": "read_only_fixture",
        "external_reads_allowed": True,
        "read_scope": "local_fixture_file",
        "read_target": "tools/fixtures/guest_db_readonly_fixture.json",
        "max_records": 1,
        "writes_allowed": False,
    }
    data.update(overrides)
    return data


def declared_adapter_entry(**overrides):
    data = {
        "adapter_id": "guest_db_readonly",
        "source_contract_id": "alexis_guest_db",
        "enabled": False,
        "adapter_type": "structured_database",
        "execution_mode": "read_only_declared",
        "external_reads_allowed": True,
        "read_scope": "declared_local_database",
        "read_target": "UNCONFIGURED",
        "max_records": 1,
        "writes_allowed": False,
    }
    data.update(overrides)
    return data


def readonly_fixed_id_adapter_entry(**overrides):
    data = {
        "adapter_id": "guest_db_readonly",
        "source_contract_id": "alexis_guest_db",
        "enabled": False,
        "adapter_type": "structured_database",
        "execution_mode": "read_only_fixed_id",
        "external_reads_allowed": True,
        "read_scope": "declared_local_database",
        "read_target": (
            "agents/alexis/adapters/guest_db/resources/canonical/"
            "GUESTS_CANONICAL.csv"
        ),
        "max_records": 1,
        "writes_allowed": False,
    }
    data.update(overrides)
    return data


def bounded_lookup_request(**overrides):
    data = {
        "lookup_id": "lookup-known",
        "source_contract_id": "alexis_guest_db",
        "lookup_mode": "fixed_id",
        "query": None,
        "lookup_key": "entity_id",
        "lookup_value": "dr_saju_matthew",
        "max_records": 1,
    }
    data.update(overrides)
    return data


def with_temp_registry(entries):
    root = Path(tempfile.mkdtemp())
    path = root / REGISTRY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "adapters": entries}),
        encoding="utf-8",
    )
    clear_cache()
    return root


def cleanup(root):
    shutil.rmtree(root)
    clear_cache()


def disabled_contract():
    return ContextAdapterContract(
        adapter_id="synthetic_guest_context",
        source_contract_id="alexis_guest_db",
        enabled=False,
        adapter_type="synthetic",
        execution_mode="synthetic_only",
        external_reads_allowed=False,
        read_scope=None,
        read_target=None,
        max_records=None,
        writes_allowed=None,
        raw_data={},
    )


def test_adapter_registry_loads():
    contracts = list_context_adapter_contracts(ROOT)

    assert len(contracts) == 3
    assert contracts[0].adapter_id == "synthetic_guest_context"
    assert contracts[0].source_contract_id == "alexis_guest_db"
    assert contracts[0].external_reads_allowed is False
    assert contracts[1].adapter_id == "guest_db_readonly_fixture"
    assert contracts[1].enabled is False
    assert contracts[1].external_reads_allowed is True
    assert contracts[1].read_scope == "local_fixture_file"
    assert (
        contracts[1].read_target
        == "tools/fixtures/guest_db_readonly_fixture.json"
    )
    assert contracts[1].max_records == 1
    assert contracts[1].writes_allowed is False
    assert contracts[2].adapter_id == "guest_db_readonly"
    assert contracts[2].enabled is False
    assert contracts[2].execution_mode == "read_only_fixed_id"
    assert contracts[2].read_scope == "declared_local_database"
    assert contracts[2].read_target == (
        "agents/alexis/adapters/guest_db/resources/canonical/"
        "GUESTS_CANONICAL.csv"
    )
    assert contracts[2].max_records == 1
    assert contracts[2].writes_allowed is False


def test_source_contract_id_resolves_to_synthetic_adapter_id():
    contract = get_context_adapter_for_source(
        "alexis_guest_db",
        root=ROOT,
    )

    assert contract is not None
    assert contract.adapter_id == "synthetic_guest_context"
    assert contract.enabled is True


def test_invalid_registry_shape_fails_closed():
    root = with_temp_registry(
        [
            adapter_entry(enabled="yes"),
        ]
    )

    try:
        assert list_context_adapter_contracts(root) == []
        assert get_context_adapter_for_source(
            "alexis_guest_db",
            root=root,
        ) is None
    finally:
        cleanup(root)


def test_missing_external_reads_allowed_fails_closed():
    entry = adapter_entry()
    entry.pop("external_reads_allowed")
    root = with_temp_registry([entry])

    try:
        assert list_context_adapter_contracts(root) == []
        assert get_context_adapter_for_source(
            "alexis_guest_db",
            root=root,
        ) is None
    finally:
        cleanup(root)


def test_non_bool_external_reads_allowed_fails_closed():
    root = with_temp_registry([
        adapter_entry(external_reads_allowed="no"),
    ])

    try:
        assert list_context_adapter_contracts(root) == []
        assert get_context_adapter_for_source(
            "alexis_guest_db",
            root=root,
        ) is None
    finally:
        cleanup(root)


def test_synthetic_only_external_reads_true_fails_closed():
    root = with_temp_registry([
        adapter_entry(external_reads_allowed=True),
    ])

    try:
        assert list_context_adapter_contracts(root) == []
        assert get_context_adapter_for_source(
            "alexis_guest_db",
            root=root,
        ) is None
    finally:
        cleanup(root)


def test_synthetic_only_external_reads_true_fails_strict_validation():
    root = with_temp_registry([
        adapter_entry(external_reads_allowed=True),
    ])

    try:
        try:
            load_context_adapter_registry_strict(root)
        except Exception as exc:
            assert "allows external reads" in str(exc)
        else:
            raise AssertionError("expected strict registry validation failure")
    finally:
        cleanup(root)


def test_fixture_adapter_with_external_read_metadata_passes():
    root = with_temp_registry([
        fixture_adapter_entry(),
    ])

    try:
        contracts = list_context_adapter_contracts(root)
    finally:
        cleanup(root)

    assert len(contracts) == 1
    assert contracts[0].adapter_id == "guest_db_readonly_fixture"
    assert contracts[0].read_scope == "local_fixture_file"
    assert (
        contracts[0].read_target
        == "tools/fixtures/guest_db_readonly_fixture.json"
    )
    assert contracts[0].max_records == 1
    assert contracts[0].writes_allowed is False


def test_external_read_adapter_missing_metadata_fails_closed():
    entry = fixture_adapter_entry()
    entry.pop("read_scope")
    root = with_temp_registry([entry])

    try:
        assert list_context_adapter_contracts(root) == []
        assert get_context_adapter_for_source(
            "alexis_guest_db",
            root=root,
        ) is None
    finally:
        cleanup(root)


def test_external_read_adapter_writes_allowed_true_fails_closed():
    root = with_temp_registry([
        fixture_adapter_entry(writes_allowed=True),
    ])

    try:
        assert list_context_adapter_contracts(root) == []
        assert get_context_adapter_for_source(
            "alexis_guest_db",
            root=root,
        ) is None
    finally:
        cleanup(root)


def test_read_only_fixture_max_records_gt_one_fails_closed():
    root = with_temp_registry([
        fixture_adapter_entry(max_records=2),
    ])

    try:
        assert list_context_adapter_contracts(root) == []
        assert get_context_adapter_for_source(
            "alexis_guest_db",
            root=root,
        ) is None
    finally:
        cleanup(root)


def test_disabled_declared_adapter_with_unconfigured_target_passes():
    root = with_temp_registry([
        declared_adapter_entry(),
    ])

    try:
        contracts = list_context_adapter_contracts(root)
    finally:
        cleanup(root)

    assert len(contracts) == 1
    assert contracts[0].adapter_id == "guest_db_readonly"
    assert contracts[0].enabled is False
    assert contracts[0].read_scope == "declared_local_database"
    assert contracts[0].read_target == "UNCONFIGURED"


def test_enabled_declared_adapter_unconfigured_target_fails_closed():
    root = with_temp_registry([
        declared_adapter_entry(enabled=True),
    ])

    try:
        assert list_context_adapter_contracts(root) == []
    finally:
        cleanup(root)


def test_enabled_declared_adapter_concrete_json_target_passes():
    root = with_temp_registry([
        declared_adapter_entry(
            enabled=True,
            read_target="data/guest_db.json",
        ),
    ])

    try:
        contracts = list_context_adapter_contracts(root)
    finally:
        cleanup(root)

    assert len(contracts) == 1
    assert contracts[0].enabled is True
    assert contracts[0].read_target == "data/guest_db.json"


def test_enabled_declared_adapter_concrete_sqlite_target_passes():
    root = with_temp_registry([
        declared_adapter_entry(
            enabled=True,
            read_target="data/guest_db.sqlite",
        ),
    ])

    try:
        contracts = list_context_adapter_contracts(root)
    finally:
        cleanup(root)

    assert len(contracts) == 1
    assert contracts[0].enabled is True
    assert contracts[0].read_target == "data/guest_db.sqlite"


def test_read_only_fixed_id_canonical_csv_target_passes():
    root = with_temp_registry([
        readonly_fixed_id_adapter_entry(enabled=True),
    ])

    try:
        contracts = list_context_adapter_contracts(root)
    finally:
        cleanup(root)

    assert len(contracts) == 1
    assert contracts[0].enabled is True
    assert contracts[0].execution_mode == "read_only_fixed_id"
    assert contracts[0].read_target == (
        "agents/alexis/adapters/guest_db/resources/canonical/"
        "GUESTS_CANONICAL.csv"
    )


def test_valid_adapter_lookup_request_passes_registry_validation():
    root = with_temp_registry([
        readonly_fixed_id_adapter_entry(
            enabled=True,
            bounded_lookup_request=bounded_lookup_request(),
        ),
    ])

    try:
        contracts = list_context_adapter_contracts(root)
    finally:
        cleanup(root)

    assert len(contracts) == 1
    assert contracts[0].lookup_request is not None
    assert contracts[0].lookup_request.lookup_id == "lookup-known"
    assert contracts[0].lookup_request.lookup_mode == "fixed_id"
    assert contracts[0].lookup_request.lookup_key == "entity_id"


def test_lookup_request_source_contract_id_mismatch_fails():
    root = with_temp_registry([
        readonly_fixed_id_adapter_entry(
            bounded_lookup_request=bounded_lookup_request(
                source_contract_id="wrong_source",
            ),
        ),
    ])

    try:
        assert list_context_adapter_contracts(root) == []
    finally:
        cleanup(root)


def test_lookup_request_max_records_gt_adapter_max_records_fails():
    root = with_temp_registry([
        readonly_fixed_id_adapter_entry(
            max_records=1,
            bounded_lookup_request=bounded_lookup_request(max_records=2),
        ),
    ])

    try:
        assert list_context_adapter_contracts(root) == []
    finally:
        cleanup(root)


def test_read_only_fixed_id_non_fixed_lookup_mode_fails():
    root = with_temp_registry([
        readonly_fixed_id_adapter_entry(
            bounded_lookup_request=bounded_lookup_request(
                lookup_mode="declared_fixture",
                lookup_key=None,
                lookup_value=None,
            ),
        ),
    ])

    try:
        assert list_context_adapter_contracts(root) == []
    finally:
        cleanup(root)


def test_read_only_fixed_id_max_records_gt_one_fails_closed():
    root = with_temp_registry([
        readonly_fixed_id_adapter_entry(max_records=2),
    ])

    try:
        assert list_context_adapter_contracts(root) == []
    finally:
        cleanup(root)


def test_declared_local_database_absolute_read_target_fails_closed():
    root = with_temp_registry([
        declared_adapter_entry(read_target="/data/guest_db.json"),
    ])

    try:
        assert list_context_adapter_contracts(root) == []
    finally:
        cleanup(root)


def test_declared_local_database_parent_path_fails_closed():
    root = with_temp_registry([
        declared_adapter_entry(read_target="data/../guest_db.json"),
    ])

    try:
        assert list_context_adapter_contracts(root) == []
    finally:
        cleanup(root)


def test_declared_local_database_wrong_prefix_fails_closed():
    root = with_temp_registry([
        declared_adapter_entry(read_target="tools/fixtures/guest_db.json"),
    ])

    try:
        assert list_context_adapter_contracts(root) == []
    finally:
        cleanup(root)


def test_declared_local_database_wrong_extension_fails_closed():
    root = with_temp_registry([
        declared_adapter_entry(read_target="data/guest_db.txt"),
    ])

    try:
        assert list_context_adapter_contracts(root) == []
    finally:
        cleanup(root)


def test_declared_local_database_writes_allowed_true_fails_closed():
    root = with_temp_registry([
        declared_adapter_entry(
            read_target="data/guest_db.json",
            writes_allowed=True,
        ),
    ])

    try:
        assert list_context_adapter_contracts(root) == []
    finally:
        cleanup(root)


def test_read_only_declared_max_records_gt_one_fails_closed():
    root = with_temp_registry([
        declared_adapter_entry(max_records=2),
    ])

    try:
        assert list_context_adapter_contracts(root) == []
    finally:
        cleanup(root)


def test_local_fixture_absolute_read_target_fails_closed():
    root = with_temp_registry([
        fixture_adapter_entry(read_target="/tools/fixtures/guest.json"),
    ])

    try:
        assert list_context_adapter_contracts(root) == []
    finally:
        cleanup(root)


def test_local_fixture_parent_path_read_target_fails_closed():
    root = with_temp_registry([
        fixture_adapter_entry(read_target="tools/fixtures/../guest.json"),
    ])

    try:
        assert list_context_adapter_contracts(root) == []
    finally:
        cleanup(root)


def test_local_fixture_wrong_prefix_read_target_fails_closed():
    root = with_temp_registry([
        fixture_adapter_entry(read_target="config/fixtures/guest.json"),
    ])

    try:
        assert list_context_adapter_contracts(root) == []
    finally:
        cleanup(root)


def test_local_fixture_non_json_read_target_fails_closed():
    root = with_temp_registry([
        fixture_adapter_entry(read_target="tools/fixtures/guest.txt"),
    ])

    try:
        assert list_context_adapter_contracts(root) == []
    finally:
        cleanup(root)


def test_disabled_adapter_mapping_fails_closed():
    original_lookup = composer.get_context_adapter_for_source

    def lookup(source_contract_id):
        return disabled_contract()

    composer.get_context_adapter_for_source = lookup

    try:
        with Env(
            JUNIPER_ENABLE_CONTEXT_INJECTION="1",
            JUNIPER_DISABLE_CONTEXT_INJECTION=None,
        ):
            result = compose_bounded_context(
                request_id="req_adapter_disabled",
                agent="alexis",
                shared_capability="draft_email",
                planner_mode="NEW_REQUEST",
            )
    finally:
        composer.get_context_adapter_for_source = original_lookup

    assert result.injection_performed is False
    assert result.rendered_blocks == []
    assert "context_adapter_mapping_unavailable" in result.skipped_reasons


def test_missing_adapter_mapping_fails_closed():
    original_lookup = composer.get_context_adapter_for_source

    def lookup(source_contract_id):
        return None

    composer.get_context_adapter_for_source = lookup

    try:
        with Env(
            JUNIPER_ENABLE_CONTEXT_INJECTION="1",
            JUNIPER_DISABLE_CONTEXT_INJECTION=None,
        ):
            result = compose_bounded_context(
                request_id="req_adapter_missing",
                agent="alexis",
                shared_capability="draft_email",
                planner_mode="NEW_REQUEST",
            )
    finally:
        composer.get_context_adapter_for_source = original_lookup

    assert result.injection_performed is False
    assert result.rendered_blocks == []
    assert "context_adapter_mapping_unavailable" in result.skipped_reasons


def test_compose_bounded_context_still_renders_same_block():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
    ):
        result = compose_bounded_context(
            request_id="req_adapter_registry",
            agent="alexis",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    assert result.injection_performed is True
    assert result.rendered_blocks == [MICRO_BLOCK]


def test_rollback_behavior_unchanged():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION="1",
    ):
        result = compose_bounded_context(
            request_id="req_adapter_registry_rollback",
            agent="alexis",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    assert result.injection_performed is False
    assert result.rendered_blocks == []
    assert "context_injection_rollback_enabled" in result.skipped_reasons


def test_telemetry_remains_content_safe():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
    ):
        result = compose_bounded_context(
            request_id="req_adapter_registry_telemetry",
            agent="alexis",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    assert forbidden_keys_in_payload(result.trace_payload) == []
    assert "BOUNDED CONTEXT" not in repr(result.trace_payload)


def main():
    test_adapter_registry_loads()
    test_source_contract_id_resolves_to_synthetic_adapter_id()
    test_invalid_registry_shape_fails_closed()
    test_missing_external_reads_allowed_fails_closed()
    test_non_bool_external_reads_allowed_fails_closed()
    test_synthetic_only_external_reads_true_fails_closed()
    test_synthetic_only_external_reads_true_fails_strict_validation()
    test_fixture_adapter_with_external_read_metadata_passes()
    test_external_read_adapter_missing_metadata_fails_closed()
    test_external_read_adapter_writes_allowed_true_fails_closed()
    test_read_only_fixture_max_records_gt_one_fails_closed()
    test_disabled_declared_adapter_with_unconfigured_target_passes()
    test_enabled_declared_adapter_unconfigured_target_fails_closed()
    test_enabled_declared_adapter_concrete_json_target_passes()
    test_enabled_declared_adapter_concrete_sqlite_target_passes()
    test_read_only_fixed_id_canonical_csv_target_passes()
    test_valid_adapter_lookup_request_passes_registry_validation()
    test_lookup_request_source_contract_id_mismatch_fails()
    test_lookup_request_max_records_gt_adapter_max_records_fails()
    test_read_only_fixed_id_non_fixed_lookup_mode_fails()
    test_read_only_fixed_id_max_records_gt_one_fails_closed()
    test_declared_local_database_absolute_read_target_fails_closed()
    test_declared_local_database_parent_path_fails_closed()
    test_declared_local_database_wrong_prefix_fails_closed()
    test_declared_local_database_wrong_extension_fails_closed()
    test_declared_local_database_writes_allowed_true_fails_closed()
    test_read_only_declared_max_records_gt_one_fails_closed()
    test_local_fixture_absolute_read_target_fails_closed()
    test_local_fixture_parent_path_read_target_fails_closed()
    test_local_fixture_wrong_prefix_read_target_fails_closed()
    test_local_fixture_non_json_read_target_fails_closed()
    test_disabled_adapter_mapping_fails_closed()
    test_missing_adapter_mapping_fails_closed()
    test_compose_bounded_context_still_renders_same_block()
    test_rollback_behavior_unchanged()
    test_telemetry_remains_content_safe()
    print("PASS context adapter registry")


if __name__ == "__main__":
    main()
