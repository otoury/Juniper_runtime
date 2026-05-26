from __future__ import annotations

from typing import Final


CANONICAL_BOUNDARY_TERMINOLOGY_VERSION: Final = "stage169_boundary_terms_v1"

SUBSTRATES: Final = frozenset({"governance", "retrieval", "visibility", "workflow"})

SEMANTIC_AUTHORITY_FIELDS: Final = frozenset(
    {
        "capability_escalation",
        "capability_escalation_allowed",
        "direct_response_type",
        "execution_target",
        "expected_output_type",
        "fallback_engines",
        "interaction_mode",
        "lookup_metadata",
        "memory_write_allowed",
        "memory_writes_allowed",
        "minimum_engine_tier",
        "needs_capability_context",
        "needs_followup_resolution",
        "needs_full_planning",
        "operation",
        "planner_semantic_authority",
        "requires_active_artifact",
        "requires_artifact_context",
        "requires_current_information",
        "requires_source_fidelity",
        "requires_web",
        "semantic_operation",
        "semantic_output_type",
        "shared_capability",
        "task_family",
        "transform_intent",
        "transform_type",
        "uses_active_artifact",
    }
)

MEMORY_FIELDS: Final = frozenset(
    {
        "memory_state",
        "memory_write",
        "memory_write_allowed",
        "memory_write_performed",
        "memory_writes_allowed",
    }
)

AUTONOMY_FIELDS: Final = frozenset(
    {
        "autonomy_escalation_allowed",
        "autonomy_escalation_performed",
        "hidden_autonomy",
        "hidden_autonomy_escalation_allowed",
        "hidden_autonomy_escalation_performed",
    }
)

MUTATION_FIELDS: Final = frozenset(
    {
        "artifact_mutation_performed",
        "candidate_mutation_performed",
        "cross_substrate_planner_mutation_performed",
        "db_write_performed",
        "governance_state_mutation_performed",
        "retrieval_policy_mutation_performed",
        "workflow_state_mutation_performed",
    }
)

SUBSTRATE_STATE_FIELDS: Final = {
    "governance": frozenset({"governance_state", "governance_policy"}),
    "retrieval": frozenset({"retrieval_policy", "lookup_metadata"}),
    "workflow": frozenset(
        {
            "workflow_state",
            "workflow_status",
            "workflow_state_mutation_performed",
        }
    ),
    "visibility": frozenset({"planner_prompt", "hidden_context_injection_performed"}),
}

ALLOWED_VISIBILITY_ATTACHMENT_TARGETS: Final = frozenset(
    {
        "audit_receipt",
        "operator_report",
        "planner_visible_governance_metadata",
        "telemetry",
    }
)

ALLOWED_DIAGNOSTIC_ATTACHMENT_TARGETS: Final = frozenset(
    {
        "audit_receipt",
        "operator_report",
        "telemetry",
    }
)

FORBIDDEN_ATTACHMENT_TARGETS: Final = frozenset(
    {
        "execution_planner_output",
        "governance_state",
        "lookup_metadata",
        "memory_state",
        "planner_prompt",
        "retrieval_policy",
        "semantic_planning_metadata",
        "workflow_state",
    }
)

FORBIDDEN_CONTENT_FIELDS: Final = frozenset(
    {
        "address",
        "api_key",
        "article_body",
        "authorization_header",
        "bearer_token",
        "citations",
        "contact",
        "contact_value",
        "credential",
        "credential_env_var",
        "email",
        "link",
        "phone",
        "prompt",
        "provider_payload",
        "query",
        "ranking",
        "raw_provider_payload",
        "raw_results",
        "rendered_context",
        "results",
        "secret",
        "snippet",
        "source_refs",
        "summary",
        "title",
        "token",
        "url",
    }
)

SEMANTIC_MUTATION_FIELDS: Final = SEMANTIC_AUTHORITY_FIELDS


def boundary_terms_policy() -> dict[str, object]:
    return {
        "terminology_version": CANONICAL_BOUNDARY_TERMINOLOGY_VERSION,
        "canonical_boundary_terms": {
            "semantic_authority_fields": sorted(SEMANTIC_AUTHORITY_FIELDS),
            "memory_fields": sorted(MEMORY_FIELDS),
            "autonomy_fields": sorted(AUTONOMY_FIELDS),
            "mutation_fields": sorted(MUTATION_FIELDS),
            "substrate_state_fields": {
                key: sorted(value)
                for key, value in sorted(SUBSTRATE_STATE_FIELDS.items())
            },
            "forbidden_content_fields": sorted(FORBIDDEN_CONTENT_FIELDS),
            "allowed_visibility_attachment_targets": sorted(
                ALLOWED_VISIBILITY_ATTACHMENT_TARGETS
            ),
            "allowed_diagnostic_attachment_targets": sorted(
                ALLOWED_DIAGNOSTIC_ATTACHMENT_TARGETS
            ),
            "forbidden_attachment_targets": sorted(FORBIDDEN_ATTACHMENT_TARGETS),
        },
        "compatibility_aliases": {
            "semantic_mutation_fields": "semantic_authority_fields",
        },
        "fail_closed": True,
    }


__all__ = [
    "ALLOWED_DIAGNOSTIC_ATTACHMENT_TARGETS",
    "ALLOWED_VISIBILITY_ATTACHMENT_TARGETS",
    "AUTONOMY_FIELDS",
    "CANONICAL_BOUNDARY_TERMINOLOGY_VERSION",
    "FORBIDDEN_ATTACHMENT_TARGETS",
    "FORBIDDEN_CONTENT_FIELDS",
    "MEMORY_FIELDS",
    "MUTATION_FIELDS",
    "SEMANTIC_AUTHORITY_FIELDS",
    "SEMANTIC_MUTATION_FIELDS",
    "SUBSTRATE_STATE_FIELDS",
    "SUBSTRATES",
    "boundary_terms_policy",
]
