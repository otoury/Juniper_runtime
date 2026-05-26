import json
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.context_trace import (  # noqa: E402
    emit_planned_context_trace_telemetry,
    planned_context_trace_to_payload,
    trace_planned_context,
)


def write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8",
    )


def make_agent(
    root: Path,
    *,
    agent_name: str,
    bindings: dict,
    skill_names: list[str] | None = None,
    resources: list[str] | None = None,
):
    agent_dir = root / "agents" / agent_name

    for skill in skill_names or []:
        skill_path = agent_dir / "skills" / f"{skill}.md"
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        skill_path.write_text(f"{skill}\n", encoding="utf-8")

    for resource in resources or []:
        resource_path = agent_dir / "tools" / f"{resource}.py"
        resource_path.parent.mkdir(parents=True, exist_ok=True)
        resource_path.write_text("# planned context telemetry test\n")

    write_json(
        agent_dir / "capabilities" / "bindings.json",
        {
            "bindings": bindings,
        },
    )


class EnvFlag:
    def __init__(self, value: str | None):
        self.value = value
        self.previous = os.environ.get("JUNIPER_TRACE_BINDINGS")

    def __enter__(self):
        if self.value is None:
            os.environ.pop("JUNIPER_TRACE_BINDINGS", None)
        else:
            os.environ["JUNIPER_TRACE_BINDINGS"] = self.value

    def __exit__(self, exc_type, exc, tb):
        if self.previous is None:
            os.environ.pop("JUNIPER_TRACE_BINDINGS", None)
        else:
            os.environ["JUNIPER_TRACE_BINDINGS"] = self.previous


def make_reporter(events: list[dict]):
    def report_event(source_bot, event_type, payload, request_id=None):
        events.append(
            {
                "source_bot": source_bot,
                "event_type": event_type,
                "payload": payload,
                "request_id": request_id,
            }
        )

    return report_event


def test_telemetry_disabled():
    events: list[dict] = []

    with EnvFlag(None):
        trace = emit_planned_context_trace_telemetry(
            report_event=make_reporter(events),
            source_bot="alexis",
            request_id="req_disabled",
            agent_name="alexis",
            shared_capability="draft_email",
        )

    assert trace is None
    assert events == []


def test_telemetry_enabled_success():
    events: list[dict] = []

    with EnvFlag("1"):
        trace = emit_planned_context_trace_telemetry(
            report_event=make_reporter(events),
            source_bot="alexis",
            request_id="req_context_success",
            agent_name="alexis",
            shared_capability="draft_email",
            user_id="user_1",
        )

    assert trace is not None
    assert trace.resolution_status == "OK"
    assert len(events) == 1

    event = events[0]
    assert event["event_type"] == "planned_context_trace"
    assert event["request_id"] == "req_context_success"

    payload = event["payload"]
    assert payload["request_id"] == "req_context_success"
    assert payload["user_id"] == "user_1"
    assert payload["agent"] == "alexis"
    assert payload["shared_capability"] == "draft_email"
    assert payload["resolution_status"] == "OK"
    assert payload["bounded_item_count"] == 2
    assert payload["retrieval_execution"] is False
    assert payload["message_injection"] is False
    assert len(payload["planned_items"]) == 2
    assert payload["errors"] == []
    assert payload["manifest_path"].endswith(
        "agents/alexis/bindings/capabilities.json"
    )

    for item in payload["planned_items"]:
        assert item["bounded"] is True
        assert item["attributable"] is True
        assert item["planned_only"] is True


def test_error_payload():
    events: list[dict] = []

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        make_agent(
            root,
            agent_name="tester",
            bindings={
                "draft_email": {
                    "shared_capability": "draft_email",
                    "skills": ["structured_actions"],
                    "resources": ["guest_db"],
                    "context_policy": "guest_context",
                },
            },
            skill_names=["structured_actions"],
            resources=["guest_db"],
        )

        with EnvFlag("1"):
            trace = emit_planned_context_trace_telemetry(
                report_event=make_reporter(events),
                source_bot="tester",
                request_id="req_context_error",
                agent_name="tester",
                shared_capability="draft_email",
                root=root,
            )

    assert trace is not None
    assert trace.resolution_status == "ERROR"
    assert len(events) == 1

    payload = events[0]["payload"]
    assert payload["resolution_status"] == "ERROR"
    assert payload["planned_items"] == []
    assert payload["errors"][0]["error_code"] == "invalid_context_policy"
    assert payload["retrieval_execution"] is False
    assert payload["message_injection"] is False


def test_payload_serialization_safety():
    trace = trace_planned_context(
        request_id="req_context_json",
        agent_name="alexis",
        shared_capability="draft_email",
    )

    payload = planned_context_trace_to_payload(trace)
    encoded = json.dumps(payload)

    assert "planned_items" in encoded
    assert payload["retrieval_execution"] is False
    assert payload["message_injection"] is False


def main():
    test_telemetry_disabled()
    test_telemetry_enabled_success()
    test_error_payload()
    test_payload_serialization_safety()
    print("PASS context trace telemetry")


if __name__ == "__main__":
    main()
