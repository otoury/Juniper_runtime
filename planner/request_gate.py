# planner/request_gate.py

import json
import os
from dataclasses import dataclass
from enum import Enum

try:
    import httpx
except ModuleNotFoundError:
    httpx = None

from core.json_utils import extract_json
from core.schema_utils import validate_dataclass_schema
from planner.budget_gate import is_simple_standalone
from planner.capability_mapping import (
    normalize_planned_shared_capability,
)
from planner.direct_response import classify_deterministic_direct_response
from runtime.registries.contracts import build_contract_prompt_block
from runtime.registries.semantic_operations import get_operation_policy
from runtime.registries.semantic_matching import (
    infer_explicit_artifact_type_from_text,
)
from runtime.registries.semantic_taxonomy import (
    build_request_gate_taxonomy_block,
)

class InteractionMode(str, Enum):
    NEW_REQUEST = "NEW_REQUEST"
    TRANSFORM_EXISTING = "TRANSFORM_EXISTING"
    CONVERT_ARTIFACT = "CONVERT_ARTIFACT"
    CONTINUE_WORKFLOW = "CONTINUE_WORKFLOW"
    ANSWER_QUESTION = "ANSWER_QUESTION"


@dataclass
class RequestGateDecision:
    is_standalone: bool = True
    needs_followup_resolution: bool = False
    needs_capability_context: bool = False
    needs_full_planning: bool = False
    requires_artifact_context: bool = False
    safe_for_fast_path: bool = False
    reason: str = ""
    operation: str = "NONE"
    interaction_mode: str = InteractionMode.NEW_REQUEST.value
    transform_intent: str | None = None
    explicit_artifact_type: str | None = None
    requires_active_artifact: bool | str = False
    uses_active_artifact: bool = False
    preserves_artifact_type: bool | None = None
    shared_capability: str | None = None
    deterministic_direct_response: bool = False
    direct_response_type: str | None = None
    needs_model: bool = True
    needs_lookup_context: bool = True
    needs_workflow: bool = True


REQUEST_GATE_PROMPT = """
You are Juniper's request gate.

Your job is NOT to answer the user.
Your job is NOT to choose an agent or model.
Your job is only to classify the interaction shape.

Canonical interaction modes:

The canonical taxonomy is supplied below. Follow it exactly.

safe_for_fast_path=true ONLY when:
- interaction_mode is NEW_REQUEST or ANSWER_QUESTION
- no artifact context is needed
- no workflow context is needed
- no database/tool/workspace/context retrieval is needed
- no current information is needed
- no source fidelity is needed
- no high-risk or complex reasoning is needed

shared_capability is provenance only. Set it only when the request explicitly
maps to one listed shared capability with high confidence. Otherwise return
null. Do not invent, alias, or keyword-match capabilities.
"""


def analyze_request_gate(
    text: str,
    has_session_history: bool = False,
) -> RequestGateDecision:
    clean = text.strip()

    if not clean:
        return _derive_gate_fields(
            RequestGateDecision(
                interaction_mode=InteractionMode.NEW_REQUEST.value,
                safe_for_fast_path=False,
                reason="Empty request.",
            )
        )

    direct_response = classify_deterministic_direct_response(clean)

    if direct_response is not None:
        return _derive_gate_fields(
            RequestGateDecision(
                interaction_mode=InteractionMode.ANSWER_QUESTION.value,
                safe_for_fast_path=True,
                deterministic_direct_response=True,
                direct_response_type=direct_response.response_type,
                needs_model=direct_response.needs_model,
                needs_lookup_context=direct_response.needs_lookup_context,
                needs_workflow=direct_response.needs_workflow,
                reason=(
                    f"{direct_response.reason} No artifact, workflow, "
                    "lookup, or external context required."
                ),
            )
        )

    if not has_session_history and is_simple_standalone(clean):
        return _derive_gate_fields(
            RequestGateDecision(
                interaction_mode=InteractionMode.NEW_REQUEST.value,
                safe_for_fast_path=True,
                reason="Deterministic simple standalone request with no session history.",
            )
        )

    explicit_artifact_type = infer_explicit_artifact_type_from_text(
        clean
    )

    if explicit_artifact_type:
        return _derive_gate_fields(
            RequestGateDecision(
                interaction_mode=InteractionMode.NEW_REQUEST.value,
                explicit_artifact_type=explicit_artifact_type,
                safe_for_fast_path=False,
                reason=(
                    "Explicit request for a new "
                    f"{explicit_artifact_type} deliverable."
                ),
            )
        )

    if len(clean) > 1200 or "\n" in clean:
        return _derive_gate_fields(
            RequestGateDecision(
                interaction_mode=InteractionMode.NEW_REQUEST.value,
                needs_capability_context=True,
                needs_full_planning=True,
                safe_for_fast_path=False,
                reason="Long or multiline payload requires deliberate planning/source handling.",
            )
        )

    try:
        data = _call_gate_ai(clean, has_session_history)

        return _validate_gate(
            data,
            original_text=text,
        )

    except Exception as e:
        return _derive_gate_fields(
            RequestGateDecision(
                interaction_mode=InteractionMode.NEW_REQUEST.value,
                needs_full_planning=True,
                safe_for_fast_path=False,
                reason=(
                    "Request gate failed; safe fallback to full planning: "
                    f"{repr(e)}"
                ),
            )
        )


def _call_gate_ai(
    text: str,
    has_session_history: bool,
) -> dict:
    if httpx is None:
        raise RuntimeError(
            "httpx is required for live request gate calls"
        )

    base_url = os.getenv(
        "OLLAMA_URL",
        "http://thebrain.local:11434",
    )

    model = os.getenv(
        "OLLAMA_GATE_MODEL",
        os.getenv(
            "OLLAMA_ROUTER_MODEL",
            "qwen2.5:7b-instruct",
        ),
    )

    contract_block = build_contract_prompt_block(
        "request_gate"
    )

    taxonomy_block = build_request_gate_taxonomy_block()

    prompt = f"""
        {REQUEST_GATE_PROMPT}

        {taxonomy_block}

        {contract_block}

        HAS_SESSION_HISTORY:
        {has_session_history}

        LATEST USER MESSAGE:
        {text}
    """

    r = httpx.post(
        f"{base_url}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        },
        timeout=30.0,
    )

    r.raise_for_status()

    raw = r.json().get("response", "")
    return extract_json(raw)


def _validate_gate(
    data: dict,
    original_text: str = "",
) -> RequestGateDecision:
    decision = validate_dataclass_schema(
        RequestGateDecision,
        data,
    )

    decision.reason = str(
        decision.reason or "Request gate decision."
    ).strip()

    decision.transform_intent = (
        str(decision.transform_intent).strip()
        if decision.transform_intent
        else None
    )

    decision.shared_capability = normalize_planned_shared_capability(
        decision.shared_capability
    )
    decision.direct_response_type = (
        str(decision.direct_response_type).strip().lower()
        if decision.direct_response_type
        else None
    )
    return _derive_gate_fields(decision)


def _derive_gate_fields(
    decision: RequestGateDecision,
) -> RequestGateDecision:
    decision.shared_capability = normalize_planned_shared_capability(
        decision.shared_capability
    )

    allowed_modes = {mode.value for mode in InteractionMode}

    mode = str(
        decision.interaction_mode or InteractionMode.NEW_REQUEST.value
    ).upper().strip()

    if mode not in allowed_modes:
        mode = InteractionMode.NEW_REQUEST.value

    decision.interaction_mode = mode

    def apply_policy(
        operation: str,
        *,
        public_operation: str,
    ) -> dict:
        policy = get_operation_policy(operation)
        required_artifact = policy["requires_active_artifact"]

        decision.operation = public_operation
        decision.requires_active_artifact = required_artifact
        decision.requires_artifact_context = bool(
            policy["requires_artifact_context"]
        )
        decision.needs_capability_context = bool(
            policy["needs_capability_context"]
        )
        decision.preserves_artifact_type = policy[
            "preserves_artifact_type"
        ]

        if required_artifact == "optional":
            decision.uses_active_artifact = bool(
                decision.uses_active_artifact
            )
        else:
            decision.uses_active_artifact = bool(required_artifact)

        return policy

    if mode == InteractionMode.TRANSFORM_EXISTING.value:
        decision.shared_capability = None
        decision.deterministic_direct_response = False
        decision.direct_response_type = None
        decision.needs_model = True
        decision.needs_lookup_context = True
        decision.needs_workflow = False
        apply_policy(
            "TRANSFORM",
            public_operation="TRANSFORM",
        )
        decision.is_standalone = False
        decision.needs_followup_resolution = True
        decision.safe_for_fast_path = False

        if not decision.transform_intent:
            decision.transform_intent = "transform existing artifact"
    
    elif mode == InteractionMode.CONVERT_ARTIFACT.value:
        decision.shared_capability = None
        decision.deterministic_direct_response = False
        decision.direct_response_type = None
        decision.needs_model = True
        decision.needs_lookup_context = True
        decision.needs_workflow = False
        apply_policy(
            "CONVERT",
            public_operation="CONVERT",
        )
        decision.is_standalone = False
        decision.needs_followup_resolution = True
        decision.safe_for_fast_path = False

        if not decision.transform_intent:
            decision.transform_intent = "convert existing artifact"

    elif mode == InteractionMode.CONTINUE_WORKFLOW.value:
        decision.deterministic_direct_response = False
        decision.direct_response_type = None
        decision.needs_model = True
        decision.needs_lookup_context = True
        decision.needs_workflow = True
        apply_policy(
            "ACTION",
            public_operation="CONTINUE",
        )
        decision.is_standalone = False
        decision.needs_followup_resolution = True
        decision.safe_for_fast_path = False
        decision.transform_intent = None

    elif mode == InteractionMode.ANSWER_QUESTION.value:
        decision.is_standalone = True
        decision.needs_followup_resolution = False
        decision.requires_artifact_context = False
        decision.needs_capability_context = False
        decision.operation = "ANSWER"
        decision.transform_intent = None
        decision.requires_active_artifact = False
        decision.uses_active_artifact = False
        decision.preserves_artifact_type = None
        if decision.deterministic_direct_response:
            decision.needs_model = False
            decision.needs_lookup_context = False
            decision.needs_workflow = False

    else:
        decision.deterministic_direct_response = False
        decision.direct_response_type = None
        decision.needs_model = True
        decision.needs_lookup_context = bool(decision.needs_capability_context)
        decision.needs_workflow = False
        apply_policy(
            "NEW_REQUEST",
            public_operation="NONE",
        )
        decision.is_standalone = True
        decision.needs_followup_resolution = False
        decision.transform_intent = None

    if (
        decision.needs_capability_context
        or decision.needs_full_planning
    ):
        decision.safe_for_fast_path = False
        decision.deterministic_direct_response = False
        decision.direct_response_type = None
        decision.needs_model = True

    if decision.requires_artifact_context:
        decision.safe_for_fast_path = False
        decision.deterministic_direct_response = False
        decision.direct_response_type = None
        decision.needs_model = True

    if not decision.direct_response_type:
        decision.deterministic_direct_response = False

    if decision.deterministic_direct_response:
        decision.safe_for_fast_path = True
        decision.needs_model = False
        decision.needs_lookup_context = False
        decision.needs_workflow = False

    if not decision.reason:
        decision.reason = "Request gate decision."

    return decision
