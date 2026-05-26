from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Callable
from urllib.error import URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from runtime.registries.source_ingestion_registry import SourceIngestionDeclaration
from runtime.ingestion.source_audit import (
    SOURCE_INGESTION_AUDIT_LOG_PATH,
    append_source_ingestion_audit_record,
)
from runtime.ingestion.source_item_store import (
    SOURCE_ITEM_STORE_PATH,
    append_source_items,
    source_item_from_fetch_entry,
)


FETCH_STATUS_FETCHED = "fetched"
FETCH_STATUS_SKIPPED = "skipped"
FETCH_STATUS_FAILED = "failed"
MAX_FEED_BYTES = 524288
MAX_FEED_ENTRIES = 20
FETCH_TIMEOUT_SECONDS = 5


class SourceIngestionFetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceFeedEntryMetadata:
    title: str
    link: str
    published: str

    def to_trace(self) -> dict[str, str]:
        return {
            "title": self.title,
            "link": self.link,
            "published": self.published,
        }


@dataclass(frozen=True)
class SourceIngestionFetchResult:
    source_id: str
    source_type: str
    owning_agent: str
    governance_state: str
    fetch_timestamp: str
    fetch_status: str
    fetch_performed: bool
    duration_ms: int
    entry_count: int
    stored_item_count: int
    entries: tuple[SourceFeedEntryMetadata, ...]
    skipped_reasons: tuple[str, ...]

    def to_trace(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "owning_agent": self.owning_agent,
            "governance_state": self.governance_state,
            "fetch_timestamp": self.fetch_timestamp,
            "fetch_status": self.fetch_status,
            "fetch_performed": self.fetch_performed,
            "duration_ms": self.duration_ms,
            "entry_count": self.entry_count,
            "stored_item_count": self.stored_item_count,
            "entries": [entry.to_trace() for entry in self.entries],
            "skipped_reasons": list(self.skipped_reasons),
        }


FetchFunction = Callable[[str, int, int], bytes]


def fetch_declared_rss_source(
    declaration: SourceIngestionDeclaration,
    *,
    fetch_fn: FetchFunction | None = None,
    timeout_seconds: int = FETCH_TIMEOUT_SECONDS,
    max_feed_bytes: int = MAX_FEED_BYTES,
    max_entries: int = MAX_FEED_ENTRIES,
    audit_path: str = str(SOURCE_INGESTION_AUDIT_LOG_PATH),
    item_store_path: str = str(SOURCE_ITEM_STORE_PATH),
    write_audit: bool = True,
    write_items: bool = True,
    now: datetime | None = None,
) -> SourceIngestionFetchResult:
    started_at = perf_counter()
    timestamp = _normalize_timestamp(now or datetime.now(timezone.utc))

    if declaration.governance_state == "disabled":
        return _finalize(
            _result(
                declaration,
                timestamp=timestamp,
                status=FETCH_STATUS_SKIPPED,
                fetch_performed=False,
                duration_ms=_duration_ms(started_at),
                entries=(),
                stored_item_count=0,
                skipped_reasons=("governance_disabled",),
            ),
            audit_path=audit_path,
            write_audit=write_audit,
        )

    if declaration.governance_state not in {"audit_only", "enabled"}:
        return _finalize(
            _result(
                declaration,
                timestamp=timestamp,
                status=FETCH_STATUS_SKIPPED,
                fetch_performed=False,
                duration_ms=_duration_ms(started_at),
                entries=(),
                stored_item_count=0,
                skipped_reasons=("unsupported_governance_state",),
            ),
            audit_path=audit_path,
            write_audit=write_audit,
        )

    if declaration.source_type != "rss_feed":
        return _finalize(
            _result(
                declaration,
                timestamp=timestamp,
                status=FETCH_STATUS_FAILED,
                fetch_performed=False,
                duration_ms=_duration_ms(started_at),
                entries=(),
                stored_item_count=0,
                skipped_reasons=("unsupported_source_type",),
            ),
            audit_path=audit_path,
            write_audit=write_audit,
        )

    try:
        payload = (fetch_fn or _bounded_http_fetch)(
            declaration.url,
            timeout_seconds,
            max_feed_bytes,
        )
        if len(payload) > max_feed_bytes:
            raise SourceIngestionFetchError("feed_response_too_large")
        entries = _parse_rss_metadata(payload, max_entries=max_entries)
    except TimeoutError:
        return _failed(
            declaration,
            timestamp=timestamp,
            started_at=started_at,
            reason="fetch_timeout",
            audit_path=audit_path,
            write_audit=write_audit,
        )
    except (ElementTree.ParseError, UnicodeDecodeError):
        return _failed(
            declaration,
            timestamp=timestamp,
            started_at=started_at,
            reason="malformed_feed",
            audit_path=audit_path,
            write_audit=write_audit,
        )
    except SourceIngestionFetchError as exc:
        return _failed(
            declaration,
            timestamp=timestamp,
            started_at=started_at,
            reason=str(exc) or "fetch_failed",
            audit_path=audit_path,
            write_audit=write_audit,
        )
    except (OSError, URLError):
        return _failed(
            declaration,
            timestamp=timestamp,
            started_at=started_at,
            reason="fetch_failed",
            audit_path=audit_path,
            write_audit=write_audit,
        )

    stored_item_count = _store_fetch_items(
        declaration,
        entries=entries,
        fetched_at=timestamp.isoformat(),
        item_store_path=item_store_path,
        write_items=write_items,
    )
    return _finalize(
        _result(
            declaration,
            timestamp=timestamp,
            status=FETCH_STATUS_FETCHED,
            fetch_performed=True,
            duration_ms=_duration_ms(started_at),
            entries=entries,
            stored_item_count=stored_item_count,
            skipped_reasons=(),
        ),
        audit_path=audit_path,
        write_audit=write_audit,
    )


def fetch_declared_rss_sources(
    declarations: tuple[SourceIngestionDeclaration, ...],
    *,
    fetch_fn: FetchFunction | None = None,
    timeout_seconds: int = FETCH_TIMEOUT_SECONDS,
    max_feed_bytes: int = MAX_FEED_BYTES,
    max_entries: int = MAX_FEED_ENTRIES,
    audit_path: str = str(SOURCE_INGESTION_AUDIT_LOG_PATH),
    item_store_path: str = str(SOURCE_ITEM_STORE_PATH),
    write_audit: bool = True,
    write_items: bool = True,
    now: datetime | None = None,
) -> tuple[SourceIngestionFetchResult, ...]:
    return tuple(
        fetch_declared_rss_source(
            declaration,
            fetch_fn=fetch_fn,
            timeout_seconds=timeout_seconds,
            max_feed_bytes=max_feed_bytes,
            max_entries=max_entries,
            audit_path=audit_path,
            item_store_path=item_store_path,
            write_audit=write_audit,
            write_items=write_items,
            now=now,
        )
        for declaration in declarations
    )


def _bounded_http_fetch(
    url: str,
    timeout_seconds: int,
    max_feed_bytes: int,
) -> bytes:
    request = Request(
        url,
        headers={"User-Agent": "JuniperSourceIngestion/1.0"},
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        payload = response.read(max_feed_bytes + 1)
    if len(payload) > max_feed_bytes:
        raise SourceIngestionFetchError("feed_response_too_large")
    return payload


def _parse_rss_metadata(
    payload: bytes,
    *,
    max_entries: int,
) -> tuple[SourceFeedEntryMetadata, ...]:
    if max_entries < 1:
        return ()
    root = ElementTree.fromstring(payload)
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    if not items:
        raise SourceIngestionFetchError("malformed_feed")

    entries = []
    for item in items[:max_entries]:
        entries.append(
            SourceFeedEntryMetadata(
                title=_entry_text(item, "title"),
                link=_entry_link(item),
                published=(
                    _entry_text(item, "pubDate")
                    or _entry_text(item, "published")
                    or _entry_text(item, "updated")
                ),
            )
        )
    return tuple(entries)


def _entry_text(item: ElementTree.Element, tag: str) -> str:
    direct = item.find(tag)
    if direct is None:
        direct = item.find(f"{{http://www.w3.org/2005/Atom}}{tag}")
    if direct is None or direct.text is None:
        return ""
    return _safe_text(direct.text)


def _entry_link(item: ElementTree.Element) -> str:
    rss_link = _entry_text(item, "link")
    if rss_link:
        return rss_link
    atom_link = item.find("{http://www.w3.org/2005/Atom}link")
    if atom_link is None:
        return ""
    href = atom_link.attrib.get("href")
    return _safe_text(href) if isinstance(href, str) else ""


def _safe_text(value: str) -> str:
    return " ".join(value.split())[:500]


def _failed(
    declaration: SourceIngestionDeclaration,
    *,
    timestamp: datetime,
    started_at: float,
    reason: str,
    audit_path: str,
    write_audit: bool,
) -> SourceIngestionFetchResult:
    return _finalize(
        _result(
            declaration,
            timestamp=timestamp,
            status=FETCH_STATUS_FAILED,
            fetch_performed=False,
            duration_ms=_duration_ms(started_at),
            entries=(),
            stored_item_count=0,
            skipped_reasons=(reason,),
        ),
        audit_path=audit_path,
        write_audit=write_audit,
    )


def _result(
    declaration: SourceIngestionDeclaration,
    *,
    timestamp: datetime,
    status: str,
    fetch_performed: bool,
    duration_ms: int,
    entries: tuple[SourceFeedEntryMetadata, ...],
    stored_item_count: int,
    skipped_reasons: tuple[str, ...],
) -> SourceIngestionFetchResult:
    return SourceIngestionFetchResult(
        source_id=declaration.source_id,
        source_type=declaration.source_type,
        owning_agent=declaration.owning_agent,
        governance_state=declaration.governance_state,
        fetch_timestamp=timestamp.isoformat(),
        fetch_status=status,
        fetch_performed=fetch_performed,
        duration_ms=duration_ms,
        entry_count=len(entries),
        stored_item_count=stored_item_count,
        entries=entries,
        skipped_reasons=skipped_reasons,
    )


def _store_fetch_items(
    declaration: SourceIngestionDeclaration,
    *,
    entries: tuple[SourceFeedEntryMetadata, ...],
    fetched_at: str,
    item_store_path: str,
    write_items: bool,
) -> int:
    if not write_items or not declaration.storage_policy.get(
        "metadata_storage_allowed"
    ):
        return 0
    items = tuple(
        source_item_from_fetch_entry(
            source_id=declaration.source_id,
            owning_agent=declaration.owning_agent,
            governance_state=declaration.governance_state,
            manifest_path=str(declaration.manifest_path),
            title=entry.title,
            link=entry.link,
            published=entry.published,
            fetched_at=fetched_at,
        )
        for entry in entries
    )
    return len(append_source_items(items, store_path=item_store_path))


def _finalize(
    result: SourceIngestionFetchResult,
    *,
    audit_path: str,
    write_audit: bool,
) -> SourceIngestionFetchResult:
    if write_audit:
        append_source_ingestion_audit_record(result, audit_path=audit_path)
    return result


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _duration_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))


__all__ = [
    "FETCH_STATUS_FAILED",
    "FETCH_STATUS_FETCHED",
    "FETCH_STATUS_SKIPPED",
    "FETCH_TIMEOUT_SECONDS",
    "MAX_FEED_BYTES",
    "MAX_FEED_ENTRIES",
    "SourceFeedEntryMetadata",
    "SourceIngestionFetchError",
    "SourceIngestionFetchResult",
    "fetch_declared_rss_sources",
    "fetch_declared_rss_source",
]
