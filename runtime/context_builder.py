# runtime/context_builder.py

from __future__ import annotations

from dataclasses import dataclass



CONTEXT_LIGHT_OUTPUT_TYPES = {
    "lower_third",
    "rewrite",
    "summary",
    "translation",
}


@dataclass
class ContextBudget:
    max_system_chars: int = 10000
    max_runtime_context_chars: int = 4000
    include_guest_context: bool = True
    include_workspace_context: bool = True
    include_session_history: bool = True
    max_session_messages: int = 6
    workspace_files: list[str] | None = None


class RuntimeContextBuilder:
    """
    Backward-compatible builder used by existing agents.

    New runtime orchestration should use build_runtime_messages().
    """

    def __init__(self, policy=None, *args, **kwargs):
        self.policy = policy

    def build(self, ctx):
        if self.policy and hasattr(self.policy, "build"):
            return self.policy.build(ctx)

        if self.policy and hasattr(self.policy, "select"):
            return self.policy.select(ctx)

        return ctx

    def build_context(self, ctx):
        return self.build(ctx)
    
    def get_budget(
        self,
        *,
        semantic_output_type: str | None,
        interaction_mode: str | None,
    ) -> ContextBudget:
        if self.policy and hasattr(self.policy, "get_budget"):
            return self.policy.get_budget(
                semantic_output_type=semantic_output_type,
                interaction_mode=interaction_mode,
            )

        return ContextBudget()

    def build_system_message(
        self,
        *,
        base_components: list[str],
        runtime_components: list[str],
        budget: ContextBudget,
    ) -> str:
        base_text = "\n\n".join(
            block.strip()
            for block in base_components
            if block and block.strip()
        )

        runtime_text = "\n\n".join(
            block.strip()
            for block in runtime_components
            if block and block.strip()
        )

        if budget.max_runtime_context_chars:
            runtime_text = runtime_text[:budget.max_runtime_context_chars]

        parts = []

        if base_text:
            parts.append(base_text)

        if runtime_text:
            parts.append("RUNTIME CONTEXT:\n" + runtime_text)

        system_text = "\n\n".join(parts).strip()

        if budget.max_system_chars:
            system_text = system_text[:budget.max_system_chars]

        return system_text

    def __call__(self, ctx):
        return self.build(ctx)


def should_include_agent_context(
    *,
    fast_path: bool,
    semantic_output_type: str | None,
    interaction_mode: str,
) -> bool:
    if fast_path:
        return False

    if interaction_mode == "TRANSFORM_EXISTING":
        return False

    if semantic_output_type in CONTEXT_LIGHT_OUTPUT_TYPES:
        return False

    return True

def build_runtime_messages(
    *,
    agent,
    resolved_text: str,
    dispatch,
    user_id: str,
    recent_memory,
    plan,
    gate,
    active_artifact: dict | None,
    fast_path: bool,
):
    # Local import prevents circular import:
    # agents.base -> runtime.context_builder -> agents.base
    from agents.base import AgentContext

    execution_source_text = resolved_text

    include_agent_context = should_include_agent_context(
        fast_path=fast_path,
        semantic_output_type=plan.semantic_output_type,
        interaction_mode=gate.interaction_mode,
    )

    ctx = AgentContext(
        user_input=execution_source_text,
        dispatch=dispatch,
        user_id=user_id,
        session_history=recent_memory,
        include_guest_context=include_agent_context,
        include_workspace_context=include_agent_context,
        semantic_output_type=plan.semantic_output_type,
        interaction_mode=gate.interaction_mode,
        expected_output_type=plan.expected_output_type,
    )

    return agent.build_messages(ctx), execution_source_text


__all__ = [
    "ContextBudget",
    "RuntimeContextBuilder",
    "build_runtime_messages",
    "inject_artifact_contract",
    "should_include_agent_context",
]
