import json
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.binding_trace import (  # noqa: E402
    binding_trace_to_payload,
    emit_planned_capability_trace_telemetry,
    trace_planned_capability,
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
):
    agent_dir = root / "agents" / agent_name

    for skill in skill_names or []:
        skill_path = agent_dir / "skills" / f"{skill}.md"
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        skill_path.write_text(f"{skill}\n", encoding="utf-8")

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
        trace = emit_planned_capability_trace_telemetry(
            report_event=make_reporter(events),
            source_bot="alexis",
            request_id="req_disabled",
            agent_name="alexis",
            shared_capability="draft_email",
            semantic_operation="ACTION",
            expected_output_type="artifact",
        )

    assert trace is None
    assert events == []


def test_telemetry_enabled_success():
    events: list[dict] = []

    with EnvFlag("1"):
        trace = emit_planned_capability_trace_telemetry(
            report_event=make_reporter(events),
            source_bot="alexis",
            request_id="req_success",
            agent_name="alexis",
            shared_capability="draft_email",
            user_id="user_1",
            semantic_operation="ACTION",
            expected_output_type="artifact",
        )

    assert trace is not None
    assert trace.resolution_status == "OK"
    assert len(events) == 1

    event = events[0]
    assert event["event_type"] == "planned_capability_trace"
    assert event["request_id"] == "req_success"

    payload = event["payload"]
    assert payload["request_id"] == "req_success"
    assert payload["user_id"] == "user_1"
    assert payload["agent"] == "alexis"
    assert payload["shared_capability"] == "draft_email"
    assert payload["semantic_operation"] == "ACTION"
    assert payload["expected_output_type"] == "artifact"
    assert payload["resolution_status"] == "OK"
    assert payload["error"] is None
    assert payload["binding"]["binding_id"] == "draft_email"
    assert payload["binding"]["skills"] == ["structured_actions"]
    assert payload["binding"]["resources"] == ["guest_db"]
    assert payload["binding"]["tone"] == "newsroom"
    assert payload["binding"]["approval_policy"] is None
    assert isinstance(payload["binding"]["manifest_path"], str)


def test_missing_binding_trace_emission():
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
                    "resources": [],
                },
            },
            skill_names=["structured_actions"],
        )

        with EnvFlag("1"):
            trace = emit_planned_capability_trace_telemetry(
                report_event=make_reporter(events),
                source_bot="tester",
                request_id="req_missing_binding",
                agent_name="tester",
                shared_capability="send_email",
                root=root,
            )

    assert trace is not None
    assert trace.resolution_status == "ERROR"
    assert len(events) == 1

    payload = events[0]["payload"]
    assert payload["resolution_status"] == "ERROR"
    assert payload["binding"] is None
    assert payload["error"]["error_code"] == "missing_binding"
    assert payload["shared_capability"] == "send_email"


def test_payload_serialization_safety():
    trace = trace_planned_capability(
        request_id="req_json",
        agent_name="alexis",
        shared_capability="draft_email",
    )

    payload = binding_trace_to_payload(trace)
    encoded = json.dumps(payload)

    assert "draft_email" in encoded
    assert payload["binding"]["manifest_path"].endswith(
        "agents/alexis/bindings/capabilities.json"
    )


def main():
    test_telemetry_disabled()
    test_telemetry_enabled_success()
    test_missing_binding_trace_emission()
    test_payload_serialization_safety()
    print("PASS binding trace telemetry")


if __name__ == "__main__":
    main()
