# Juniper Topology Bible

## Purpose

This document defines canonical top-level ownership for the Juniper repository and establishes topology guard expectations.

Core rule: semantic authority remains planner-first; directory ownership must not blur semantic/runtime boundaries.

## Canonical Top-Level Directories

### `agents/`
Allowed:
- Agent-local declarations, bindings, contracts, policies, governance, workflows, tools.
- Shared agent-facing semantic and capability declarations under `agents/shared/`.

Forbidden:
- Runtime engine internals.
- Gateway transport code.
- Planner orchestration internals.

Valid placement examples:
- `agents/alexis/workflows/news_summary_workflow.py`
- `agents/shared/capabilities/actions.json`

### `gateway/`
Allowed:
- Ingress/egress boundary logic, routing, delivery-channel integration points.

Forbidden:
- Semantic planning authority.
- Artifact contract semantics.

Valid placement examples:
- `gateway/routing/`
- `gateway/system/`

### `planner/`
Allowed:
- Semantic intent normalization, request interpretation, planning contracts/policies.

Forbidden:
- Runtime execution engine internals.
- Agent-specific bindings/config instances.

Valid placement examples:
- `planner/contracts/`
- `planner/policies/`

### `runtime/`
Allowed:
- Domain-neutral execution substrate: orchestration, validation, registries, scheduling, ingestion, artifacts, tracing.
- Runtime utility helpers that remain infrastructural and are bounded by explicit utility boundary contracts.

Forbidden:
- Agent-domain semantics in module naming/ownership.
- Planner semantic reinterpretation.
- Utility-layer semantic authority, hidden orchestration, hidden retrieval influence, hidden trust influence, or memory writes.

Valid placement examples:
- `runtime/lookup/`
- `runtime/scheduling/`
- `runtime/ingestion/`
- `runtime/artifacts/`
- `runtime/registries/`

### `semantics/`
Allowed:
- Shared ontology-level semantic definitions and guidance.

Forbidden:
- Runtime execution settings.
- Agent-local instance declarations.

Valid placement examples:
- `semantics/interaction_modes.json`
- `semantics/operations.json`

### `core/`
Allowed:
- Cross-cutting core primitives that are not planner/runtime/agent-specific.

Forbidden:
- Hidden runtime feature dumping.

### `memory/`
Allowed:
- Memory persistence layer and memory-owned storage structures.

Forbidden:
- Planner authority logic.
- Gateway delivery logic.

### `runner/`
Allowed:
- Operator/dev entrypoints and local run surfaces.

Forbidden:
- Canonical runtime ownership of business logic.

### `tools/`
Allowed:
- Tests, audits, diagnostics scripts, operator utilities.

Forbidden:
- Production runtime ownership.

### `tests/`
Allowed:
- Test fixtures and suite inputs.

Forbidden:
- Runtime production logic.

### `docs/`
Allowed:
- Architecture, operations, contracts, conformance and checkpoint documentation.

### `archive/`
Allowed:
- Retired code/config and historical snapshots.

Forbidden:
- Active runtime imports.

### `logs/`
Allowed:
- Runtime logs and append-only audit outputs.

Forbidden:
- Source code ownership.

### `scripts/`
Allowed:
- Operational helper scripts and repo automation.

Forbidden:
- Core runtime/planner semantic ownership.

### `traces/`
Allowed:
- Trace outputs and diagnostics artifacts.

Forbidden:
- Production code ownership.

## Data-Only vs Code-Owning

### Data-only directories (no Python package/module ownership)
- `workspace/`: agent workspace data only.
- `workflow/`: persisted workflow state data only.
- `logs/`, `traces/`: operational outputs only.

Data-only guard expectations:
- No `__init__.py`
- No `*.py` runtime modules
- No imports from these directories as code packages

### Code-owning directories
- `agents/`, `gateway/`, `planner/`, `runtime/`, `semantics/`, `core/`, `memory/`, `runner/`, `tools/`, `scripts/`, `tests/`, `docs/`, `archive/` (archived code excluded from active imports)

## Forbidden Root-Level Ownership

The following root-level ownership patterns are forbidden in canonical topology:
- `config/`
- `contracts/`
- `policies/`
- `actions/`
- `router/`
- `runtime_trace/`
- `system/`
- `learning/`

If historical references exist, they must be transitional only and retired by guarded cleanup stages.

## Topology Guard Expectations

Guards should enforce:
1. No reintroduction of forbidden root layers above.
2. `runtime/workflows/` exists for workflow runtime helpers.
3. Root `workflow/` remains data-only (`workflow/state` persistence path allowed).
4. Root `workspace/` remains data-only.
5. Runtime subsystem ownership remains under canonical runtime subpackages:
   - `runtime/lookup`
   - `runtime/scheduling`
   - `runtime/ingestion`
   - `runtime/artifacts`
   - `runtime/registries`
6. Runtime utility boundary validators reject utility-layer declarations outside runtime topology and fail closed on semantic, orchestration, retrieval, trust, governance, autonomy, or memory influence fields.

## Placement Anti-Patterns

Do not place:
- Runtime Python utilities under root `contracts/` or `config/`.
- Persistent adapter/resource bindings under agent `context/` ownership.
- Agent-domain naming inside runtime module names for generic subsystems.
- Planner semantic authority into runtime policy loaders.

## Canonical Placement Examples

- Lookup runtime policy validation: `runtime/lookup/policy_validation.py`
- Scheduler loop: `runtime/scheduling/workflow_loop.py`
- Source ingestion execution: `runtime/ingestion/source_execution.py`
- Shared summarize skill contract: `agents/shared/skills/summarize/contract.json`
- Alexis workflow: `agents/alexis/workflows/news_summary_workflow.py`
- Planner attachment policy: `planner/policies/artifact_attachment.json`
