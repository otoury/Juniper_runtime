# runtime/execution_manager.py

from __future__ import annotations

from typing import Any

from runtime.runtime_manager import execute_with_fallbacks
from runtime.response_pipeline import process_response
from runtime.recovery_policy import build_artifact_retry_engines
from runtime.execution_containment import contain_execution_result


class ExecutionManagerResult(dict):
    """
    Canonical runtime execution result.

    Keys:
    - response
    - raw_response
    - normalized_response
    - execution_result
    - pipeline_result
    - retried
    """


def execute_request(
    *,
    messages,
    plan,
    response_format,
    runtime_report,
    agent_root=None,
    process_response_fn=process_response,
) -> ExecutionManagerResult:
    """
    Runtime execution lifecycle.

    Responsibilities:
    - primary execution
    - response normalization
    - artifact recovery retry
    - canonical response production

    NOT responsible for:
    - transport
    - UI messaging
    - persistence
    - approvals
    """

    execution_result = execute_with_fallbacks(
        messages=messages,
        execution_target=plan.execution_target,
        fallback_engines=plan.fallback_engines,
        report_callback=runtime_report,
        response_format=response_format,
    )
    execution_result = contain_execution_result(
        execution_result,
        reason="blocked_execution_manager_response",
    )

    raw_response = execution_result["response"]

    pipeline_result = process_response_fn(
        raw_response=raw_response,
        semantic_output_type=plan.semantic_output_type,
        agent_root=agent_root,
    )

    normalized_response = pipeline_result.normalized_response

    retried = False

    if (
        plan.expected_output_type == "artifact"
        and not normalized_response
        and not execution_result.get("provider_blocked")
    ):
        retried = True

        retry_engines = build_artifact_retry_engines(
            failed_engine=execution_result.get("engine"),
        )

        if retry_engines:
            execution_result = execute_with_fallbacks(
                messages=messages,
                execution_target=retry_engines[0],
                fallback_engines=retry_engines[1:],
                report_callback=runtime_report,
                response_format=response_format,
            )
            execution_result = contain_execution_result(
                execution_result,
                reason="blocked_execution_manager_retry_response",
            )

            raw_response = execution_result["response"]

            pipeline_result = process_response_fn(
                raw_response=raw_response,
                semantic_output_type=plan.semantic_output_type,
                agent_root=agent_root,
            )

            normalized_response = (
                pipeline_result.normalized_response
            )

    return ExecutionManagerResult(
        response=normalized_response,
        raw_response=raw_response,
        normalized_response=normalized_response,
        execution_result=execution_result,
        pipeline_result=pipeline_result,
        retried=retried,
    )


__all__ = [
    "execute_request",
    "ExecutionManagerResult",
]
