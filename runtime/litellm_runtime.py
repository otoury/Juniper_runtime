import os

from runtime.governance.operational_controls import evaluate_cloud_execution_control
from runtime.execution_classes import (
    EXECUTION_CLASS_PAID_CLOUD_MODEL,
    evaluate_execution_class_dry_run,
)
from runtime.execution_containment import (
    build_blocked_execution_diagnostics,
    render_blocked_execution_response,
)

try:
    from litellm import completion
except ModuleNotFoundError:
    completion = None


def cloud_dry_run_enabled() -> bool:
    decision = evaluate_cloud_execution_control()
    return not decision.allowed


def cloud_execution_decision():
    return evaluate_cloud_execution_control()


def _engine_to_litellm_model(engine: dict) -> str:
    provider = engine.get("provider")

    if provider == "openai":
        return engine["model"]

    if provider == "ollama":
        model = (
            engine.get("model")
            or os.getenv(
                engine.get("model_env", "OLLAMA_AGENT_MODEL"),
                engine.get("default_model", "qwen3:8b"),
            )
        )

        return f"ollama_chat/{model}"

    raise ValueError(f"Unsupported provider for LiteLLM: {provider}")


def execute_litellm(
    messages,
    engine: dict,
    response_format=None,
):
    provider = engine.get("provider")
    model = _engine_to_litellm_model(engine)

    cloud_decision = (
        cloud_execution_decision()
        if provider == "openai"
        else None
    )

    if provider == "openai" and cloud_decision and not cloud_decision.allowed:
        dry_run_decision = evaluate_execution_class_dry_run(
            EXECUTION_CLASS_PAID_CLOUD_MODEL,
            dry_run=True,
        )
        return {
            "text": render_blocked_execution_response(),
            "model": model,
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            },
            "dry_run": True,
            "provider_blocked": True,
            "operational_diagnostics": build_blocked_execution_diagnostics(
                messages=messages,
                engine=engine,
                model=model,
                response_format=response_format,
                control_diagnostics=cloud_decision.to_diagnostics(),
                execution_class=dry_run_decision.execution_class,
                dry_run_effect=dry_run_decision.dry_run_effect,
                blocked_reason=dry_run_decision.reason,
            ),
        }

    if completion is None:
        raise RuntimeError(
            "litellm is required for live model execution"
        )

    response = completion(
        model=model,
        messages=messages,
        api_base=(
            os.getenv("OLLAMA_URL", "http://thebrain.local:11434")
            if provider == "ollama"
            else None
        ),
        timeout=180,
        drop_params=True,
        response_format=response_format,
    )

    usage = getattr(response, "usage", None)

    return {
        "text": response.choices[0].message.content,
        "model": model,
        "usage": {
            "input_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
            "output_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
            "total_tokens": getattr(usage, "total_tokens", 0) if usage else 0,
        },
        "dry_run": False,
    }
