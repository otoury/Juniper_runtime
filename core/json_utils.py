import json
import re


def extract_json(text: str) -> dict:
    """
    Extract first JSON object from model output.
    """

    match = re.search(r"\{.*\}", text, re.DOTALL)

    if not match:
        raise ValueError(
            f"No JSON object found in response:\n{text}"
        )

    return json.loads(match.group())