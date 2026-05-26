# Proposed Public Repository Structure

This document proposes a curated public GitHub structure for Juniper as a technical portfolio project. It is not a publication plan and does not move files.

## Publication Approach

Use a fresh public repository or orphan branch assembled from an allowlist. Do not publish the current repository history because tracked files include secrets, private data, generated traces, and operator-owned artifacts.

## Include

```text
juniper/
  README.md
  LICENSE
  requirements.txt
  docs/
    semantic_runtime_architecture.md
    juniper_semantic_authority_map.md
    juniper_topology_bible.md
    bounded_context_injection.md
    binding_context_composition.md
    binding_driven_execution.md
    public_repo_structure.md
  core/
  semantics/
  planner/
  runtime/
  agents/
    shared/
    alexis/
      contracts/
      policies/
      skills/
      workflows/
      normalizers/
      adapters/
    steve/
      ingestion/
      tests/
  gateway/
  runner/
  scripts/
  tools/
    fixtures/
    test_*.py
  tests/
  examples/
    synthetic_guest_lookup/
    typed_artifact_transform/
    governed_external_search/
```

## Include With Review

- `gateway/`
  - Include only source code that reads credentials and IDs from environment variables.
  - Exclude runtime auth state, pending users, allowed users, and real Telegram identifiers.
- `agents/alexis/`
  - Include contracts, skills, workflow code, policies, and adapters.
  - Exclude real guest databases and derived canonical guest data.
- `agents/steve/`
  - Include ingestion architecture and code if examples are synthetic.
  - Exclude operator-owned CVs, resumes, job applications, generated drafts, and derived reports.
- `docs/`
  - Include architecture docs after removing local paths, private workflow notes, and operator-specific material.
- `tools/fixtures/`
  - Include only synthetic fixtures.
  - Prefer `.example.test` email domains and obviously fake phone numbers.

## Exclude

- `.env`, `.env.*`, and any credential-bearing config.
- `.venv/`, `.pytest_cache/`, `.agents/`, `.codex/`, and cache directories.
- `logs/`, `traces/`, `diagnostics/`, `memory/`, `data/`, `archive/`, and generated workflow state.
- `workspace/`, including `workspace/alexis/` and `workspace/steve/`.
- `agents/alexis/adapters/guest_db/resources/raw/`
- `agents/alexis/adapters/guest_db/resources/canonical/`
- `agents/steve/resources/`
- `reports/` and `reports/codex_batches/`, except for hand-authored public audit docs.
- `codex_batches/`
- `juniper_*.txt`, `test_result.txt`, prompt dumps, session dumps, and local transcript exports.
- Real resumes, CVs, cover letters, application materials, guest data, candidate data, emails, phone numbers, Telegram IDs, owner IDs, and private hostnames.

## Public Examples

Create small, explicit examples rather than publishing real operational data:

- `examples/synthetic_guest_lookup/`
  - Tiny synthetic guest records with fake names, `.example.test` emails, and no real phone numbers.
- `examples/typed_artifact_transform/`
  - Demonstrates transform preservation of artifact types.
- `examples/governed_external_search/`
  - Demonstrates authorization and receipt boundaries using a fake provider.
- `examples/context_injection/`
  - Shows bounded context selection with synthetic provenance.

## Documentation Shape

The public README should frame Juniper as:

> A local-first semantic AI orchestration/runtime experiment exploring typed workflows, provenance, contract-driven artifacts, governance, and human-in-the-loop AI systems.

Avoid AGI claims, startup language, autonomous-agent marketing, platform claims, and claims not directly supported by code and tests.

## Validation Before Publication

Run these checks on the sanitized public export:

```bash
git diff --check
rg -n --hidden "(api[_-]?key|secret|token|password|credential|bearer|authorization)" .
rg -n --hidden "([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}|<local-path-pattern>|chat_id|owner_id|telegram)" .
```

Then run a dedicated secret scanner such as `gitleaks` or `trufflehog` on the sanitized export and verify that tests still pass with synthetic fixtures.
