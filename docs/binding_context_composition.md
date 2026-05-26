# Binding Context Composition Design

## Purpose

This document defines the first safe runtime consumption boundary for agent
capability bindings: context composition. It is a design and invariant step
only. Runtime behavior, planner behavior, dispatch, approvals, semantic
operation logic, and execution are not changed by this document.

## Why Context Composition First

Context composition is the safest first boundary because it is additive,
bounded, observable, and reversible. A binding-aware context layer can add
small, attributable pieces of context after planning has already produced
semantic state. It does not need to choose an operation, change the execution
target, route actions, or execute resources.

This is lower risk than execution integration because context can be planned,
traced, size-limited, and disabled without changing the underlying request
plan. If a binding-aware context addition is wrong, the runtime should be able
to show exactly what was added and remove that behavior without changing the
planner or action system.

## Current State

Juniper already has context assembly infrastructure:

- `RuntimeContextBuilder` builds runtime context for agents.
- `AlexisContextPolicy` controls Alexis-specific context behavior.
- Context assembly currently does not consume capability bindings.
- Agent bindings are resolved and traced read-only through `runtime.bindings`
  and `runtime.binding_trace`.
- Planned shared capability provenance can identify a capability before
  execution, but bindings remain observational only.

## Target Flow

The future flow is:

```text
request
-> planner/gate
-> shared capability provenance
-> binding resolution
-> binding-aware context composition
-> execution
```

Binding resolution happens after semantic planning. Binding-aware context
composition consumes the resolved binding as metadata. It must not mutate the
plan, reinterpret the request, or route execution.

## Binding-Aware Context Rules

Binding-aware context should be declarative and capability-scoped:

- `draft_email` may include bounded guest context from `guest_db` when the
  binding permits that resource and the context policy allows guest lookup.
- `producer_note` may include newsroom formatting hints and internal-note
  constraints, but should not retrieve unrelated guest or research context.
- `create_lower_third` may include lower-third constraints such as brevity,
  single-line formatting, and no trailing period.
- `send_email` may include approval visibility context, such as reminding the
  model that delivery is approval-gated, but must not execute delivery or hide
  approval requirements.

Context additions should be small, typed, and attributable. A context block
should state what binding, policy, and source caused it to be included.

## Hard Invariants

- Bindings cannot redefine semantic intent.
- Bindings cannot alter planner decisions.
- Bindings cannot silently expand retrieval scope.
- Context additions must remain bounded and inspectable.
- No hidden keyword routing.
- No direct resource execution from prompts.
- Context policy must stay declarative.
- Private resources remain agent-local.
- Missing or invalid bindings must be surfaced as context planning failures or
  warnings, not hidden fallbacks.
- Approval-sensitive capabilities cannot use context to weaken or obscure
  approval requirements.

## Proposed Context Policy Structure

A future binding-aware context policy may use fields like:

```json
{
  "include_user_preferences": true,
  "include_recent_artifacts": false,
  "include_guest_context": true,
  "resource_scopes": ["booking"],
  "bounded_entity_types": ["guest"],
  "max_context_items": 3,
  "retrieval_policy": {
    "mode": "bounded_agent_local",
    "requires_explicit_resource_binding": true,
    "allow_external_network": false
  },
  "contract_hints": ["outreach_email"]
}
```

These fields are policy hints for context planning, not permission to execute
tools directly. Resource names must still resolve through validated local
binding references.

## Context Composition Phases

Phase 1: read-only context planning trace.

The runtime computes what context would be included for a planned capability
and binding, then emits trace/provenance only. Nothing is injected into model
messages.

## Read-Only Context Planning Trace

The first implementation surface is a read-only trace helper:

```text
trace_planned_context(
    request_id=...,
    agent_name=...,
    shared_capability=...,
)
```

The helper resolves the agent binding, validates the binding's
`context_policy`, and returns planned context items that describe what would be
included by a future binding-aware context composer. These items are synthetic
and must be marked `planned_only=true`. The trace must not call retrieval
adapters, read memory records, load recent artifacts, mutate runtime messages,
or inject prompt context.

The initial supported policy fields are intentionally narrow:

- `include_guest_context`
- `include_recent_artifacts`
- `include_user_preferences`
- `resource_scopes`
- `max_context_items`

Every planned item must be bounded, attributable, and inspectable. Missing
bindings, missing resources, invalid policies, and item-limit enforcement are
reported through typed context planning errors. Future telemetry should expose
the same provenance so context injection can be audited before any execution
phase consumes it.

## Context Trace Telemetry

Planned context traces may be emitted as telemetry only when binding tracing is
explicitly enabled:

```text
JUNIPER_TRACE_BINDINGS=1
```

The telemetry event is `planned_context_trace`. It serializes the planned-only
context trace, including the request ID, agent, shared capability, resolution
status, context policy, bounded item count, planned items, typed errors, and
manifest path. The payload must keep `retrieval_execution=false` and
`message_injection=false`.

This event is debug-only observability. It does not perform retrieval, load
memory, load artifacts, mutate prompts, or inject context. Its purpose is to
validate future binding-aware context composition before any runtime
consumption boundary starts using planned context.

## Bounded Context Injection Boundary

The first acceptable active integration step after read-only tracing is bounded
additive context injection. The detailed guardrail design lives in
`docs/bounded_context_injection.md`. Any future injection must be disabled by
default, explicitly enabled, bounded by item and token limits, attributable,
inspectable through telemetry, and unable to mutate planner, approval,
dispatch, or execution behavior.

Phase 2: additive bounded context inclusion.

The runtime may include small binding-approved context blocks with explicit
limits, source attribution, and telemetry. Execution dispatch remains
unchanged.

Phase 3: capability-aware retrieval adapters.

Agent-local resources may expose constrained adapters for context retrieval.
Adapters return bounded context records, not executable actions.

Phase 4: autogenerated context policies.

Generated agents may declare context behavior through bindings and context
policy manifests. The same validation and trace layers must prove that the
generated policy is bounded before runtime uses it.

## Alexis Examples

`draft_email` with `guest_db`:

- Binding resolves `draft_email` for Alexis.
- Context policy allows `include_guest_context=true`.
- Resource scope is limited to booking/guest context.
- Runtime may include at most a small number of matched guest records.
- Each injected record is attributed to `guest_db` and the `draft_email`
  binding.

`producer_note`:

- Binding resolves `producer_note`.
- Context policy may include newsroom tone and internal-note formatting hints.
- Guest lookup is not included unless explicitly declared and bounded.
- The context stays focused on note shape, audience, and constraints.

`create_lower_third`:

- Binding resolves `create_lower_third`.
- Context policy may include lower-third contract hints.
- Runtime may include formatting constraints such as max words, single-line
  output, and no meta response.
- No retrieval is needed by default.

## Failure Behavior

Missing binding:

The context planner should produce a typed failure or warning and skip
binding-aware context unless an explicit fallback policy exists.

Missing resource:

The context planner should report the missing local resource and skip context
that depends on it. It must not search for similarly named tools.

Invalid context policy:

The policy should fail validation before context is injected. Invalid policy
must not silently degrade into broader retrieval.

Retrieval overflow:

Retrieval adapters must enforce `max_context_items`, byte limits, and source
limits. Overflow should be reported in context provenance.

Approval-sensitive capability:

Approval-related context may make approval requirements visible, but cannot
weaken, bypass, or reinterpret approval policy. `send_email` remains distinct
from `draft_email`.

## Non-Goals

- No execution routing.
- No autonomous retrieval.
- No hidden memory injection.
- No planner mutation.
- No unrestricted RAG.
- No keyword routing.
- No direct tool execution from model text.
- No binding-driven action dispatch.

## Future Autogenerated Agents

Autogenerated agents such as Yossi should eventually define context behavior
declaratively through bindings and context policies rather than handwritten
runtime logic. A Yossi binding could state which shared capability it supports,
which local resources are available, and which bounded context policy applies.

Before any generated agent participates in runtime execution, the context
planner should prove that its binding and context policy are valid, bounded,
and attributable. This gives generated agents a path to useful specialization
without creating hidden routing or prompt-only tool behavior.

## Future Implementation Guardrails

- Context composition must remain observable.
- Every injected source must be attributable.
- Future telemetry should expose context provenance.
- Context traces should show binding ID, shared capability, policy fields,
  selected resources, source counts, and any skipped context.
- Context injection should be easy to disable by capability, agent, or debug
  flag during rollout.
- Runtime tests should verify that context additions do not change planner
  output, execution target, approval flags, or action semantics.
