from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any


SOURCE_ITEM_STORE_PATH = Path("logs/source_items.jsonl")
MAX_LATEST_ITEMS = 50
FRESHNESS_STATUS_ADEQUATE = "adequate"
FRESHNESS_STATUS_STALE = "stale"
FRESHNESS_STATUS_INSUFFICIENT_COVERAGE = "insufficient_coverage"
FRESHNESS_STATUS_FETCH_HEALTH_FAILED = "fetch_health_failed"
INSUFFICIENCY_REASON_STALE_SOURCES = "stale_sources"
INSUFFICIENCY_REASON_STALE_ITEMS = "stale_items"
INSUFFICIENCY_REASON_INSUFFICIENT_TOPIC_COVERAGE = (
    "insufficient_topic_coverage"
)
INSUFFICIENCY_REASON_INSUFFICIENT_SOURCE_DIVERSITY = (
    "insufficient_source_diversity"
)
INSUFFICIENCY_REASON_FETCH_HEALTH_FAILED = "fetch_health_failed"


@dataclass(frozen=True)
class SourceFreshnessPolicy:
    max_item_age: timedelta
    max_fetch_age: timedelta
    minimum_fresh_items: int
    minimum_source_count: int

    def to_record(self) -> dict[str, int]:
        return {
            "max_item_age": int(self.max_item_age.total_seconds()),
            "max_fetch_age": int(self.max_fetch_age.total_seconds()),
            "minimum_fresh_items": self.minimum_fresh_items,
            "minimum_source_count": self.minimum_source_count,
        }


@dataclass(frozen=True)
class SourceFreshnessEvaluationResult:
    status: str
    policy: SourceFreshnessPolicy
    evaluated_at: str
    fresh_items: tuple["SourceItem", ...]
    source_refs: tuple[dict[str, str], ...]
    invalid_item_count: int
    stale_item_count: int
    candidate_item_count: int = 0
    topic_matched_item_count: int = 0
    topic_entity_focus: dict[str, tuple[str, ...]] | None = None
    insufficiency_reason: str | None = None

    @property
    def adequate(self) -> bool:
        return self.status == FRESHNESS_STATUS_ADEQUATE

    def to_record(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "adequate": self.adequate,
            "policy": self.policy.to_record(),
            "evaluated_at": self.evaluated_at,
            "fresh_item_count": len(self.fresh_items),
            "source_count": len({item.source_id for item in self.fresh_items}),
            "source_refs": list(self.source_refs),
            "invalid_item_count": self.invalid_item_count,
            "stale_item_count": self.stale_item_count,
            "candidate_item_count": self.candidate_item_count,
            "topic_matched_item_count": self.topic_matched_item_count,
            "topic_entity_focus": (
                {
                    key: list(value)
                    for key, value in self.topic_entity_focus.items()
                }
                if self.topic_entity_focus
                else None
            ),
            "insufficiency_reason": self.insufficiency_reason,
        }


@dataclass(frozen=True)
class SourceItem:
    item_id: str
    source_ref_id: str
    source_id: str
    title: str
    link: str
    published: str
    fetched_at: str
    provenance: dict[str, str]
    source_governance: dict[str, str]

    def to_record(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "source_ref_id": self.source_ref_id,
            "source_id": self.source_id,
            "title": self.title,
            "link": self.link,
            "published": self.published,
            "fetched_at": self.fetched_at,
            "provenance": dict(self.provenance),
            "source_governance": dict(self.source_governance),
        }


def source_item_id(*, source_id: str, title: str, link: str, published: str) -> str:
    identity = "|".join(
        (
            _safe_text(source_id, limit=200),
            _safe_text(link, limit=1000),
            _safe_text(title, limit=500),
            _safe_text(published, limit=200),
        )
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def rss_source_ref_id(*, source_id: str, item_id: str) -> str:
    identity = "|".join(
        (
            "rss_source_item",
            _safe_text(source_id, limit=200),
            _safe_text(item_id, limit=128),
        )
    )
    return f"rss_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}"


def source_item_from_fetch_entry(
    *,
    source_id: str,
    owning_agent: str,
    governance_state: str,
    manifest_path: str,
    title: str,
    link: str,
    published: str,
    fetched_at: str,
) -> SourceItem:
    safe_title = _safe_text(title, limit=500)
    safe_link = _safe_text(link, limit=1000)
    safe_published = _safe_text(published, limit=200)
    safe_source_id = _safe_text(source_id, limit=200)
    item_id = source_item_id(
        source_id=safe_source_id,
        title=safe_title,
        link=safe_link,
        published=safe_published,
    )
    return SourceItem(
        item_id=item_id,
        source_ref_id=rss_source_ref_id(source_id=safe_source_id, item_id=item_id),
        source_id=safe_source_id,
        title=safe_title,
        link=safe_link,
        published=safe_published,
        fetched_at=_safe_text(fetched_at, limit=100),
        provenance={
            "kind": "rss_metadata",
            "owning_agent": _safe_text(owning_agent, limit=100),
            "manifest_path": _safe_text(manifest_path, limit=500),
        },
        source_governance={
            "governance_state": _safe_text(governance_state, limit=50),
            "metadata_storage_allowed": "true",
        },
    )


def append_source_items(
    items: tuple[SourceItem, ...],
    *,
    store_path: str | Path = SOURCE_ITEM_STORE_PATH,
) -> tuple[SourceItem, ...]:
    if not items:
        return ()
    path = Path(store_path)
    existing_ids = {item.item_id for item in load_source_items(path)}
    new_items = tuple(item for item in items if item.item_id not in existing_ids)
    if not new_items:
        return ()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for item in new_items:
            handle.write(
                json.dumps(item.to_record(), sort_keys=True, separators=(",", ":"))
                + "\n"
            )
        handle.flush()
        os.fsync(handle.fileno())
    return new_items


def load_source_items(
    store_path: str | Path = SOURCE_ITEM_STORE_PATH,
) -> tuple[SourceItem, ...]:
    path = Path(store_path)
    if not path.exists():
        return ()
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            item = _item_from_record(value)
            if item is not None:
                items.append(item)
    return tuple(items)


def latest_source_items(
    *,
    store_path: str | Path = SOURCE_ITEM_STORE_PATH,
    max_items: int = 10,
    owning_agent: str | None = None,
    source_id: str | None = None,
    topic_entity_focus: dict[str, Any] | None = None,
) -> tuple[SourceItem, ...]:
    bounded_max = _bounded_max_items(max_items)
    items = load_source_items(store_path)
    if owning_agent:
        items = tuple(
            item
            for item in items
            if item.provenance.get("owning_agent") == owning_agent
        )
    if source_id:
        items = tuple(item for item in items if item.source_id == source_id)
    items = filter_source_items_by_topic_focus(
        items,
        topic_entity_focus=topic_entity_focus,
    )

    by_id: dict[str, SourceItem] = {}
    for item in items:
        current = by_id.get(item.item_id)
        if current is None or _sort_timestamp(item) >= _sort_timestamp(current):
            by_id[item.item_id] = item
    return tuple(
        sorted(
            by_id.values(),
            key=lambda item: (_sort_timestamp(item), item.item_id),
            reverse=True,
        )[:bounded_max]
    )


def evaluate_source_item_freshness(
    items: tuple[SourceItem, ...],
    *,
    policy: SourceFreshnessPolicy | dict[str, Any],
    now: datetime | None = None,
    max_items: int = 10,
    candidate_item_count: int | None = None,
    topic_matched_item_count: int | None = None,
    topic_entity_focus: dict[str, Any] | None = None,
) -> SourceFreshnessEvaluationResult:
    resolved_policy = _coerce_freshness_policy(policy)
    evaluated_at = _normalize_timestamp(now or datetime.now(timezone.utc))
    bounded_max = _bounded_max_items(max_items)
    normalized_focus = normalize_topic_entity_focus(topic_entity_focus)

    fresh_items: list[SourceItem] = []
    stale_item_count = 0
    invalid_item_count = 0
    recent_fetch_seen = False

    evaluated_items = tuple(sorted(
        _dedupe_items(items),
        key=lambda source_item: (_sort_timestamp(source_item), source_item.item_id),
        reverse=True,
    ))

    for item in evaluated_items:
        published = _parse_timestamp(item.published)
        fetched_at = _parse_timestamp(item.fetched_at)
        if published is None or fetched_at is None:
            invalid_item_count += 1
            continue
        item_is_current = _is_within_age(
            published,
            now=evaluated_at,
            max_age=resolved_policy.max_item_age,
        )
        fetch_is_current = _is_within_age(
            fetched_at,
            now=evaluated_at,
            max_age=resolved_policy.max_fetch_age,
        )
        if fetch_is_current:
            recent_fetch_seen = True
        if item_is_current and fetch_is_current:
            fresh_items.append(item)
        else:
            stale_item_count += 1

    bounded_fresh_items = tuple(fresh_items[:bounded_max])
    bounded_source_ref_items = evaluated_items[:bounded_max]
    source_count = len({item.source_id for item in bounded_fresh_items})
    insufficiency_reason = None
    if not recent_fetch_seen and items:
        status = FRESHNESS_STATUS_FETCH_HEALTH_FAILED
        insufficiency_reason = INSUFFICIENCY_REASON_FETCH_HEALTH_FAILED
    elif normalized_focus and len(bounded_fresh_items) < (
        resolved_policy.minimum_fresh_items
    ):
        status = FRESHNESS_STATUS_INSUFFICIENT_COVERAGE
        insufficiency_reason = INSUFFICIENCY_REASON_INSUFFICIENT_TOPIC_COVERAGE
    elif len(bounded_fresh_items) < resolved_policy.minimum_fresh_items:
        if items:
            status = FRESHNESS_STATUS_STALE
            insufficiency_reason = INSUFFICIENCY_REASON_STALE_ITEMS
        else:
            status = FRESHNESS_STATUS_INSUFFICIENT_COVERAGE
            insufficiency_reason = INSUFFICIENCY_REASON_STALE_SOURCES
    elif source_count < resolved_policy.minimum_source_count:
        status = FRESHNESS_STATUS_INSUFFICIENT_COVERAGE
        insufficiency_reason = INSUFFICIENCY_REASON_INSUFFICIENT_SOURCE_DIVERSITY
    else:
        status = FRESHNESS_STATUS_ADEQUATE

    return SourceFreshnessEvaluationResult(
        status=status,
        policy=resolved_policy,
        evaluated_at=evaluated_at.isoformat(),
        fresh_items=bounded_fresh_items,
        source_refs=_source_refs(bounded_source_ref_items),
        invalid_item_count=invalid_item_count,
        stale_item_count=stale_item_count,
        candidate_item_count=(
            candidate_item_count
            if isinstance(candidate_item_count, int)
            and not isinstance(candidate_item_count, bool)
            and candidate_item_count >= 0
            else len(evaluated_items)
        ),
        topic_matched_item_count=(
            topic_matched_item_count
            if isinstance(topic_matched_item_count, int)
            and not isinstance(topic_matched_item_count, bool)
            and topic_matched_item_count >= 0
            else len(evaluated_items)
        ),
        topic_entity_focus=normalized_focus,
        insufficiency_reason=insufficiency_reason,
    )


def evaluate_latest_source_item_freshness(
    *,
    store_path: str | Path = SOURCE_ITEM_STORE_PATH,
    policy: SourceFreshnessPolicy | dict[str, Any],
    max_items: int = 10,
    owning_agent: str | None = None,
    source_id: str | None = None,
    now: datetime | None = None,
    topic_entity_focus: dict[str, Any] | None = None,
) -> SourceFreshnessEvaluationResult:
    normalized_focus = normalize_topic_entity_focus(topic_entity_focus)
    all_items = _candidate_source_items(
        store_path=store_path,
        owning_agent=owning_agent,
        source_id=source_id,
        max_items=MAX_LATEST_ITEMS if not normalized_focus else None,
    )
    items = filter_source_items_by_topic_focus(
        all_items,
        topic_entity_focus=normalized_focus,
    )
    return evaluate_source_item_freshness(
        items,
        policy=policy,
        now=now,
        max_items=max_items,
        candidate_item_count=len(all_items),
        topic_matched_item_count=len(items),
        topic_entity_focus=topic_entity_focus,
    )


def filter_source_items_by_topic_focus(
    items: tuple[SourceItem, ...],
    *,
    topic_entity_focus: dict[str, Any] | None,
) -> tuple[SourceItem, ...]:
    focus = normalize_topic_entity_focus(topic_entity_focus)
    if not focus:
        return items
    return tuple(item for item in items if _source_item_matches_focus(item, focus))


def normalize_topic_entity_focus(
    value: dict[str, Any] | None,
) -> dict[str, tuple[str, ...]] | None:
    if not isinstance(value, dict):
        return None
    topics = _normalized_focus_terms(value.get("topics"))
    entities = _normalized_focus_terms(value.get("entities"))
    if not topics and not entities:
        return None
    return {"topics": topics, "entities": entities}


def _item_from_record(value: dict[str, Any]) -> SourceItem | None:
    required = ("item_id", "source_id", "title", "link", "published", "fetched_at")
    if any(not isinstance(value.get(key), str) for key in required):
        return None
    provenance = value.get("provenance")
    governance = value.get("source_governance")
    if not isinstance(provenance, dict) or not isinstance(governance, dict):
        return None
    item_id = _safe_text(value["item_id"], limit=128)
    source_id = _safe_text(value["source_id"], limit=200)
    source_ref_id = _safe_text(value.get("source_ref_id"), limit=64)
    if not source_ref_id:
        source_ref_id = rss_source_ref_id(source_id=source_id, item_id=item_id)
    return SourceItem(
        item_id=item_id,
        source_ref_id=source_ref_id,
        source_id=source_id,
        title=_safe_text(value["title"], limit=500),
        link=_safe_text(value["link"], limit=1000),
        published=_safe_text(value["published"], limit=200),
        fetched_at=_safe_text(value["fetched_at"], limit=100),
        provenance=_safe_string_map(provenance),
        source_governance=_safe_string_map(governance),
    )


def _sort_timestamp(item: SourceItem) -> datetime:
    return _parse_timestamp(item.published) or _parse_timestamp(item.fetched_at) or (
        datetime.min.replace(tzinfo=timezone.utc)
    )


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_within_age(
    timestamp: datetime,
    *,
    now: datetime,
    max_age: timedelta,
) -> bool:
    return now - timestamp <= max_age


def _coerce_freshness_policy(
    policy: SourceFreshnessPolicy | dict[str, Any],
) -> SourceFreshnessPolicy:
    if isinstance(policy, SourceFreshnessPolicy):
        return policy
    if not isinstance(policy, dict):
        return SourceFreshnessPolicy(
            max_item_age=timedelta(seconds=0),
            max_fetch_age=timedelta(seconds=0),
            minimum_fresh_items=1,
            minimum_source_count=1,
        )
    return SourceFreshnessPolicy(
        max_item_age=_coerce_age(policy.get("max_item_age")),
        max_fetch_age=_coerce_age(policy.get("max_fetch_age")),
        minimum_fresh_items=_coerce_minimum(
            policy.get("minimum_fresh_items"),
        ),
        minimum_source_count=_coerce_minimum(
            policy.get("minimum_source_count"),
        ),
    )


def _coerce_age(value: Any) -> timedelta:
    if isinstance(value, timedelta):
        if value.total_seconds() > 0:
            return value
        return timedelta(seconds=0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return timedelta(seconds=0)
    return timedelta(seconds=max(0, int(value)))


def _coerce_minimum(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 1
    return max(1, value)


def _dedupe_items(items: tuple[SourceItem, ...]) -> tuple[SourceItem, ...]:
    by_id: dict[str, SourceItem] = {}
    for item in items:
        current = by_id.get(item.item_id)
        if current is None or _sort_timestamp(item) >= _sort_timestamp(current):
            by_id[item.item_id] = item
    return tuple(by_id.values())


def _candidate_source_items(
    *,
    store_path: str | Path,
    owning_agent: str | None,
    source_id: str | None,
    max_items: int | None,
) -> tuple[SourceItem, ...]:
    items = load_source_items(store_path)
    if owning_agent:
        items = tuple(
            item
            for item in items
            if item.provenance.get("owning_agent") == owning_agent
        )
    if source_id:
        items = tuple(item for item in items if item.source_id == source_id)

    ordered = tuple(
        sorted(
            _dedupe_items(items),
            key=lambda item: (_sort_timestamp(item), item.item_id),
            reverse=True,
        )
    )
    if max_items is None:
        return ordered
    return ordered[:_bounded_max_items(max_items)]


def _source_item_matches_focus(
    item: SourceItem,
    focus: dict[str, tuple[str, ...]],
) -> bool:
    haystack = _metadata_tokens(
        " ".join(
            (
                item.title,
                item.source_id,
                item.link,
                item.provenance.get("manifest_path", ""),
            )
        )
    )
    if not haystack:
        return False
    return any(
        _contains_term_tokens(haystack, _metadata_tokens(term))
        for terms in focus.values()
        for term in terms
    )


def _normalized_focus_terms(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    terms: list[str] = []
    seen: set[str] = set()
    for item in value:
        normalized = " ".join(_metadata_tokens(item))
        if normalized and normalized not in seen:
            seen.add(normalized)
            terms.append(normalized)
    return tuple(terms[:10])


def _contains_term_tokens(
    haystack: tuple[str, ...],
    term: tuple[str, ...],
) -> bool:
    if not term or len(term) > len(haystack):
        return False
    limit = len(haystack) - len(term) + 1
    for index in range(limit):
        if haystack[index : index + len(term)] == term:
            return True
    return False


def _metadata_tokens(value: Any) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    tokens: list[str] = []
    current: list[str] = []
    for char in value.casefold():
        if char.isalnum():
            current.append(char)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tuple(tokens)


def _source_refs(items: tuple[SourceItem, ...]) -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "item_id": item.item_id,
            "source_ref_id": item.source_ref_id,
            "source_id": item.source_id,
            "source_type": "rss_feed",
            "link": item.link,
            "published": item.published,
            "fetched_at": item.fetched_at,
            "provenance": item.provenance.get("kind", ""),
            "owning_agent": item.provenance.get("owning_agent", ""),
            "manifest_path": item.provenance.get("manifest_path", ""),
        }
        for item in items
    )


def _safe_text(value: Any, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _safe_string_map(value: dict[str, Any]) -> dict[str, str]:
    return {
        str(key): _safe_text(item, limit=500)
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str)
    }


def _bounded_max_items(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return 1
    return min(value, MAX_LATEST_ITEMS)


__all__ = [
    "FRESHNESS_STATUS_ADEQUATE",
    "FRESHNESS_STATUS_FETCH_HEALTH_FAILED",
    "FRESHNESS_STATUS_INSUFFICIENT_COVERAGE",
    "FRESHNESS_STATUS_STALE",
    "INSUFFICIENCY_REASON_FETCH_HEALTH_FAILED",
    "INSUFFICIENCY_REASON_INSUFFICIENT_SOURCE_DIVERSITY",
    "INSUFFICIENCY_REASON_INSUFFICIENT_TOPIC_COVERAGE",
    "INSUFFICIENCY_REASON_STALE_ITEMS",
    "INSUFFICIENCY_REASON_STALE_SOURCES",
    "MAX_LATEST_ITEMS",
    "SOURCE_ITEM_STORE_PATH",
    "SourceFreshnessEvaluationResult",
    "SourceFreshnessPolicy",
    "SourceItem",
    "append_source_items",
    "evaluate_latest_source_item_freshness",
    "evaluate_source_item_freshness",
    "filter_source_items_by_topic_focus",
    "latest_source_items",
    "load_source_items",
    "normalize_topic_entity_focus",
    "rss_source_ref_id",
    "source_item_from_fetch_entry",
    "source_item_id",
]
