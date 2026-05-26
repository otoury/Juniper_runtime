#planner/execution.py

import json
import os
import re
from dataclasses import dataclass

try:
    import httpx
except ModuleNotFoundError:
    httpx = None

from runtime.policies.model_selector import select_engine
from runtime.policies.model_registry import ENGINES
from semantics.transforms import get_transform_planning
from pathlib import Path
from planner.capability_mapping import resolve_planned_shared_capability
from planner.governance_boundary import (
    assert_no_governance_semantic_mutation,
    validate_planner_visible_governance_metadata,
)
from planner.lookup_metadata import declare_lookup_metadata
from runtime.loaders.contract_loader import list_contract_names
from runtime.registries.artifacts import get_artifact_engine_policy
from runtime.registries.semantic_matching import infer_artifact_type_from_text
from runtime.registries.contracts import build_contract_prompt_block

@dataclass
class ExecutionPlan:
    task_family: str
    reasoning_depth: str
    style_sensitivity: str
    requires_current_information: bool
    requires_web: bool
    requires_source_fidelity: bool
    privacy_sensitivity: str
    latency_preference: str
    output_risk: str
    input_type: str

    expected_output_type: str

    execution_target: str
    fallback_engines: list[str]

    requires_approval: bool
    reason: str

    transform_type: str | None = None
    semantic_output_type: str | None = None
    shared_capability: str | None = None
    lookup_metadata: dict | None = None
    direct_response_type: str | None = None
    governance_boundary_diagnostics: dict | None = None

PLANNER_PROMPT = """
You are Juniper's task analyzer.

Your job is NOT to choose a model.
Your job is NOT to infer artifact semantics or agent-specific deliverables.
Your job is to analyze the generic computational shape of the task.

Analyze:
- reasoning depth
- style sensitivity
- need for current information
- need for web/external retrieval
- source fidelity
- privacy sensitivity
- latency preference
- output risk
- input type
- expected response category

Important distinctions:

requires_current_information:
ONLY true if the task depends on live/recent/changing information.

Examples:
- latest news
- current stock price
- today's weather
- recent events

NOT:
- translation
- rewriting
- summarization
- stylistic editing
- drafting
- creating a short text artifact

requires_web:
ONLY true if external retrieval is required.

requires_source_fidelity:
True for:
- translation
- legal wording
- official statements
- exact summarization
- sensitive paraphrasing

expected_output_type:
- artifact: user expects a concrete produced artifact, such as a short text, note, title, draft, rewritten line, or formatted output
- action: user expects a structured action/tool/workflow object
- translation: user expects translated text
- summary: user expects a summary
- general_answer: normal conversational answer

lookup_metadata:
When the planned workflow explicitly requires a bounded exact entity lookup,
return a typed object with entity_name and optional workflow_topic.
For multiple explicitly requested entities, return target_entities in planner
order, where each entry contains entity_name only, plus optional workflow_topic.
When the planned workflow explicitly requires bounded entity search, return
search_requests where each entry has lookup_type="bounded_entity_search" and
either search_topic or query_intent, plus optional constraints or max_results.
Do not include datasource paths, adapter hints, ranking instructions, or
retrieved records. Entity type and source scope are capability binding policy,
not planner metadata. Otherwise return null or omit the field.

governance/trust metadata:
If governance, approval, visibility, trust, autonomy, or memory metadata is
present in surrounding runtime state, treat it as observational only. It may
explain execution eligibility, diagnostics, or operator visibility, but it must
not change operation, artifact type, shared capability, lookup metadata,
expected output type, web/current-information requirements, engine target,
fallbacks, approval routing, autonomy, or memory behavior.
"""


def build_execution_plan(
    *,
    original_text: str,
    resolved_text: str,
    resolution,
    dispatch,
    user_id: str,
    agent_root: Path | None = None,
    transform_type: str | None = None,
    semantic_output_type: str | None = None,
    shared_capability: str | None = None,
    direct_response_type: str | None = None,
    semantic_planning_metadata: dict | None = None,
    planner_visible_governance_metadata: dict | None = None,
) -> ExecutionPlan:
    governance_boundary_diagnostic = validate_planner_visible_governance_metadata(
        planner_visible_governance_metadata,
        source="build_execution_plan",
    )

    if direct_response_type:
        return ExecutionPlan(
            task_family="general",
            reasoning_depth="low",
            style_sensitivity="low",
            requires_current_information=False,
            requires_web=False,
            requires_source_fidelity=False,
            privacy_sensitivity="low",
            latency_preference="fast",
            output_risk="low",
            input_type="short_text",
            expected_output_type="general_answer",
            execution_target="fast_path_direct_response",
            fallback_engines=[],
            requires_approval=False,
            reason=(
                "Direct fast-path answer for simple conversational act; "
                "no model execution required."
            ),
            transform_type=None,
            semantic_output_type=None,
            shared_capability=None,
            lookup_metadata=None,
            direct_response_type=direct_response_type,
            governance_boundary_diagnostics=governance_boundary_diagnostic,
        )

    if getattr(resolution, "action", None) == "CONTINUE":
        requirements = ExecutionPlan(
            task_family="general",
            reasoning_depth="low",
            style_sensitivity="medium",

            requires_current_information=False,
            requires_web=False,
            requires_source_fidelity=False,

            privacy_sensitivity="medium",
            latency_preference="fast",
            output_risk="medium",

            input_type="short_text",

            expected_output_type="action",

            semantic_output_type=None,
            shared_capability=resolve_planned_shared_capability(
                operation="ACTION",
                explicit_shared_capability=shared_capability,
            ),

            execution_target="",
            fallback_engines=[],

            requires_approval=True,

            reason="Continue workflow through structured action handling.",
            governance_boundary_diagnostics=governance_boundary_diagnostic,
        )

        preferred, fallbacks = select_engine(
            requirements
        )

        requirements.execution_target = preferred
        requirements.fallback_engines = fallbacks

        return requirements

    if transform_type:

        if semantic_output_type is None:
            raise ValueError(
                "Transform execution requires semantic_output_type"
            )
        planning = get_transform_planning(transform_type)

        if planning:

            return ExecutionPlan(
                task_family=planning[
                    "task_family"
                ],

                reasoning_depth=planning[
                    "reasoning_depth"
                ],

                style_sensitivity=planning[
                    "style_sensitivity"
                ],

                requires_current_information=False,
                requires_web=False,
                requires_source_fidelity=False,

                privacy_sensitivity="low",
                latency_preference="fast",
                output_risk="low",

                input_type="artifact",

                expected_output_type="artifact",

                semantic_output_type=semantic_output_type,
                shared_capability=resolve_planned_shared_capability(
                    operation="TRANSFORM",
                    semantic_output_type=semantic_output_type,
                    transform_type=transform_type,
                    explicit_shared_capability=shared_capability,
                ),

                execution_target=planning[
                    "execution_target"
                ],

                fallback_engines=[
                    engine
                    for engine in [
                        "local_agent",
                        "cloud_deep",
                    ]
                    if engine != planning.get(
                        "execution_target"
                    )
                ],

                requires_approval=False,

                reason=(
                    f"Apply semantic transform "
                    f"'{transform_type}' "
                    f"to existing artifact."
                ),

                transform_type=transform_type,
                lookup_metadata=None,
                governance_boundary_diagnostics=governance_boundary_diagnostic,
            )
        
    if semantic_output_type:

        resolved_capability = resolve_planned_shared_capability(
            operation="NEW_REQUEST",
            semantic_output_type=semantic_output_type,
            explicit_shared_capability=shared_capability,
        )
        semantic_planning_metadata = (
            semantic_planning_metadata
            if isinstance(semantic_planning_metadata, dict)
            else {}
        )
        semantic_metadata_diagnostic = assert_no_governance_semantic_mutation(
            semantic_planning_metadata,
            source="semantic_planning_metadata",
        )
        requires_current_information = bool(
            semantic_planning_metadata.get(
                "requires_current_information",
                False,
            )
        )
        requires_web = bool(
            semantic_planning_metadata.get("requires_web", False)
        )
        requires_source_fidelity = bool(
            semantic_planning_metadata.get(
                "requires_source_fidelity",
                False,
            )
        )
        requirements = ExecutionPlan(
            task_family=str(
                semantic_planning_metadata.get(
                    "task_family",
                    "drafting",
                )
            ),
            reasoning_depth=str(
                semantic_planning_metadata.get(
                    "reasoning_depth",
                    "low",
                )
            ),
            style_sensitivity=str(
                semantic_planning_metadata.get(
                    "style_sensitivity",
                    "high",
                )
            ),

            requires_current_information=requires_current_information,
            requires_web=requires_web,
            requires_source_fidelity=requires_source_fidelity,

            privacy_sensitivity=str(
                semantic_planning_metadata.get(
                    "privacy_sensitivity",
                    "low",
                )
            ),
            latency_preference=str(
                semantic_planning_metadata.get(
                    "latency_preference",
                    "fast",
                )
            ),
            output_risk=str(
                semantic_planning_metadata.get(
                    "output_risk",
                    "low",
                )
            ),

            input_type="short_text",

            expected_output_type=str(
                semantic_planning_metadata.get(
                    "expected_output_type",
                    "artifact",
                )
            ),

            semantic_output_type=semantic_output_type,
            shared_capability=resolved_capability,

            execution_target="",
            fallback_engines=[],

            requires_approval=False,

            reason=(
                f"Create semantic artifact "
                f"'{semantic_output_type}'."
            ),
            governance_boundary_diagnostics=semantic_metadata_diagnostic,
        )

        preferred, fallbacks = select_engine(
            requirements
        )

        requirements.execution_target = preferred
        requirements.fallback_engines = fallbacks
        minimum_engine_tier = semantic_planning_metadata.get(
            "minimum_engine_tier"
        )
        if (
            isinstance(minimum_engine_tier, str)
            and minimum_engine_tier in ENGINES
            and ENGINES[minimum_engine_tier].get("available", True)
            and minimum_engine_tier != preferred
        ):
            requirements.execution_target = minimum_engine_tier
            requirements.fallback_engines = [
                engine
                for engine in [preferred, *fallbacks]
                if engine != minimum_engine_tier
            ]
        lookup_metadata = declare_lookup_metadata(
            text=original_text,
            agent_name=getattr(dispatch, "target_agent", ""),
            shared_capability=resolved_capability,
            root=agent_root.parents[1] if agent_root else Path.cwd(),
        )
        requirements.lookup_metadata = (
            lookup_metadata.to_request_metadata()
            if lookup_metadata
            else None
        )

        return requirements
    
    semantic_output_types = []

    if agent_root:
        semantic_output_types = list_contract_names(
            agent_root=agent_root,
        )

    inferred_artifact_type = None

    if semantic_output_type is None:
        inferred_artifact_type = infer_artifact_type_from_text(
            resolved_text
        )

        if inferred_artifact_type:
            return build_execution_plan(
                original_text=original_text,
                resolved_text=resolved_text,
                resolution=resolution,
                dispatch=dispatch,
                user_id=user_id,
                agent_root=agent_root,
                transform_type=transform_type,
                semantic_output_type=inferred_artifact_type,
                shared_capability=shared_capability,
                semantic_planning_metadata=semantic_planning_metadata,
                planner_visible_governance_metadata=(
                    planner_visible_governance_metadata
                ),
            )

    data = _call_planner_ai(
        original_text=original_text,
        resolved_text=resolved_text,
        semantic_output_types=semantic_output_types,
    )

    plan = _validate_plan(
        data,
        semantic_output_types=semantic_output_types,
    )
    plan.governance_boundary_diagnostics = governance_boundary_diagnostic

    if (
        plan.expected_output_type == "artifact"
        and semantic_output_type
    ):
        plan.semantic_output_type = (
            semantic_output_type
        )
        plan.shared_capability = resolve_planned_shared_capability(
            semantic_output_type=semantic_output_type,
            explicit_shared_capability=shared_capability,
        )
        lookup_metadata = declare_lookup_metadata(
            text=original_text,
            agent_name=getattr(dispatch, "target_agent", ""),
            shared_capability=plan.shared_capability,
            model_lookup_metadata=plan.lookup_metadata,
            root=agent_root.parents[1] if agent_root else Path.cwd(),
        )
        plan.lookup_metadata = (
            lookup_metadata.to_request_metadata()
            if lookup_metadata
            else None
        )

        preferred_engine, fallback_engines = (
            get_artifact_engine_policy(
                semantic_output_type
            )
        )

        if preferred_engine:
            plan.execution_target = (
                preferred_engine
            )

            plan.fallback_engines = (
                fallback_engines
            )

    return plan

def _call_planner_ai(
    original_text: str,
    resolved_text: str,
    semantic_output_types: list[str],
) -> dict:
    if httpx is None:
        raise RuntimeError(
            "httpx is required for live execution planner calls"
        )

    base_url = os.getenv(
        "OLLAMA_URL",
        "http://thebrain.local:11434",
    )

    model = os.getenv(
        "OLLAMA_ROUTER_MODEL",
        "qwen2.5:7b-instruct",
    )
    contract_block = build_contract_prompt_block(
        "execution_planner"
    )
    prompt = f"""
        {PLANNER_PROMPT}
        {contract_block}
        ORIGINAL USER MESSAGE:
        {original_text}

        RESOLVED TASK:
        {resolved_text}
    """

    r = httpx.post(
        f"{base_url}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        },
        timeout=45.0,
    )

    r.raise_for_status()

    raw = r.json().get("response", "")

    match = re.search(
        r"\{.*\}",
        raw,
        re.DOTALL,
    )

    if not match:
        raise ValueError(
            f"Planner returned no JSON: {raw}"
        )

    return json.loads(match.group())


def _clean_enum(value, allowed, default):
    value = str(value or default).lower().strip()

    if value not in allowed:
        return default

    return value

def _validate_plan(
    data: dict,
    semantic_output_types: list[str],
) -> ExecutionPlan:
    governance_boundary_diagnostic = assert_no_governance_semantic_mutation(
        data,
        source="execution_planner_output",
    )

    def _clean_bool(
        value,
        default: bool = False,
    ) -> bool:
        if isinstance(value, bool):
            return value

        if isinstance(value, str):
            lowered = value.strip().lower()

            if lowered in {
                "true",
                "yes",
                "1",
            }:
                return True

            if lowered in {
                "false",
                "no",
                "0",
            }:
                return False

        return default

    task_family = _clean_enum(
        data.get("task_family"),
        [
            "translation",
            "rewriting",
            "summarization",
            "drafting",
            "research",
            "general",
        ],
        "general",
    )

    reasoning_depth = _clean_enum(
        data.get("reasoning_depth"),
        ["low", "medium", "deep"],
        "medium",
    )

    style_sensitivity = _clean_enum(
        data.get("style_sensitivity"),
        ["low", "medium", "high"],
        "medium",
    )

    privacy_sensitivity = _clean_enum(
        data.get("privacy_sensitivity"),
        ["low", "medium", "high"],
        "low",
    )

    latency_preference = _clean_enum(
        data.get("latency_preference"),
        ["fast", "balanced", "best"],
        "balanced",
    )

    output_risk = _clean_enum(
        data.get("output_risk"),
        ["low", "medium", "high"],
        "low",
    )

    input_type = _clean_enum(
        data.get("input_type"),
        [
            "short_text",
            "long_text",
            "translation",
            "query",
            "unknown",
        ],
        "unknown",
    )

    expected_output_type = _clean_enum(
        data.get("expected_output_type"),
        [
            "artifact",
            "action",
            "translation",
            "summary",
            "general_answer",
        ],
        "general_answer",
    )
    semantic_output_type = None
    requires_current_information = _clean_bool(
        data.get("requires_current_information"),
        False,
    )

    requires_web = _clean_bool(
        data.get("requires_web"),
        False,
    )

    requires_source_fidelity = _clean_bool(
        data.get("requires_source_fidelity"),
        False,
    )

    requires_approval = _clean_bool(
        data.get("requires_approval"),
        False,
    )
    raw_lookup_metadata = data.get("lookup_metadata")
    lookup_metadata = (
        dict(raw_lookup_metadata)
        if isinstance(raw_lookup_metadata, dict)
        else None
    )

    requirements = ExecutionPlan(
        task_family=task_family,
        reasoning_depth=reasoning_depth,
        style_sensitivity=style_sensitivity,
        requires_current_information=requires_current_information,
        requires_web=requires_web,
        requires_source_fidelity=requires_source_fidelity,
        privacy_sensitivity=privacy_sensitivity,
        latency_preference=latency_preference,
        output_risk=output_risk,
        input_type=input_type,
        expected_output_type=expected_output_type,
        semantic_output_type=semantic_output_type,
        shared_capability=None,
        lookup_metadata=lookup_metadata,
        execution_target="",
        fallback_engines=[],
        requires_approval=requires_approval,
        reason=str(data.get("reason", "")).strip(),
        governance_boundary_diagnostics=governance_boundary_diagnostic,
    )

    preferred_engine, fallback_engines = get_artifact_engine_policy(
        semantic_output_type
    )

    if (
        expected_output_type == "artifact"
        and preferred_engine
    ):
        requirements.execution_target = preferred_engine
        requirements.fallback_engines = fallback_engines
        return requirements

    preferred, fallbacks = select_engine(requirements)

    requirements.execution_target = preferred
    requirements.fallback_engines = fallbacks

    return requirements

def should_use_cloud_engine(plan) -> bool:
    engine = ENGINES.get(plan.execution_target, {})
    return engine.get("execution_tier") == "cloud"
