import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.context_micro_injection import (  # noqa: E402
    MICRO_BLOCK,
    maybe_apply_micro_context_injection,
)
from runtime.context_types import (  # noqa: E402
    ALLOWED_RENDERING_POLICIES,
    ResolvedContextItem,
    ResolvedContextProvenance,
    resolved_context_item_dict,
    validate_context_item_source_contract,
    validate_rendering_policy,
    validate_resolved_context_item,
    validate_resolved_context_provenance,
)


def valid_item(**overrides):
    data = {
        "id": "ctx_1",
        "source_contract_id": "alexis_guest_db",
        "content": "[Bounded guest context: guest_db is available for booking context.]",
        "content_type": "synthetic_notice",
        "provenance": ResolvedContextProvenance(
            source_contract_id="alexis_guest_db",
            retrieval_executed=False,
            attribution="synthetic_system_notice",
        ),
        "estimated_tokens": 8,
        "trust_level": "system_declared",
        "rendering_policy": "bounded_context_block",
        "metadata": {
            "source_type": "agent_resource",
        },
    }
    data.update(overrides)
    return ResolvedContextItem(**data)


def error_fields(item):
    return {
        error.field
        for error in validate_resolved_context_item(item)
    }


def provenance_error_fields(provenance):
    return {
        error.field
        for error in validate_resolved_context_provenance(provenance)
    }


def test_valid_resolved_context_item_can_be_constructed():
    item = valid_item()

    assert item.id == "ctx_1"
    assert item.source_contract_id == "alexis_guest_db"
    assert validate_resolved_context_item(item) == []


def test_valid_provenance_validates():
    provenance = ResolvedContextProvenance(
        source_contract_id="alexis_guest_db",
        retrieval_executed=False,
        attribution="synthetic_system_notice",
    )

    assert validate_resolved_context_provenance(provenance) == []


def test_empty_provenance_source_contract_id_fails():
    provenance = ResolvedContextProvenance(
        source_contract_id="",
        retrieval_executed=False,
        attribution="synthetic_system_notice",
    )

    assert "provenance.source_contract_id" in provenance_error_fields(
        provenance
    )


def test_empty_provenance_attribution_fails():
    provenance = ResolvedContextProvenance(
        source_contract_id="alexis_guest_db",
        retrieval_executed=False,
        attribution="",
    )

    assert "provenance.attribution" in provenance_error_fields(
        provenance
    )


def test_non_bool_retrieval_executed_fails():
    provenance = ResolvedContextProvenance(
        source_contract_id="alexis_guest_db",
        retrieval_executed="no",
        attribution="synthetic_system_notice",
    )

    assert "provenance.retrieval_executed" in provenance_error_fields(
        provenance
    )


def test_empty_source_contract_id_fails_validation():
    item = valid_item(source_contract_id="")

    assert "source_contract_id" in error_fields(item)


def test_matching_item_and_provenance_source_contract_passes():
    item = valid_item()

    assert validate_context_item_source_contract(item) == []


def test_mismatched_item_and_provenance_source_contract_fails():
    item = valid_item(
        provenance=ResolvedContextProvenance(
            source_contract_id="different_source",
            retrieval_executed=False,
            attribution="synthetic_system_notice",
        )
    )
    errors = validate_context_item_source_contract(item)

    assert "source_contract_id" in error_fields(item)
    assert any(
        error.error_code == "context_source_contract_mismatch"
        for error in errors
    )


def test_declared_source_exists_when_required():
    item = valid_item()

    assert validate_context_item_source_contract(
        item,
        require_declared_source=True,
        root=ROOT,
    ) == []


def test_missing_declared_source_fails_when_required():
    item = valid_item(
        source_contract_id="missing_source",
        provenance=ResolvedContextProvenance(
            source_contract_id="missing_source",
            retrieval_executed=False,
            attribution="synthetic_system_notice",
        ),
    )
    errors = validate_context_item_source_contract(
        item,
        require_declared_source=True,
        root=ROOT,
    )

    assert any(
        error.error_code == "context_source_contract_not_declared"
        for error in errors
    )


def test_empty_content_fails_validation():
    item = valid_item(content="")

    assert "content" in error_fields(item)


def test_negative_token_estimate_fails_validation():
    item = valid_item(estimated_tokens=-1)

    assert "estimated_tokens" in error_fields(item)


def test_each_allowed_rendering_policy_validates():
    assert ALLOWED_RENDERING_POLICIES == {
        "inline_notice",
        "bounded_context_block",
        "cite_only",
        "hidden_from_prompt",
    }

    for policy in ALLOWED_RENDERING_POLICIES:
        assert validate_rendering_policy(policy) is None
        assert validate_resolved_context_item(
            valid_item(rendering_policy=policy)
        ) == []


def test_unknown_rendering_policy_fails_validation():
    item = valid_item(rendering_policy="prompt_spaghetti")
    errors = validate_resolved_context_item(item)

    assert "rendering_policy" in error_fields(item)
    assert any(
        error.error_code == "invalid_rendering_policy"
        for error in errors
    )


def test_empty_rendering_policy_fails_validation():
    item = valid_item(rendering_policy="")
    errors = validate_resolved_context_item(item)

    assert "rendering_policy" in error_fields(item)
    assert any(
        error.error_code == "invalid_rendering_policy"
        for error in errors
    )


def test_serialization_preserves_required_fields():
    item = valid_item()
    data = resolved_context_item_dict(item)

    assert data["id"] == "ctx_1"
    assert data["source_contract_id"] == "alexis_guest_db"
    assert data["content_type"] == "synthetic_notice"
    assert data["provenance"]["source_contract_id"] == "alexis_guest_db"
    assert data["provenance"]["retrieval_executed"] is False
    assert data["provenance"]["attribution"] == "synthetic_system_notice"
    assert data["estimated_tokens"] == 8
    assert data["trust_level"] == "system_declared"
    assert data["rendering_policy"] == "bounded_context_block"


def test_synthetic_injection_behavior_remains_unchanged():
    import os

    previous_enable = os.environ.get("JUNIPER_ENABLE_CONTEXT_INJECTION")
    previous_disable = os.environ.get("JUNIPER_DISABLE_CONTEXT_INJECTION")

    try:
        os.environ["JUNIPER_ENABLE_CONTEXT_INJECTION"] = "1"
        os.environ.pop("JUNIPER_DISABLE_CONTEXT_INJECTION", None)
        result = maybe_apply_micro_context_injection(
            [{"role": "user", "content": "draft outreach"}],
            request_id="req_context_types",
            agent_name="alexis",
            shared_capability="draft_email",
            operation="NEW_REQUEST",
        )
    finally:
        if previous_enable is None:
            os.environ.pop("JUNIPER_ENABLE_CONTEXT_INJECTION", None)
        else:
            os.environ["JUNIPER_ENABLE_CONTEXT_INJECTION"] = previous_enable

        if previous_disable is None:
            os.environ.pop("JUNIPER_DISABLE_CONTEXT_INJECTION", None)
        else:
            os.environ["JUNIPER_DISABLE_CONTEXT_INJECTION"] = previous_disable

    assert result.injection_performed is True
    assert result.messages[-1]["content"] == MICRO_BLOCK
    assert result.sources == ["alexis.guest_db"]


def main():
    test_valid_resolved_context_item_can_be_constructed()
    test_valid_provenance_validates()
    test_empty_provenance_source_contract_id_fails()
    test_empty_provenance_attribution_fails()
    test_non_bool_retrieval_executed_fails()
    test_empty_source_contract_id_fails_validation()
    test_matching_item_and_provenance_source_contract_passes()
    test_mismatched_item_and_provenance_source_contract_fails()
    test_declared_source_exists_when_required()
    test_missing_declared_source_fails_when_required()
    test_empty_content_fails_validation()
    test_negative_token_estimate_fails_validation()
    test_each_allowed_rendering_policy_validates()
    test_unknown_rendering_policy_fails_validation()
    test_empty_rendering_policy_fails_validation()
    test_serialization_preserves_required_fields()
    test_synthetic_injection_behavior_remains_unchanged()
    print("PASS context types")


if __name__ == "__main__":
    main()
