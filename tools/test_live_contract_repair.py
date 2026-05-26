# tools/test_live_contract_repair.py

import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from runtime.contracts.exceptions import ContractValidationError
from runtime.validation_manager import (
    validate_runtime_response,
)
from runtime.repair_manager import (
    repair_contract_response,
)

from agents.alexis import AlexisAgent


class DummyPlan:
    semantic_output_type = "lower_third"
    expected_output_type = "artifact"
    execution_target = "local_agent"
    fallback_engines = []


def runtime_report(event_type, payload):
    print(f"\n[{event_type}]")
    print(payload)


agent = AlexisAgent()

plan = DummyPlan()

messages = [
    {
        "role": "system",
        "content": "You are Alexis.",
    },
    {
        "role": "user",
        "content": "Create lower third about AI regulation",
    },
]

raw_response = '{"text":"AI Regulation Needs Oversight"}'

normalized_response = (
    "AI Regulation Needs Oversight"
)

parsed_payload = {
    "text": "AI Regulation Needs Oversight"
}

print("\n=== INITIAL VALIDATION ===")

try:
    validate_runtime_response(
        agent=agent,
        plan=plan,
        normalized_response=normalized_response,
        parsed_payload=parsed_payload,
        is_dry_run=False,
        source_bot="alexis",
        user_id="test",
        request_id="repair_test",
        report_event=lambda *args, **kwargs: None,
    )

    print("ERROR: validation unexpectedly passed")

except ContractValidationError as exc:

    print("\nVALIDATION FAILED AS EXPECTED")
    print(exc.violations)

    repaired = repair_contract_response(
        messages=messages,
        raw_response=raw_response,
        violations=exc.violations,
        agent=agent,
        plan=plan,
        response_format={"type": "json_object"},
        runtime_report=runtime_report,
        execution_target=plan.execution_target,
    )

    print("\n=== REPAIRED RESPONSE ===\n")

    print(repaired["raw_response"])

    print("\n=== REVALIDATION ===\n")

    final_validation = validate_runtime_response(
        agent=agent,
        plan=plan,
        normalized_response=repaired[
            "normalized_response"
        ],
        parsed_payload=repaired[
            "pipeline_result"
        ].parsed_payload,
        is_dry_run=False,
        source_bot="alexis",
        user_id="test",
        request_id="repair_test",
        report_event=lambda *args, **kwargs: None,
    )

    print("FINAL VALIDATION:", final_validation.response)
