"""运行编排：采集 → 清洗去重 → 事件聚合 → 提炼 → 存储 → 归档 → 看板。

单源失败只标记降级，不中断整体流程。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from qf_wire.config.loader import WireConfig
from qf_wire.core.cleaner import BEIJING_TZ
from qf_wire.core.errors import EXIT_OK, EXIT_PARTIAL, EXIT_UNAVAILABLE
from qf_wire.core.models import Event, Source, SourceItem, Topic, TopicDigest
from qf_wire.logging.setup import get_logger
from qf_wire.pipeline.archive import archive_day
from qf_wire.pipeline.digest import digest_topic
from qf_wire.pipeline.fetch import fetch_many
from qf_wire.pipeline.process import process_items, sort_items
from qf_wire.pipeline.render import build_dashboard_payload, write_data_js
from qf_wire.sources.base import FetchResult
from qf_wire.storage.sqlite import WireStore

logger = get_logger(__name__)


@dataclass(slots=True)
class RunOptions:
    topics: list[Topic]
    sources_only: bool = False
    day: date | None = None
    max_workers: int = 12
    render: bool = True
    archive: bool = True
    persist: bool = True


@dataclass(slots=True)
class RunResult:
    run_id: str
    day: date
    started_at: datetime
    finished_at: datetime
    status: str
    exit_code: int
    sources: list[FetchResult] = field(default_factory=list)
    items_by_topic: dict[str, list[SourceItem]] = field(default_factory=dict)
    events_by_topic: dict[str, list[Event]] = field(default_factory=dict)
    digests: dict[str, TopicDigest] = field(default_factory=dict)
    data_js: Path | None = None
    archive_dir: Path | None = None

    @property
    def item_count(self) -> int:
        return sum(len(items) for items in self.items_by_topic.values())

    @property
    def unavailable_sources(self) -> list[FetchResult]:
        return [result for result in self.sources if result.status == "unavailable"]

    def summary(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "day": self.day.isoformat(),
            "status": self.status,
            "exit_code": self.exit_code,
            "topics": list(self.items_by_topic),
            "items": self.item_count,
            "sources_total": len(self.sources),
            "sources_ok": sum(1 for item in self.sources if item.status == "ok"),
            "sources_degraded": sum(1 for item in self.sources if item.status == "degraded"),
            "sources_unavailable": len(self.unavailable_sources),
            "digests": {
                topic: {"status": digest.status, "fallback": digest.fallback}
                for topic, digest in self.digests.items()
            },
            "data_js": str(self.data_js) if self.data_js else None,
            "archive": str(self.archive_dir) if self.archive_dir else None,
        }


def today_beijing() -> date:
    return datetime.now(BEIJING_TZ).date()


def _unique_sources(config: WireConfig, topics: list[Topic]) -> list[Source]:
    seen: set[str] = set()
    result: list[Source] = []
    for topic in topics:
        for source in config.sources_for(topic):
            if source.id in seen:
                continue
            seen.add(source.id)
            result.append(source)
    return result


def run(config: WireConfig, options: RunOptions) -> RunResult:
    started_at = datetime.now(timezone.utc)
    day = options.day or today_beijing()
    run_id = f"{day.isoformat()}-{uuid.uuid4().hex[:10]}"
    config.paths.ensure()
    selected_topics = options.topics
    sources = _unique_sources(config, selected_topics)

    logger.info(
        "开始运行 %s：%d 个赛道，%d 个信源%s",
        run_id,
        len(selected_topics),
        len(sources),
        "（仅采集）" if options.sources_only else "",
    )
    results: list[FetchResult] = fetch_many(sources, max_workers=options.max_workers) if sources else []

    items_by_topic: dict[str, list[SourceItem]] = {}
    events_by_topic: dict[str, list[Event]] = {}
    for topic in selected_topics:
        topic_results = [result for result in results if result.source_id in topic.sources]
        for result in topic_results:
            for item in result.items:
                item.topic = topic.id
        processed = process_items(topic_results)
        items = sort_items(processed.items)
        items_by_topic[topic.id] = items
        events_by_topic[topic.id] = processed.events
        logger.info(
            "赛道 %s：%d 条资讯，%d 个事件，%d 个源不可用",
            topic.id,
            len(items),
            len(processed.events),
            sum(1 for result in topic_results if result.status == "unavailable"),
        )

    digests: dict[str, TopicDigest] = {}
    if not options.sources_only:
        for topic in selected_topics:
            digests[topic.id] = digest_topic(topic, day, items_by_topic.get(topic.id, []), config)

    exit_code = _exit_code(results)
    status = _run_status(results, digests)
    finished_at = datetime.now(timezone.utc)

    store = WireStore(config.paths.db_path)
    try:
        if options.persist:
            store.record_run(
                run_id=run_id,
                day=day,
                topic=selected_topics[0].id if len(selected_topics) == 1 else None,
                mode="sources-only" if options.sources_only else "full",
                status=status,
                exit_code=exit_code,
                started_at=started_at,
                finished_at=finished_at,
                results=results,
                items_by_topic=items_by_topic,
                events_by_topic=events_by_topic,
                digests=digests.values(),
            )
        archive_path = (
            archive_day(
                config.paths.archive_dir,
                day=day,
                run_id=run_id,
                generated_at=finished_at,
                source_results=results,
                items_by_topic=items_by_topic,
                events_by_topic=events_by_topic,
                digests=digests,
            )
            if options.archive
            else None
        )
        data_js = _render_from_store(config, store, day) if options.render else None
    finally:
        store.close()

    result = RunResult(
        run_id=run_id,
        day=day,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        exit_code=exit_code,
        sources=results,
        items_by_topic=items_by_topic,
        events_by_topic=events_by_topic,
        digests=digests,
        data_js=data_js,
        archive_dir=archive_path,
    )
    logger.info(
        "运行结束 %s：%s，%d 条资讯，退出码 %d",
        run_id,
        status,
        result.item_count,
        exit_code,
    )
    return result


def _exit_code(results: list[FetchResult]) -> int:
    if not results:
        return EXIT_UNAVAILABLE
    unavailable = [result for result in results if result.status == "unavailable"]
    if not unavailable:
        return EXIT_OK
    if len(unavailable) == len(results):
        return EXIT_UNAVAILABLE
    return EXIT_PARTIAL


def _run_status(results: list[FetchResult], digests: dict[str, TopicDigest]) -> str:
    if results and all(result.status == "unavailable" for result in results):
        return "unavailable"
    if any(result.status == "unavailable" for result in results):
        return "partial"
    if any(digest.partial for digest in digests.values()):
        return "partial"
    return "ok"


def render_day(config: WireConfig, store: WireStore, day: date) -> Path:
    """从 SQLite 取当天全部赛道数据，写出 data.js。"""
    return _render_from_store(config, store, day)


def _render_from_store(config: WireConfig, store: WireStore, day: date) -> Path:
    items_by_topic = store.items_for_day(day)
    digests = store.digests_for_day(day)
    events_by_topic = {
        topic.id: store.events_for_topic(topic.id, day) for topic in config.topics
    }
    payload = build_dashboard_payload(
        config.topics,
        items_by_topic,
        digests,
        events_by_topic,
        source_results=None,
        generated_at=datetime.now(timezone.utc),
    )
    status_rows = store.source_status(day)
    payload["sourceStatus"] = [
        {
            "id": row["source_id"],
            "name": row["source_name"],
            "topic": row["topic"],
            "status": row["status"],
            "error": row["error"],
            "itemCount": row["item_count"],
            "attempts": row["attempts"],
            "elapsedMs": row["elapsed_ms"],
        }
        for row in status_rows
    ]
    unavailable = [row for row in status_rows if row["status"] == "unavailable"]
    if unavailable:
        payload["sourceNotice"] = [
            f"{row['source_name'] or row['source_id']}：该源今日不可用" for row in unavailable
        ]
    return write_data_js(config.paths.data_js, payload)


def digest_day(
    config: WireConfig,
    store: WireStore,
    day: date,
    topics: list[Topic],
    render: bool = True,
) -> dict[str, TopicDigest]:
    """对历史某天的已归档数据重新提炼。"""
    items_by_topic = store.items_for_day(day)
    digests: dict[str, TopicDigest] = {}
    for topic in topics:
        items = sort_items(items_by_topic.get(topic.id, []))
        digest = digest_topic(topic, day, items, config)
        store.save_digest(digest)
        digests[topic.id] = digest
        logger.info("赛道 %s 于 %s 重新提炼：%s", topic.id, day, digest.status)
    if render and day == today_beijing():
        render_day(config, store, day)
    return digests


def day_range(end: date, days: int) -> list[date]:
    return [end - timedelta(days=offset) for offset in range(days - 1, -1, -1)]
