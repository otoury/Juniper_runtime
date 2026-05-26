from runtime.policies.model_registry import ENGINES
from runtime.litellm_runtime import execute_litellm
from runtime.execution_containment import contain_execution_result


JSON_ONLY_INSTRUCTION = "Respond in valid JSON only."


def is_cloud_engine(engine: dict) -> bool:
    return engine.get("provider") == "openai"


def ensure_json_response_instruction(
    messages: list[dict],
    response_format=None,
) -> list[dict]:
    if not _is_json_object_response_format(response_format):
        return messages

    if _messages_contain_json_instruction(messages):
        return messages

    normalized = [
        dict(message)
        for message in messages
    ]

    if normalized and normalized[0].get("role") == "system":
        normalized[0]["content"] = (
            str(normalized[0].get("content") or "").rstrip()
            + "\n\n"
            + JSON_ONLY_INSTRUCTION
        ).strip()
        return normalized

    return [
        {
            "role": "system",
            "content": JSON_ONLY_INSTRUCTION,
        },
        *normalized,
    ]


def _is_json_object_response_format(response_format) -> bool:
    return (
        isinstance(response_format, dict)
        and response_format.get("type") == "json_object"
    )


def _messages_contain_json_instruction(messages: list[dict]) -> bool:
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str) and "json" in content.lower():
            return True
    return False


def execute_with_fallbacks(
    messages,
    execution_target: str,
    fallback_engines: list[str] | None = None,
    report_callback=None,
    response_format=None,
):
    attempted = []
    engine_names = [execution_target] + list(fallback_engines or [])
    execution_messages = ensure_json_response_instruction(
        messages,
        response_format=response_format,
    )

    last_error = None
    presence_started = False

    for engine_name in engine_names:
        engine = ENGINES.get(engine_name)

        if not engine:
            attempted.append({
                "engine": engine_name,
                "ok": False,
                "error": "engine not found",
            })
            continue

        execution_tier = "cloud" if is_cloud_engine(engine) else "local"

        if report_callback:
            if not presence_started:
                report_callback("execution_presence_started", {
                    "phase": _presence_phase_for_engine(engine),
                    "engine": engine_name,
                    "execution_tier": execution_tier,
                })
                presence_started = True

            report_callback("execution_presence_progress", {
                "phase": _presence_phase_for_engine(engine),
                "engine": engine_name,
                "model": engine.get("model") or engine.get("default_model"),
                "execution_tier": execution_tier,
                "web_search": engine.get("web_search", False),
            })

            report_callback("execution_attempt_started", {
                "engine": engine_name,
                "model": engine.get("model") or engine.get("default_model"),
                "execution_tier": execution_tier,
                "web_search": engine.get("web_search", False),
            })

        try:
            result = execute_litellm(
                messages=execution_messages,
                engine=engine,
                response_format=response_format,
            )
            result = contain_execution_result(result)
            attempted.append({
                "engine": engine_name,
                "model": result["model"],
                "execution_tier": execution_tier,
                "ok": True,
            })

            if report_callback and presence_started:
                report_callback("execution_presence_stopped", {
                    "status": "completed",
                    "engine": engine_name,
                    "model": result["model"],
                    "execution_tier": execution_tier,
                })

            return {
                "response": result["text"],
                "engine": engine_name,
                "model": result["model"],
                "execution_tier": execution_tier,
                "attempted": attempted,
                "usage": result.get("usage", {}),
                "dry_run": result.get("dry_run", False),
                "provider_blocked": result.get("provider_blocked", False),
                "operational_diagnostics": result.get(
                    "operational_diagnostics",
                ),
            }

        except Exception as e:
            last_error = e

            attempted.append({
                "engine": engine_name,
                "model": engine.get("model") or engine.get("default_model"),
                "execution_tier": execution_tier,
                "ok": False,
                "error": repr(e),
            })

            if report_callback:
                report_callback("execution_attempt_failed", {
                    "engine": engine_name,
                    "model": engine.get("model") or engine.get("default_model"),
                    "execution_tier": execution_tier,
                    "error": repr(e),
                })

    error = (
        "All execution engines failed: "
        + repr(last_error)
        + " | attempts="
        + repr(attempted)
    )

    if report_callback and presence_started:
        report_callback("execution_presence_stopped", {
            "status": "failed",
            "error": error,
            "attempted": attempted,
        })

    raise RuntimeError(error)


def _presence_phase_for_engine(engine: dict) -> str:
    if engine.get("web_search"):
        return "web_search"
    if is_cloud_engine(engine) or engine.get("role") == "heavy_local_reasoning":
        return "deep_reasoning"
    return "thinking"


__all__ = [
    "JSON_ONLY_INSTRUCTION",
    "ensure_json_response_instruction",
    "execute_with_fallbacks",
    "is_cloud_engine",
]
