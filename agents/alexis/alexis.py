# agents/alexis/alexis.py


import json
from pathlib import Path

from agents.base import BaseAgent

from runtime.actions.parser import parse_agent_output

from .contract_validator import alexis_contract_validator
from runtime.context_builder import RuntimeContextBuilder
from .semantics import classify_guest_semantic_intent

from .context_policy import AlexisContextPolicy
from .adapters.guest_db.exact_entity_lookup_adapter import (
    ALEXIS_GUEST_SOURCE_SCOPE,
    execute_alexis_guest_exact_entity_lookup,
)
from .adapters.guest_db.bounded_entity_search_adapter import (
    execute_alexis_guest_bounded_entity_search,
)
from .adapters.guest_db.semantic_index import build_guest_db_semantic_index
from .tools.guest_db import (
    _load_guests,
    build_context as build_guest_context,
    search_guests,
)
from .workflows.latest_news_workflow import (
    extract_latest_news_topic_focus,
    maybe_run_latest_news_workflow,
)
from .workflows.news_summary_workflow import maybe_run_news_summary_workflow
from .workflows.rss_cache_introspection_workflow import (
    maybe_run_rss_cache_introspection_workflow,
)
from .workflows.guest_workflow_telemetry import (
    build_alexis_guest_workflow_telemetry,
    summarize_alexis_guest_workflow_telemetry,
)
from .workflows.rss_brief_transform import maybe_transform_active_rss_brief
from .workflows.latest_news_workflow import is_latest_news_request
from .workflows.news_summary_workflow import is_news_summary_request
from runtime.registries.source_ingestion_registry import (
    audit_agent_source_ingestion_declarations,
    validate_source_ingestion_readiness,
)
from runtime.workflows.rss_first_gate import RssFirstRoutingResult


DOMAIN_TASKS = {
    "lower_third": {
        "triggers": [
            "lower third",
            "lower-third",
            "chyron",
            "banner",
        ],
    },
    "producer_note": {
        "triggers": [
            "producer note",
            "control room",
            "internal note",
        ],
    },
    "guest_booking": {
        "triggers": [
            "guest",
            "guests",
            "book",
            "booking",
            "outreach",
            "invite",
        ],
    },
    "rewrite": {
        "triggers": [
            "rewrite",
            "shorter",
            "punchier",
            "sharper",
            "tighten",
            "clean up",
        ],
    },
}


class AlexisAgent(BaseAgent):
    name = "alexis"

    agent_root = Path(__file__).resolve().parent
    contract_validator = alexis_contract_validator

    requires_structured_output = True
    output_parser = staticmethod(parse_agent_output)
    context_builder = RuntimeContextBuilder(
        policy=AlexisContextPolicy()
    )
    _load_guests = _load_guests
    search_guests = search_guests
    build_guest_context = build_guest_context

    def __init__(self, workspace_path="workspace/alexis", **kwargs):
        super().__init__(**kwargs)
        self.workspace = Path(workspace_path)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._guest_cache = None
    
    def get_agent_runtime_components(
        self,
        ctx,
        budget,
    ) -> list[str]:
        if not budget.include_guest_context:
            return []

        guests = self.search_guests(
            ctx.user_input
        )

        return self.build_guest_context(
            guests=guests,
        )

    def get_lookup_executor(
        self,
        lookup_request: dict,
        lookup_capability: dict | None = None,
    ):
        if not isinstance(lookup_request, dict):
            return None

        if lookup_capability is not None:
            if not isinstance(lookup_capability, dict):
                return None

            if "guest_db" not in lookup_capability.get("adapter_owners", []):
                return None

            if lookup_request.get("lookup_type") not in lookup_capability.get(
                "supported_lookup_types",
                [],
            ):
                return None

            if lookup_request.get("source_scope") not in lookup_capability.get(
                "source_scopes",
                [],
            ):
                return None

        if lookup_request.get("source_scope") != ALEXIS_GUEST_SOURCE_SCOPE:
            return None

        lookup_type = lookup_request.get("lookup_type")
        if lookup_type == "exact_entity_lookup":
            return execute_alexis_guest_exact_entity_lookup

        if lookup_type == "bounded_entity_search":
            return execute_alexis_guest_bounded_entity_search

        return None

    def handle_local_workflow_request(
        self,
        text: str,
        continuity=None,
        active_artifact=None,
    ):
        rss_cache_introspection = maybe_run_rss_cache_introspection_workflow(
            text=text,
            active_artifact=active_artifact,
        )
        if rss_cache_introspection is not None:
            return rss_cache_introspection

        if active_artifact is not None:
            transformed_brief = maybe_transform_active_rss_brief(
                text=text,
                active_artifact=active_artifact,
            )
            if transformed_brief is not None:
                return transformed_brief

        workflow_request = _resolve_alexis_workflow_request(
            text=text,
            continuity=continuity,
        )
        if _is_alexis_rss_first_request(workflow_request["text"]):
            return None

        return (
            maybe_run_news_summary_workflow(
                text=workflow_request["text"],
                topic_entity_focus=workflow_request["topic_entity_focus"],
            )
            or maybe_run_latest_news_workflow(
                text=workflow_request["text"],
                topic_entity_focus=workflow_request["topic_entity_focus"],
            )
        )

    def handle_local_artifact_transform_request(
        self,
        text: str,
        active_artifact=None,
    ):
        return maybe_transform_active_rss_brief(
            text=text,
            active_artifact=active_artifact,
        )

    def handle_rss_first_workflow_request(self, text: str, continuity=None):
        workflow_request = _resolve_alexis_workflow_request(
            text=text,
            continuity=continuity,
        )
        if not _is_alexis_rss_first_request(workflow_request["text"]):
            return RssFirstRoutingResult(
                applicable=False,
                ready=False,
                reason="Request is outside Alexis RSS-first workflow scope.",
            )

        manifest_ready, manifest_reason, manifest_metadata = (
            _alexis_rss_manifest_readiness(self.agent_root)
        )
        if not manifest_ready:
            return RssFirstRoutingResult(
                applicable=True,
                ready=False,
                reason=manifest_reason,
                workflow_id=_alexis_rss_workflow_id(workflow_request["text"]),
                event_payload=manifest_metadata,
            )

        workflow_result = (
            maybe_run_news_summary_workflow(
                text=workflow_request["text"],
                topic_entity_focus=workflow_request["topic_entity_focus"],
            )
            or maybe_run_latest_news_workflow(
                text=workflow_request["text"],
                topic_entity_focus=workflow_request["topic_entity_focus"],
            )
        )
        if workflow_result is None:
            return RssFirstRoutingResult(
                applicable=False,
                ready=False,
                reason="No Alexis RSS-first workflow matched the request.",
                event_payload=manifest_metadata,
            )

        payload = workflow_result.to_event_payload()
        payload.update(manifest_metadata)
        if not workflow_result.cache_hit:
            return RssFirstRoutingResult(
                applicable=True,
                ready=False,
                reason=(
                    "RSS cache readiness failed: "
                    f"{workflow_result.freshness_status}."
                ),
                workflow_id=workflow_result.workflow_id,
                response=workflow_result.response,
                event_payload=payload,
                artifact=workflow_result.artifact,
            )

        return RssFirstRoutingResult(
            applicable=True,
            ready=True,
            reason="RSS source manifest and cache readiness gates passed.",
            workflow_id=workflow_result.workflow_id,
            response=workflow_result.response,
            event_payload=payload,
            artifact=workflow_result.artifact,
        )

    def classify_semantic_intent(self, text: str):
        return classify_guest_semantic_intent(text)

    def render_direct_response(
        self,
        *,
        direct_response_type: str,
        text: str,
    ) -> str | None:
        if direct_response_type != "capability_summary":
            return None

        return (
            "I can help find and rank potential guests, prepare outreach drafts "
            "when you explicitly ask for drafting or contacting, and help with "
            "Alexis newsroom artifacts like producer notes and lower thirds."
        )

    def materialize_direct_artifact(self, *, semantic_output_type, text, planning):
        if semantic_output_type != "guest_candidate_list":
            return None

        from runtime.registries.provider_binding_registry import (
            get_provider_binding,
        )
        from runtime.workflows.candidate_merge import (
            materialize_guest_candidate_list_merge,
        )
        from runtime.workflows.ranking import (
            materialize_guest_candidate_ranking,
        )
        from runtime.workflows.semantic_guest_retrieval import (
            materialize_semantic_guest_db_retrieval,
        )

        query_text = _guest_discovery_query_text(
            planning=planning,
            fallback=text,
        )
        index = build_guest_db_semantic_index().index
        provider_binding = get_provider_binding(
            "alexis_guest_db",
            agent_name=self.name,
        )
        provider_metadata = (
            provider_binding.to_metadata()
            if provider_binding is not None
            else {}
        )
        retrieved = materialize_semantic_guest_db_retrieval(
            semantic_query={
                "query_text": query_text,
                "max_results": 5,
            },
            guest_semantic_index=index,
            provider_binding_metadata=provider_metadata,
            workflow_id="guest_discovery",
            step_id="candidate_retrieval",
            artifact_ref="artifact:guest_candidate_list:guest_discovery",
        )
        lookup_intent = {
            "query_text": query_text,
            "topic": query_text,
            "topic_text": query_text,
        }
        merged = materialize_guest_candidate_list_merge(
            candidate_artifacts=[retrieved.artifact],
            artifact_refs=["artifact:guest_candidate_list:guest_discovery"],
        ).artifact
        workflow_telemetry = build_alexis_guest_workflow_telemetry(
            candidate_artifact=retrieved.artifact,
            lookup_intent=lookup_intent,
            merge_artifact=merged,
            provider_id="search_api",
            root=str(self.agent_root.parents[1]),
        )
        ranked = materialize_guest_candidate_ranking(
            candidate_artifact=merged,
            input_artifact_ref="artifact:guest_candidate_list:guest_discovery",
        ).artifact

        return {
            "artifact": ranked,
            "response": _render_ranked_guest_candidates(ranked),
            "events": {
                "retrieval": retrieved.to_audit_record(),
                "guest_db_adequacy": (
                    workflow_telemetry["guest_db_adequacy"]
                ),
                "guest_external_discovery_handoff": (
                    workflow_telemetry[
                        "guest_external_discovery_handoff"
                    ]
                ),
                "contact_retrieval_diagnostics": (
                    workflow_telemetry["contact_retrieval_diagnostics"]
                ),
                "guest_workflow_telemetry": (
                    summarize_alexis_guest_workflow_telemetry(
                        workflow_telemetry
                    )
                ),
                "ranking": ranked.get("provenance", {}),
            },
        }


def _guest_discovery_query_text(*, planning, fallback: str) -> str:
    intent = classify_guest_semantic_intent(fallback)
    if intent is not None and intent.topic_text:
        return intent.topic_text

    lookup_metadata = getattr(getattr(planning, "plan", None), "lookup_metadata", None)
    if isinstance(lookup_metadata, dict):
        search_requests = lookup_metadata.get("search_requests")
        if isinstance(search_requests, list):
            for request in search_requests:
                if not isinstance(request, dict):
                    continue
                for key in ("search_topic", "query_intent"):
                    value = request.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()

    return fallback.strip()


def _render_ranked_guest_candidates(artifact: dict) -> str:
    candidates = artifact.get("ranked_candidates")
    if not isinstance(candidates, list) or not candidates:
        return "I found no matching guest candidates in the database."

    lines = ["Guest candidates:"]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        name = candidate.get("display_name") or candidate.get("candidate_id")
        title = candidate.get("title")
        if title:
            lines.append(f"{candidate.get('rank', len(lines))}. {name} — {title}")
        else:
            lines.append(f"{candidate.get('rank', len(lines))}. {name}")

    return "\n".join(lines)


def _is_alexis_rss_first_request(text: str) -> bool:
    return is_news_summary_request(text) or is_latest_news_request(text)


def _resolve_alexis_workflow_request(
    *,
    text: str,
    continuity,
) -> dict:
    explicit_text = text.strip()
    if _is_alexis_rss_first_request(explicit_text):
        latest_news_topic = extract_latest_news_topic_focus(explicit_text)
        return {
            "text": explicit_text,
            "topic_entity_focus": (
                {"topics": [latest_news_topic], "entities": []}
                if latest_news_topic
                else None
            ),
            "continuity_applied": False,
        }

    latest_turn = (
        continuity.latest_turn()
        if continuity is not None and getattr(continuity, "has_turns", False)
        else None
    )
    if latest_turn is None:
        return {
            "text": explicit_text,
            "topic_entity_focus": None,
            "continuity_applied": False,
        }

    prior_request = latest_turn.user_text
    if not _is_alexis_rss_first_request(prior_request):
        return {
            "text": explicit_text,
            "topic_entity_focus": None,
            "continuity_applied": False,
        }

    if _is_alexis_news_brief_followup(explicit_text):
        prior_topic = extract_latest_news_topic_focus(prior_request)
        return {
            "text": "give me a news briefing",
            "topic_entity_focus": (
                {"topics": [prior_topic], "entities": []}
                if prior_topic
                else None
            ),
            "continuity_applied": True,
        }

    focus = _extract_lightweight_topic_focus(explicit_text)
    if not focus:
        return {
            "text": explicit_text,
            "topic_entity_focus": None,
            "continuity_applied": False,
        }

    return {
        "text": prior_request,
        "topic_entity_focus": {"topics": [focus], "entities": []},
        "continuity_applied": True,
    }


def _extract_lightweight_topic_focus(text: str) -> str | None:
    clean = " ".join(text.strip(" \t\r\n?.!;:").split())
    if not clean:
        return None
    if len(clean) > 80 or len(clean.split()) > 8:
        return None

    lowered = clean.casefold()
    prefixes = (
        "what about ",
        "how about ",
        "and what about ",
        "and ",
        "about ",
        "on ",
        "for ",
    )
    for prefix in prefixes:
        if lowered.startswith(prefix):
            clean = clean[len(prefix):].strip(" \t\r\n?.!;:")
            lowered = clean.casefold()
            break

    if not clean or lowered in {"that", "this", "it", "those", "these"}:
        return None

    return clean


def _is_alexis_news_brief_followup(text: str) -> bool:
    normalized = " ".join(
        token.strip(" \t\r\n?.!;:,").casefold()
        for token in text.split()
        if token.strip(" \t\r\n?.!;:,")
    )
    return normalized in {
        "give me the brief",
        "give me a brief",
        "give me the briefing",
        "brief me",
        "the brief",
    }


def _alexis_rss_workflow_id(text: str) -> str:
    if is_news_summary_request(text):
        return "alexis_latest_news_briefing"
    if is_latest_news_request(text):
        return "alexis_latest_news"
    return "alexis_rss_first"


def _alexis_rss_manifest_readiness(agent_root: Path) -> tuple[bool, str, dict]:
    root = agent_root.parents[1]
    declarations, errors = audit_agent_source_ingestion_declarations(
        "alexis",
        root=root,
    )
    readiness_errors = [
        error
        for declaration in declarations
        for error in validate_source_ingestion_readiness(declaration.raw_data)
    ]
    all_errors = (*errors, *readiness_errors)
    metadata = {
        "source_manifest_ready": not all_errors,
        "source_declaration_count": len(declarations),
        "source_readiness_error_count": len(all_errors),
        "source_readiness_errors": [
            {
                "error_code": error.error_code,
                "field": error.field,
                "message": error.message,
            }
            for error in all_errors[:10]
        ],
    }
    if all_errors:
        return False, "RSS source declaration readiness failed.", metadata
    if not declarations:
        return False, "No declared RSS sources are available.", metadata
    if not any(
        declaration.source_type == "rss_feed"
        and declaration.storage_policy.get("metadata_storage_allowed") is True
        for declaration in declarations
    ):
        return (
            False,
            "No declared RSS source allows metadata cache use.",
            metadata,
        )
    return True, "RSS source declaration readiness passed.", metadata
    
