from runtime.states import RequestState

VALID_TRANSITIONS = {

    RequestState.RECEIVED: [
        RequestState.ROUTED,
        RequestState.FAILED,
    ],

    RequestState.ROUTED: [
        RequestState.CONTEXT_RESOLVED,
        RequestState.FAILED,
    ],

    RequestState.CONTEXT_RESOLVED: [
        RequestState.PLANNED,
        RequestState.FAILED,
    ],

    RequestState.PLANNED: [
        RequestState.EXECUTING,
        RequestState.FAILED,
    ],

    RequestState.EXECUTING: [
        RequestState.ACTION_PENDING,
        RequestState.COMPLETED,
        RequestState.FAILED,
    ],

    RequestState.ACTION_PENDING: [
        RequestState.TOOL_RUNNING,
        RequestState.COMPLETED,
        RequestState.FAILED,
    ],

    RequestState.TOOL_RUNNING: [
        RequestState.COMPLETED,
        RequestState.FAILED,
    ],
}


def validate_transition(
    old_state,
    new_state,
):
    allowed = VALID_TRANSITIONS.get(
        old_state,
        [],
    )

    return new_state in allowed
