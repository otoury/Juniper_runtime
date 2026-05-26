# tools/test_contract_repair.py

import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from runtime.contracts.exceptions import ContractValidationError
from runtime.repair_manager import (
    build_contract_repair_messages,
)


class DummyPlan:
    semantic_output_type = "lower_third"
    execution_target = "test"


class DummyAgent:
    agent_root = Path("agents/alexis")


messages = [
    {
        "role": "system",
        "content": "You are Alexis.",
    },
    {
        "role": "user",
        "content": "Create lower third",
    },
]

violations = [
    "Missing required field: artifact_type",
    "Unexpected field: text",
]

result = build_contract_repair_messages(
    original_messages=messages,
    raw_response='{"text":"AI Regulation"}',
    violations=violations,
    agent=DummyAgent(),
    plan=DummyPlan(),
)

print("\n=== REPAIR MESSAGE ===\n")
print(result[-1]["content"])
