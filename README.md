# Juniper

Juniper is a local-first semantic AI orchestration/runtime experiment exploring typed workflows, provenance, contract-driven artifacts, governance, and human-in-the-loop AI systems.

This repository is intended as a technical portfolio presentation, not a product launch. The project investigates how AI-assisted workflows can be structured so the runtime owns semantics, contracts, normalization, orchestration, and execution planning while models produce candidate outputs.

## What Juniper Explores

- Typed artifacts as canonical runtime objects.
- Semantic planning separated from execution planning.
- Contract-driven validation and repair.
- Provenance and traceability for generated outputs.
- Governance boundaries for external retrieval, cloud execution, and operator approval.
- Local-first operation with optional provider integrations behind explicit controls.
- Human review before sensitive or externally visible actions.

## Architecture Themes

Juniper is organized around explicit authority boundaries:

- `semantics/` defines operations, transforms, intents, and registries.
- `planner/` maps requests into semantic and execution plans.
- `runtime/` owns execution, validation, artifacts, context, governance, adapters, and workflow state.
- `agents/shared/` holds reusable contracts, policies, artifacts, capabilities, transforms, and governance definitions.
- Agent-specific folders contain domain workflows and contracts that sit on top of shared runtime semantics.

The central design constraint is that downstream systems should not reinterpret intent. The planner normalizes semantics, execution planners execute bounded plans, validators enforce contracts, and repair systems repair outputs rather than changing ontology.

## Current Focus

The codebase includes experiments around:

- Semantic transform resolution.
- Context injection with bounded provenance.
- External retrieval contracts and execution receipts.
- Structured artifacts for summaries, search results, candidate lists, and user-facing renderings.
- Operational controls for live providers and approval-gated actions.
- Regression tests for semantic authority, governance boundaries, validation routing, and workflow behavior.

## Non-Goals

Juniper does not claim to be AGI, an autonomous production agent platform, or a finished commercial product. It is a local research and engineering project focused on runtime structure, trace integrity, and careful boundaries around model-generated candidates.

## Suggested Reading

- `docs/semantic_runtime_architecture.md`
- `docs/juniper_semantic_authority_map.md`
- `docs/juniper_topology_bible.md`
- `docs/bounded_context_injection.md`
- `docs/binding_context_composition.md`

## Repository Hygiene Note

A public version of Juniper should use only sanitized source, docs, tests, and synthetic examples. Local logs, traces, credentials, private contact data, resumes/CVs, generated reports, prompt dumps, and operator-specific workspace files should not be published.
