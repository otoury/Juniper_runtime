# agents/alexis/context_policy.py

from runtime.context_builder import ContextBudget


class AlexisContextPolicy:
    def get_budget(
        self,
        *,
        semantic_output_type: str | None,
        interaction_mode: str | None,
    ) -> ContextBudget:

        # Artifact transforms should be tiny and stable.
        if interaction_mode == "TRANSFORM_EXISTING":
            return ContextBudget(
                max_system_chars=5000,
                max_runtime_context_chars=1000,
                include_guest_context=False,
                include_workspace_context=False,
                include_session_history=True,
                max_session_messages=4,
                workspace_files=[],
            )

        if semantic_output_type == "lower_third":
            return ContextBudget(
                max_system_chars=5000,
                max_runtime_context_chars=1000,
                include_guest_context=False,
                include_workspace_context=False,
                include_session_history=True,
                max_session_messages=4,
                workspace_files=[],
            )

        if semantic_output_type == "guest_booking":
            return ContextBudget(
                max_system_chars=12000,
                max_runtime_context_chars=7000,
                include_guest_context=True,
                include_workspace_context=True,
                include_session_history=True,
                max_session_messages=8,
                workspace_files=[
                    "USER.md",
                    "BOOKING_PROCEDURES.md",
                ],
            )

        if semantic_output_type == "outreach_email":
            return ContextBudget(
                max_system_chars=10000,
                max_runtime_context_chars=5000,
                include_guest_context=True,
                include_workspace_context=True,
                include_session_history=True,
                max_session_messages=8,
                workspace_files=[
                    "USER.md",
                    "BOOKING_PROCEDURES.md",
                ],
            )

        return ContextBudget(
            max_system_chars=10000,
            max_runtime_context_chars=4000,
            include_guest_context=False,
            include_workspace_context=True,
            include_session_history=True,
            max_session_messages=6,
            workspace_files=[
                "USER.md",
            ],
        )
