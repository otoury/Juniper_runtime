# runtime/validation_manager.py

from __future__ import annotations

from dataclasses import dataclass

from runtime.contracts.semantic_validation import looks_like_meta_response
from runtime.contracts.exceptions import ContractValidationError
from runtime.artifacts.extractors import normalize_artifact_response
from runtime.quality.registry import validate_normalized_artifact_quality


@dataclass
class ValidationResult:
    response: str
    actions: list
    parsed: object | None
    normalized_artifact: object | None = None


def validate_runtime_response(
    *,
    agent,
    plan,
    gate=None,
    normalized_response: str,
    parsed_payload,
    is_dry_run: bool,
    source_bot: str,
    user_id: str,
    request_id: str,
    report_event,
) -> ValidationResult:
    """
    Runtime validation lifecycle.

    Responsibilities:
    - parse structured agent output when present
    - enforce semantic anti-meta contract
    - strip actions for artifact-like outputs
    - run agent-owned contract validation

    Does NOT:
    - enqueue actions
    - persist artifacts
    - write memory
    """

    agent_validation = None

    if getattr(agent, "output_parser", None):
        parsed = agent.output_parser(normalized_response)
        response = parsed.assistant_response
        actions = parsed.actions
        if not is_dry_run and looks_like_meta_response(response):
            report_event(
                source_bot,
                "semantic_contract_failure",
                {
                    "user_id": user_id,
                    "agent": agent.name,
                    "response": response[:500],
                },
                request_id=request_id,
            )

            raise ValueError(
                "Semantic contract failure: "
                "model described completion "
                "instead of performing task."
            )

        if plan.expected_output_type in [
            "artifact",
            "translation",
            "summary",
        ]:
            actions = []

    else:
        parsed = None
        response = normalized_response
        actions = []
    normalized_artifact = None

    if not is_dry_run and plan.expected_output_type == "artifact":
        normalized_artifact = normalize_artifact_response(
            artifact_type=plan.semantic_output_type,
            response=response,
        )

        response = normalized_artifact.extracted_content
        parsed_payload = (
            normalized_artifact.structured_payload
            if normalized_artifact.structured_payload is not None
            else parsed_payload
        )
        
        report_event(
            source_bot,
            "artifact_normalized",
            {
                "user_id": user_id,
                "agent": agent.name,
                "semantic_output_type": plan.semantic_output_type,
                "normalized_content": response[:500],
            },
            request_id=request_id,
        )

    if not is_dry_run:
        agent_validation = agent.validate_response(
        plan=plan,
        response=response,
        actions=actions,
        parsed_payload=parsed_payload,
    )

    if agent_validation and not agent_validation.ok:
        report_event(
            source_bot,
            "contract_validation_failure",
            {
                "user_id": user_id,
                "agent": agent.name,
                "error": agent_validation.error,
                "violations": getattr(
                    agent_validation,
                    "violations",
                    None,
                ),
                "response": response[:500],
                "normalized_content": (
                    normalized_artifact.extracted_content[:500]
                    if normalized_artifact
                    else None
                ),
                "structured_payload": (
                    normalized_artifact.structured_payload
                    if normalized_artifact
                    else None
                ),
            },
            request_id=request_id,
        )

        raise ContractValidationError(
            message=(
                f"Contract validation failed: "
                f"{agent_validation.error}"
            ),
            violations=getattr(
                agent_validation,
                "violations",
                None,
            ),
        )
    if not is_dry_run and plan.expected_output_type == "artifact":

        quality = (
            validate_normalized_artifact_quality(
                artifact=normalized_artifact,
                interaction_mode=getattr(
                    gate,
                    "interaction_mode",
                    None,
                ),
                transform_type=getattr(
                    plan,
                    "transform_type",
                    None,
                ),
            )
        )

        if quality and not quality.ok:
            violations = [
                f"{v.code}: {v.message}"
                for v in quality.violations
            ]

            report_event(
                source_bot,
                "artifact_quality_failure",
                {
                    "user_id": user_id,
                    "agent": agent.name,
                    "semantic_output_type": plan.semantic_output_type,
                    "violations": violations,
                    "response": response[:500],
                },
                request_id=request_id,
            )

            raise ContractValidationError(
                message="Artifact quality validation failed.",
                violations=violations,
            )
            
            
    return ValidationResult(
        response=response,
        actions=actions,
        parsed=parsed,
        normalized_artifact=normalized_artifact,
    )


__all__ = [
    "ValidationResult",
    "validate_runtime_response",
]
