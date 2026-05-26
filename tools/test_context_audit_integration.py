import contextlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.registries.context_injection_binding_registry import (  # noqa: E402
    load_context_injection_registry,
)
from runtime.registries.resource_binding_registry import (  # noqa: E402
    load_context_source_registry,
)
from tools.audit_registry_ownership import (  # noqa: E402
    audit_context_adapter_registry,
    audit_context_registry_linkages,
)


INJECTIONS_PATH = Path("agents/alexis/bindings/context_injections.json")
SOURCES_PATH = Path("agents/alexis/bindings/resources.json")
ADAPTERS_PATH = Path("agents/alexis/bindings/adapters.json")


def clear_caches():
    load_context_injection_registry.cache_clear()
    load_context_source_registry.cache_clear()


def base_injection(**overrides):
    data = {
        "id": "alexis_guest_context_notice",
        "enabled": True,
        "agent_scope": ["alexis"],
        "shared_capability_scope": ["draft_email"],
        "source_contract_id": "alexis_guest_db",
        "operation_scope": ["NEW_REQUEST"],
        "injection_mode": "synthetic",
        "content": "[Bounded guest context: guest_db is available for booking context.]",
        "source_name": "alexis.guest_db",
        "source_type": "agent_resource",
        "max_items": 1,
        "max_tokens": 80,
        "requires_provenance_validation": True,
        "rollback_env_flag": "JUNIPER_DISABLE_CONTEXT_INJECTION",
        "telemetry_label": "guest_context_notice",
    }
    data.update(overrides)
    return data


def base_source(**overrides):
    data = {
        "binding_id": "alexis_guest_db",
        "adapter_type": "structured_database",
        "enabled": False,
        "allowed_capabilities": ["draft_email"],
        "requires_provenance_validation": True,
        "max_injection_tokens": 256,
        "execution_mode": "manual_future",
        "description": "Structured guest booking database.",
    }
    data.update(overrides)
    return data


def base_adapter(**overrides):
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


def fixture_adapter(**overrides):
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


def declared_adapter(**overrides):
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


def readonly_fixed_id_adapter(**overrides):
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
        "bounded_lookup_request": {
            "lookup_id": "lookup-known",
            "source_contract_id": "alexis_guest_db",
            "lookup_mode": "fixed_id",
            "query": "sensitive query text",
            "lookup_key": "entity_id",
            "lookup_value": "dr_saju_matthew",
            "max_records": 1,
        },
    }
    data.update(overrides)
    return data


def with_temp_registry(injections, sources):
    temp_root = Path(tempfile.mkdtemp())
    injections_path = temp_root / INJECTIONS_PATH
    sources_path = temp_root / SOURCES_PATH
    injections_path.parent.mkdir(parents=True, exist_ok=True)
    sources_path.parent.mkdir(parents=True, exist_ok=True)
    injections_path.write_text(
        json.dumps({"version": 1, "injections": injections}),
        encoding="utf-8",
    )
    sources_path.write_text(
        json.dumps({"version": 1, "bindings": sources}),
        encoding="utf-8",
    )
    clear_caches()
    return temp_root


def with_temp_adapter_registry(sources, adapters):
    temp_root = Path(tempfile.mkdtemp())
    sources_path = temp_root / SOURCES_PATH
    adapters_path = temp_root / ADAPTERS_PATH
    sources_path.parent.mkdir(parents=True, exist_ok=True)
    adapters_path.parent.mkdir(parents=True, exist_ok=True)
    sources_path.write_text(
        json.dumps({"version": 1, "bindings": sources}),
        encoding="utf-8",
    )
    adapters_path.write_text(
        json.dumps({"version": 1, "adapters": adapters}),
        encoding="utf-8",
    )
    clear_caches()
    return temp_root


def cleanup(root: Path):
    shutil.rmtree(root)
    clear_caches()


def run_audit(root: Path):
    buffer = io.StringIO()

    with contextlib.redirect_stdout(buffer):
        count, errors = audit_context_registry_linkages(root)

    return count, errors, buffer.getvalue()


def run_adapter_audit(root: Path):
    buffer = io.StringIO()

    with contextlib.redirect_stdout(buffer):
        count, errors = audit_context_adapter_registry(root)

    return count, errors, buffer.getvalue()


def test_audit_passes_with_valid_linkage():
    root = with_temp_registry(
        [base_injection()],
        [base_source()],
    )

    try:
        count, errors, output = run_audit(root)
    finally:
        cleanup(root)

    assert count == 1
    assert errors == 0
    assert "OK: context linkage" in output
    assert "alexis_guest_context_notice -> alexis_guest_db" in output


def test_audit_fails_nonzero_with_missing_source_linkage():
    root = with_temp_registry(
        [base_injection(source_contract_id="missing_source")],
        [base_source()],
    )

    try:
        count, errors, output = run_audit(root)
    finally:
        cleanup(root)

    assert count == 1
    assert errors > 0
    assert "ERROR context linkage" in output
    assert "alexis_guest_context_notice -> missing_source" in output
    assert "missing_source_contract" in output


def test_audit_fails_nonzero_with_capability_mismatch():
    root = with_temp_registry(
        [base_injection(shared_capability_scope=["draft_email"])],
        [base_source(allowed_capabilities=["producer_note"])],
    )

    try:
        count, errors, output = run_audit(root)
    finally:
        cleanup(root)

    assert count == 1
    assert errors > 0
    assert "ERROR context linkage" in output
    assert "alexis_guest_context_notice -> alexis_guest_db" in output
    assert "capability_scope_mismatch" in output


def test_audit_output_includes_injection_and_source_ids():
    root = with_temp_registry(
        [base_injection()],
        [base_source()],
    )

    try:
        _, _, output = run_audit(root)
    finally:
        cleanup(root)

    assert "alexis_guest_context_notice" in output
    assert "alexis_guest_db" in output


def test_adapter_audit_passes_with_valid_mapping():
    root = with_temp_adapter_registry(
        [base_source()],
        [base_adapter()],
    )

    try:
        count, errors, output = run_adapter_audit(root)
    finally:
        cleanup(root)

    assert count == 1
    assert errors == 0
    assert "OK: context adapter mapping" in output
    assert "alexis_guest_db -> synthetic_guest_context" in output
    assert "external_reads_allowed=False" in output
    assert "compatibility=OK" in output


def test_adapter_audit_fails_with_permission_incompatibility():
    root = with_temp_adapter_registry(
        [base_source()],
        [base_adapter(external_reads_allowed=True)],
    )

    try:
        count, errors, output = run_adapter_audit(root)
    finally:
        cleanup(root)

    assert count == 0
    assert errors > 0
    assert "ERROR context adapter registry" in output
    assert "allows external reads" in output


def test_adapter_audit_fails_with_missing_source():
    root = with_temp_adapter_registry(
        [base_source()],
        [base_adapter(source_contract_id="missing_source")],
    )

    try:
        count, errors, output = run_adapter_audit(root)
    finally:
        cleanup(root)

    assert count == 1
    assert errors > 0
    assert "ERROR context adapter mapping" in output
    assert "missing_source -> synthetic_guest_context" in output
    assert "missing context source contract" in output


def test_adapter_audit_fails_with_unsupported_adapter_type():
    root = with_temp_adapter_registry(
        [base_source()],
        [base_adapter(adapter_type="database")],
    )

    try:
        count, errors, output = run_adapter_audit(root)
    finally:
        cleanup(root)

    assert count == 0
    assert errors > 0
    assert "ERROR context adapter registry" in output
    assert "unsupported adapter_type" in output


def test_adapter_audit_fails_with_unsupported_execution_mode():
    root = with_temp_adapter_registry(
        [base_source()],
        [base_adapter(execution_mode="live")],
    )

    try:
        count, errors, output = run_adapter_audit(root)
    finally:
        cleanup(root)

    assert count == 0
    assert errors > 0
    assert "ERROR context adapter registry" in output
    assert "unsupported execution_mode" in output


def test_adapter_audit_fails_with_duplicate_source_mapping():
    root = with_temp_adapter_registry(
        [base_source()],
        [
            base_adapter(adapter_id="synthetic_guest_context"),
            base_adapter(adapter_id="synthetic_guest_context_duplicate"),
        ],
    )

    try:
        count, errors, output = run_adapter_audit(root)
    finally:
        cleanup(root)

    assert count == 2
    assert errors == 2
    assert "duplicate enabled source_contract_id mapping" in output


def test_adapter_audit_reports_disabled_mapping_as_inert():
    root = with_temp_adapter_registry(
        [base_source()],
        [base_adapter(enabled=False)],
    )

    try:
        count, errors, output = run_adapter_audit(root)
    finally:
        cleanup(root)

    assert count == 1
    assert errors == 0
    assert "DISABLED inert context adapter mapping" in output
    assert "alexis_guest_db -> synthetic_guest_context" in output


def test_adapter_audit_reports_external_read_metadata():
    root = with_temp_adapter_registry(
        [base_source()],
        [fixture_adapter()],
    )

    try:
        count, errors, output = run_adapter_audit(root)
    finally:
        cleanup(root)

    assert count == 1
    assert errors == 0
    assert "DISABLED inert context adapter mapping" in output
    assert "alexis_guest_db -> guest_db_readonly_fixture" in output
    assert "read_scope=local_fixture_file" in output
    assert "read_target=tools/fixtures/guest_db_readonly_fixture.json" in output
    assert "max_records=1" in output
    assert "writes_allowed=False" in output


def test_adapter_audit_reports_disabled_declared_adapter_as_inert():
    root = with_temp_adapter_registry(
        [base_source()],
        [declared_adapter()],
    )

    try:
        count, errors, output = run_adapter_audit(root)
    finally:
        cleanup(root)

    assert count == 1
    assert errors == 0
    assert "DISABLED inert context adapter mapping" in output
    assert "alexis_guest_db -> guest_db_readonly" in output
    assert "execution_mode=read_only_declared" in output
    assert "read_scope=declared_local_database" in output
    assert "read_target=UNCONFIGURED" in output
    assert "max_records=1" in output
    assert "writes_allowed=False" in output


def test_adapter_audit_fails_enabled_declared_unconfigured_target():
    root = with_temp_adapter_registry(
        [base_source()],
        [declared_adapter(enabled=True)],
    )

    try:
        count, errors, output = run_adapter_audit(root)
    finally:
        cleanup(root)

    assert count == 0
    assert errors > 0
    assert "ERROR context adapter registry" in output
    assert "must not be UNCONFIGURED when enabled=true" in output


def test_adapter_audit_reports_safe_lookup_request_metadata():
    root = with_temp_adapter_registry(
        [base_source()],
        [readonly_fixed_id_adapter()],
    )

    try:
        count, errors, output = run_adapter_audit(root)
    finally:
        cleanup(root)

    assert count == 1
    assert errors == 0
    assert "lookup_id=lookup-known" in output
    assert "lookup_mode=fixed_id" in output
    assert "lookup_key=entity_id" in output
    assert "lookup_value" not in output
    assert "dr_saju_matthew" not in output
    assert "sensitive query text" not in output


def test_adapter_audit_fails_lookup_request_source_mismatch():
    root = with_temp_adapter_registry(
        [base_source()],
        [
            readonly_fixed_id_adapter(
                bounded_lookup_request={
                    "lookup_id": "lookup-known",
                    "source_contract_id": "wrong_source",
                    "lookup_mode": "fixed_id",
                    "query": None,
                    "lookup_key": "entity_id",
                    "lookup_value": "dr_saju_matthew",
                    "max_records": 1,
                },
            ),
        ],
    )

    try:
        count, errors, output = run_adapter_audit(root)
    finally:
        cleanup(root)

    assert count == 0
    assert errors > 0
    assert "ERROR context adapter registry" in output
    assert "source_contract_id must match" in output


def test_adapter_audit_fails_lookup_request_max_records_exceeds_adapter():
    root = with_temp_adapter_registry(
        [base_source()],
        [
            readonly_fixed_id_adapter(
                bounded_lookup_request={
                    "lookup_id": "lookup-known",
                    "source_contract_id": "alexis_guest_db",
                    "lookup_mode": "fixed_id",
                    "query": None,
                    "lookup_key": "entity_id",
                    "lookup_value": "dr_saju_matthew",
                    "max_records": 2,
                },
            ),
        ],
    )

    try:
        count, errors, output = run_adapter_audit(root)
    finally:
        cleanup(root)

    assert count == 0
    assert errors > 0
    assert "ERROR context adapter registry" in output
    assert "max_records" in output


def test_adapter_audit_fails_fixed_id_adapter_non_fixed_lookup_mode():
    root = with_temp_adapter_registry(
        [base_source()],
        [
            readonly_fixed_id_adapter(
                bounded_lookup_request={
                    "lookup_id": "lookup-known",
                    "source_contract_id": "alexis_guest_db",
                    "lookup_mode": "declared_fixture",
                    "query": None,
                    "lookup_key": None,
                    "lookup_value": None,
                    "max_records": 1,
                },
            ),
        ],
    )

    try:
        count, errors, output = run_adapter_audit(root)
    finally:
        cleanup(root)

    assert count == 0
    assert errors > 0
    assert "ERROR context adapter registry" in output
    assert "requires lookup_mode='fixed_id'" in output


def test_adapter_audit_passes_enabled_declared_concrete_target():
    root = with_temp_adapter_registry(
        [base_source()],
        [
            declared_adapter(
                enabled=True,
                read_target="data/guest_db.json",
            ),
        ],
    )

    try:
        count, errors, output = run_adapter_audit(root)
    finally:
        cleanup(root)

    assert count == 1
    assert errors == 0
    assert "OK: context adapter mapping" in output
    assert "alexis_guest_db -> guest_db_readonly" in output
    assert "execution_mode=read_only_declared" in output
    assert "read_scope=declared_local_database" in output
    assert "read_target=data/guest_db.json" in output


def test_adapter_audit_fails_declared_wrong_prefix():
    root = with_temp_adapter_registry(
        [base_source()],
        [
            declared_adapter(
                read_target="tools/fixtures/guest_db.json",
            ),
        ],
    )

    try:
        count, errors, output = run_adapter_audit(root)
    finally:
        cleanup(root)

    assert count == 0
    assert errors > 0
    assert "ERROR context adapter registry" in output
    assert "must start with 'data/'" in output


def test_adapter_audit_fails_with_unconfined_fixture_target():
    root = with_temp_adapter_registry(
        [base_source()],
        [fixture_adapter(read_target="../guest.json")],
    )

    try:
        count, errors, output = run_adapter_audit(root)
    finally:
        cleanup(root)

    assert count == 0
    assert errors > 0
    assert "ERROR context adapter registry" in output
    assert "must not contain '..'" in output


def main():
    test_audit_passes_with_valid_linkage()
    test_audit_fails_nonzero_with_missing_source_linkage()
    test_audit_fails_nonzero_with_capability_mismatch()
    test_audit_output_includes_injection_and_source_ids()
    test_adapter_audit_passes_with_valid_mapping()
    test_adapter_audit_fails_with_permission_incompatibility()
    test_adapter_audit_fails_with_missing_source()
    test_adapter_audit_fails_with_unsupported_adapter_type()
    test_adapter_audit_fails_with_unsupported_execution_mode()
    test_adapter_audit_fails_with_duplicate_source_mapping()
    test_adapter_audit_reports_disabled_mapping_as_inert()
    test_adapter_audit_reports_external_read_metadata()
    test_adapter_audit_reports_disabled_declared_adapter_as_inert()
    test_adapter_audit_fails_enabled_declared_unconfigured_target()
    test_adapter_audit_reports_safe_lookup_request_metadata()
    test_adapter_audit_fails_lookup_request_source_mismatch()
    test_adapter_audit_fails_lookup_request_max_records_exceeds_adapter()
    test_adapter_audit_fails_fixed_id_adapter_non_fixed_lookup_mode()
    test_adapter_audit_passes_enabled_declared_concrete_target()
    test_adapter_audit_fails_declared_wrong_prefix()
    test_adapter_audit_fails_with_unconfined_fixture_target()
    print("PASS context audit integration")


if __name__ == "__main__":
    main()
