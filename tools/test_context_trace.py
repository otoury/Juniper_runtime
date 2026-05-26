import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runtime.context_trace as context_trace  # noqa: E402
from runtime.context_trace import (  # noqa: E402
    planned_context_trace_dict,
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
        resource_path.write_text("# planned context test resource\n")

    write_json(
        agent_dir / "capabilities" / "bindings.json",
        {
            "bindings": bindings,
        },
    )


def test_alexis_draft_email_planned_guest_context():
    trace = trace_planned_context(
        request_id="req_draft_context",
        agent_name="alexis",
        shared_capability="draft_email",
    )

    assert trace.resolution_status == "OK"
    assert trace.context_policy["include_guest_context"] is True
    assert trace.bounded_item_count == 2

    source_names = {item.source_name for item in trace.planned_items}
    assert "alexis.guest_db" in source_names
    assert "user_preferences" in source_names

    for item in trace.planned_items:
        assert item.bounded is True
        assert item.attributable is True
        assert item.planned_only is True


def test_producer_note_planned_artifact_context():
    trace = trace_planned_context(
        request_id="req_producer_context",
        agent_name="alexis",
        shared_capability="producer_note",
    )

    assert trace.resolution_status == "OK"
    assert trace.bounded_item_count == 1
    assert trace.planned_items[0].source_type == "recent_artifacts"
    assert trace.planned_items[0].source_name == "producer_note"


def test_missing_binding():
    trace = trace_planned_context(
        request_id="req_missing_binding",
        agent_name="alexis",
        shared_capability="missing_capability",
    )

    assert trace.resolution_status == "ERROR"
    assert trace.planned_items == []
    assert trace.errors[0].error_code == "missing_shared_capability"


def test_invalid_context_policy():
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

        trace = trace_planned_context(
            request_id="req_invalid_policy",
            agent_name="tester",
            shared_capability="draft_email",
            root=root,
        )

    assert trace.resolution_status == "ERROR"
    assert trace.errors[0].error_code == "invalid_context_policy"
    assert trace.planned_items == []


def test_max_context_items_enforcement():
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
                    "context_policy": {
                        "include_guest_context": True,
                        "include_recent_artifacts": True,
                        "include_user_preferences": True,
                        "resource_scopes": ["booking"],
                        "max_context_items": 1,
                    },
                },
            },
            skill_names=["structured_actions"],
            resources=["guest_db"],
        )

        trace = trace_planned_context(
            request_id="req_max_items",
            agent_name="tester",
            shared_capability="draft_email",
            root=root,
        )

    assert trace.resolution_status == "WARNING"
    assert trace.bounded_item_count == 1
    assert len(trace.planned_items) == 1
    assert any(
        error.error_code == "max_context_items_enforced"
        for error in trace.errors
    )


def test_no_retrieval_execution_occurs():
    original_candidate_items = context_trace._candidate_items
    called = {"count": 0}

    def counting_candidate_items(**kwargs):
        called["count"] += 1
        return original_candidate_items(**kwargs)

    context_trace._candidate_items = counting_candidate_items

    try:
        trace = trace_planned_context(
            request_id="req_no_retrieval",
            agent_name="alexis",
            shared_capability="draft_email",
        )
    finally:
        context_trace._candidate_items = original_candidate_items

    assert called["count"] == 1
    assert trace.retrieval_policy["retrieval_execution"] is False
    assert trace.retrieval_policy["message_injection"] is False

    payload = planned_context_trace_dict(trace)
    json.dumps(payload)
    assert all(
        item["planned_only"] is True
        for item in payload["planned_items"]
    )


def main():
    test_alexis_draft_email_planned_guest_context()
    test_producer_note_planned_artifact_context()
    test_missing_binding()
    test_invalid_context_policy()
    test_max_context_items_enforcement()
    test_no_retrieval_execution_occurs()
    print("PASS context trace")


if __name__ == "__main__":
    main()
