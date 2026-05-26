from __future__ import annotations

from runtime.policies.model_registry import ENGINES
from runtime.litellm_runtime import execute_litellm


def run_local(
    messages,
    model=None,
):
    engine = {
        "provider": "ollama",
        "model": model,
    }

    result = execute_litellm(
        messages=messages,
        engine=engine,
    )

    return result["text"]


def run_cloud(
    messages,
    model,
    web_search=False,
):
    engine = {
        "provider": "openai",
        "model": model,
        "web_search": web_search,
    }

    result = execute_litellm(
        messages=messages,
        engine=engine,
    )

    return result["text"]
