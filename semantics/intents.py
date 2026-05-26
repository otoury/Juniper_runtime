from semantics.contracts import SemanticIntent


SEMANTIC_INTENTS = {

    "artifact_create": SemanticIntent(
        name="artifact_create",

        description="Create a new user-facing artifact.",

        expected_output_type="artifact",

        requires_artifact_context=False,

        style_sensitive=True,

        supports_transformations=True,
    ),

    "artifact_transform": SemanticIntent(
        name="artifact_transform",

        description="Transform an existing artifact.",

        expected_output_type="artifact",

        requires_artifact_context=True,

        style_sensitive=True,

        supports_transformations=True,
    ),

    "workflow_action": SemanticIntent(
        name="workflow_action",

        description="Create executable workflow action.",

        expected_output_type="action",

        requires_artifact_context=False,

        style_sensitive=False,
    ),

    "translation": SemanticIntent(
        name="translation",

        description="Translate content while preserving meaning.",

        expected_output_type="translation",

        requires_artifact_context=False,

        style_sensitive=True,
    ),

    "summary": SemanticIntent(
        name="summary",

        description="Summarize provided information.",

        expected_output_type="summary",

        requires_artifact_context=False,

        style_sensitive=False,
    ),
}
