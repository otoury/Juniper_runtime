from runtime.policies.model_registry import ENGINES

ARTIFACT_OUTPUT_TYPES = {
    "artifact",
    "translation",
    "summary",
}


def _is_available(engine: dict) -> bool:
    return engine.get("available", True)


def _is_cloud(engine: dict) -> bool:
    return engine.get("provider") == "openai"


def _is_local(engine: dict) -> bool:
    return not _is_cloud(engine)


def _needs_cloud(requirements) -> bool:
    return (
        requirements.requires_current_information
        or requirements.requires_web
        or requirements.requires_source_fidelity
        or requirements.reasoning_depth == "deep"
    )


def _is_artifact_work(requirements) -> bool:
    return requirements.expected_output_type == "artifact"


def select_engine(requirements) -> tuple[str, list[str]]:
    candidates = []

    for engine_name, engine in ENGINES.items():
        if not _is_available(engine):
            continue

        score = 0

        is_cloud = _is_cloud(engine)
        is_local = _is_local(engine)

        is_artifact_task = (
            requirements.expected_output_type in ARTIFACT_OUTPUT_TYPES
            or bool(getattr(requirements, "semantic_output_type", None))
        )

        if is_artifact_task and not requirements.requires_web:
            preferred = "local_agent"

            fallbacks = [
                "local_router_primary",
                "cloud_fast",
                "cloud_deep",
            ]

            return preferred, [
                engine
                for engine in fallbacks
                if engine in ENGINES
                and engine != preferred
                and ENGINES[engine].get("available", True)
            ]        

        # Default bias: local first.
        if is_local:
            score += 20

        if is_cloud:
            score -= 10

        # Cloud only wins when the task truly needs cloud.
        if _needs_cloud(requirements):
            if is_cloud:
                score += 35
            else:
                score -= 10

        # Web/current info requires web engines.
        if requirements.requires_current_information or requirements.requires_web:
            if engine.get("web_search"):
                score += 50
            else:
                score -= 80

        # Source fidelity / translation can justify cloud.
        if requirements.requires_source_fidelity:
            score += engine.get("translation_quality", 0) * 8
            if engine.get("translation_quality", 0) < 4:
                score -= 40

        # Artifact work should NOT automatically become cloud work.
        if _is_artifact_work(requirements):
            if engine_name == "local_agent":
                score += 18

            if engine_name == "local_reasoner_fallback":
                score += 22

            if is_cloud and requirements.reasoning_depth != "deep":
                score -= 15

        # Style sensitivity: prefer capable engines, but don't force cloud.
        style_map = {
            "low": 1,
            "medium": 3,
            "high": 5,
        }

        required_style = style_map.get(
            requirements.style_sensitivity,
            1,
        )

        creative_quality = engine.get(
            "creative_writing_quality",
            1,
        )

        score += creative_quality * 4

        if creative_quality < required_style:
            score -= 6 * (required_style - creative_quality)

        # Reasoning.
        depth_map = {
            "low": 1,
            "medium": 3,
            "deep": 5,
        }

        required_depth = depth_map.get(
            requirements.reasoning_depth,
            1,
        )

        reasoning_quality = engine.get(
            "reasoning_quality",
            1,
        )

        score += reasoning_quality * 3

        if reasoning_quality < required_depth:
            score -= 8 * (required_depth - reasoning_quality)

        # qwen3:8b should be a real local option for artifact/rewrite work,
        # not only a last-resort crash fallback.
        if engine_name == "local_reasoner_fallback":
            if (
                requirements.reasoning_depth in ["medium", "deep"]
                or requirements.style_sensitivity == "high"
                or _is_artifact_work(requirements)
            ):
                score += 14
            else:
                score -= 10

        # Avoid deep cloud unless truly needed.
        if engine_name in ["cloud_deep", "cloud_web_deep"]:
            if requirements.reasoning_depth != "deep":
                score -= 35

        # Prefer fast cloud over deep cloud when cloud is necessary but shallow.
        if (
            _needs_cloud(requirements)
            and requirements.reasoning_depth != "deep"
            and engine_name in ["cloud_fast", "cloud_web_fast"]
        ):
            score += 15

        # Latency matters, but should not override privacy/local preference.
        if requirements.latency_preference == "fast":
            score += engine.get("speed", 0) * 2

        elif requirements.latency_preference == "balanced":
            score += engine.get("speed", 0)

        candidates.append((engine_name, score))

    candidates.sort(
        key=lambda x: x[1],
        reverse=True,
    )

    preferred = candidates[0][0]

    fallback_candidates = candidates[1:]

    if requirements.requires_current_information or requirements.requires_web:
        fallback_candidates = [
            (name, score)
            for name, score in fallback_candidates
            if ENGINES[name].get("web_search")
        ]

    fallbacks = [
        name
        for name, _score in fallback_candidates[:3]
        if name != preferred
    ]

    return preferred, fallbacks
