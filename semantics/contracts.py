from dataclasses import dataclass, field


@dataclass
class SemanticIntent:

    name: str

    description: str

    expected_output_type: str

    requires_artifact_context: bool = False

    style_sensitive: bool = False

    supports_transformations: bool = False

    valid_artifact_types: list[str] = field(default_factory=list)


@dataclass
class TransformType:

    name: str

    description: str

    semantic_effects: list[str]

    requires_existing_artifact: bool = True


@dataclass
class ArtifactType:

    name: str

    description: str

    formatting_constraints: list[str]

    style_sensitive: bool

    transform_types: list[str]
