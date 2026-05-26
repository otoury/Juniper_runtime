# Juniper Semantic Runtime Architecture

## Runtime Overview

Juniper is a local-first semantic cognitive runtime. The runtime owns semantic interpretation, orchestration, contracts, normalization, execution planning, validation, artifact persistence, and action routing. Models generate candidate outputs; they do not own runtime semantics.

The runtime separates these concerns:

- Routing and request gating classify the interaction shape.
- Context resolution rewrites dependent requests only when needed.
- Execution planning chooses output category, semantic artifact type, engines, and fallback policy.
- Skill loading builds agent prompts from semantic state.
- Artifact normalization and validation enforce artifact contracts.
- Action parsing and approval handling manage workflow actions separately from artifacts.

## Core Semantic Concepts

An `operation` is the canonical semantic operation the runtime will perform, such as creating new work, transforming existing work, converting work, or continuing a workflow action.

An `interaction_mode` is the request-shape label used by the gate and prompt taxonomy. It maps user interaction into runtime planning modes such as `NEW_REQUEST`, `TRANSFORM_EXISTING`, `CONVERT_ARTIFACT`, `CONTINUE_WORKFLOW`, and `ANSWER_QUESTION`.

An `artifact` is a typed runtime object with a semantic identity, such as `email_draft`, `producer_note`, or `written_piece`. Typed artifacts are canonical objects; transforms preserve artifact type unless conversion is explicit.

A `transform` is an edit to an active artifact. It preserves artifact identity and uses a `transform_type`, such as `shorten`, `expand_scope`, or `punchy`.

An `action` is a workflow object, not an artifact. Actions include queued work such as `send_email`, with approval requirements enforced by capability policy.

Attachment semantics define whether the latest request may use the active artifact. Attachment must be explicit and bounded by operation policy.

Workflow continuation is an `ACTION` operation: it may use an active artifact as context, but it must not become artifact transformation, artifact inference, or artifact validation.

## Operation Taxonomy

Operation policy lives in `agents/shared/semantics/operations.json`.

### NEW_REQUEST

Purpose: handle standalone requests without active artifact attachment.

Attachment: does not require or use active artifact context.

Preservation: not applicable because no previous artifact identity is being preserved.

Validation: if execution planning creates an artifact, normal artifact validation applies. If the request is a general answer, artifact validation does not apply.

### TRANSFORM

Purpose: revise active artifact content without changing artifact type.

Attachment: requires active artifact context.

Preservation: must preserve artifact type. A `producer_note` transform remains a `producer_note`; an `email_draft` transform remains an `email_draft`.

Validation: artifact output is normalized and validated as the preserved artifact type.

### CONVERT

Purpose: convert active artifact/content into a different artifact type.

Attachment: requires active artifact context.

Preservation: does not preserve artifact type. Conversion intentionally changes type.

Validation: output is validated as the target artifact type when a target type is inferred.

### ACTION / CONTINUE_WORKFLOW

Purpose: deliver, send, save, schedule, approve, or otherwise act on existing work without rewriting it.

Attachment: active artifact context is optional. It may be attached for payload construction, but the operation remains action-oriented.

Preservation: does not preserve artifact type because it is not producing a new artifact.

Validation: workflow actions bypass artifact validation. Structured action envelopes flow to action parsing and approval handling.

## Artifact System

`semantic_output_type` is the typed artifact identity selected for artifact-producing work. It guides skill loading, response normalization, validation, persistence, and engine policy.

Explicit artifact requests are detected from artifact registry creation examples and preserved through request planning into execution planning. Execution planning consumes `semantic_output_type` when provided instead of re-inferring from generic text.

Artifact transforms preserve the active artifact type. Transform planning should not reinterpret the artifact identity.

Neutral artifacts, such as `written_piece`, cover explicit prose artifact requests like “write 150 words about AI regulation” without becoming a fallback for all general answers.

Important current artifact types:

- `email_draft`: booking or outreach email draft.
- `producer_note`: internal producer/control-room note.
- `lower_third`: broadcast lower-third/chyron text.
- `guest_list`: structured list of possible guests.
- `guest_candidate_list`: structured runtime list of guest candidates normalized from bounded sources.
- `written_piece`: neutral prose writeup or short explanatory piece.
- `search_api_result_set`: raw provider-neutral search API results with query,
  URLs, source refs, citations, cost/dry-run/external-call flags, and
  provenance before any model summary or domain normalization.
- `external_search_result_set`: raw governed external-search result boundary
  before provider integration. It records query, raw result containers, source
  refs, citations, explicit normalized-result lineage, external-call status,
  cost status, and provenance, but no provider metadata, summaries, ranking,
  selection, delivery payloads, or domain-normalized objects.
- `external_discovery_result_set`: raw external discovery results with provider provenance, citations, and source references before domain normalization.

External discovery normalization is domain-owned. Shared provider infrastructure may
capture raw `external_discovery_result_set` artifacts, but Alexis-owned guest
normalizers convert those raw artifacts into `guest_candidate_list` artifacts
without provider execution, ranking, scoring, selection, delivery, or outreach
drafting.

Guest candidate list merge is a structural runtime boundary. Local DB candidates,
externally discovered public-source candidates, user-supplied candidates, and
manual-operator-verified candidates retain explicit `candidate_origin` values;
contact data retains explicit verification state (`verified`,
`public_source_observed`, `possible_unverified`, `blocked_private`, or
`missing`). Bounded duplicate grouping may emit `guest_candidate_merge_receipt`
records with provenance and receipt refs, but external public-source fields must
not automatically overwrite local DB fields, contacts must not be promoted, and
merge receipts must not perform ranking, hidden trust scoring, live calls, DB
writes, memory writes, or semantic reinterpretation.

## Transform System

`transform_type` is the canonical transform selected for active-artifact edits. It is resolved by `resolve_transform_type()` from the config-backed transform registry.

Transforms are defined in `agents/shared/transforms/transforms.json`.

Examples:

- `shorten`: compression transform for shorter output.
- `expand_scope`: adds another angle, implication, mention, or dimension.
- `punchy`: style transform for punchier wording.

Transforms belong to artifact operations. `ACTION` operations must not resolve transform types or enter transform planning.

## Action System

Actions are workflow objects, not artifacts. They are parsed from structured action envelopes and routed through action capability validation and approval handling.

Capabilities are registry-backed in `agents/shared/capabilities/actions.json`.

`send_email` and `draft_email` are distinct:

- `send_email` queues an email delivery request and requires approval.
- `draft_email` creates an email draft artifact/capability and does not send anything.

Actions must not enter artifact validation. A workflow continuation may attach an artifact to build an action payload, but it should produce `expected_output_type=action`, `semantic_output_type=null`, and no `transform_type`.

## Trust Lineage

Trust progression records are scoped runtime diagnostics. A trust state may be
carried forward only when its prior lineage matches the current owning agent,
workflow id, workflow type, capability, and action type scope. Approval decisions
do not promote trust, and unrelated workflow/capability classes must fail closed
with explicit trust-bleed prevention diagnostics instead of inheriting a prior
trust state.

Resumptions, nested workflow calls, and delegated workflow steps must emit an
explicit bounded trust inheritance decision before any prior trust state is
carried forward. Resumption inheritance additionally requires a valid resume
integrity receipt. Nested workflow and delegated-step boundaries do not allow
cross-workflow or cross-capability trust bleed; non-matching lineage scopes must
produce fail-closed diagnostics rather than reinterpret trust.

Retrieval history, retrieval receipts, lookup/retrieval lineage, source refs,
citations, raw provider metadata, provider success state, lookup success state,
record counts, semantic match scores, and retrieval diagnostics are not trust
authority. They may be preserved as informational provenance or operator-visible
diagnostics only. They must not promote, demote, score, accumulate, or otherwise
change trust state, approval state, approval routing, autonomy state, memory
state, or governance state.

Trust provenance must be operator/governance driven. Valid trust progression
provenance is limited to explicit operator verification, explicit governance
decision records, scoped trust lineage, and content-safe verification receipts.
Trust progression must fail closed when provenance contains retrieval authority
fields, provider success/failure markers, retrieval scores, hidden reputation
signals, memory-write flags, or autonomy-escalation flags.

Prohibited influence paths include provider success to trust or approval,
retrieval history to trust or approval, retrieval receipts to trust or approval,
retrieval lineage to trust or approval, retrieval scores to trust or approval,
hidden reputation to trust or approval, memory writes to trust or approval, and
hidden autonomy escalation to trust or approval. Retrieval success and retrieval
failure remain informational outcomes only.

## Governance-To-Planner Boundary

Governance, trust, approval, visibility, autonomy, and memory state are not
planner semantic authority. They may constrain execution eligibility, expose
content-safe operator diagnostics, or describe runtime configuration, but they
must not redefine user semantic intent, operation, artifact type, transform
type, shared capability, lookup metadata, web/current-information requirements,
engine routing, approval routing, autonomy, or memory behavior.

Planner-visible governance metadata must be explicit, content-safe,
observational, and marked with `semantic_reinterpretation_performed=false`.
Planner guards fail closed when governance/trust-shaped payloads carry semantic
mutation fields or when visibility metadata includes non-observational fields.
Boundary diagnostics must record whether planner semantic authority was
preserved, which fields were blocked, and that governance can constrain
execution only.

## Visibility Isolation

Visibility and diagnostic surfaces are observational runtime outputs. They may
be attached only to explicit operator-report, telemetry, audit-receipt, or
bounded planner-visible governance metadata channels. They must not be attached
to planner prompts, semantic planning metadata, execution-planner output,
lookup metadata, retrieval policy, workflow state, governance state, or memory
state.

Diagnostic payloads are never planner or runtime semantic context. They must
not mutate retrieval, workflow, governance, artifact, candidate, database, or
memory state; they must report `hidden_context_injection_performed=false` and
`planner_semantic_authority=false` when those fields apply. Content-bearing
fields such as raw results, queries, prompts, URLs, source refs, citations,
contact values, snippets, summaries, and provider payloads are excluded from
visibility and diagnostics unless an explicit typed artifact contract owns that
content.

## Cross-Substrate Boundaries

Retrieval, workflow, governance, and visibility are independent semantic
substrates. Cross-substrate interaction is allowed only through explicit,
auditable contracts declared in
`agents/shared/contracts/cross_substrate_interaction_contracts.json`.

Allowed influence directions are intentionally narrow:

- governance may constrain retrieval or workflow execution eligibility;
- workflow may issue explicit lookup requests to retrieval;
- retrieval may return explicit provenance to workflow;
- retrieval, workflow, and governance may emit content-safe observational
  diagnostics to visibility.

The inverse paths are not implied. Visibility must not influence retrieval,
workflow, governance, planner prompts, or semantic state. Retrieval outcomes
must not mutate governance state, workflow state, planner semantics, memory, or
autonomy. Workflow state must not implicitly rewrite retrieval policy or
governance state. Governance constraints must not become semantic overrides.

Forbidden coupling paths include implicit substrate inheritance, hidden
orchestration, cross-substrate planner mutation, memory writes, hidden autonomy,
and any hidden semantic coupling between substrates. Boundary validators must
fail closed and produce auditable diagnostics when a payload carries foreign
state, semantic mutation fields, memory flags, or hidden-autonomy flags.

## Helper Semantic Purity

Helper and utility functions are execution aids only. They may format, copy,
bound, summarize counts, or build explicit contract payloads, but they are not a
semantic substrate and must not become hidden orchestrators between retrieval,
workflow, governance, visibility, planner, artifact, or memory authority.

Helper purity rules live in
`agents/shared/contracts/helper_purity_rules.json`. Runtime helper validation
must fail closed when helper inputs or outputs contain hidden routing decisions,
planner semantic mutation fields, hidden visibility attachments, hidden
governance injection, memory writes, hidden autonomy flags, or foreign substrate
state. Cross-substrate helper pass-through is allowed only when the normal
cross-substrate contract is explicit, auditable, and valid for the declared
source substrate, target substrate, and interaction type.

Helper purity diagnostics are observational only. They must report that helpers
have no semantic authority, planner meaning was not mutated, hidden helper
routing did not occur, hidden visibility or governance injection did not occur,
and memory writes did not occur. Diagnostics may be emitted to operator,
telemetry, or audit surfaces, but they must not become planner context or hidden
runtime context.

## Runtime Utility Boundary

Runtime utilities are infrastructural helpers only. They may format, validate,
load, normalize, serialize, trace, or adapt runtime-owned structures, but they
are not semantic authority and must not perform hidden orchestration.

Utility boundary policy lives in
`agents/shared/contracts/runtime_utility_boundary_rules.json`. Utility
diagnostics are observational and content-safe. They report whether semantic
isolation and runtime topology conformance were preserved, which fields were
blocked, and whether validation failed closed.

Prohibited utility influence paths include utility-driven planner semantic
mutation, execution planning, workflow mutation, hidden orchestration, retrieval
policy or ranking changes, hidden lookup-context injection, trust or approval
state changes, governance state changes, memory writes, and hidden autonomy
escalation.

Runtime utility validation fails closed when a utility payload carries semantic
planning fields, workflow/governance/retrieval/trust control fields, mutation
flags, autonomy flags, or memory-write fields. Utility topology must remain
runtime-owned; utility-layer code must not be introduced under planner,
semantics, agent, gateway, or root-level utility ownership as a way to bypass
runtime semantic boundaries.

## Attachment Semantics

`uses_active_artifact` means the request attaches the active artifact as semantic context.

`requires_artifact_context` means the operation cannot be correctly planned without active artifact context.

Artifacts may attach for:

- transforms of active work,
- conversions of active work,
- workflow actions that operate on active work.

Standalone requests override active artifacts. Explicit new artifact creation, translations, new producer notes, new emails, and normal answers should not inherit the active artifact unless the interaction is explicitly dependent.

## Skill Loading

Skill loading is operation-aware. Skills are selected from agent manifests using `semantic_output_type`, `interaction_mode`, and `expected_output_type`.

Artifact transforms should receive artifact and rewrite instructions, not action-envelope instructions. For example, `TRANSFORM_EXISTING + producer_note + expected_output_type=artifact` loads producer-note/rewrite guidance but must not load `structured_actions`.

`structured_actions` loads for action/workflow outputs, such as `CONTINUE_WORKFLOW` with `expected_output_type=action`. This prevents action-envelope prompt contamination during artifact generation.

## Validation & Repair

Artifact validation runs after artifact normalization when `expected_output_type=artifact`. It enforces configured artifact contracts and quality constraints.

Semantic contract failures catch responses that describe completion instead of performing the task.

Repair is a response-repair path. It repairs output contract violations; it does not reinterpret user intent or change ontology.

Validators should remain semantic-free. They enforce contracts for the plan they receive; they should not infer operation, artifact type, transform intent, or user intent.

## Semantic Registries / Config

Current shared semantic registries:

- Operations: `agents/shared/semantics/operations.json`
- Transforms: `agents/shared/transforms/transforms.json`
- Actions/capabilities: `agents/shared/capabilities/actions.json`
- Artifacts: `agents/shared/artifacts/artifacts.json` plus agent artifact registry loading
- External discovery providers: `agents/shared/semantics/external_discovery_provider_contracts.json`
- External search contracts: `agents/shared/semantics/external_search_contracts.json`
- External search provider authorization contracts: `agents/shared/contracts/external_search_provider_authorization_contracts.json`
- External search provider authorization governance: `agents/shared/governance/external_search_provider_authorization.json`
- External search provider authorization policy: `agents/shared/policies/external_search_provider_authorization_policy.json`
- External search provider authorization bindings: `agents/shared/bindings/external_search_providers.json`
- Contact discovery safety contracts: `agents/shared/contracts/contact_discovery_safety_contracts.json`
- Contact discovery safety governance: `agents/shared/governance/contact_discovery_safety.json`
- Contact discovery safety policy: `agents/shared/policies/contact_discovery_safety_policy.json`
- Taxonomy/prompt guidance: `config/semantic_taxonomy.json`

The runtime should prefer registry/config-driven semantics over hardcoded branching.

`external_search` is a canonical governed semantic/runtime contract for
external-search shaped work before provider integration. It is deliberately
provider-free: planners may express a bounded query request, but the contract
forbids provider selection, adapter invocation, network or browser calls,
credential access, cloud model web search, summarization, ranking, domain
normalization, delivery, and writes. Its result artifact is
`external_search_result_set`, which is an audit boundary only and must fail
closed if execution or provider fields appear.

Multiple `external_search_result_set` artifacts may be merged only through the
explicit bounded result-set merge helper. That merge preserves the
`external_search_result_set` artifact type, appends raw results in input order
within declared result-set and result-count limits, carries source refs,
citations, receipt refs, and normalized-result lineage forward, and records
`merge_metadata`. It must not deduplicate, summarize, rank, select, normalize
into domain objects, invoke providers, perform delivery, or reinterpret the
retrieval semantics of any input result set.

Raw retrieval artifacts are evidence boundaries, not planner or runtime
semantic grounding authority. Artifact policy must explicitly deny planner and
runtime semantic grounding for raw retrieval result sets, and active artifact
attachment must fail closed instead of allowing those artifacts to select
operation, capability, artifact type, or user intent.

Retrieval authority is isolated from trust and approval authority. Retrieval
subsystems may report execution status, provider authorization, receipt refs,
lineage refs, source refs, citations, and counts as provenance, but those fields
must not enter trust progression or approval semantics as authority. Runtime
diagnostics for retrieval/trust boundaries must state that retrieval is
informational/provenance-bearing only, trust progression is
operator/governance-driven only, retrieval success did not alter trust, provider
success trust accumulation did not occur, retrieval-based trust scoring did not
occur, hidden reputation systems were not used, memory writes did not occur, and
hidden autonomy escalation did not occur.

Retrieval is the umbrella runtime term for bounded evidence acquisition.
Lookup is a bounded retrieval specialization: planner-declared, capability
bound, agent-local, governed, and explicitly materialized before any context
rendering or injection. Lookup terminology remains in compatibility fields such
as `lookup_type` and `lookup_pipeline`, but those fields describe this bounded
retrieval specialization rather than a separate semantic umbrella.

The runtime external-search adapter subsystem is domain-neutral and closed by
default. The default `runtime_external_search_closed_adapter` validates
`external_search` requests against the shared contract and can materialize a
non-executed `external_search_result_set` audit artifact with empty raw results,
source refs, and citations. It does not select providers, call provider
adapters, access credentials, use browser/network APIs, summarize, rank,
normalize into domain objects, or deliver outputs. Provider-specific adapters
remain outside this semantic boundary until a later governed stage explicitly
evolves the contract.

External-search provider authorization is a runtime governance boundary, not a
planner semantic authority. Governance JSON controls the provider/resource
permission state (`blocked`, `audit_only`, or `allowed`); policy JSON defines the
bounded runtime behavior of those states; contract JSON defines required
decision/audit structure; binding JSON only connects declared
provider/resource/contract/governance/policy references. Missing provider
authorization fails closed before live provider execution can be authorized.
Authorization decisions must be content-safe audit records and must not include
queries, raw results, citations, credentials, rendered context, provider
payloads, semantic-intent choices, provider fallback choices, or memory writes.

Contact discovery safety is a runtime governance/policy boundary, not planner
semantic authority. It must be satisfied before any future live guest/contact
search path can treat discovered contact data as usable contact data. The policy
allows only explicitly public professional sources, requires explicit contact
verification state, distinguishes public professional email, public office/press
contact, public booking representative, public social profile, and
unverified/possible contact classes, and fails closed for private or personal
contact data. It forbids guessed/generated emails, private phone harvesting,
personal address discovery, social-engineering language, raw provider payloads as
contact records, memory writes, and automatic DB updates. Contact-safety audit
records must remain content-safe and must not include contact values, queries,
raw results, source refs, citations, provider payloads, or rendered context.

Guest/contact retrieval diagnostics are an operator projection only. They may
summarize already-materialized guest DB adequacy, external handoff eligibility,
contact-safety governance, provider authorization, execution-disabled state,
candidate merge state, and receipt refs. They must not execute retrieval, call
providers, write DB records, mutate candidates or artifacts, mutate workflow
state, write memory, inject hidden context, or become planner semantic
authority. Diagnostic payloads must suppress raw private/contact-sensitive
fields including contact values, queries, raw provider results, source refs,
citations, provider payloads, and rendered context.

`search_api` is a provider-neutral external discovery declaration, distinct from
`cloud_web`/cloud-AI provider semantics. It is declaration-only unless an
adapter is explicitly dry-run/mock gated or otherwise authorized by a task. The
shared contract records provider ID/type, governance, free-tier and cost
metadata, query/result bounds, timeouts, and source-reference requirements, but
does not itself authorize live provider calls. Search API output is raw
`search_api_result_set` data with URLs, source refs, citations, external-call
status, dry-run status, cost status, and provenance. Models may summarize only
after source normalization, and Alexis-specific newsroom semantics remain owned
by Alexis after the generic search result artifact boundary.

Retrieval-to-newsroom synthesis is an explicit agent-local semantic boundary.
Raw retrieval artifacts such as `search_api_result_set`,
`external_search_result_set`, and `external_discovery_result_set` may not become
newsroom synthesis artifacts and may not lend planner or runtime semantic
authority to synthesis. Alexis newsroom synthesis may consume only normalized
source items, source refs, citations, and retrieval lineage refs across this
boundary. The resulting synthesis artifact must carry a
`retrieval_synthesis_boundary` record that states raw retrieval payloads and
provider final prose did not cross, source grounding was preserved, semantic
authority was not inherited, and delivery was not performed.

Latest-news fallback order is declarative: `rss_first`, then `search_api`, then
`cloud_web_deep_premium`. The premium cloud web tier is not active by default
and is not an execution path. It requires explicit governance, source fidelity,
source references, citations, cost awareness, and prior inadequacy from both
RSS and search_api before it can be considered by a later governed stage.

RSS-first live-retrieval escalation is governed separately from fallback
eligibility. RSS inadequacy may prepare a fallback handoff, but it does not by
itself authorize an external live call. The
`rss_external_live_retrieval_governance` artifact records the policy decision,
explicit-live-request requirement, channel/user checks, provider live-governance
requirements, source-reference/citation/cost requirements, and fail-closed
reasons while preserving `external_call_performed=false` until an execution
stage is explicitly authorized.

RSS-to-external-search handoff is an explicit typed boundary. The
`rss_external_search_handoff` artifact may prepare a canonical provider-free
`external_search` request only after RSS coverage is inadequate and RSS external
live-retrieval governance allows escalation. It is not execution: it records
`handoff_is_execution=false`, `external_call_performed=false`, no provider
fields, and bounded query materialization provenance. Adequate RSS coverage,
unknown RSS adequacy, or governance-blocked escalation must produce an
ineligible handoff with reason codes and no prepared request. Query
materialization is bounded to one query from already-normalized RSS topic/entity
focus, with an auditable default when no focus exists; runtime/context systems
must not reinterpret user intent at this boundary.

## Architectural Principles

- No keyword patches as primary architecture.
- Semantics should be registry/config-driven where possible.
- Actions are not artifacts.
- Transforms preserve artifact identity.
- Conversion changes artifact identity intentionally.
- Planning is operation-aware.
- Execution planning must not reinterpret semantics already normalized by the gate/planner.
- Validators enforce contracts; they do not infer semantics.
- Attachment boundaries are explicit.
- Workflow actions bypass artifact validation.
- Models generate candidates; runtime owns semantic authority.

## Current Known Future Directions

- Multi-step planning for workflows that need decomposition.
- Research/synthesis decomposition for richer information tasks.
- Richer neutral prose handling without making neutral prose a global fallback.
- Workflow graphs for multi-action approval and execution.
- Planner decomposition into smaller, more inspectable planning stages.

## Current Runtime Flow

1. Request enters the runtime.
2. Request gate classifies interaction mode, operation, attachment needs, and explicit artifact type when present.
3. Context resolution rewrites dependent follow-ups or leaves standalone requests alone.
4. Request planning attaches active artifacts only when allowed, resolves transform type for artifact operations, and carries semantic artifact type forward.
5. Execution planning sets expected output type, semantic output type, engine, and fallback policy.
6. Skill loading builds the agent prompt using operation-aware semantic state.
7. Execution runs the selected model/engine and returns a candidate.
8. Response pipeline normalizes artifact or structured action output.
9. Validation enforces artifact or semantic contracts where applicable.
10. Actions are parsed, validated against capabilities, and queued for approval when required.
11. Artifact results are persisted when configured.
12. The final response is returned.
