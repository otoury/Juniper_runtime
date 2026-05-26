import sys
import json
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.binding_trace import (  # noqa: E402
    planned_capability_trace_dict,
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


def test_alexis_draft_email_trace():
    trace = trace_planned_capability(
        request_id="req_draft",
        agent_name="alexis",
        shared_capability="draft_email",
        semantic_operation="ACTION",
        expected_output_type="artifact",
    )

    assert trace.resolution_status == "OK"
    assert trace.request_id == "req_draft"
    assert trace.agent_name == "alexis"
    assert trace.shared_capability == "draft_email"
    assert trace.semantic_operation == "ACTION"
    assert trace.expected_output_type == "artifact"
    assert trace.resolved_binding is not None
    assert trace.resolved_binding.binding_id == "draft_email"
    assert trace.skills == ["structured_actions"]
    assert trace.resources == ["guest_db"]
    assert trace.tone == "newsroom"
    assert trace.approval_policy is None


def test_alexis_create_lower_third_trace():
    trace = trace_planned_capability(
        request_id="req_lower",
        agent_name="alexis",
        shared_capability="create_lower_third",
        semantic_operation="NEW_REQUEST",
        expected_output_type="artifact",
    )

    assert trace.resolution_status == "OK"
    assert trace.resolved_binding is not None
    assert trace.resolved_binding.binding_id == "create_lower_third"
    assert trace.skills == ["lower_third"]
    assert trace.resources == []
    assert trace.tone == "broadcast"


def test_missing_capability_trace():
    trace = trace_planned_capability(
        request_id="req_missing_capability",
        agent_name="alexis",
        shared_capability="missing_capability",
    )

    assert trace.resolution_status == "ERROR"
    assert trace.resolved_binding is None
    assert trace.resolution_error is not None
    assert trace.resolution_error.error_code == "missing_shared_capability"
    assert trace.skills == []
    assert trace.resources == []


def test_missing_agent_trace():
    trace = trace_planned_capability(
        request_id="req_missing_agent",
        agent_name="missing_agent",
        shared_capability="draft_email",
    )

    assert trace.resolution_status == "ERROR"
    assert trace.resolution_error is not None
    assert trace.resolution_error.error_code == "missing_agent"


def test_missing_binding_trace():
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

        trace = trace_planned_capability(
            request_id="req_missing_binding",
            agent_name="tester",
            shared_capability="send_email",
            root=root,
        )

    assert trace.resolution_status == "ERROR"
    assert trace.resolution_error is not None
    assert trace.resolution_error.error_code == "missing_binding"


def test_trace_dict_serializes_paths():
    trace = trace_planned_capability(
        request_id="req_dict",
        agent_name="alexis",
        shared_capability="draft_email",
    )
    payload = planned_capability_trace_dict(trace)

    assert payload["resolution_status"] == "OK"
    assert isinstance(
        payload["resolved_binding"]["raw_manifest_path"],
        str,
    )


def main():
    test_alexis_draft_email_trace()
    test_alexis_create_lower_third_trace()
    test_missing_capability_trace()
    test_missing_agent_trace()
    test_missing_binding_trace()
    test_trace_dict_serializes_paths()
    print("PASS planned capability trace")


if __name__ == "__main__":
    main()
