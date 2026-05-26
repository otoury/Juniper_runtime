from __future__ import annotations

import json

from runtime.artifacts.extractors import normalize_artifact_response
from runtime.runtime_manager import execute_with_fallbacks
from runtime.response_pipeline import process_response
from runtime.loaders.contract_loader import (
    load_contract_schema,
    load_contract_repair_prompt,
)
from runtime.registries.contracts import (
    build_contract_prompt_block,
)


def build_contract_repair_messages(
    *,
    original_messages: list[dict],
    raw_response: str,
    violations: list[str],
    agent,
    plan,
) -> list[dict]:
    schema = load_contract_schema(
        agent_root=agent.agent_root,
        name=plan.semantic_output_type,
    )

    contract_block = build_contract_prompt_block(
        "artifact_repair"
    )

    normalized_artifact = normalize_artifact_response(
        artifact_type=plan.semantic_output_type,
        response=raw_response,
    )

    repair_prompt = load_contract_repair_prompt(
        agent_root=agent.agent_root,
        name=plan.semantic_output_type,
    )

    if not repair_prompt:
        repair_prompt = """
Your previous response violated the output contract.
Repair the canonical artifact content only.
Do not explain the repair.
"""

    transform_repair_note = ""

    if _allows_compact_email_transform(plan):
        transform_repair_note = """
For this email_draft transformation, a compact email is valid.
Preserve the email_draft artifact type.
Include a salutation, body, concrete ask, and signoff.
Do not add artificial extra paragraphs just to satisfy structure.
Do not include labels, field names, explanations, or meta-language.
"""

    repair_user_message = (
        f"{repair_prompt.strip()}\n\n"
        f"{transform_repair_note.strip()}\n\n"
        f"{contract_block}\n\n"
        "ARTIFACT TYPE:\n"
        f"{plan.semantic_output_type}\n\n"
        "QUALITY VIOLATIONS:\n"
        + "\n".join(f"- {v}" for v in violations)
        + "\n\nEXPECTED OUTPUT SCHEMA:\n"
        + json.dumps(schema, indent=2, ensure_ascii=False)
        + "\n\nORIGINAL ARTIFACT CONTENT:\n"
        + normalized_artifact.extracted_content
    )

    return (
        list(original_messages)
        + [
            {
                "role": "user",
                "content": repair_user_message,
            }
        ]
    )


def _allows_compact_email_transform(plan) -> bool:
    return (
        getattr(plan, "semantic_output_type", None) == "email_draft"
        and getattr(plan, "transform_type", None)
        in {"expand_scope", "shorten"}
    )


def repair_contract_response(
    *,
    messages: list[dict],
    raw_response: str,
    violations: list[str],
    agent,
    plan,
    response_format,
    runtime_report,
    execution_target,
):
    repair_messages = build_contract_repair_messages(
        original_messages=messages,
        raw_response=raw_response,
        violations=violations,
        agent=agent,
        plan=plan,
    )

    runtime_report(
        "contract_repair_started",
        {
            "semantic_output_type": plan.semantic_output_type,
            "violations": violations,
            "plan_engine": plan.execution_target,
            "repair_engine": execution_target,
        },
    )

    execution_result = execute_with_fallbacks(
        messages=repair_messages,
        execution_target=execution_target,
        fallback_engines=[],
        report_callback=runtime_report,
        response_format=response_format,
    )

    raw_repaired_response = execution_result["response"]

    pipeline_result = process_response(
        raw_response=raw_repaired_response,
        semantic_output_type=plan.semantic_output_type,
        agent_root=agent.agent_root,
    )

    runtime_report(
        "contract_repair_completed",
        {
            "semantic_output_type": plan.semantic_output_type,
            "engine": execution_result.get("engine"),
            "model": execution_result.get("model"),
            "raw_response_len": len(raw_repaired_response or ""),
            "normalized_len": len(
                pipeline_result.normalized_response or ""
            ),
        },
    )

    return {
        "execution_result": execution_result,
        "raw_response": raw_repaired_response,
        "pipeline_result": pipeline_result,
        "normalized_response": pipeline_result.normalized_response,
    }


__all__ = [
    "repair_contract_response",
    "build_contract_repair_messages",
]
