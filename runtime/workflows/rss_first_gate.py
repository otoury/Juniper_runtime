from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RssFirstRoutingResult:
    applicable: bool
    ready: bool
    reason: str
    workflow_id: str | None = None
    response: str | None = None
    event_payload: dict[str, Any] | None = None
    artifact: dict[str, Any] | None = None

    def to_event_payload(self) -> dict[str, Any]:
        payload = {
            "applicable": self.applicable,
            "ready": self.ready,
            "reason": self.reason,
            "workflow_id": self.workflow_id,
        }
        if isinstance(self.event_payload, dict):
            payload.update(self.event_payload)
        return payload


def coerce_rss_first_routing_result(value: Any) -> RssFirstRoutingResult | None:
    if isinstance(value, RssFirstRoutingResult):
        return value

    if not isinstance(value, dict):
        return None

    applicable = value.get("applicable")
    ready = value.get("ready")
    if not isinstance(applicable, bool) or not isinstance(ready, bool):
        return None

    response = value.get("response")
    return RssFirstRoutingResult(
        applicable=applicable,
        ready=ready,
        reason=_safe_text(value.get("reason"), default="RSS-first routing gate."),
        workflow_id=_optional_text(value.get("workflow_id")),
        response=response.strip() if isinstance(response, str) else None,
        event_payload=(
            dict(value.get("event_payload"))
            if isinstance(value.get("event_payload"), dict)
            else None
        ),
        artifact=(
            dict(value.get("artifact"))
            if isinstance(value.get("artifact"), dict)
            else None
        ),
    )


def _safe_text(value: Any, *, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return " ".join(value.split())
    return default


def _optional_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return " ".join(value.split())
    return None


__all__ = [
    "RssFirstRoutingResult",
    "coerce_rss_first_routing_result",
]
