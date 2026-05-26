import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.registries.semantic_taxonomy import (
    build_context_resolver_taxonomy_block,
    build_request_gate_taxonomy_block,
    load_semantic_taxonomy,
)


def main():
    taxonomy = load_semantic_taxonomy()
    assert "action_capabilities" not in taxonomy

    request_gate_block = build_request_gate_taxonomy_block()
    resolver_block = build_context_resolver_taxonomy_block()

    expected = (
        "- send_email: Queue an email delivery request for approval; "
        "do not send directly. (requires_approval=True)"
    )

    assert "Action capabilities:" in request_gate_block
    assert "Action capabilities:" in resolver_block
    assert expected in request_gate_block
    assert expected in resolver_block

    print("PASS taxonomy capability guidance")


if __name__ == "__main__":
    main()
