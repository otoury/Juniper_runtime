import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.trace_agent_bindings import trace_agent_bindings  # noqa: E402


def only_trace(payload: dict) -> dict:
    assert len(payload["traces"]) == 1, payload
    return payload["traces"][0]


def test_full_alexis_trace():
    payload = trace_agent_bindings("alexis")
    traces = payload["traces"]

    assert payload["agent"] == "alexis"
    assert payload["mode"] == "all_bindings"
    assert len(traces) == 4
    assert {trace["shared_capability"] for trace in traces} == {
        "create_lower_third",
        "draft_email",
        "producer_note",
        "send_email",
    }
    assert all(
        trace["validation_status"] == "OK"
        for trace in traces
    )


def test_single_capability_trace():
    payload = trace_agent_bindings("alexis", "draft_email")
    trace = only_trace(payload)

    assert payload["mode"] == "single_capability"
    assert trace["validation_status"] == "OK"
    assert trace["shared_capability"] == "draft_email"
    assert trace["binding_id"] == "draft_email"
    assert trace["skills"] == ["structured_actions"]
    assert trace["resources"] == ["guest_db"]
    assert trace["tone"] == "newsroom"


def test_missing_capability_trace():
    payload = trace_agent_bindings("alexis", "missing_capability")
    trace = only_trace(payload)

    assert trace["validation_status"] == "ERROR"
    assert trace["error_code"] == "missing_shared_capability"
    assert trace["shared_capability"] == "missing_capability"


def test_missing_agent_trace():
    payload = trace_agent_bindings("missing_agent")
    trace = only_trace(payload)

    assert payload["agent"] == "missing_agent"
    assert trace["validation_status"] == "ERROR"
    assert trace["error_code"] == "missing_agent"


def main():
    test_full_alexis_trace()
    test_single_capability_trace()
    test_missing_capability_trace()
    test_missing_agent_trace()
    print("PASS binding trace")


if __name__ == "__main__":
    main()
