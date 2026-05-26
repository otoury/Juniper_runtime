# Juniper Semantic Authority Map

## Purpose

This document defines who is allowed to decide what inside Juniper.

Ownership, authority, and execution are related but separate:

- Ownership means where a concept, declaration, registry, or implementation
  belongs.
- Authority means which layer is allowed to make a specific decision.
- Execution means carrying out an already-authorized decision within bounded
  runtime constraints.

## Core Rule

Planner owns semantic intent.

Runtime executes intent.
Bindings constrain execution.
Contracts constrain guarantees.
Policies constrain behavior.
Governance constrains permission.

Runtime, context assembly, adapters, bindings, skills, policies, and validators
must not reinterpret semantic intent. They may reject, constrain, route through
declared bindings, or fail closed. They may not invent a new meaning.

## Canonical Authority Matrix

| Decision | Primary Authority | Secondary Constraints | Forbidden Authorities | Notes |
|---|---|---|---|---|
| user semantic intent | planner request gate | terminology bible, semantic runtime architecture | runtime, bindings, adapters, skills, context assembly | Planner decides what the user is asking for. |
| interaction mode | planner request gate | semantic operations registry, active artifact state | runtime execution, adapter bindings, context injection | Modes such as `NEW_REQUEST`, `TRANSFORM_EXISTING`, `CONVERT_ARTIFACT`, and `CONTINUE_WORKFLOW` are semantic planner decisions. |
| capability selection | planner capability mapping | shared capability registry, agent availability, governance | context assembly, adapters, skills, transforms | Bindings may expose available capabilities; they do not choose meaning. |
| operation selection | planner + semantic operations registry | contracts, capability compatibility | runtime policy, adapter config, context rendering | Operations are semantic units of work, not runtime steps. |
| workflow selection | planner or explicit user/operator request | agent workflow declarations, governance, contracts | scheduler executor, adapter bindings, skills | Scheduled tasks may reference workflows but must not define workflow meaning. |
| transform resolution | transform registry + planner | artifact type, active artifact rules, transform contracts | runtime repair, skills, context assembly | Transforms must preserve or intentionally convert artifact type according to declared semantics. |
| action instantiation | runtime action layer | selected operation, workflow, contracts, governance | adapters, skills, context assembly | Actions are runtime-instantiated steps derived from semantic operations. |
| execution planning | planner/runtime execution builder | contracts, policies, privacy/currentness constraints | scheduler declarations, adapter bindings, model outputs | Execution plans configure one action; they do not redefine the action's meaning. |
| engine selection | runtime execution builder / model policy | execution plan, privacy, latency, risk, availability | semantic bindings, adapters, context assembly | Engine choice is execution behavior, not semantic intent. |
| adapter eligibility | runtime adapter registry + agent bindings | contracts, governance, capability compatibility | planner semantic inference, skills, context assembly | Adapters may be eligible or ineligible; they do not interpret user meaning. |
| binding resolution | agent binding resolver | shared capability definitions, policies, governance | planner replacement logic, adapters, skills | Bindings are additive and constraining; they must not reinterpret planner intent or capability meaning. |
| governance approval | governance gate / runtime permission layer | user/operator approval, contract rules, policy state | planner, skills, adapters | Governance can allow, deny, block, or audit-only. It does not change semantics. |
| context assembly | runtime context composer | selected intent, active artifact bounds, injection policy, provenance | planner replacement logic, adapter bindings | Context is temporary bounded runtime assembly for one run. It must not choose capabilities or operations. |
| lookup execution | runtime lookup pipeline | lookup contracts, lookup policies, governance, adapter eligibility | planner reinterpretation, context assembly, skills | Lookup executes explicit bounded lookup requests. It must not become hidden retrieval. |
| source ingestion | runtime ingestion | source ingestion contracts, source declarations, governance, audit policy | scheduler semantics, summarizer, memory | Source ingestion fetches or normalizes declared sources only within governance. |
| rendering | runtime renderer / gateway renderer | artifact schema, render policy, channel constraints | artifact schema registry, planner, adapters | Rendering turns artifacts or context material into rendered output. It must not create new semantic facts. |
| delivery | runtime delivery + adapter | artifact/rendering output, governance, transport policy, audit | skills, context assembly, scheduler alone | Delivery is an external operation through adapters. |
| retry/fallback | runtime policy | execution plan, contract bounds, governance | semantic planner, bindings, adapters | Retry and fallback affect execution behavior only. |
| artifact schema | artifact registry / contracts | semantic artifact definitions, validators | renderer, planner output text, bindings | Artifact schemas define structure and guarantees. Renderers do not define schemas. |
| validation | validators / contract registry | artifact schema, contracts, policies | repair systems, adapters, model output | Validators enforce declared contracts; they do not reinterpret intent. |
| memory persistence | memory subsystem | explicit memory capability, governance, provenance, audit | context assembly, lookup, source store, scheduler | Memory writes require explicit authorization and must not be hidden prompt stuffing. |
| audit persistence | audit subsystem | content-safety rules, provenance requirements | memory subsystem, delivery adapters | Audit records operational facts; audit is not memory. |
| scheduler triggering | scheduler / scheduled task registry | scheduled task declarations, governance, locking, audit | workflows themselves, adapters, planner mutation | A scheduled task is a trigger declaration plus workflow reference, not the workflow. |

## Forbidden Authority Drift

Bindings must not redefine planner meaning.
`agents/*/capabilities/bindings.json` and agent-local binding files may add
resources, policies, governance, adapter eligibility, and execution bounds.
They may not reinterpret a user request or silently map it to a different
capability.

Context assembly must not select capabilities.
`runtime/context_composer.py`, context injection, and lookup context rendering
may assemble bounded runtime material after semantic decisions exist. They must
not decide what the user meant.

Adapters must not change semantic interpretation.
Adapters such as guest DB, RSS, Telegram, filesystem, or future delivery
adapters execute bounded external operations. They may fail closed or return
normalized results. They may not reinterpret intent, change operation type, or
expand scope.

Workflows must not bypass contracts.
Agent-local workflows may sequence operations, but each operation must remain
within contracts, governance, and policy bounds.

Runtime policy must not mutate semantic meaning.
Timeouts, retries, fallback order, concurrency, render limits, storage limits,
and cancellation behavior are execution constraints. They cannot change
capability, operation, workflow, or artifact type.

Skills must not act as routing authority.
Skills provide agent behavior guidance. They are not a substitute for planner
semantic routing, capability selection, or governance.

Transforms must not act as hidden planners.
Transforms operate on active artifacts or declared source structures. They may
not infer new workflows, trigger hidden lookup, or convert artifact type unless
conversion was explicitly selected.

Validators must not reinterpret intent.
Validators enforce declared structure and guarantees. They may reject or fail
closed, but they cannot repair ontology.

Repair systems must not repair ontology.
Repair systems may repair malformed outputs within a known contract. They must
not invent a different semantic operation, artifact type, workflow, or
capability.

Schedulers must not create autonomous semantics.
Scheduler triggering may instantiate allowed workflows under governance. It may
not create tasks, modify schedules, infer topics, or alter workflow meaning.

## Transitional Areas

- `runtime/request_planner.py` remains a broad orchestration hub. It carries
  planning outputs into lookup request creation, lookup execution, context
  materialization, rendering decisions, and summaries. This is acceptable only
  while planner semantic authority remains primary.

- `planner/execution.py` currently contains both semantic-facing fields and
  execution configuration fields. This is transitional. Execution planning must
  not become a source of semantic reinterpretation.

- `agents/alexis/capabilities/bindings.json` combines capability bindings,
  lookup policies, render policies, injection policies, resources, tone, and
  context policy. This is acceptable only as additive local binding and
  constraint data.

- `agents/alexis/bindings/resources.json`,
  `agents/alexis/bindings/adapters.json`, and
  `agents/alexis/bindings/context_injections.json` currently store persistent binding
  and registry data under a `context` path. Topology is transitional; authority
  must still treat these as binding/config constraints, not context semantics.

- `runtime/registries/context_source_registry.py`,
  `runtime/registries/context_adapter_registry.py`, and
  `runtime/registries/context_injection_registry.py` currently validate
  persistent binding/config data through context-named modules. These
  registries may validate and resolve; they may not execute or reinterpret.

- `agents/alexis/workflows/latest_news_workflow.py` and
  `agents/alexis/workflows/news_summary_workflow.py` are Python workflow
  helpers. They remain transitional implementations of agent-local workflows,
  not the source of planner semantic authority.

- `runtime/scheduling/workflow_executor.py` currently contains narrow
  allowlisted workflow execution paths. This is acceptable only because
  governance and allowlists remain explicit; scheduler execution must not
  become workflow semantic authority.

## Future Risks

Capability vs operation overlap:
Capabilities describe what Juniper is allowed or able to do. Operations are
semantic units of work inside workflows. If capability files start encoding
operation choice, bindings may become hidden planners.

Workflow vs action overlap:
Workflows are semantic recipes. Actions are runtime-instantiated executable
steps. If runtime queues or scheduled plans start acting like workflow
definitions, execution structures may collapse into semantic structures.

Source vs binding overlap:
RSS feeds and external feeds are valid sources under source ingestion. Guest DB
resource configuration is an adapter binding. Reusing `source` for both can
confuse ingestion ownership with adapter/resource eligibility.

Context vs memory overlap:
Context is temporary bounded assembly for one run. Memory is governed
persistence. Context render blocks, lookup packets, and injected snippets must
not become memory without explicit memory capability, provenance, and audit.

Runtime vs planner overlap:
Runtime may execute, reject, constrain, validate, or audit. Planner owns
semantic intent, interaction mode, and capability/operation selection. Runtime
systems must not infer hidden routes from adapter availability, context policy,
or skill text.

Contract vs policy overlap:
Contracts define guarantees and forbidden behavior. Policies define runtime
behavior within those guarantees. If policies redefine guarantees, runtime
configuration becomes semantic authority.

Skill vs routing overlap:
Agent skills guide style and behavior after a semantic decision exists. If
skills are used to choose capabilities or workflows, they become hidden routing
authority.

## Non-goals

This document defines authority boundaries so future cleanup can preserve
Juniper's local-first, bounded, governed runtime philosophy.
