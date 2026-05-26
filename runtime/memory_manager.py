# runtime/memory_manager.py

from __future__ import annotations

from memory.store import append_memory


def strip_transport_metadata(text: str) -> str:
    text = text.strip()

    if "\n\n---\n[" in text:
        text = text.split("\n\n---\n[")[0]

    return text.strip()


def update_session(
    *,
    sessions: dict,
    user_id: str,
    user_text: str,
    assistant_text: str,
    max_messages: int = 6,
):
    if user_id not in sessions:
        sessions[user_id] = []

    sessions[user_id].extend([
        {
            "role": "user",
            "content": user_text,
        },
        {
            "role": "assistant",
            "content": assistant_text,
        },
    ])

    sessions[user_id] = sessions[user_id][-max_messages:]


def persist_conversation_memory(
    *,
    agent_name: str,
    user_id: str,
    session_id: str,
    user_text: str,
    assistant_text: str,
    sessions: dict,
):
    update_session(
        sessions=sessions,
        user_id=user_id,
        user_text=user_text,
        assistant_text=assistant_text,
    )

    append_memory(
        agent_name,
        user_id,
        "user",
        user_text,
        session_id=session_id,
    )

    memory_response = strip_transport_metadata(assistant_text)

    append_memory(
        agent_name,
        user_id,
        "assistant",
        memory_response,
        session_id=session_id,
    )


__all__ = [
    "persist_conversation_memory",
    "strip_transport_metadata",
    "update_session",
]
