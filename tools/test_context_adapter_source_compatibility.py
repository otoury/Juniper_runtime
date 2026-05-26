import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.context_adapter_source_compatibility import (
    validate_context_adapter_source_compatibility,
)


def source(**overrides):
    data = {
        "source_type": "structured_database",
        "execution_mode": "manual_future",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def adapter(**overrides):
    data = {
        "adapter_type": "synthetic",
        "execution_mode": "synthetic_only",
        "external_reads_allowed": False,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def error_codes(errors):
    return [error.error_code for error in errors]


def test_current_synthetic_mapping_passes():
    assert validate_context_adapter_source_compatibility(
        source=source(),
        adapter=adapter(),
    ) == []


def test_synthetic_only_external_reads_true_fails():
    errors = validate_context_adapter_source_compatibility(
        source=source(),
        adapter=adapter(external_reads_allowed=True),
    )

    assert error_codes(errors) == ["synthetic_only_external_reads"]


def test_non_synthetic_external_source_without_permission_fails():
    errors = validate_context_adapter_source_compatibility(
        source=source(),
        adapter=adapter(
            adapter_type="structured_database",
            execution_mode="read_only_fixture",
            external_reads_allowed=False,
        ),
    )

    assert "external_source_requires_read_permission" in error_codes(errors)


def test_read_only_fixture_external_source_with_permission_passes():
    errors = validate_context_adapter_source_compatibility(
        source=source(),
        adapter=adapter(
            adapter_type="structured_database",
            execution_mode="read_only_fixture",
            external_reads_allowed=True,
        ),
    )

    assert errors == []


def test_read_only_declared_external_source_with_permission_passes():
    errors = validate_context_adapter_source_compatibility(
        source=source(),
        adapter=adapter(
            adapter_type="structured_database",
            execution_mode="read_only_declared",
            external_reads_allowed=True,
        ),
    )

    assert errors == []


def test_read_only_declared_without_permission_fails():
    errors = validate_context_adapter_source_compatibility(
        source=source(),
        adapter=adapter(
            adapter_type="structured_database",
            execution_mode="read_only_declared",
            external_reads_allowed=False,
        ),
    )

    assert "external_source_requires_read_permission" in error_codes(errors)
    assert "read_only_declared_external_reads" in error_codes(errors)


def test_unsupported_source_adapter_compatibility_fails_clearly():
    errors = validate_context_adapter_source_compatibility(
        source=source(source_type="unknown_source"),
        adapter=adapter(adapter_type="unknown_adapter"),
    )

    assert "unsupported_source_type" in error_codes(errors)
    assert "unsupported_adapter_type" in error_codes(errors)


def main():
    test_current_synthetic_mapping_passes()
    test_synthetic_only_external_reads_true_fails()
    test_non_synthetic_external_source_without_permission_fails()
    test_read_only_fixture_external_source_with_permission_passes()
    test_read_only_declared_external_source_with_permission_passes()
    test_read_only_declared_without_permission_fails()
    test_unsupported_source_adapter_compatibility_fails_clearly()
    print("PASS context adapter source compatibility")


if __name__ == "__main__":
    main()
