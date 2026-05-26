# Bounded Context Injection Design

## Purpose

This document defines the first acceptable active integration step for
binding-aware context composition: bounded additive context injection. It is a
design and guardrail document. Juniper does not currently inject binding-aware
context into runtime messages, and this document does not change runtime
behavior.

## Why Bounded Additive Injection First

Bounded additive context injection is the first acceptable active step because
it can be constrained without changing semantic authority:

- It is additive only: it may add context, but it must not rewrite the plan.
- It is bounded: every injected item must have size and count limits.
- It is attributable: every item must identify its source and reason.
- It is inspectable: telemetry and traces must show exactly what was added.
- It is reversible: the feature can be disabled without changing execution
  semantics.
- It is lower risk than execution integration because it does not dispatch
  actions, select skills, execute tools, or alter approval policy.

This boundary exists to let Juniper enrich prompts with controlled context
after semantic planning has already happened. It must not become a second
planner or a hidden retrieval system.

## Current State

Juniper currently has:

- Read-only `PlannedContextTrace` generation.
- Debug-only `planned_context_trace` telemetry.
- Binding-aware context policies in agent binding metadata.
- No retrieval execution from context planning.
- No prompt or message injection from binding-aware context planning.

The current implementation is observational. It can show what would be
included later, but it includes nothing in runtime messages.

## Hard Safety Invariants

- No planner mutation.
- No semantic reinterpretation.
- No hidden retrieval.
- No unrestricted memory loading.
- Every injected item must be attributable.
- Every injected item must be bounded.
- Injection policy must remain declarative.
- Approval-sensitive capabilities may restrict injection.
- Transforms cannot silently inherit unrelated action context.
- Context injection cannot change execution target, dispatch, validation, or
  approval requirements.
- Retrieved context cannot create or change shared capability identity.

## Proposed Injection Boundaries

Acceptable bounded context sources include:

- Bounded guest context summaries from explicitly bound agent-local resources.
- Bounded recent artifact snippets scoped to the planned capability.
- Bounded user preference summaries.
- Contract hints from known agent/shared contracts.
- Formatting constraints for the planned artifact or capability.

Each boundary must have a source type, a scope, a maximum item count, a maximum
token budget, and provenance metadata. Context should be summarized before
injection when raw records are too large or too sensitive.

## Explicit Non-Boundaries

Bounded context injection must not include:

- Autonomous search.
- Recursive retrieval.
- Unrestricted vector search.
- Hidden memory graphs.
- Prompt-driven tool execution.
- Planner rewriting.
- Capability inference from retrieved context.
- Background expansion of retrieval scope.
- Runtime selection of new resources that were not declared by binding/policy.

## Proposed Injection Policy Structure

A future injection policy may use:

```json
{
  "enabled": false,
  "max_items": 3,
  "max_tokens": 500,
  "allowed_source_types": [
    "agent_resource",
    "recent_artifacts",
    "memory",
    "contract"
  ],
  "redact_sensitive": true,
  "approval_sensitive": false,
  "inject_as": "bounded_context_block",
  "provenance_visibility": "telemetry_and_trace"
}
```

`enabled=false` must be the safe default. Enabling injection should require an
explicit rollout flag and a validated binding/context policy.

## Injection Provenance Requirements

Every injected item should expose:

- `source`
- `inclusion_reason`
- `token_count`
- `truncation_status`
- `retrieval_scope`
- `attributable=true`

The runtime should also record the binding ID, shared capability, policy path,
and whether the item was injected, skipped, truncated, or rejected.

## Runtime Phases

Phase 1: read-only trace.

Already complete. Juniper can trace planned binding-aware context without
retrieval execution or prompt injection.

Phase 2: disabled-by-default injection scaffolding.

The runtime may define typed injection policy and payload structures, but they
must not be called by default and must not alter runtime messages.

## Disabled Injection Scaffolding

The disabled scaffolding layer may build a `ContextInjectionPlan` from an
existing `PlannedContextTrace`. This is plan-building only. It must not perform
retrieval, load memory, load artifacts, call agent resources, mutate runtime
messages, or inject prompt context.

The scaffolding defines policy and payload types so future rollout work has a
stable contract:

- `ContextInjectionPolicy`
- `InjectedContextItem`
- `ContextInjectionPlan`
- `ContextInjectionError`

Even when a supplied policy says `enabled=true`, the current scaffolding keeps
`ContextInjectionPlan.enabled=false`, `injection_performed=false`, and
`provenance_only=true`. Each `InjectedContextItem` must keep `injected=false`.
The point is to prove bounds, source filtering, token estimates, attribution,
and error behavior before runtime injection exists.

Invalid policies fail closed. Approval-sensitive policies are reported as
disabled. Source type, item count, and token limits are enforced at the plan
layer without executing retrieval.

Phase 3: bounded additive injection behind explicit flag.

Runtime may inject bounded context blocks only when an explicit flag enables
the feature and validated policy permits it. Telemetry must prove what was
added.

The proposed experimental rollout path for this phase is defined in
`docs/experimental_context_injection_rollout.md`. Any future rollout must stay
disabled by default, capability-scoped, telemetry-first, and reversible.

Phase 4: capability-aware retrieval adapters.

Agent-local adapters may return bounded context records for declared resources.
Adapters must not execute actions or change runtime state.

Phase 5: autogenerated context policies.

Generated agents may declare safe context policies. Those policies must pass
the same validation, tracing, and bounded-injection checks before use.

## Alexis Examples

`draft_email` plus bounded guest summary:

- Binding: `draft_email`.
- Resource: `guest_db`.
- Injection may include at most a small summary of matched guest records.
- The injected block must show `source=alexis.guest_db`, scope `booking`, item
  count, token count, and truncation status.

`create_lower_third` plus formatting constraints:

- Binding: `create_lower_third`.
- Injection may include contract/formatting hints such as single-line output,
  max word count, and no trailing period.
- No retrieval is needed by default.

`producer_note` plus newsroom formatting hints:

- Binding: `producer_note`.
- Injection may include internal-note tone and audience hints.
- It must not pull guest context unless the binding and policy explicitly
  allow it.

## Failure Behavior

Overflow:

If selected context exceeds item or token limits, the runtime must truncate or
skip items and report this in provenance.

Missing resource:

If a bound policy requires a resource that is unavailable, injection must skip
that item and emit a typed error. It must not search for similar resources.

Invalid policy:

Invalid policies must fail closed. No context should be injected from an
invalid policy.

Approval-sensitive capability:

Approval-sensitive capabilities may restrict or disable context injection.
Context cannot weaken or obscure approval requirements.

Attribution failure:

If an item cannot prove its source and inclusion reason, it must not be
injected.

Truncation:

Truncated context must record the original estimated size, final size, and
truncation reason.

## Telemetry and Provenance Requirements

Future injected context must emit provenance telemetry. Telemetry should show:

- request ID
- agent
- shared capability
- binding ID
- policy fields
- injected item count
- skipped item count
- token totals
- truncation events
- source attribution
- retrieval scope
- whether injection was enabled by flag

Telemetry must make it possible to compare planned context, injected context,
and final runtime messages without exposing sensitive raw content by default.

## Future Autogenerated Agents

Autogenerated agents such as Yossi should eventually declare safe context
policies through bindings rather than handwritten retrieval logic. A generated
agent might declare that a reminder capability can use bounded user preference
summaries and recent task artifacts, with strict item and token limits.

Generated policies must remain declarative. They must pass binding validation,
context planning trace, injection policy validation, and provenance checks
before any context is injected.

## What Juniper Must Never Become

Juniper must not become:

- Opaque RAG.
- Autonomous hidden retrieval.
- Prompt spaghetti.
- A self-mutating planner.
- An uncontrolled memory injection system.
- A heuristic routing system.
- A prompt-only tool execution layer.
- A system where retrieved context changes semantic intent.

Bindings may help compose context only after semantic planning has already
produced explicit state. Context can support execution, but it cannot become
the authority for what the runtime is doing.
