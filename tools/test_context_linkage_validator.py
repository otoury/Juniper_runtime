import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.context_micro_injection import (  # noqa: E402
    MICRO_BLOCK,
    maybe_apply_micro_context_injection,
)
from runtime.registries.context_injection_binding_registry import (  # noqa: E402
    load_context_injection_registry,
)
from runtime.registries.context_linkage_validator import (  # noqa: E402
    validate_context_injection_source_linkages,
)
from runtime.registries.resource_binding_registry import (  # noqa: E402
    load_context_source_registry,
)


INJECTIONS_PATH = Path("agents/alexis/bindings/context_injections.json")
SOURCES_PATH = Path("agents/alexis/bindings/resources.json")


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


def write_registry(root: Path, injections, sources):
    injections_path = root / INJECTIONS_PATH
    sources_path = root / SOURCES_PATH
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


def with_temp_registry(injections, sources):
    temp_root = Path(tempfile.mkdtemp())
    write_registry(
        temp_root,
        injections,
        sources,
    )
    return temp_root


def cleanup(root: Path):
    shutil.rmtree(root)
    clear_caches()


def error_codes(linkages):
    return [
        error.error_code
        for linkage in linkages
        for error in linkage.errors
    ]


def test_valid_linkage_passes():
    linkages = validate_context_injection_source_linkages(ROOT)

    assert len(linkages) == 1
    assert linkages[0].valid is True
    assert linkages[0].injection_id == "alexis_guest_context_notice"
    assert linkages[0].source_contract_id == "alexis_guest_db"
    assert linkages[0].errors == []


def test_missing_source_contract_fails_validation():
    root = with_temp_registry(
        [base_injection(source_contract_id="missing_source")],
        [base_source()],
    )

    try:
        linkages = validate_context_injection_source_linkages(root)
    finally:
        cleanup(root)

    assert linkages[0].valid is False
    assert "missing_source_contract" in error_codes(linkages)


def test_capability_mismatch_fails_validation():
    root = with_temp_registry(
        [base_injection(shared_capability_scope=["draft_email"])],
        [base_source(allowed_capabilities=["producer_note"])],
    )

    try:
        linkages = validate_context_injection_source_linkages(root)
    finally:
        cleanup(root)

    assert linkages[0].valid is False
    assert "capability_scope_mismatch" in error_codes(linkages)


def test_provenance_mismatch_fails_validation():
    root = with_temp_registry(
        [base_injection(requires_provenance_validation=False)],
        [base_source(requires_provenance_validation=True)],
    )

    try:
        linkages = validate_context_injection_source_linkages(root)
    finally:
        cleanup(root)

    assert linkages[0].valid is False
    assert "provenance_requirement_mismatch" in error_codes(linkages)


def test_token_budget_metadata_resolves():
    linkages = validate_context_injection_source_linkages(ROOT)

    assert linkages[0].injection_max_tokens == 80
    assert linkages[0].source_max_injection_tokens == 256


def test_runtime_injection_behavior_remains_unchanged():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
        JUNIPER_ENABLE_CONTEXT_INJECTION_CAPABILITIES=None,
    ):
        result = maybe_apply_micro_context_injection(
            [{"role": "user", "content": "draft outreach"}],
            request_id="req_linkage_runtime",
            agent_name="alexis",
            shared_capability="draft_email",
            operation="NEW_REQUEST",
        )

    assert result.injection_performed is True
    assert result.messages[-1]["content"] == MICRO_BLOCK
    assert result.sources == ["alexis.guest_db"]


def main():
    test_valid_linkage_passes()
    test_missing_source_contract_fails_validation()
    test_capability_mismatch_fails_validation()
    test_provenance_mismatch_fails_validation()
    test_token_budget_metadata_resolves()
    test_runtime_injection_behavior_remains_unchanged()
    print("PASS context linkage validator")


if __name__ == "__main__":
    main()
