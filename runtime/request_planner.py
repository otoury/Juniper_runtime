# runtime/request_planner.py

from __future__ import annotations

import os
import time
from dataclasses import dataclass, replace
from typing import Any

from gateway.context_resolver import ContextResolution,resolve_followup
from memory.artifacts import load_active_artifact
from planner.execution import ExecutionPlan, build_execution_plan
from planner.request_gate import analyze_request_gate, InteractionMode
from runtime.registries.semantic_operations import get_operation_policy
from runtime.registries.semantic_matching import infer_artifact_type_from_text
from runtime.lookup.execution import (
    execute_lookup_requests,
    lookup_execution_result_to_metadata,
)
from runtime.lookup.context_materializer import (
    materialize_lookup_context_packets,
)
from runtime.lookup.context_render_gate import (
    evaluate_lookup_context_render_gate,
)
from runtime.lookup.context_renderer import render_lookup_context_blocks
from runtime.lookup.pipeline_summary import build_lookup_pipeline_summary
from runtime.lookup.request_planner import (
    create_explicit_lookup_request,
    create_explicit_lookup_requests,
)
from runtime.registries.lookup_capability_registry import (
    LookupCapabilityRegistration,
    LookupCapabilityRegistrationError,
    ResolvedLookupCapability,
    resolve_lookup_capability,
)
from runtime.attachment_guard import (
    AttachmentValidationError,
    validate_active_artifact_attachment,
)
from runtime.registries.artifacts import artifact_allows_semantic_grounding
from semantics.transforms import resolve_transform_type


@dataclass
class LookupCapabilityPolicyBundle:
    registration: LookupCapabilityRegistration
    compatibility: object
    governance: object
    execution_policy: object
    request_policy: dict[str, Any] | None
    materialization_policy: dict[str, Any] | None
    render_policy: dict[str, Any] | None
    injection_policy: dict[str, Any] | None

    def policy_section(self, name: str) -> dict[str, Any] | None:
        if name == "lookup_request_policy":
            return _copy_policy(self.request_policy)
        if name == "lookup_context_materialization_policy":
            return _copy_policy(self.materialization_policy)
        if name == "lookup_context_render_policy":
            return _copy_policy(self.render_policy)
        if name == "lookup_context_injection_policy":
            return _copy_policy(self.injection_policy)
        return None


@dataclass
class RequestPlanningResult:
    gate: object
    resolution: ContextResolution
    plan: ExecutionPlan
    resolved_text: str
    semantic_output_type: str | None
    shared_capability: str | None
    active_artifact: dict | None
    fast_path: bool
    transform_type: str | None
    lookup_requests: list[dict[str, Any]]
    lookup_request_traces: list[dict[str, Any]]
    lookup_results: list[dict[str, Any]]
    lookup_execution_traces: list[dict[str, Any]]
    lookup_context_packets: list[dict[str, Any]]
    lookup_context_render_decision: dict[str, Any] | None
    rendered_lookup_context: dict[str, Any] | None
    lookup_capability: LookupCapabilityPolicyBundle | None
    lookup_pipeline_summary: dict[str, Any]
    timings: dict

def _mark_phase(
    timings: dict,
    name: str,
    start_time: float,
) -> None:
    timings[name] = round(
        (time.time() - start_time) * 1000,
        2,
    )


def _build_transform_resolution(
    *,
    text: str,
    gate,
) -> ContextResolution:
    return ContextResolution(
        original_text=text,
        resolved_text=text,
        is_followup=True,
        action="TRANSFORM",
        confidence=1.0,
        reason=gate.reason,
    )

def _build_convert_text(
    *,
    text: str,
    gate,
    active_artifact: dict,
    target_artifact_type: str | None,
) -> str:
    source_artifact_type = active_artifact.get(
        "artifact_type",
        "artifact",
    )

    content = active_artifact.get("content", "")

    target = target_artifact_type or "requested artifact type"

    return (
        f"Convert this existing {source_artifact_type} artifact "
        f"into a {target} artifact.\n\n"
        "Preserve the underlying facts and intent.\n"
        "Change the artifact type only because the user requested conversion.\n\n"
        "CURRENT ARTIFACT:\n"
        f"{content}\n\n"
        "USER CONVERSION REQUEST:\n"
        f"{text}\n\n"
        "NORMALIZED CONVERSION INTENT:\n"
        f"{gate.transform_intent or text}\n\n"
        f"Return ONLY the new {target} artifact."
    )

def _build_default_resolution(
    *,
    text: str,
    gate,
) -> ContextResolution:
    return ContextResolution(
        original_text=text,
        resolved_text=text,
        is_followup=False,
        action="NONE",
        confidence=1.0,
        reason=gate.reason,
    )


def _build_transform_text(
    *,
    text: str,
    gate,
    active_artifact: dict,
) -> str:
    artifact_type = active_artifact.get(
        "artifact_type",
        "artifact",
    )

    content = active_artifact.get("content", "")

    return (
        f"Transform this existing {artifact_type} artifact.\n\n"
        "Preserve the artifact type and formatting constraints.\n\n"
        "CURRENT ARTIFACT:\n"
        f"{content}\n\n"
        "USER TRANSFORMATION REQUEST:\n"
        f"{text}\n\n"
        "NORMALIZED TRANSFORM INTENT:\n"
        f"{gate.transform_intent or text}\n\n"
        "Return ONLY the transformed artifact.\n"

    )


def _build_workflow_action_text(
    *,
    text: str,
    active_artifact: dict,
) -> str:
    artifact_type = active_artifact.get(
        "artifact_type",
        "artifact",
    )

    content = active_artifact.get("content", "")

    return (
        "Continue the workflow for this existing "
        f"{artifact_type} artifact.\n\n"
        "Do not transform or rewrite the artifact unless the user "
        "explicitly asks for editing.\n\n"
        "ACTIVE ARTIFACT:\n"
        f"{content}\n\n"
        "USER WORKFLOW REQUEST:\n"
        f"{text}\n\n"
        "Return the appropriate structured workflow action if one is "
        "available; otherwise explain that the action is not available."
    )


def _lock_artifact_plan_to_non_web(
    plan: ExecutionPlan,
) -> None:
    if plan.expected_output_type != "artifact":
        return

    if (
        plan.requires_current_information
        or plan.requires_web
        or plan.requires_source_fidelity
    ):
        return

    plan.requires_current_information = False
    plan.requires_web = False
    plan.requires_source_fidelity = False

    if plan.execution_target == "cloud_web_fast":
        plan.execution_target = "cloud_fast"

    if plan.execution_target == "cloud_web_deep":
        plan.execution_target = "cloud_deep"

    plan.fallback_engines = [
        engine
        for engine in plan.fallback_engines
        if "web" not in engine
        and engine != plan.execution_target
    ]


def _policy_requires_active_artifact(policy: dict) -> bool:
    return policy.get("requires_active_artifact") is True


def _operation_policy_for_gate(gate) -> dict:
    if gate.operation == "TRANSFORM":
        return get_operation_policy("TRANSFORM")

    if gate.operation == "CONVERT":
        return get_operation_policy("CONVERT")

    if gate.operation == "CONTINUE":
        return get_operation_policy("ACTION")

    return get_operation_policy("NEW_REQUEST")


def _is_artifact_operation(gate) -> bool:
    return gate.operation in {"TRANSFORM", "CONVERT"}


def _validate_active_artifact_semantic_grounding(
    *,
    active_artifact: dict | None,
    agent_root,
) -> None:
    if not isinstance(active_artifact, dict):
        return

    artifact_type = active_artifact.get("artifact_type")
    if artifact_allows_semantic_grounding(
        artifact_type,
        authority="planner",
        agent_root=agent_root,
    ) and artifact_allows_semantic_grounding(
        artifact_type,
        authority="runtime",
        agent_root=agent_root,
    ):
        return

    raise ValueError(
        "Active artifact is not allowed to provide planner/runtime "
        "semantic grounding."
    )


def _validate_active_artifact_attachment_path(
    *,
    active_artifact: dict | None,
) -> None:
    validation = validate_active_artifact_attachment(active_artifact)
    if validation.allowed is True:
        return

    raise AttachmentValidationError(validation)


def _agent_semantic_intent(
    *,
    agent,
    text: str,
) -> dict[str, Any] | None:
    classifier = getattr(agent, "classify_semantic_intent", None)
    if not callable(classifier):
        return None

    intent = classifier(text)
    if intent is None:
        return None

    semantic_output_type = getattr(intent, "semantic_output_type", None)
    shared_capability = getattr(intent, "shared_capability", None)
    semantic_operation = getattr(intent, "semantic_operation", None)
    planning_metadata = getattr(intent, "planning_metadata", None)

    if not isinstance(semantic_output_type, str) or not semantic_output_type.strip():
        return None

    return {
        "semantic_output_type": semantic_output_type.strip(),
        "shared_capability": (
            shared_capability.strip()
            if isinstance(shared_capability, str)
            else None
        ),
        "semantic_operation": (
            semantic_operation.strip()
            if isinstance(semantic_operation, str)
            else None
        ),
        "planning_metadata": (
            dict(planning_metadata)
            if isinstance(planning_metadata, dict)
            else {}
        ),
    }


def build_planning_result_without_lookup_execution(
    *,
    text: str,
    agent,
    user_id: str,
    recent_memory,
    context_packet,
    dispatch,
) -> RequestPlanningResult:
    timings = {}

    start = time.time()
    _mark_memory(timings, "start")
    gate = analyze_request_gate(
        text,
        has_session_history=bool(recent_memory),
    )
    _mark_phase(timings, "analyze_request_gate", start)
    _mark_memory(timings, "after_gate")

    fast_path = bool(gate.safe_for_fast_path)
    transform_type = None
    semantic_output_type = None
    semantic_shared_capability = getattr(gate, "shared_capability", None)
    semantic_planning_metadata = {}
    active_artifact = None
    target_artifact_type = None
    transform_policy = get_operation_policy("TRANSFORM")
    convert_policy = get_operation_policy("CONVERT")
    action_policy = get_operation_policy("ACTION")
    new_request_policy = get_operation_policy("NEW_REQUEST")
    operation_policy = _operation_policy_for_gate(gate)
   
    should_load_active_artifact = gate.uses_active_artifact

    if (
        gate.interaction_mode in [
            InteractionMode.TRANSFORM_EXISTING.value,
            InteractionMode.CONVERT_ARTIFACT.value,
        ] 
        and not gate.uses_active_artifact
        and _policy_requires_active_artifact(operation_policy)
    ):
        raise ValueError(
            "Artifact operation requires uses_active_artifact=true"
        )

    is_artifact_operation = _is_artifact_operation(gate)

    if should_load_active_artifact:
        start = time.time()

        active_artifact = load_active_artifact(
            agent_name=agent.name,
            user_id=user_id,
        )        

        _mark_phase(timings, "load_active_artifact", start)
        _validate_active_artifact_attachment_path(
            active_artifact=active_artifact,
        )
        _validate_active_artifact_semantic_grounding(
            active_artifact=active_artifact,
            agent_root=agent.agent_root,
        )

        if is_artifact_operation:
            transform_type = resolve_transform_type(
                gate.transform_intent or text
            ) or resolve_transform_type(
                text
            )

        if active_artifact and is_artifact_operation:
            semantic_output_type = active_artifact.get(
                "artifact_type"
            )
    if (
        gate.interaction_mode == InteractionMode.NEW_REQUEST.value
        and gate.uses_active_artifact
        and not new_request_policy["requires_active_artifact"]
    ):
        raise ValueError(
            "NEW_REQUEST cannot use active artifact context"
        )

    if (
        gate.interaction_mode == InteractionMode.NEW_REQUEST.value
        and not gate.uses_active_artifact
        and gate.explicit_artifact_type
    ):
        semantic_output_type = gate.explicit_artifact_type


    if is_artifact_operation:
        resolution = _build_transform_resolution(
            text=text,
            gate=gate,
        )

    elif gate.needs_followup_resolution:
        start = time.time()
        resolution = resolve_followup(
            text,
            context_packet,
        )
        _mark_phase(timings, "resolve_followup", start)

    else:
        resolution = _build_default_resolution(
            text=text,
            gate=gate,
        )

    resolved_text = resolution.resolved_text
    _mark_memory(timings, "after_resolution");
    if (
        gate.interaction_mode == InteractionMode.TRANSFORM_EXISTING.value
        and active_artifact
        and transform_policy["preserves_artifact_type"]
    ):
        resolved_text = _build_transform_text(
            text=text,
            gate=gate,
            active_artifact=active_artifact,
        )

        semantic_output_type = active_artifact.get(
            "artifact_type"
        )

    elif (
        gate.interaction_mode == InteractionMode.CONTINUE_WORKFLOW.value
        and active_artifact
    ):
        resolved_text = _build_workflow_action_text(
            text=text,
            active_artifact=active_artifact,
        )
        semantic_output_type = None

        if action_policy["needs_capability_context"]:
            resolution = replace(
                resolution,
                is_followup=True,
                action="CONTINUE",
            )

    elif (
        gate.interaction_mode == InteractionMode.CONVERT_ARTIFACT.value
        and not convert_policy["preserves_artifact_type"]
    ):
        target_artifact_type = infer_artifact_type_from_text(
            gate.transform_intent or text
        )

        semantic_output_type = target_artifact_type

        if active_artifact:
            resolved_text = _build_convert_text(
                text=text,
                gate=gate,
                active_artifact=active_artifact,
                target_artifact_type=target_artifact_type,
            )
            # start = time.time()

    elif (
        gate.interaction_mode == InteractionMode.NEW_REQUEST.value
        and semantic_output_type is None
        and not getattr(gate, "deterministic_direct_response", False)
    ):
        agent_intent = _agent_semantic_intent(
            agent=agent,
            text=resolved_text,
        )
        if agent_intent is not None:
            semantic_output_type = agent_intent["semantic_output_type"]
            semantic_shared_capability = (
                agent_intent["shared_capability"]
                or semantic_shared_capability
            )
            semantic_planning_metadata = agent_intent["planning_metadata"]

    plan = build_execution_plan(
        original_text=text,
        resolved_text=resolved_text,
        resolution=resolution,
        dispatch=dispatch,
        user_id=user_id,
        agent_root=agent.agent_root,
        transform_type=transform_type,
        semantic_output_type=semantic_output_type,
        shared_capability=semantic_shared_capability,
        semantic_planning_metadata=semantic_planning_metadata,
        direct_response_type=(
            getattr(gate, "direct_response_type", None)
            if getattr(gate, "deterministic_direct_response", False)
            else None
        ),
    )
    _mark_phase(timings, "build_execution_plan", start)
    _mark_memory(timings,"after_plan")

    if os.getenv("JUNIPER_DISABLE_FALLBACKS") == "1":
        plan.fallback_engines = []

    _lock_artifact_plan_to_non_web(plan)

    lookup_capability = _resolve_runtime_lookup_capability(
        agent=agent,
        shared_capability=plan.shared_capability,
    )

    planned_lookups = create_explicit_lookup_requests(
        agent_name=agent.name,
        shared_capability=plan.shared_capability,
        planner_lookup=plan.lookup_metadata,
        resolved_capability=lookup_capability,
    )
    if not planned_lookups:
        planned_lookups = [
            create_explicit_lookup_request(
                agent_name=agent.name,
                shared_capability=plan.shared_capability,
                planner_lookup=plan.lookup_metadata,
                resolved_capability=lookup_capability,
            )
        ]

    lookup_requests = [
        planned.request
        for planned in planned_lookups
        if planned.request is not None
    ]
    lookup_request_traces = [
        planned.trace
        for planned in planned_lookups
        if planned.status != "lookup_not_declared"
    ]

    planning_result = RequestPlanningResult(
        gate=gate,
        resolution=resolution,
        plan=plan,
        resolved_text=resolved_text,
        semantic_output_type=semantic_output_type,
        shared_capability=plan.shared_capability,
        active_artifact=active_artifact,
        fast_path=fast_path,
        transform_type=transform_type,
        lookup_requests=lookup_requests,
        lookup_request_traces=lookup_request_traces,
        lookup_results=[],
        lookup_execution_traces=[],
        lookup_context_packets=[],
        lookup_context_render_decision=None,
        rendered_lookup_context=None,
        lookup_capability=_policy_bundle_from_resolved(lookup_capability),
        lookup_pipeline_summary={},
        timings=timings,
    )
    planning_result.lookup_pipeline_summary = build_lookup_pipeline_summary(
        planning=planning_result,
    )
    return planning_result


def execute_planned_lookup_requests(
    *,
    planning_result: RequestPlanningResult,
    agent,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lookup_execution_results = execute_lookup_requests(
        agent=agent,
        lookup_requests=planning_result.lookup_requests,
        lookup_capability=planning_result.lookup_capability,
        require_lookup_capability=bool(planning_result.lookup_requests),
    )
    lookup_results = [
        lookup_execution_result_to_metadata(result)
        for result in lookup_execution_results
    ]
    lookup_execution_traces = [
        result.trace
        for result in lookup_execution_results
    ]

    return lookup_results, lookup_execution_traces


def _resolve_runtime_lookup_capability(
    *,
    agent,
    shared_capability: str | None,
) -> ResolvedLookupCapability | LookupCapabilityRegistrationError | None:
    if not isinstance(shared_capability, str) or not shared_capability.strip():
        return None

    resolved_capability = resolve_lookup_capability(
        agent=agent.name,
        shared_capability=shared_capability,
    )
    if isinstance(resolved_capability, LookupCapabilityRegistrationError):
        return None

    return resolved_capability


def _policy_bundle_from_resolved(
    resolved_capability: (
        ResolvedLookupCapability | LookupCapabilityRegistrationError | None
    ),
) -> LookupCapabilityPolicyBundle | None:
    if not isinstance(resolved_capability, ResolvedLookupCapability):
        return None

    return LookupCapabilityPolicyBundle(
        registration=resolved_capability.registration,
        compatibility=resolved_capability.compatibility,
        governance=resolved_capability.governance,
        execution_policy=resolved_capability.execution_policy,
        request_policy=resolved_capability.policy_section(
            "lookup_request_policy"
        ),
        materialization_policy=resolved_capability.policy_section(
            "lookup_context_materialization_policy"
        ),
        render_policy=resolved_capability.policy_section(
            "lookup_context_render_policy"
        ),
        injection_policy=resolved_capability.policy_section(
            "lookup_context_injection_policy"
        ),
    )


def attach_lookup_execution_results(
    *,
    planning_result: RequestPlanningResult,
    agent,
) -> RequestPlanningResult:
    lookup_results, lookup_execution_traces = execute_planned_lookup_requests(
        planning_result=planning_result,
        agent=agent,
    )
    lookup_context_packets = materialize_lookup_context_packets(
        lookup_results=lookup_results,
        materialization_policy=_lookup_context_materialization_policy(
            planning_result=planning_result,
        ),
    )
    render_decision = evaluate_lookup_context_render_gate(
        lookup_context_packets=lookup_context_packets,
        render_policy=_lookup_context_render_policy(
            planning_result=planning_result,
        ),
    )
    rendered_lookup_context = render_lookup_context_blocks(
        lookup_context_packets=lookup_context_packets,
        render_decision=render_decision,
        render_policy=_lookup_context_render_policy(
            planning_result=planning_result,
        ),
    )

    updated = replace(
        planning_result,
        lookup_results=lookup_results,
        lookup_execution_traces=lookup_execution_traces,
        lookup_context_packets=lookup_context_packets,
        lookup_context_render_decision=render_decision,
        rendered_lookup_context=rendered_lookup_context,
    )
    updated.lookup_pipeline_summary = build_lookup_pipeline_summary(
        planning=updated,
    )
    return updated


def _lookup_context_materialization_policy(
    *,
    planning_result: RequestPlanningResult,
) -> dict[str, Any] | None:
    lookup_capability = planning_result.lookup_capability
    if lookup_capability is None:
        return None

    if not lookup_capability.governance.context_allowed:
        return None

    policy = lookup_capability.policy_section(
        "lookup_context_materialization_policy"
    )
    return policy


def _lookup_context_render_policy(
    *,
    planning_result: RequestPlanningResult,
) -> dict[str, Any] | None:
    lookup_capability = planning_result.lookup_capability
    if lookup_capability is None:
        return None

    if not lookup_capability.governance.context_allowed:
        return None

    return lookup_capability.policy_section("lookup_context_render_policy")


def _copy_policy(policy: dict[str, Any] | None) -> dict[str, Any] | None:
    return dict(policy) if isinstance(policy, dict) else None


def plan_request(
    *,
    text: str,
    agent,
    user_id: str,
    recent_memory,
    context_packet,
    dispatch,
) -> RequestPlanningResult:
    planning_result = build_planning_result_without_lookup_execution(
        text=text,
        agent=agent,
        user_id=user_id,
        recent_memory=recent_memory,
        context_packet=context_packet,
        dispatch=dispatch,
    )

    return attach_lookup_execution_results(
        planning_result=planning_result,
        agent=agent,
    )

import resource


def _rss_mb() -> float:
    return round(
        resource.getrusage(
            resource.RUSAGE_SELF
        ).ru_maxrss / 1024,
        2,
    )


def _mark_memory(
    timings: dict,
    label: str,
) -> None:
    timings[f"rss_{label}"] = _rss_mb()

__all__ = [
    "RequestPlanningResult",
    "attach_lookup_execution_results",
    "build_planning_result_without_lookup_execution",
    "execute_planned_lookup_requests",
    "plan_request",
]
