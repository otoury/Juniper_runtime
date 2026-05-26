import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.alexis import AlexisAgent

from tools.trace_report import print_report
from runtime.telemetry_manager import get_session_id
from runtime.request_runner import run_request

LOG_PATH = Path("logs/juniper_events.jsonl")
DEFAULT_TEST_FILE = Path("tests/alexis_pipeline_tests.txt")
USER_ID = "test_pipeline_user"
KNOWN_ENVIRONMENT_FAILURE_MARKERS = (
    "litellm is required for live model execution",
    "httpx is required for live request gate calls",
    "httpx is required for live execution planner calls",
)


def parse_value(raw: str):
    value = raw.strip()

    if value.lower() == "true":
        return True

    if value.lower() == "false":
        return False

    if value.lower() == "null":
        return None

    return value


def parse_tests(path: Path):
    text = path.read_text(encoding="utf-8")
    blocks = []
    current = []

    for line in text.splitlines():
        if line.startswith(">"):
            if current:
                blocks.append("\n".join(current).strip())
                current = []

        current.append(line)

    if current:
        blocks.append("\n".join(current).strip())

    tests = []

    for block in blocks:
        lines = block.splitlines()

        if not lines or not lines[0].startswith(">"):
            continue

        name = lines[0][1:].strip()
        expects = {}
        body_lines = []
        in_body = False

        for line in lines[1:]:
            if line.strip() == "---":
                in_body = True
                continue

            if not in_body and line.startswith("EXPECT "):
                raw = line[len("EXPECT "):].strip()

                if "=" not in raw:
                    continue

                key, value = raw.split("=", 1)
                expects[key.strip()] = parse_value(value)
                continue

            if in_body:
                body_lines.append(line)

        body = "\n".join(body_lines).strip()

        if not name or not body:
            continue

        tests.append({
            "name": name,
            "text": body,
            "expect": expects,
        })

    return tests


def load_events(session_id):
    if not LOG_PATH.exists():
        return []

    events = []

    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except Exception:
            continue

        if event.get("session_id") == session_id:
            events.append(event)

    return events


def events_for_request(events, request_id):
    return [
        e for e in events
        if e.get("request_id") == request_id
    ]


def latest_request_id(events):
    for event in reversed(events):
        request_id = event.get("request_id")

        if request_id:
            return request_id

    return None


def get_event(events, event_type):
    for event in events:
        if event.get("event_type") == event_type:
            return event

    return None


def get_value(req_events, key):
    fast_event = get_event(req_events, "fast_path_selected")
    context_event = get_event(req_events, "context_resolved")
    gate_event = get_event(req_events, "request_gate_decision")
    action_event = get_event(req_events, "agent_action_queued")
    execution_event = (
        get_event(req_events, "execution_attempt_started")
        or get_event(req_events, "execution_started")
    )
    error_event = get_event(req_events, "error")

    if key == "fast_path":
        return fast_event is not None

    if key == "is_followup":
        if context_event:
            return context_event.get("payload", {}).get("is_followup")
        return None

    if key == "requires_artifact_context":
        if gate_event:
            return gate_event.get("payload", {}).get(
                "requires_artifact_context"
            )
        return None

    if key == "uses_active_artifact":
        if gate_event:
            return gate_event.get("payload", {}).get(
                "uses_active_artifact"
            )
        return None

    if key == "interaction_mode":
        if gate_event:
            return gate_event.get("payload", {}).get("interaction_mode")
        return None

    if key == "transform_type":
        if context_event:
            return context_event.get("payload", {}).get("transform_type")
        return None

    if key == "semantic_output_type":
        plan_event = get_event(req_events, "execution_plan_created")
        if plan_event:
            return plan_event.get("payload", {}).get(
                "semantic_output_type"
            )
        return None

    if key == "expected_output_type":
        plan_event = get_event(req_events, "execution_plan_created")
        if plan_event:
            return plan_event.get("payload", {}).get(
                "expected_output_type"
            )
        return None

    if key == "artifact_quality_validation_attempted":
        return get_event(req_events, "artifact_quality_failure") is not None

    if key == "action_type":
        if action_event:
            return action_event.get("payload", {}).get("action_type")
        return None

    if key == "queued_action_type":
        if action_event:
            return action_event.get("payload", {}).get("action_type")
        return None

    if key == "queued_requires_approval":
        if action_event:
            return action_event.get("payload", {}).get(
                "requires_approval"
            )
        return None

    if key == "execution_tier":
        if execution_event:
            return execution_event.get("payload", {}).get("execution_tier")
        return None

    if key == "engine":
        if execution_event:
            return execution_event.get("payload", {}).get("engine")
        return None

    if key == "web_search":
        if execution_event:
            return execution_event.get("payload", {}).get("web_search")
        return None

    if key == "error":
        return error_event is not None

    return None


def _first_marker(text: str | None) -> str | None:
    normalized = str(text or "").lower()
    for marker in KNOWN_ENVIRONMENT_FAILURE_MARKERS:
        if marker in normalized:
            return marker
    return None


def classify_environment_unavailable(req_events):
    error_event = get_event(req_events, "error")
    gate_event = get_event(req_events, "request_gate_decision")
    context_event = get_event(req_events, "context_resolved")
    plan_event = get_event(req_events, "execution_plan_created")

    # If we failed before request-gate/context/plan events exist,
    # classify as infrastructure unavailable, not semantic drift.
    if (
        error_event is not None
        and gate_event is None
        and context_event is None
        and plan_event is None
    ):
        raw_error = error_event.get("payload", {}).get("error")
        return (
            "pre-gate infrastructure failure before semantic pipeline: "
            f"{raw_error!r}"
        )

    if error_event:
        marker = _first_marker(
            error_event.get("payload", {}).get("error")
        )
        if marker:
            return (
                "runtime dependency unavailable from error payload: "
                f"{marker}"
            )

    if gate_event:
        marker = _first_marker(
            gate_event.get("payload", {}).get("reason")
        )
        if marker:
            return (
                "request gate dependency unavailable from gate reason: "
                f"{marker}"
            )

    if context_event:
        marker = _first_marker(
            context_event.get("payload", {}).get("reason")
        )
        if marker:
            return (
                "planner dependency unavailable from context reason: "
                f"{marker}"
            )

    return None


def check_test(name, req_events, expect, elapsed):
    env_issue = classify_environment_unavailable(req_events)
    if env_issue is not None:
        print(f"⚠️ ENV_UNAVAILABLE: {name} — {elapsed:.2f}s")
        print(f"  - {env_issue}")
        return "environment_unavailable"

    problems = []

    for key, expected in expect.items():
        got = get_value(req_events, key)

        if got != expected:
            problems.append(f"{key} expected {expected!r} got {got!r}")

    if problems:
        print(f"❌ FAIL: {name} — {elapsed:.2f}s")
        for problem in problems:
            print(f"  - {problem}")
        return "semantic_failure"

    print(f"✅ PASS: {name} — {elapsed:.2f}s")
    return "pass"


def main():
    args = [
        arg for arg in sys.argv[1:]
        if arg != "--trace"
    ]

    show_trace = "--trace" in sys.argv[1:]

    path = Path(args[0]) if args else DEFAULT_TEST_FILE

    if not path.exists():
        raise FileNotFoundError(f"Missing test file: {path}")

    tests = parse_tests(path)

    if not tests:
        raise RuntimeError(f"No tests found in {path}")

    agent = AlexisAgent()
    session_id = get_session_id()

    passed = 0
    semantic_failed = 0
    environment_unavailable = 0
    suite_start = time.perf_counter()
    timings = []

    print(f"Running {len(tests)} tests from: {path}")
    print(f"Session: {session_id}")

    for test in tests:
        print("\n" + "=" * 60)
        print(f"TEST: {test['name']}")
        print("INPUT:")
        print(test["text"])

        before = load_events(session_id)
        before_ids = {e.get("request_id") for e in before}

        test_start = time.perf_counter()

        response = run_request(
            source_bot="alexis",
            agent=agent,
            user_id=USER_ID,
            text=test["text"],
        )

        elapsed = time.perf_counter() - test_start
        timings.append((test["name"], elapsed))

        print("\nRESPONSE:")
        print(response[:800])
        print(f"\n⏱ Test runtime: {elapsed:.2f}s")

        time.sleep(0.2)

        after = load_events(session_id)
        new_events = [
            e for e in after
            if e.get("request_id") not in before_ids
            and e.get("request_id") is not None
        ]

        request_id = latest_request_id(new_events)

        if not request_id:
            print(f"❌ FAIL: {test['name']} — {elapsed:.2f}s")
            print("  - no request_id found")
            semantic_failed += 1
            continue

        req_events = events_for_request(after, request_id)

        outcome = check_test(
            test["name"],
            req_events,
            test["expect"],
            elapsed,
        )
        if outcome == "pass":
            passed += 1
        elif outcome == "environment_unavailable":
            environment_unavailable += 1
        else:
            semantic_failed += 1
        if show_trace:
            print_report(
                events=after,
                request_id=request_id,
            )
    suite_elapsed = time.perf_counter() - suite_start

    print("\n" + "=" * 60)
    print("TIMINGS:")

    for name, elapsed in timings:
        print(f"- {name}: {elapsed:.2f}s")

    print("\n" + "=" * 60)
    print(
        "RESULT: "
        f"pass={passed} "
        f"semantic_fail={semantic_failed} "
        f"environment_unavailable={environment_unavailable}"
    )
    print(f"⏱ Total test time: {suite_elapsed:.2f}s")

    if semantic_failed:
        raise SystemExit(1)

    if environment_unavailable:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
