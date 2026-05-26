from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from runtime.governance.boundary_terms import (
    CANONICAL_BOUNDARY_TERMINOLOGY_VERSION,
    boundary_terms_policy,
)
from runtime.governance.substrate_boundary import (
    ALLOWED_INFLUENCE_DIRECTIONS,
    CROSS_SUBSTRATE_CONTRACT_ID,
    CROSS_SUBSTRATE_CONTRACTS_PATH,
    PROHIBITED_IMPLICIT_COUPLING_PATHS,
)
from runtime.governance.validator_support import safe_string, unique_values


ROOT = Path(__file__).resolve().parents[2]
CANONICAL_BOUNDARY_TERMS_PATH = Path(
    "agents/shared/contracts/canonical_boundary_terms.json"
)

SEMANTIC_SURFACE_AUDIT_VERSION = "stage172_semantic_surface_audit_v1"
SEMANTIC_SURFACE_AUDIT_DIAGNOSTIC_TYPE = "semantic_surface_area_audit"

_DEFAULT_CANONICAL_CONCEPT_OWNERS = {
    "allowed_influence_direction": "runtime.governance.substrate_boundary",
    "canonical_boundary_terms": "runtime.governance.boundary_terms",
    "prohibited_implicit_coupling_path": "runtime.governance.substrate_boundary",
    "semantic_authority_fields": "runtime.governance.boundary_terms",
    "substrate_state_fields": "runtime.governance.boundary_terms",
}


def build_semantic_surface_area_audit(
    *,
    surfaces: Sequence[Mapping[str, Any]] | None = None,
    source: str = "semantic_surface_area_audit",
    root: Path | str = ROOT,
) -> dict[str, Any]:
    """Build a read-only report for semantic surface-area drift."""
    root_path = Path(root)
    surface_items = (
        _safe_mapping_list(surfaces)
        if surfaces is not None
        else default_semantic_surface_declarations(root=root_path)
    )

    duplicated = detect_duplicated_semantic_concepts(surface_items)
    terminology = detect_terminology_inconsistencies(
        surface_items,
        root=root_path,
    )
    overlaps = detect_overlapping_substrate_rules(
        surface_items,
        root=root_path,
    )
    redundant = detect_redundant_diagnostics(surface_items)

    blocked = _finding_paths(
        {
            "duplicated_semantic_concepts": duplicated,
            "terminology_inconsistencies": terminology,
            "overlapping_substrate_rules": overlaps,
            "redundant_diagnostics": redundant,
        }
    )
    conformant = not blocked

    return {
        "contract_id": SEMANTIC_SURFACE_AUDIT_VERSION,
        "diagnostic_type": SEMANTIC_SURFACE_AUDIT_DIAGNOSTIC_TYPE,
        "source": safe_string(source) or "semantic_surface_area_audit",
        "conformant": conformant,
        "allowed": conformant,
        "content_safe": True,
        "observational_only": True,
        "planner_semantic_authority": False,
        "semantic_reinterpretation_performed": False,
        "hidden_context_injection_performed": False,
        "hidden_orchestration_performed": False,
        "memory_write_performed": False,
        "checked_surface_count": len(surface_items),
        "duplicated_semantic_concepts": duplicated,
        "terminology_inconsistencies": terminology,
        "overlapping_substrate_rules": overlaps,
        "redundant_diagnostics": redundant,
        "blocked_fields": blocked,
        "skipped_reasons": ([] if conformant else ["semantic_surface_area_drift"]),
        "reason": (
            "Semantic surface declarations are canonical and non-overlapping."
            if conformant
            else "Semantic surface declarations contain duplicated concepts or drift."
        ),
    }


def default_semantic_surface_declarations(
    *,
    root: Path | str = ROOT,
) -> list[dict[str, Any]]:
    policy = boundary_terms_policy()
    canonical_terms = policy["canonical_boundary_terms"]
    aliases = policy["compatibility_aliases"]

    substrate_rules = [
        {
            "source": source,
            "target": target,
            "interaction_type": interaction_type,
        }
        for source, target, interaction_type in sorted(ALLOWED_INFLUENCE_DIRECTIONS)
    ]

    return [
        {
            "surface_id": "canonical_boundary_terms",
            "owner": "runtime.governance.boundary_terms",
            "concepts": [
                {
                    "concept_id": "canonical_boundary_terms",
                    "canonical_owner": "runtime.governance.boundary_terms",
                    "terms": sorted(canonical_terms),
                    "compatibility_aliases": dict(aliases),
                },
                {
                    "concept_id": "semantic_authority_fields",
                    "canonical_owner": "runtime.governance.boundary_terms",
                    "terms": ["semantic_authority_fields"],
                    "compatibility_aliases": {
                        key: value
                        for key, value in aliases.items()
                        if value == "semantic_authority_fields"
                    },
                },
                {
                    "concept_id": "substrate_state_fields",
                    "canonical_owner": "runtime.governance.boundary_terms",
                    "terms": ["substrate_state_fields"],
                },
            ],
            "contract_ids": [CANONICAL_BOUNDARY_TERMINOLOGY_VERSION],
        },
        {
            "surface_id": "cross_substrate_boundary",
            "owner": "runtime.governance.substrate_boundary",
            "concepts": [
                {
                    "concept_id": "allowed_influence_direction",
                    "canonical_owner": "runtime.governance.substrate_boundary",
                    "terms": ["allowed_influence_direction"],
                },
                {
                    "concept_id": "prohibited_implicit_coupling_path",
                    "canonical_owner": "runtime.governance.substrate_boundary",
                    "terms": ["prohibited_implicit_coupling_path"],
                },
            ],
            "substrate_rules": substrate_rules,
            "prohibited_substrate_rules": sorted(PROHIBITED_IMPLICIT_COUPLING_PATHS),
            "contract_ids": [CROSS_SUBSTRATE_CONTRACT_ID],
        },
        {
            "surface_id": "shared_contracts",
            "owner": "agents.shared.contracts",
            "concept_references": [
                "canonical_boundary_terms",
                "allowed_influence_direction",
                "prohibited_implicit_coupling_path",
            ],
            "contract_ids": [
                CANONICAL_BOUNDARY_TERMINOLOGY_VERSION,
                CROSS_SUBSTRATE_CONTRACT_ID,
            ],
        },
    ]


def detect_duplicated_semantic_concepts(
    surfaces: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    declarations: dict[str, list[dict[str, str]]] = {}
    references: dict[str, list[str]] = {}

    for surface in surfaces:
        owner = _owner(surface)
        for concept in _concepts(surface):
            concept_id = safe_string(concept.get("concept_id"))
            if not concept_id:
                continue
            declarations.setdefault(concept_id, []).append(
                {
                    "owner": owner,
                    "surface_id": _surface_id(surface),
                    "canonical_owner": safe_string(concept.get("canonical_owner"))
                    or _DEFAULT_CANONICAL_CONCEPT_OWNERS.get(concept_id, ""),
                }
            )
        for reference in _text_list(surface.get("concept_references")):
            references.setdefault(reference, []).append(owner)

    findings: list[dict[str, Any]] = []
    for concept_id, items in sorted(declarations.items()):
        owners = unique_values([item["owner"] for item in items])
        canonical_owners = unique_values(
            [item["canonical_owner"] for item in items if item["canonical_owner"]]
        )
        expected_owner = (
            canonical_owners[0]
            if len(canonical_owners) == 1
            else _DEFAULT_CANONICAL_CONCEPT_OWNERS.get(concept_id)
        )
        duplicate_owners = [
            owner for owner in owners if not expected_owner or owner != expected_owner
        ]
        if len(owners) > 1 and duplicate_owners:
            findings.append(
                {
                    "concept_id": concept_id,
                    "canonical_owner": expected_owner,
                    "declared_owners": owners,
                    "duplicate_owners": duplicate_owners,
                    "referencing_owners": sorted(set(references.get(concept_id, []))),
                    "reason": "Concept has multiple declaring owners instead of shared references.",
                }
            )
    return findings


def detect_terminology_inconsistencies(
    surfaces: Sequence[Mapping[str, Any]],
    *,
    root: Path | str = ROOT,
) -> list[dict[str, Any]]:
    policy = boundary_terms_policy()
    canonical_terms = set(policy["canonical_boundary_terms"])
    aliases = dict(policy["compatibility_aliases"])
    findings: list[dict[str, Any]] = []

    for surface in surfaces:
        owner = _owner(surface)
        for concept in _concepts(surface):
            concept_id = safe_string(concept.get("concept_id"))
            for term in _text_list(concept.get("terms")):
                alias_target = aliases.get(term)
                if (
                    term == concept_id
                    or term in canonical_terms
                    or alias_target == concept_id
                ):
                    continue
                findings.append(
                    {
                        "surface_id": _surface_id(surface),
                        "owner": owner,
                        "concept_id": concept_id,
                        "term": term,
                        "reason": "Term is not canonical and is not a declared compatibility alias.",
                    }
                )
            for alias, target in _mapping_items(concept.get("compatibility_aliases")):
                if target not in canonical_terms:
                    findings.append(
                        {
                            "surface_id": _surface_id(surface),
                            "owner": owner,
                            "concept_id": concept_id,
                            "term": alias,
                            "alias_target": target,
                            "reason": "Compatibility alias points at a non-canonical term.",
                        }
                    )

    findings.extend(_contract_terminology_drift(root=Path(root)))
    return findings


def detect_overlapping_substrate_rules(
    surfaces: Sequence[Mapping[str, Any]],
    *,
    root: Path | str = ROOT,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    seen: dict[tuple[str, str, str], list[str]] = {}

    for surface in surfaces:
        owner = _owner(surface)
        for rule in _rule_list(surface.get("substrate_rules")):
            key = (
                rule.get("source", ""),
                rule.get("target", ""),
                rule.get("interaction_type", ""),
            )
            seen.setdefault(key, []).append(owner)

    for key, owners in sorted(seen.items()):
        unique_owners = sorted(set(owners))
        if len(unique_owners) > 1:
            findings.append(
                {
                    "rule": {
                        "source": key[0],
                        "target": key[1],
                        "interaction_type": key[2],
                    },
                    "declared_owners": unique_owners,
                    "reason": "Substrate influence rule is owned by multiple surfaces.",
                }
            )

    findings.extend(_contract_substrate_rule_drift(root=Path(root)))
    return findings


def detect_redundant_diagnostics(
    surfaces: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    diagnostics: dict[str, list[str]] = {}
    for surface in surfaces:
        owner = _owner(surface)
        for diagnostic_type in _text_list(surface.get("diagnostic_types")):
            diagnostics.setdefault(diagnostic_type, []).append(owner)

    findings: list[dict[str, Any]] = []
    for diagnostic_type, owners in sorted(diagnostics.items()):
        unique_owners = sorted(set(owners))
        if len(unique_owners) > 1:
            findings.append(
                {
                    "diagnostic_type": diagnostic_type,
                    "declared_owners": unique_owners,
                    "reason": "Diagnostic type is declared by multiple surfaces.",
                }
            )
    return findings


@lru_cache(maxsize=None)
def _load_json(path: str) -> Mapping[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, Mapping) else {}


def _contract_terminology_drift(*, root: Path) -> list[dict[str, Any]]:
    path = root / CANONICAL_BOUNDARY_TERMS_PATH
    data = _load_json(str(path))
    policy = boundary_terms_policy()
    policy_terms = set(policy["canonical_boundary_terms"])
    policy_aliases = dict(policy["compatibility_aliases"])
    findings: list[dict[str, Any]] = []

    contract = _contract_by_id(data, CANONICAL_BOUNDARY_TERMINOLOGY_VERSION)
    if not contract:
        return [
            {
                "surface_id": str(CANONICAL_BOUNDARY_TERMS_PATH),
                "owner": "agents.shared.contracts",
                "reason": "Canonical boundary terms contract is missing.",
            }
        ]

    contract_terms = set(_mapping(contract.get("canonical_terms")))
    if contract_terms != policy_terms:
        findings.append(
            {
                "surface_id": str(CANONICAL_BOUNDARY_TERMS_PATH),
                "owner": "agents.shared.contracts",
                "policy_terms": sorted(policy_terms),
                "contract_terms": sorted(contract_terms),
                "reason": "Canonical boundary terminology differs between code and contract.",
            }
        )

    contract_aliases = _mapping(contract.get("compatibility_aliases"))
    if contract_aliases != policy_aliases:
        findings.append(
            {
                "surface_id": str(CANONICAL_BOUNDARY_TERMS_PATH),
                "owner": "agents.shared.contracts",
                "policy_aliases": policy_aliases,
                "contract_aliases": contract_aliases,
                "reason": "Compatibility aliases differ between code and contract.",
            }
        )
    return findings


def _contract_substrate_rule_drift(*, root: Path) -> list[dict[str, Any]]:
    path = root / CROSS_SUBSTRATE_CONTRACTS_PATH
    data = _load_json(str(path))
    contract = _contract_by_id(data, CROSS_SUBSTRATE_CONTRACT_ID)
    if not contract:
        return [
            {
                "surface_id": str(CROSS_SUBSTRATE_CONTRACTS_PATH),
                "owner": "agents.shared.contracts",
                "reason": "Cross-substrate interaction contract is missing.",
            }
        ]

    contract_rules = {
        (
            safe_string(rule.get("source")) or "",
            safe_string(rule.get("target")) or "",
            safe_string(rule.get("interaction_type")) or "",
        )
        for rule in _rule_list(contract.get("allowed_influence_directions"))
    }
    code_rules = set(ALLOWED_INFLUENCE_DIRECTIONS)
    findings: list[dict[str, Any]] = []

    if contract_rules != code_rules:
        findings.append(
            {
                "surface_id": str(CROSS_SUBSTRATE_CONTRACTS_PATH),
                "owner": "agents.shared.contracts",
                "code_rules": _format_rules(code_rules),
                "contract_rules": _format_rules(contract_rules),
                "reason": "Allowed substrate rules differ between code and contract.",
            }
        )

    contract_prohibited = set(_text_list(contract.get("prohibited_implicit_coupling_paths")))
    if contract_prohibited != set(PROHIBITED_IMPLICIT_COUPLING_PATHS):
        findings.append(
            {
                "surface_id": str(CROSS_SUBSTRATE_CONTRACTS_PATH),
                "owner": "agents.shared.contracts",
                "code_rules": sorted(PROHIBITED_IMPLICIT_COUPLING_PATHS),
                "contract_rules": sorted(contract_prohibited),
                "reason": "Prohibited substrate paths differ between code and contract.",
            }
        )
    return findings


def _finding_paths(sections: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[str]:
    paths: list[str] = []
    for section, items in sections.items():
        for index, _item in enumerate(items):
            paths.append(f"{section}[{index}]")
    return paths


def _concepts(surface: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return _safe_mapping_list(surface.get("concepts"))


def _rule_list(value: Any) -> list[dict[str, str]]:
    rules: list[dict[str, str]] = []
    for item in _safe_mapping_list(value):
        source = safe_string(item.get("source"))
        target = safe_string(item.get("target"))
        interaction_type = safe_string(item.get("interaction_type"))
        if source and target and interaction_type:
            rules.append(
                {
                    "source": source,
                    "target": target,
                    "interaction_type": interaction_type,
                }
            )
    return rules


def _safe_mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return unique_values([str(item) for item in value if safe_string(item)])


def _mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): str(item)
        for key, item in value.items()
        if safe_string(key) and safe_string(item)
    }


def _mapping_items(value: Any) -> list[tuple[str, str]]:
    return sorted(_mapping(value).items())


def _contract_by_id(data: Mapping[str, Any], contract_id: str) -> Mapping[str, Any]:
    contracts = data.get("contracts", [])
    if not isinstance(contracts, Sequence) or isinstance(contracts, (str, bytes)):
        return {}
    for contract in contracts:
        if isinstance(contract, Mapping) and contract.get("id") == contract_id:
            return contract
    return {}


def _format_rules(rules: set[tuple[str, str, str]]) -> list[dict[str, str]]:
    return [
        {
            "source": source,
            "target": target,
            "interaction_type": interaction_type,
        }
        for source, target, interaction_type in sorted(rules)
    ]


def _surface_id(surface: Mapping[str, Any]) -> str:
    return safe_string(surface.get("surface_id")) or "unknown_surface"


def _owner(surface: Mapping[str, Any]) -> str:
    return safe_string(surface.get("owner")) or "unknown_owner"


__all__ = [
    "SEMANTIC_SURFACE_AUDIT_DIAGNOSTIC_TYPE",
    "SEMANTIC_SURFACE_AUDIT_VERSION",
    "build_semantic_surface_area_audit",
    "default_semantic_surface_declarations",
    "detect_duplicated_semantic_concepts",
    "detect_overlapping_substrate_rules",
    "detect_redundant_diagnostics",
    "detect_terminology_inconsistencies",
]
