# runner/request_runner.py

import json
import time
import uuid
import os
import inspect

from runtime.contracts.exceptions import ContractValidationError

from memory.store import load_session_memory
from memory.context_packet import build_context_packet
from memory.artifacts import save_active_artifact

from runtime.policies.model_registry import ENGINES

from gateway.routing.juniper import DispatchDecision

from planner.execution import should_use_cloud_engine

from runtime.action_manager import process_actions
from runtime.conversation_continuity import build_conversation_continuity
from runtime.context_builder import build_runtime_messages
from runtime.context_micro_injection import (
    maybe_apply_micro_context_injection,
)
from runtime.context_trace import emit_planned_context_trace_telemetry
from runtime.execution_manager import execute_request
from runtime.lookup.context_injection import maybe_inject_lookup_context
from runtime.lookup.pipeline_telemetry import (
    emit_lookup_context_injection_trace,
    emit_lookup_pipeline_trace_events,
)
from runtime.lookup.pipeline_summary import build_lookup_pipeline_summary
from runtime.binding_trace import emit_planned_capability_trace_telemetry
from runtime.memory_manager import persist_conversation_memory
from runtime.persistence_manager import persist_runtime_result
from runtime.request_planner import plan_request
from runtime.repair_manager import repair_contract_response
from runtime.telemetry_manager import get_session_id, report_event, report_memory_snapshot
from runtime.trace.store import create_trace
from runtime.validation_manager import validate_runtime_response
from runtime.workflows.rss_first_gate import coerce_rss_first_routing_result
from planner.direct_response import render_deterministic_direct_response


sessions = {}
session_active_artifacts = {}
MAX_CONTRACT_REPAIR_ATTEMPTS = 2

def run_request(
    source_bot: str,
    agent,
    user_id: str,
    text: str,
    progress_callback=None,
    notify_owner=None,
) -> str:

    text = text.strip()
    request_id = str(uuid.uuid4())[:8]
    session_id = get_session_id()

    create_trace(
        request_id=request_id,
        session_id=session_id,
        source_bot=source_bot,
        user_id=user_id,
        original_text=text,
    )

    if not text:
        report_event(
            source_bot,
            "empty_message_skipped",
            {"user_id": user_id},
            request_id=request_id,
        )
        return ""

    dispatch = DispatchDecision(
        target_agent=agent.name,
        cognition="LOCAL",
        task_type="direct_bot_message",
        tools_needed=[],
        reason=f"direct message to {agent.name} bot",
        confidence=1.0,
    )

    report_event(
        source_bot,
        "request_received",
        {
            "user_id": user_id,
            "agent": agent.name,
            "text": text[:800],
        },
        request_id=request_id,
    )

    t0 = time.time()
    recent_memory = _load_bounded_recent_memory(
        agent_name=agent.name,
        user_id=user_id,
        session_id=session_id,
        source_bot=source_bot,
        request_id=request_id,
    )
    continuity = build_conversation_continuity(recent_memory)
    report_event(
        source_bot,
        "conversation_continuity_built",
        {
            "user_id": user_id,
            "agent": agent.name,
            **continuity.to_event_payload(),
        },
        request_id=request_id,
    )

    local_artifact_transform = _maybe_handle_agent_local_artifact_transform(
        agent=agent,
        text=text,
        active_artifact=_load_session_active_artifact(
            agent_name=agent.name,
            user_id=user_id,
            session_id=session_id,
        ),
    )
    if local_artifact_transform is not None:
        payload = (
            local_artifact_transform.to_event_payload()
            if hasattr(local_artifact_transform, "to_event_payload")
            else {"workflow_id": "unknown_local_artifact_transform"}
        )
        report_event(
            source_bot,
            "agent_local_workflow_completed",
            {
                "user_id": user_id,
                "agent": agent.name,
                **payload,
            },
            request_id=request_id,
        )
        _store_session_active_artifact(
            agent_name=agent.name,
            user_id=user_id,
            session_id=session_id,
            artifact=getattr(local_artifact_transform, "artifact", None),
            workflow_id=getattr(local_artifact_transform, "workflow_id", None),
        )
        _persist_completed_conversation_turn(
            source_bot=source_bot,
            agent_name=agent.name,
            user_id=user_id,
            session_id=session_id,
            request_id=request_id,
            text=text,
            response=local_artifact_transform.response,
            started_at=t0,
        )
        return local_artifact_transform.response

    rss_first_result = _maybe_handle_agent_rss_first_workflow(
        agent=agent,
        text=text,
        continuity=continuity,
    )
    if rss_first_result is not None:
        report_event(
            source_bot,
            "rss_first_routing_gate_decision",
            {
                "user_id": user_id,
                "agent": agent.name,
                **rss_first_result.to_event_payload(),
            },
            request_id=request_id,
        )
        if rss_first_result.applicable and rss_first_result.response:
            report_event(
                source_bot,
                "agent_local_workflow_completed",
                {
                    "user_id": user_id,
                    "agent": agent.name,
                    **rss_first_result.to_event_payload(),
                },
                request_id=request_id,
            )
            _store_session_active_artifact(
                agent_name=agent.name,
                user_id=user_id,
                session_id=session_id,
                artifact=rss_first_result.artifact,
                workflow_id=rss_first_result.workflow_id,
            )
            _persist_completed_conversation_turn(
                source_bot=source_bot,
                agent_name=agent.name,
                user_id=user_id,
                session_id=session_id,
                request_id=request_id,
                text=text,
                response=rss_first_result.response,
                started_at=t0,
            )
            return rss_first_result.response

    local_workflow = None
    if rss_first_result is None or not rss_first_result.applicable:
        local_workflow = _maybe_handle_agent_local_workflow(
            agent=agent,
            text=text,
            continuity=continuity,
            active_artifact=_load_session_active_artifact(
                agent_name=agent.name,
                user_id=user_id,
                session_id=session_id,
            ),
        )
    if local_workflow is not None:
        payload = (
            local_workflow.to_event_payload()
            if hasattr(local_workflow, "to_event_payload")
            else {"workflow_id": "unknown_local_workflow"}
        )
        report_event(
            source_bot,
            "agent_local_workflow_completed",
            {
                "user_id": user_id,
                "agent": agent.name,
                **payload,
            },
            request_id=request_id,
        )
        _store_session_active_artifact(
            agent_name=agent.name,
            user_id=user_id,
            session_id=session_id,
            artifact=getattr(local_workflow, "artifact", None),
            workflow_id=getattr(local_workflow, "workflow_id", None),
        )
        _persist_completed_conversation_turn(
            source_bot=source_bot,
            agent_name=agent.name,
            user_id=user_id,
            session_id=session_id,
            request_id=request_id,
            text=text,
            response=local_workflow.response,
            started_at=t0,
        )
        return local_workflow.response

    report_memory_snapshot(source_bot, request_id, "start")

    try:
        context_packet = build_context_packet(
            agent.name,
            user_id,
        )

        planning = plan_request(
            text=text,
            agent=agent,
            user_id=user_id,
            recent_memory=recent_memory,
            context_packet=context_packet,
            dispatch=dispatch,
        )

        report_event(
            source_bot,
            "planner_phase_timing",
            {
                "user_id": user_id,
                "agent": agent.name,
                "timings": planning.timings,
            },
            request_id=request_id,
        )
        
        gate = planning.gate
        resolution = planning.resolution
        plan = planning.plan
        resolved_text = planning.resolved_text
        active_artifact = planning.active_artifact
        fast_path = planning.fast_path
        transform_type = planning.transform_type

        report_event(
            source_bot,
            "request_gate_decision",
            {
                "user_id": user_id,
                "agent": agent.name,
                "is_standalone": gate.is_standalone,
                "needs_followup_resolution": gate.needs_followup_resolution,
                "needs_capability_context": gate.needs_capability_context,
                "needs_full_planning": gate.needs_full_planning,
                "requires_artifact_context": gate.requires_artifact_context,
                "uses_active_artifact": gate.uses_active_artifact,
                "safe_for_fast_path": gate.safe_for_fast_path,
                "operation": gate.operation,
                "interaction_mode": gate.interaction_mode,
                "transform_intent": gate.transform_intent,
                "explicit_artifact_type": gate.explicit_artifact_type,
                "shared_capability": gate.shared_capability,
                "deterministic_direct_response": (
                    gate.deterministic_direct_response
                ),
                "direct_response_type": gate.direct_response_type,
                "needs_model": getattr(gate, "needs_model", True),
                "needs_lookup_context": getattr(
                    gate,
                    "needs_lookup_context",
                    True,
                ),
                "needs_workflow": getattr(gate, "needs_workflow", True),
                "reason": gate.reason,
            },
            request_id=request_id,
        )

        if gate.interaction_mode == "TRANSFORM_EXISTING":
            report_event(
                source_bot,
                "artifact_context_loaded",
                {
                    "user_id": user_id,
                    "agent": agent.name,
                    "artifact_found": bool(active_artifact),
                    "artifact_type": (
                        active_artifact.get("artifact_type")
                        if active_artifact else None
                    ),
                },
                request_id=request_id,
            )

        if fast_path:
            report_event(
                source_bot,
                "fast_path_selected",
                {
                    "user_id": user_id,
                    "agent": agent.name,
                    "reason": gate.reason,
                },
                request_id=request_id,
            )

        report_event(
            source_bot,
            "context_resolved",
            {
                "user_id": user_id,
                "agent": agent.name,
                "original_text": text[:800],
                "resolved_text": resolved_text[:1200],
                "is_followup": resolution.is_followup,
                "action": resolution.action,
                "operation": gate.operation,
                "interaction_mode": gate.interaction_mode,
                "transform_intent": gate.transform_intent,
                "transform_type": transform_type,
                "confidence": resolution.confidence,
                "reason": resolution.reason,
            },
            request_id=request_id,
        )

        report_event(
            source_bot,
            "execution_plan_created",
            {
                "user_id": user_id,
                "agent": agent.name,
                "task_family": plan.task_family,
                "reasoning_depth": plan.reasoning_depth,
                "style_sensitivity": plan.style_sensitivity,
                "requires_current_information": plan.requires_current_information,
                "requires_web": plan.requires_web,
                "requires_source_fidelity": plan.requires_source_fidelity,
                "privacy_sensitivity": plan.privacy_sensitivity,
                "latency_preference": plan.latency_preference,
                "output_risk": plan.output_risk,
                "input_type": plan.input_type,
                "expected_output_type": plan.expected_output_type,
                "semantic_output_type": plan.semantic_output_type,
                "shared_capability": plan.shared_capability,
                "transform_type": plan.transform_type,
                "execution_target": plan.execution_target,
                "fallback_engines": plan.fallback_engines,
                "requires_approval": plan.requires_approval,
                "direct_response_type": plan.direct_response_type,
                "reason": plan.reason,
            },
            request_id=request_id,
        )

        if _should_return_direct_fast_path(gate=gate, plan=plan):
            response = _direct_fast_path_response(
                agent=agent,
                gate=gate,
                text=text,
            )
            duration_ms = int((time.time() - t0) * 1000)

            report_event(
                source_bot,
                "execution_response",
                {
                    "user_id": user_id,
                    "agent": agent.name,
                    "engine": plan.execution_target,
                    "model": None,
                    "execution_tier": "runtime_direct",
                    "attempted": [],
                    "response": response[:4000],
                    "usage": {},
                    "dry_run": False,
                },
                request_id=request_id,
            )

            persist_runtime_result(
                agent_name=agent.name,
                user_id=user_id,
                request_id=request_id,
                response=response,
                resolved_text=resolved_text,
                plan=plan,
                gate=gate,
                transform_type=transform_type,
                is_dry_run=False,
            )

            report_memory_snapshot(
                source_bot,
                request_id,
                "before_memory_write",
            )

            persist_conversation_memory(
                agent_name=agent.name,
                user_id=user_id,
                session_id=session_id,
                user_text=text,
                assistant_text=response,
                sessions=sessions,
            )

            report_event(
                source_bot,
                "response_completed",
                {
                    "user_id": user_id,
                    "agent": agent.name,
                    "duration_ms": duration_ms,
                    "response_preview": response[:800],
                },
                request_id=request_id,
            )

            report_memory_snapshot(source_bot, request_id, "done")

            return response

        direct_artifact = _maybe_materialize_direct_artifact(
            agent=agent,
            plan=plan,
            planning=planning,
            text=text,
        )
        if direct_artifact is not None:
            response = direct_artifact["response"]
            artifact = direct_artifact["artifact"]
            duration_ms = int((time.time() - t0) * 1000)

            report_event(
                source_bot,
                "direct_artifact_materialized",
                {
                    "user_id": user_id,
                    "agent": agent.name,
                    "semantic_output_type": plan.semantic_output_type,
                    "artifact_type": artifact.get("artifact_type"),
                    "candidate_count": artifact.get("candidate_count"),
                    "ranking_executed": artifact.get("ranking_executed"),
                    "draft_generated": False,
                    "delivery_performed": False,
                    "events": direct_artifact.get("events", {}),
                },
                request_id=request_id,
            )
            report_event(
                source_bot,
                "execution_response",
                {
                    "user_id": user_id,
                    "agent": agent.name,
                    "engine": "direct_artifact_materialization",
                    "model": None,
                    "execution_tier": "runtime_direct",
                    "attempted": [],
                    "response": response[:4000],
                    "usage": {},
                    "dry_run": False,
                },
                request_id=request_id,
            )

            save_active_artifact(
                agent_name=agent.name,
                user_id=user_id,
                request_id=request_id,
                artifact_type=str(artifact.get("artifact_type")),
                content=json.dumps(artifact, ensure_ascii=False, sort_keys=True),
                source_text=resolved_text,
                operation="create",
            )

            report_memory_snapshot(
                source_bot,
                request_id,
                "before_memory_write",
            )

            persist_conversation_memory(
                agent_name=agent.name,
                user_id=user_id,
                session_id=session_id,
                user_text=text,
                assistant_text=response,
                sessions=sessions,
            )

            report_event(
                source_bot,
                "response_completed",
                {
                    "user_id": user_id,
                    "agent": agent.name,
                    "duration_ms": duration_ms,
                    "response_preview": response[:800],
                },
                request_id=request_id,
            )

            report_memory_snapshot(source_bot, request_id, "done")

            return response

        planned_shared_capability = (
            getattr(plan, "shared_capability", None)
            or getattr(plan, "shared_capability_id", None)
        )
        if planned_shared_capability:
            emit_planned_capability_trace_telemetry(
                report_event=report_event,
                source_bot=source_bot,
                request_id=request_id,
                agent_name=agent.name,
                shared_capability=planned_shared_capability,
                user_id=user_id,
                semantic_operation=gate.operation,
                expected_output_type=plan.expected_output_type,
            )
            emit_planned_context_trace_telemetry(
                report_event=report_event,
                source_bot=source_bot,
                request_id=request_id,
                agent_name=agent.name,
                shared_capability=planned_shared_capability,
                user_id=user_id,
            )

        emit_lookup_pipeline_trace_events(
            report_event=report_event,
            source_bot=source_bot,
            request_id=request_id,
            user_id=user_id,
            agent_name=agent.name,
            planning=planning,
        )

        if should_use_cloud_engine(plan) and progress_callback:
            try:
                engine = ENGINES[plan.execution_target]

                if engine.get("web_search"):
                    progress_callback({
                        "phase": "web_search",
                        "message": "Digging deeper now — using cloud + web search.",
                    })
                else:
                    progress_callback({
                        "phase": "deep_reasoning",
                        "message": "Using a stronger reasoning model now.",
                    })

            except Exception:
                pass

        messages, execution_source_text = build_runtime_messages(
            agent=agent,
            resolved_text=resolved_text,
            dispatch=dispatch,
            user_id=user_id,
            recent_memory=recent_memory,
            plan=plan,
            gate=gate,
            active_artifact=active_artifact,
            fast_path=fast_path,
        )

        injection_result = maybe_apply_micro_context_injection(
            messages,
            request_id=request_id,
            agent_name=agent.name,
            shared_capability=planned_shared_capability,
            operation=gate.operation,
            report_event=report_event,
            source_bot=source_bot,
        )
        messages = injection_result.messages
        lookup_injection_result = maybe_inject_lookup_context(
            messages,
            rendered_lookup_context=planning.rendered_lookup_context,
            render_decision=planning.lookup_context_render_decision,
            injection_policy=_lookup_context_injection_policy(
                planning=planning,
            ),
        )
        planning.lookup_pipeline_summary = build_lookup_pipeline_summary(
            planning=planning,
            injection_trace=lookup_injection_result.trace,
        )
        messages = lookup_injection_result.messages
        emit_lookup_context_injection_trace(
            report_event=report_event,
            source_bot=source_bot,
            request_id=request_id,
            user_id=user_id,
            agent_name=agent.name,
            trace=lookup_injection_result.trace,
        )

        def runtime_report(event_type, payload):
            report_event(
                source_bot,
                event_type,
                {
                    "user_id": user_id,
                    "agent": agent.name,
                    **payload,
                },
                request_id=request_id,
            )
            if (
                progress_callback
                and event_type in {
                    "execution_presence_started",
                    "execution_presence_progress",
                    "execution_presence_stopped",
                }
            ):
                try:
                    progress_callback(
                        {
                            "event_type": event_type,
                            **payload,
                        }
                    )
                except Exception:
                    pass

        response_format = (
            {"type": "json_object"}
            if agent.requires_structured_output
            else None
        )

        report_memory_snapshot(source_bot, request_id, "before_execution")

       

        manager_result = execute_request(
            messages=messages,
            plan=plan,
            response_format=response_format,
            runtime_report=runtime_report,
            agent_root=agent.agent_root,
        )

        report_memory_snapshot(source_bot, request_id, "after_execution")

        execution_result = manager_result["execution_result"]
        raw_response = manager_result["raw_response"]
        normalized_response = manager_result["normalized_response"]
        is_dry_run = execution_result.get("dry_run", False)

        report_event(
            source_bot,
            "raw_model_response",
            {
                "user_id": user_id,
                "agent": agent.name,
                "engine": execution_result.get("engine"),
                "model": execution_result.get("model"),
                "execution_tier": execution_result.get("execution_tier"),
                "raw_response_repr": repr(raw_response)[:4000],
                "raw_response_len": len(raw_response or ""),
                "usage": execution_result.get("usage", {}),
                "dry_run": is_dry_run,
            },
            request_id=request_id,
        )

        if execution_result.get("operational_diagnostics"):
            report_event(
                source_bot,
                "blocked_execution_diagnostics",
                {
                    "user_id": user_id,
                    "agent": agent.name,
                    "engine": execution_result.get("engine"),
                    "model": execution_result.get("model"),
                    "execution_tier": execution_result.get("execution_tier"),
                    "dry_run": is_dry_run,
                    "diagnostics": execution_result.get(
                        "operational_diagnostics"
                    ),
                },
                request_id=request_id,
            )

        if manager_result.get("retried"):
            report_event(
                source_bot,
                "artifact_execution_retry",
                {
                    "user_id": user_id,
                    "agent": agent.name,
                    "reason": "empty_artifact_response",
                },
                request_id=request_id,
            )
        try:
            validation = validate_runtime_response(
                agent=agent,
                plan=plan,
                gate=gate,
                normalized_response=normalized_response,
                parsed_payload=manager_result[
                    "pipeline_result"
                ].parsed_payload,
                is_dry_run=is_dry_run,
                source_bot=source_bot,
                user_id=user_id,
                request_id=request_id,
                report_event=report_event,
            )

        except ContractValidationError as exc:
            repair_attempt = 0
            last_error = exc

            while repair_attempt < MAX_CONTRACT_REPAIR_ATTEMPTS:
                repair_attempt += 1

                repair_engine = (
                    os.getenv(
                        "JUNIPER_STRUCTURED_REPAIR_ENGINE",
                        plan.execution_target,
                    )
                    if repair_attempt > 1
                    else plan.execution_target
                )

                repair_result = repair_contract_response(
                    messages=messages,
                    raw_response=raw_response,
                    violations=getattr(last_error, "violations", None) or [],
                    agent=agent,
                    plan=plan,
                    response_format=response_format,
                    runtime_report=runtime_report,
                    execution_target=repair_engine,
                )

                raw_response = repair_result["raw_response"]
                pipeline_result = repair_result["pipeline_result"]
                normalized_response = repair_result["normalized_response"]

                try:
                    validation = validate_runtime_response(
                        agent=agent,
                        plan=plan,
                        gate=gate,
                        normalized_response=normalized_response,
                        parsed_payload=pipeline_result.parsed_payload,
                        is_dry_run=is_dry_run,
                        source_bot=source_bot,
                        user_id=user_id,
                        request_id=request_id,
                        report_event=report_event,
                    )

                    break

                except ContractValidationError as repair_error:
                    last_error = repair_error

            else:
                raise last_error            
            # 2nd Validation
            validation = validate_runtime_response(
                agent=agent,
                plan=plan,
                gate=gate,
                normalized_response=normalized_response,
                parsed_payload=repair_result[
                    "pipeline_result"
                ].parsed_payload,
                is_dry_run=is_dry_run,
                source_bot=source_bot,
                user_id=user_id,
                request_id=request_id,
                report_event=report_event,
            )

        response = validation.response
        actions = validation.actions

        if validation.parsed and actions:
            process_actions(
                source_bot=source_bot,
                agent_name=agent.name,
                user_id=user_id,
                request_id=request_id,
                actions=actions,
                report_event=report_event,
                notify_owner=notify_owner,
            )

        report_event(
            source_bot,
            "execution_response",
            {
                "user_id": user_id,
                "agent": agent.name,
                "engine": execution_result["engine"],
                "model": execution_result["model"],
                "execution_tier": execution_result["execution_tier"],
                "attempted": execution_result["attempted"],
                "response": response[:4000],
                "usage": execution_result.get("usage", {}),
                "dry_run": execution_result.get("dry_run", False),
            },
            request_id=request_id,
        )

        if not response or not response.strip():
            report_event(
                source_bot,
                "empty_agent_response",
                {
                    "user_id": user_id,
                    "agent": agent.name,
                },
                request_id=request_id,
            )

            response = (
                "[Empty response]\n"
                "The selected execution engine returned nothing. "
                "Try asking again."
            )

    
        duration_ms = int((time.time() - t0) * 1000)

        persist_runtime_result(
            agent_name=agent.name,
            user_id=user_id,
            request_id=request_id,
            response=response,
            resolved_text=execution_source_text,
            plan=plan,
            gate=gate,
            transform_type=transform_type,
            is_dry_run=is_dry_run,
        )

        if not is_dry_run:
            report_memory_snapshot(
                source_bot,
                request_id,
                "before_memory_write",
            )

            persist_conversation_memory(
                agent_name=agent.name,
                user_id=user_id,
                session_id=session_id,
                user_text=text,
                assistant_text=response,
                sessions=sessions,
            )

        report_event(
            source_bot,
            "response_completed",
            {
                "user_id": user_id,
                "agent": agent.name,
                "duration_ms": duration_ms,
                "response_preview": response[:800],
            },
            request_id=request_id,
        )

        report_memory_snapshot(source_bot, request_id, "done")

        return response

    except Exception as e:
        duration_ms = int((time.time() - t0) * 1000)

        report_event(
            source_bot,
            "error",
            {
                "user_id": user_id,
                "agent": agent.name,
                "duration_ms": duration_ms,
                "error": repr(e),
            },
            request_id=request_id,
        )

        return (
            f"Sorry — {agent.name.capitalize()} hit an error. "
            "I logged it for Juniper."
        )


def _lookup_context_injection_policy(*, planning) -> dict | None:
    lookup_capability = getattr(planning, "lookup_capability", None)
    if lookup_capability is None:
        return None

    if not lookup_capability.governance.context_allowed:
        return None

    return lookup_capability.policy_section("lookup_context_injection_policy")


def _load_bounded_recent_memory(
    *,
    agent_name: str,
    user_id: str,
    session_id: str,
    source_bot: str,
    request_id: str,
) -> list[dict]:
    try:
        return load_session_memory(
            agent_name,
            user_id,
            session_id=session_id,
            limit=6,
        )
    except Exception as exc:
        report_event(
            source_bot,
            "conversation_memory_load_failed",
            {
                "user_id": user_id,
                "agent": agent_name,
                "error": repr(exc),
            },
            request_id=request_id,
        )
        return []


def _persist_completed_conversation_turn(
    *,
    source_bot: str,
    agent_name: str,
    user_id: str,
    session_id: str,
    request_id: str,
    text: str,
    response: str,
    started_at: float,
) -> None:
    _ = source_bot, request_id, started_at
    try:
        persist_conversation_memory(
            agent_name=agent_name,
            user_id=user_id,
            session_id=session_id,
            user_text=text,
            assistant_text=response,
            sessions=sessions,
        )
    except Exception:
        pass


def _maybe_handle_agent_local_workflow(
    *,
    agent,
    text: str,
    continuity=None,
    active_artifact=None,
):
    handler = getattr(agent, "handle_local_workflow_request", None)
    if not callable(handler):
        return None
    return _call_workflow_handler(
        handler,
        text=text,
        continuity=continuity,
        active_artifact=active_artifact,
    )


def _maybe_handle_agent_local_artifact_transform(
    *,
    agent,
    text: str,
    active_artifact=None,
):
    if active_artifact is None:
        return None
    handler = getattr(agent, "handle_local_artifact_transform_request", None)
    if not callable(handler):
        return None
    return _call_workflow_handler(
        handler,
        text=text,
        active_artifact=active_artifact,
    )


def _maybe_handle_agent_rss_first_workflow(*, agent, text: str, continuity=None):
    handler = getattr(agent, "handle_rss_first_workflow_request", None)
    if not callable(handler):
        return None
    return coerce_rss_first_routing_result(
        _call_workflow_handler(
            handler,
            text=text,
            continuity=continuity,
        )
    )


def _call_workflow_handler(
    handler,
    *,
    text: str,
    continuity=None,
    active_artifact=None,
):
    try:
        signature = inspect.signature(handler)
    except (TypeError, ValueError):
        return handler(text)

    if "continuity" in signature.parameters:
        kwargs = {
            "text": text,
            "continuity": continuity,
        }
        if "active_artifact" in signature.parameters:
            kwargs["active_artifact"] = active_artifact
        return handler(**kwargs)

    if "active_artifact" in signature.parameters:
        return handler(text=text, active_artifact=active_artifact)

    return handler(text)


def _session_active_artifact_key(
    *,
    agent_name: str,
    user_id: str,
    session_id: str,
) -> tuple[str, str, str]:
    return (str(session_id), str(agent_name), str(user_id))


def _store_session_active_artifact(
    *,
    agent_name: str,
    user_id: str,
    session_id: str,
    artifact,
    workflow_id: str | None,
) -> None:
    if not isinstance(artifact, dict):
        return
    if artifact.get("artifact_type") != "summary":
        return
    if artifact.get("summary_kind") != "latest_news_briefing":
        return
    session_active_artifacts[
        _session_active_artifact_key(
            agent_name=agent_name,
            user_id=user_id,
            session_id=session_id,
        )
    ] = {
        "artifact": artifact,
        "workflow_id": workflow_id,
    }


def _load_session_active_artifact(
    *,
    agent_name: str,
    user_id: str,
    session_id: str,
):
    record = session_active_artifacts.get(
        _session_active_artifact_key(
            agent_name=agent_name,
            user_id=user_id,
            session_id=session_id,
        )
    )
    if not isinstance(record, dict):
        return None
    artifact = record.get("artifact")
    return artifact if isinstance(artifact, dict) else None


def _should_return_direct_fast_path(*, gate, plan) -> bool:
    return (
        bool(getattr(gate, "safe_for_fast_path", False))
        and getattr(gate, "interaction_mode", None) == "ANSWER_QUESTION"
        and getattr(gate, "operation", None) == "ANSWER"
        and bool(getattr(gate, "deterministic_direct_response", False))
        and bool(getattr(gate, "direct_response_type", None))
        and getattr(plan, "direct_response_type", None)
        == getattr(gate, "direct_response_type", None)
        and getattr(plan, "execution_target", None) == "fast_path_direct_response"
    )


def _direct_fast_path_response(*, agent, gate, text: str) -> str:
    response = render_deterministic_direct_response(
        getattr(gate, "direct_response_type", None)
    )

    if response:
        return response

    renderer = getattr(agent, "render_direct_response", None)
    if callable(renderer):
        response = renderer(
            direct_response_type=getattr(gate, "direct_response_type", None),
            text=text,
        )
        if isinstance(response, str) and response.strip():
            return response.strip()

    return "Got it."


def _maybe_materialize_direct_artifact(*, agent, plan, planning, text: str):
    materializer = getattr(agent, "materialize_direct_artifact", None)
    if not callable(materializer):
        return None

    result = materializer(
        semantic_output_type=getattr(plan, "semantic_output_type", None),
        text=text,
        planning=planning,
    )

    if not isinstance(result, dict):
        return None

    artifact = result.get("artifact")
    response = result.get("response")
    if not isinstance(artifact, dict):
        return None
    if not isinstance(response, str) or not response.strip():
        return None

    return {
        "artifact": artifact,
        "response": response.strip(),
        "events": result.get("events") if isinstance(result.get("events"), dict) else {},
    }
