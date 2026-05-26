# agents/alexis/contract_validator.py

from pathlib import Path

from runtime.contracts.base_validator import ContractValidator


AGENT_ROOT = Path(__file__).resolve().parent

alexis_contract_validator = ContractValidator(
    agent_root=AGENT_ROOT,
)
