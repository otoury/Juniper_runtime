from dataclasses import dataclass


@dataclass
class AgentAction:
    action_type: str
    confidence: float
    requires_approval: bool
    payload: dict
    reason: str = ""
