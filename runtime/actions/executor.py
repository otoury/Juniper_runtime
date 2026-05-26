from tools.executor import execute_tool
from runtime.actions.queue import update_action_status


def execute_action(action: dict):
    result = execute_tool(
        action["action_type"],
        action.get("payload", {}),
    )

    if result.success:
        update_action_status(
            action["action_id"],
            "completed",
        )
    else:
        update_action_status(
            action["action_id"],
            "failed",
        )

    return result