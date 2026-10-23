"""清洗、去重与轻量事件聚合。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from qf_wire.core.cleaner import clean_items
from qf_wire.core.cluster import ClusterSettings, build_events
from qf_wire.core.deduper import dedupe
from qf_wire.core.models import Event, SourceItem
from qf_wire.logging.setup import get_logger
from qf_wire.sources.base import FetchResult

logger = get_logger(__name__)


@dataclass(slots=True)
class ProcessResult:
    items: list[SourceItem]
    events: list[Event]
    raw_count: int
    dropped: int


def collect_items(results: list[FetchResult]) -> list[SourceItem]:
    """汇总成功信源的条目，并补齐 source_id / sources 字段。"""
    collected: list[SourceItem] = []
    for result in results:
        if result.status == "unavailable":
            continue
        for item in result.items:
            sources = list(item.sources)
            if result.source_id and result.source_id not in sources:
                sources.insert(0, result.source_id)
            update: dict[str, object] = {"sources": sources}
            if not item.source_id:
                update["source_id"] = result.source_id
            if not item.topic and result.topic:
                update["topic"] = result.topic
            collected.append(item.model_copy(update=update))
    return collected


def process_items(
    results: list[FetchResult],
    *,
    now: datetime | None = None,
    max_age_days: int = 30,
    cluster: ClusterSettings | None = None,
) -> ProcessResult:
    """清洗 → 去重 → 事件聚合。"""
    raw = collect_items(results)
    cleaned = clean_items(raw, now=now, max_age_days=max_age_days)
    unique = dedupe(cleaned)
    events = build_events(unique, settings=cluster)
    dropped = len(raw) - len(unique)
    if dropped > 0:
        logger.info("清洗去重：原始 %d 条，保留 %d 条（丢弃 %d）", len(raw), len(unique), dropped)
    return ProcessResult(items=unique, events=events, raw_count=len(raw), dropped=dropped)


def sort_items(items: list[SourceItem]) -> list[SourceItem]:
    """按发布时间倒序，无时间条目置后。"""
    return sorted(
        items,
        key=lambda item: item.published_at.timestamp() if item.published_at else 0.0,
        reverse=True,
    )
