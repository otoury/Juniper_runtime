from semantics.intents import SEMANTIC_INTENTS
from semantics.transforms import load_transform_registry
from runtime.registries.artifacts import get_artifact_config


def get_intent(name: str):
    return SEMANTIC_INTENTS.get(name)


def get_transform(name: str):
    return load_transform_registry().get(name)


def get_artifact_type(name: str):
    return get_artifact_config(name)
