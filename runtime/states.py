from enum import Enum


class RequestState(str, Enum):

    RECEIVED = "received"

    ROUTED = "routed"

    CONTEXT_RESOLVED = "context_resolved"

    PLANNED = "planned"

    EXECUTING = "executing"

    ACTION_PENDING = "action_pending"

    TOOL_RUNNING = "tool_running"

    COMPLETED = "completed"

    FAILED = "failed"
