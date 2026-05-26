# contracts/base_validator.py

from pathlib import Path

from runtime.contracts.semantic_validation import looks_like_meta_response
from runtime.contracts.result import ContractValidationResult
from runtime.loaders.contract_loader import get_contract_config
from runtime.contracts.schema_validator import validate_object_schema
from runtime.loaders.contract_loader import load_contract_schema

class ContractValidator:
    def __init__(self, agent_root: str | Path):
        self.agent_root = Path(agent_root)

    def validate(
        self,
        *,
        semantic_output_type: str | None,
        response: str,
        actions: list,
        parsed_payload=None,
    ) -> ContractValidationResult:
        config = get_contract_config(
            agent_root=self.agent_root,
            name=semantic_output_type,
        )

        rules = config.get("rules", {})
        text = (response or "").strip()

        schema = load_contract_schema(
            agent_root=self.agent_root,
            name=semantic_output_type,
        )

        if schema:
            schema_result = validate_object_schema(
                payload=parsed_payload,
                schema=schema,
            )

            if not schema_result.ok:
                return ContractValidationResult(
                    ok=False,
                    error="Schema contract failure",
                    violations=schema_result.errors,
                )

        if rules.get("non_empty") and not text:
            return ContractValidationResult(
                ok=False,
                error="Contract failure: output is empty.",
            )

        if rules.get("no_actions") and actions:
            return ContractValidationResult(
                ok=False,
                error="Contract failure: actions are not allowed.",
            )

        if rules.get("single_line") and "\n" in text:
            return ContractValidationResult(
                ok=False,
                error="Contract failure: output must be a single line.",
            )

        max_words = rules.get("max_words")

        if max_words and len(text.split()) > int(max_words):
            return ContractValidationResult(
                ok=False,
                error=(
                    "Contract failure: output exceeds "
                    f"{max_words} words."
                ),
            )

        if rules.get("must_not_end_with_period") and text.endswith("."):
            return ContractValidationResult(
                ok=False,
                error="Contract failure: output must not end with a period.",
            )

        if rules.get("forbid_meta_response"):
            if looks_like_meta_response(text):
                return ContractValidationResult(
                    ok=False,
                    error=(
                        "Contract failure: meta-response "
                        "instead of deliverable."
                    ),
                )

        return ContractValidationResult(ok=True)
