from runtime.actions.types import AgentAction


def detect_action(
    agent_name: str,
    user_text: str,
    response_text: str,
) -> AgentAction | None:
    """
    First-pass action detector.

    This does NOT execute anything.
    It only marks that the assistant produced something actionable.
    """

    text = user_text.lower()
    response = response_text.strip()

    if not response:
        return None

    if agent_name == "alexis":
        if "draft" in text and ("email" in text or "outreach" in text):
            return AgentAction(
                action_type="draft_email",
                confidence=0.8,
                requires_approval=True,
                payload={
                    "draft_text": response,
                    "source_request": user_text,
                },
                reason="User requested an outreach/email draft.",
            )

    return None
