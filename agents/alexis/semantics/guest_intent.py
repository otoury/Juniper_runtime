from __future__ import annotations

import re
from dataclasses import dataclass, field


DISCOVERY_VERBS = {
    "find",
    "identify",
    "recommend",
    "suggest",
    "surface",
}
GUEST_ENTITIES = {
    "analyst",
    "analysts",
    "expert",
    "experts",
    "guest",
    "guests",
    "panelist",
    "panelists",
}
GUEST_REFERENTS = {
    "them",
}
CONTACT_DISCOVERY_ENTITIES = {
    "booker",
    "bookers",
    "booking",
    "contact",
    "contacts",
    "scheduler",
    "schedulers",
    "office",
    "press",
    "communications",
    "comms",
}
PUBLIC_OFFICE_ENTITIES = {
    "congressman",
    "congresswoman",
    "representative",
    "rep",
    "senator",
    "governor",
    "mayor",
}
OUTREACH_ACTIONS = {
    "contact",
    "contacts",
    "draft",
    "email",
    "invite",
    "outreach",
    "send",
    "write",
}
TOPIC_STOPWORDS = (
    DISCOVERY_VERBS
    | GUEST_ENTITIES
    | OUTREACH_ACTIONS
    | {
        "a",
        "about",
        "an",
        "and",
        "for",
        "me",
        "on",
        "please",
        "best",
        "booking",
        "contacts",
        "contact",
        "segment",
        "the",
        "these",
        "this",
        "to",
    }
)


@dataclass(frozen=True)
class AlexisGuestSemanticIntent:
    semantic_operation: str
    semantic_output_type: str
    shared_capability: str | None
    topic_text: str | None
    planning_metadata: dict[str, object] = field(default_factory=dict)


def classify_guest_semantic_intent(
    text: str,
) -> AlexisGuestSemanticIntent | None:
    tokens = _tokens(text)
    token_set = set(tokens)

    if not tokens:
        return None

    has_guest_entity = bool(token_set & GUEST_ENTITIES)
    has_guest_reference = bool(token_set & GUEST_REFERENTS)
    has_discovery = bool(token_set & DISCOVERY_VERBS)
    has_outreach = bool(token_set & OUTREACH_ACTIONS)
    has_contact_discovery_entity = bool(token_set & CONTACT_DISCOVERY_ENTITIES)
    has_public_office_entity = bool(token_set & PUBLIC_OFFICE_ENTITIES)

    if (
        has_discovery
        and has_contact_discovery_entity
        and (
            "booking" in token_set
            or has_public_office_entity
        )
    ):
        return AlexisGuestSemanticIntent(
            semantic_operation="booking_contact_discovery",
            semantic_output_type="sourced_contact_result",
            shared_capability="discover_entities",
            topic_text=_topic_text(tokens),
            planning_metadata={
                "task_family": "research",
                "reasoning_depth": "deep",
                "requires_current_information": True,
                "requires_web": True,
                "requires_source_fidelity": True,
                "latency_preference": "best",
                "expected_output_type": "artifact",
                "minimum_engine_tier": "cloud_web_deep",
            },
        )

    if (
        (has_guest_entity or has_guest_reference)
        and has_outreach
        and not has_discovery
    ):
        return AlexisGuestSemanticIntent(
            semantic_operation="outreach_drafting",
            semantic_output_type="email_draft",
            shared_capability="draft_email",
            topic_text=_topic_text(tokens),
        )

    if has_guest_entity and has_discovery:
        return AlexisGuestSemanticIntent(
            semantic_operation="guest_discovery",
            semantic_output_type="guest_candidate_list",
            shared_capability="discover_entities",
            topic_text=_topic_text(tokens),
        )

    return None


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(
        token.lower()
        for token in re.findall(r"\b[a-zA-Z][a-zA-Z0-9_-]*\b", text or "")
    )


def _topic_text(tokens: tuple[str, ...]) -> str | None:
    topic_tokens = [
        token for token in tokens
        if token not in TOPIC_STOPWORDS
    ]
    return " ".join(topic_tokens) if topic_tokens else None


__all__ = [
    "AlexisGuestSemanticIntent",
    "classify_guest_semantic_intent",
]
