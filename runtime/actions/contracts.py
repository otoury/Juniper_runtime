from dataclasses import dataclass, field


@dataclass
class ActionEnvelope:
    action_type: str
    requires_approval: bool
    payload: dict
    confidence: float = 1.0
    reason: str = ""


@dataclass
class AgentOutput:
    assistant_response: str
    actions: list[ActionEnvelope] = field(default_factory=list)
