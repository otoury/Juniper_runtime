# tools/test_contract_validation.py

import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from runtime.contracts.base_validator import ContractValidator


validator = ContractValidator(
    agent_root=Path("agents/alexis")
)

cases = [
    (
        "missing_artifact_type",
        {"content": "AI Regulation Needs Oversight"},
        False,
    ),
    (
        "wrong_field",
        {"text": "AI Regulation Needs Oversight"},
        False,
    ),
    (
        "extra_field",
        {
            "artifact_type": "lower_third",
            "content": "AI Regulation Needs Oversight",
            "font_size": 36,
        },
        False,
    ),
    (
        "valid",
        {
            "artifact_type": "lower_third",
            "content": "AI Regulation Needs Oversight",
        },
        True,
    ),
]

for name, payload, expected_ok in cases:
    result = validator.validate(
        semantic_output_type="lower_third",
        response=payload.get("content", ""),
        actions=[],
        parsed_payload=payload,
    )

    status = "PASS" if result.ok == expected_ok else "FAIL"

    print(f"{status} | {name}")
    print(f"  ok={result.ok}")
    print(f"  error={result.error}")
    print(f"  violations={result.violations}")

