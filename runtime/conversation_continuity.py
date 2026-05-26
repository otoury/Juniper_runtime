from __future__ import annotations

from dataclasses import dataclass
from typing import Any


MAX_CONTINUITY_TURNS = 2
MAX_CONTINUITY_CHARS = 1200
MAX_MESSAGE_CHARS = 500


@dataclass(frozen=True)
class ConversationTurn:
    user_text: str
    assistant_text: str

    def to_record(self) -> dict[str, str]:
        return {
            "user_text": self.user_text,
            "assistant_text": self.assistant_text,
        }


@dataclass(frozen=True)
class ConversationContinuity:
    turns: tuple[ConversationTurn, ...]
    max_turns: int = MAX_CONTINUITY_TURNS
    max_chars: int = MAX_CONTINUITY_CHARS

    @property
    def has_turns(self) -> bool:
        return bool(self.turns)

    def latest_turn(self) -> ConversationTurn | None:
        if not self.turns:
            return None
        return self.turns[-1]

    def to_event_payload(self) -> dict[str, Any]:
        return {
            "turn_count": len(self.turns),
            "max_turns": self.max_turns,
            "max_chars": self.max_chars,
            "has_continuity": self.has_turns,
        }


def build_conversation_continuity(
    recent_memory: list[dict[str, Any]] | None,
    *,
    max_turns: int = MAX_CONTINUITY_TURNS,
    max_chars: int = MAX_CONTINUITY_CHARS,
) -> ConversationContinuity:
    if not recent_memory:
        return ConversationContinuity(
            turns=(),
            max_turns=max_turns,
            max_chars=max_chars,
        )

    turns: list[ConversationTurn] = []
    pending_user: str | None = None

    for entry in recent_memory:
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("role") or "").strip()
        content = _bounded_text(entry.get("content"))
        if not content:
            continue
        if role == "user":
            pending_user = content
            continue
        if role == "assistant" and pending_user:
            turns.append(
                ConversationTurn(
                    user_text=pending_user,
                    assistant_text=content,
                )
            )
            pending_user = None

    return ConversationContinuity(
        turns=_fit_turn_budget(turns[-max_turns:], max_chars=max_chars),
        max_turns=max_turns,
        max_chars=max_chars,
    )


def _fit_turn_budget(
    turns: list[ConversationTurn],
    *,
    max_chars: int,
) -> tuple[ConversationTurn, ...]:
    selected: list[ConversationTurn] = []
    total = 0
    for turn in reversed(turns):
        size = len(turn.user_text) + len(turn.assistant_text)
        if selected and total + size > max_chars:
            break
        selected.append(turn)
        total += size
    return tuple(reversed(selected))


def _bounded_text(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) <= MAX_MESSAGE_CHARS:
        return text
    return text[:MAX_MESSAGE_CHARS].rstrip()


__all__ = [
    "ConversationContinuity",
    "ConversationTurn",
    "build_conversation_continuity",
]
