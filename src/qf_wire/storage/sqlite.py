"""SQLite 归档：运行记录、条目、事件、提炼结果与信源状态。

使用 SQLAlchemy 2.x 管理连接，结构演进由 storage/migrations/*.sql 负责。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

from qf_wire.core.cleaner import parse_datetime
from qf_wire.core.models import (
    DigestItem,
    Event,
    KeyPoint,
    SourceItem,
    TopicDigest,
)
from qf_wire.logging.setup import get_logger
from qf_wire.sources.base import FetchResult

logger = get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
MIGRATION_LOCK = threading.Lock()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _day(value: date | str) -> str:
    return value.isoformat() if isinstance(value, date) else str(value)


def split_sql(script: str) -> list[str]:
    """按完整语句切分 SQL 文件，跳过纯注释行。"""
    statements: list[str] = []
    buffer = ""
    for line in script.splitlines(keepends=True):
        if line.lstrip().startswith("--") and not buffer.strip():
            buffer = ""
            continue
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                statements.append(statement)
            buffer = ""
    if buffer.strip():
        statements.append(buffer.strip())
    return statements


def _enable_sqlite_pragmas(target: Engine) -> None:
    @event.listens_for(target, "connect")
    def _set_pragmas(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=30000")
        finally:
            cursor.close()


class WireStore:
    """本地 SQLite 存储；所有写入幂等（同一天重复运行会覆盖同 URL 条目）。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            future=True,
            connect_args={"timeout": 30},
        )
        _enable_sqlite_pragmas(self.engine)
        self._ready = False

    # ---- 初始化与迁移 ----
    def initialize(self) -> None:
        if self._ready:
            return
        with MIGRATION_LOCK:
            if self._ready:
                return
            with self.engine.begin() as conn:
                conn.exec_driver_sql(
                    "CREATE TABLE IF NOT EXISTS schema_migrations ("
                    "version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
                )
                applied = {
                    row[0]
                    for row in conn.exec_driver_sql("SELECT version FROM schema_migrations")
                }
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                version = path.stem
                if version in applied:
                    continue
                self._apply_migration(path, version)
            self._ready = True

    def _apply_migration(self, path: Path, version: str) -> None:
        script = path.read_text(encoding="utf-8")
        with self.engine.begin() as conn:
            for statement in split_sql(script):
                conn.exec_driver_sql(statement)
            conn.execute(
                text("INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (:v, :t)"),
                {"v": version, "t": datetime.now(timezone.utc).isoformat()},
            )
        logger.info("已应用数据库迁移 %s", version)

    def close(self) -> None:
        self.engine.dispose()
        self._ready = False

    # ---- 写入 ----
    def record_run(
        self,
        *,
        run_id: str,
        day: date | str,
        topic: str | None,
        mode: str,
        status: str,
        exit_code: int,
        started_at: datetime,
        finished_at: datetime,
        results: list[FetchResult],
        items_by_topic: dict[str, list[SourceItem]],
        events_by_topic: dict[str, list[Event]],
        digests: Iterable[TopicDigest] = (),
    ) -> None:
        self.initialize()
        day_text = _day(day)
        all_items = [item for group in items_by_topic.values() for item in group]
        ok = sum(1 for result in results if result.status == "ok")
        degraded = sum(1 for result in results if result.status == "degraded")
        unavailable = sum(1 for result in results if result.status == "unavailable")
        now = datetime.now(timezone.utc)

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO runs (run_id, started_at, finished_at, day, topic, mode, status, "
                    "exit_code, source_total, source_ok, source_degraded, source_unavailable, item_count) "
                    "VALUES (:run_id, :started_at, :finished_at, :day, :topic, :mode, :status, "
                    ":exit_code, :source_total, :source_ok, :source_degraded, :source_unavailable, :item_count)"
                ),
                {
                    "run_id": run_id,
                    "started_at": _iso(started_at),
                    "finished_at": _iso(finished_at),
                    "day": day_text,
                    "topic": topic,
                    "mode": mode,
                    "status": status,
                    "exit_code": exit_code,
                    "source_total": len(results),
                    "source_ok": ok,
                    "source_degraded": degraded,
                    "source_unavailable": unavailable,
                    "item_count": len(all_items),
                },
            )

            for result in results:
                conn.execute(
                    text(
                        "INSERT INTO source_status (run_id, day, source_id, source_name, topic, status, "
                        "error, item_count, attempts, elapsed_ms, fetched_at) VALUES "
                        "(:run_id, :day, :source_id, :source_name, :topic, :status, :error, :item_count, "
                        ":attempts, :elapsed_ms, :fetched_at) "
                        "ON CONFLICT(day, source_id) DO UPDATE SET "
                        "run_id=excluded.run_id, source_name=excluded.source_name, topic=excluded.topic, "
                        "status=excluded.status, error=excluded.error, item_count=excluded.item_count, "
                        "attempts=excluded.attempts, elapsed_ms=excluded.elapsed_ms, "
                        "fetched_at=excluded.fetched_at"
                    ),
                    {
                        "run_id": run_id,
                        "day": day_text,
                        "source_id": result.source_id,
                        "source_name": result.source_name,
                        "topic": result.topic,
                        "status": result.status,
                        "error": result.error,
                        "item_count": result.item_count,
                        "attempts": result.attempts,
                        "elapsed_ms": result.elapsed_ms,
                        "fetched_at": _iso(result.fetched_at),
                    },
                )

            for topic_id, items in items_by_topic.items():
                for item in items:
                    conn.execute(
                        text(
                            "INSERT INTO items (day, topic, title, url, source_id, sources, summary, zh, "
                            "published_at, event_id, confidence, fetched_at) VALUES "
                            "(:day, :topic, :title, :url, :source_id, :sources, :summary, :zh, "
                            ":published_at, :event_id, :confidence, :fetched_at) "
                            "ON CONFLICT(day, url) DO UPDATE SET "
                            "topic=excluded.topic, title=excluded.title, source_id=excluded.source_id, "
                            "sources=excluded.sources, summary=excluded.summary, zh=excluded.zh, "
                            "published_at=excluded.published_at, event_id=excluded.event_id, "
                            "confidence=excluded.confidence"
                        ),
                        {
                            "day": day_text,
                            "topic": topic_id,
                            "title": item.title,
                            "url": item.url,
                            "source_id": item.source_id,
                            "sources": json.dumps(item.sources, ensure_ascii=False),
                            "summary": item.summary,
                            "zh": item.zh,
                            "published_at": _iso(item.published_at),
                            "event_id": item.event_id,
                            "confidence": item.confidence,
                            "fetched_at": _iso(now),
                        },
                    )

            for events in events_by_topic.values():
                for evt in events:
                    conn.execute(
                        text(
                            "INSERT INTO events (event_id, topic, day, title, sources, source_count, "
                            "confidence, first_seen, last_seen, updated_at) VALUES "
                            "(:event_id, :topic, :day, :title, :sources, :source_count, :confidence, "
                            ":first_seen, :last_seen, :updated_at) "
                            "ON CONFLICT(event_id) DO UPDATE SET day=excluded.day, title=excluded.title, "
                            "sources=excluded.sources, source_count=excluded.source_count, "
                            "confidence=excluded.confidence, first_seen=excluded.first_seen, "
                            "last_seen=excluded.last_seen, updated_at=excluded.updated_at"
                        ),
                        {
                            "event_id": evt.event_id,
                            "topic": evt.topic,
                            "day": day_text,
                            "title": evt.title,
                            "sources": json.dumps(evt.sources, ensure_ascii=False),
                            "source_count": evt.source_count,
                            "confidence": evt.confidence,
                            "first_seen": _iso(evt.first_seen),
                            "last_seen": _iso(evt.last_seen),
                            "updated_at": _iso(now),
                        },
                    )

            for digest in digests:
                self._save_digest(conn, digest)

    def save_digest(self, digest: TopicDigest) -> None:
        self.initialize()
        with self.engine.begin() as conn:
            self._save_digest(conn, digest)

    @staticmethod
    def _save_digest(conn: Any, digest: TopicDigest) -> None:
        conn.execute(
            text(
                "INSERT INTO digests (topic, day, summary, key_points, items, provider, model, partial, "
                "status, error, fallback, generated_at) VALUES "
                "(:topic, :day, :summary, :key_points, :items, :provider, :model, :partial, :status, "
                ":error, :fallback, :generated_at) "
                "ON CONFLICT(topic, day) DO UPDATE SET summary=excluded.summary, "
                "key_points=excluded.key_points, items=excluded.items, provider=excluded.provider, "
                "model=excluded.model, partial=excluded.partial, status=excluded.status, "
                "error=excluded.error, fallback=excluded.fallback, generated_at=excluded.generated_at"
            ),
            {
                "topic": digest.topic,
                "day": _day(digest.date),
                "summary": digest.summary,
                "key_points": json.dumps(
                    [point.model_dump(mode="json") for point in digest.key_points],
                    ensure_ascii=False,
                ),
                "items": json.dumps(
                    [item.model_dump(mode="json") for item in digest.items],
                    ensure_ascii=False,
                ),
                "provider": digest.provider,
                "model": digest.model,
                "partial": int(digest.partial),
                "status": digest.status,
                "error": digest.error,
                "fallback": int(digest.fallback),
                "generated_at": _iso(digest.generated_at or datetime.now(timezone.utc)),
            },
        )

    # ---- 查询 ----
    def count_items(self, day: date | str, topic: str | None = None) -> int:
        self.initialize()
        sql = "SELECT COUNT(*) FROM items WHERE day = :day"
        params: dict[str, Any] = {"day": _day(day)}
        if topic:
            sql += " AND topic = :topic"
            params["topic"] = topic
        with self.engine.connect() as conn:
            return int(conn.execute(text(sql), params).scalar_one())

    def items_for_day(self, day: date | str, topic: str | None = None) -> dict[str, list[SourceItem]]:
        self.initialize()
        sql = "SELECT topic, title, url, source_id, sources, summary, zh, published_at, event_id, confidence FROM items WHERE day = :day"
        params: dict[str, Any] = {"day": _day(day)}
        if topic:
            sql += " AND topic = :topic"
            params["topic"] = topic
        sql += " ORDER BY COALESCE(published_at, '') DESC, id DESC"
        result: dict[str, list[SourceItem]] = {}
        with self.engine.connect() as conn:
            for row in conn.execute(text(sql), params).mappings():
                item = SourceItem(
                    title=row["title"],
                    url=row["url"],
                    source_id=row["source_id"] or "",
                    topic=row["topic"],
                    summary=row["summary"] or "",
                    zh=row["zh"] or "",
                    published_at=parse_datetime(row["published_at"]),
                    sources=json.loads(row["sources"] or "[]"),
                    event_id=row["event_id"],
                    confidence=row["confidence"] or "medium",
                )
                result.setdefault(row["topic"], []).append(item)
        return result

    def latest_day(self) -> str | None:
        self.initialize()
        with self.engine.connect() as conn:
            value = conn.execute(text("SELECT MAX(day) FROM items")).scalar()
        return str(value) if value else None

    def get_digest(self, topic: str, day: date | str) -> TopicDigest | None:
        self.initialize()
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM digests WHERE topic = :topic AND day = :day"),
                {"topic": topic, "day": _day(day)},
            ).mappings().first()
        return self._row_to_digest(row) if row else None

    def digests_for_day(self, day: date | str) -> dict[str, TopicDigest]:
        self.initialize()
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("SELECT * FROM digests WHERE day = :day"),
                {"day": _day(day)},
            ).mappings()
            return {row["topic"]: self._row_to_digest(row) for row in rows}

    @staticmethod
    def _row_to_digest(row: Any) -> TopicDigest:
        key_points = [KeyPoint(**value) for value in json.loads(row["key_points"] or "[]")]
        items = [DigestItem(**value) for value in json.loads(row["items"] or "[]")]
        return TopicDigest(
            topic=row["topic"],
            date=parse_datetime(row["day"]).date() if parse_datetime(row["day"]) else date.today(),
            summary=row["summary"] or "",
            key_points=key_points,
            items=items,
            generated_at=parse_datetime(row["generated_at"]),
            provider=row["provider"],
            model=row["model"],
            partial=bool(row["partial"]),
            status=row["status"],
            error=row["error"],
            fallback=bool(row["fallback"]),
        )

    def events_for_topic(
        self,
        topic: str | None = None,
        day: date | str | None = None,
        limit: int = 50,
    ) -> list[Event]:
        self.initialize()
        sql = "SELECT * FROM events WHERE 1 = 1"
        params: dict[str, Any] = {"limit": limit}
        if topic:
            sql += " AND topic = :topic"
            params["topic"] = topic
        if day:
            sql += " AND day = :day"
            params["day"] = _day(day)
        sql += " ORDER BY COALESCE(last_seen, updated_at) DESC LIMIT :limit"
        with self.engine.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
            return [self._row_to_event(conn, row) for row in rows]

    def get_event(self, event_id: str) -> Event | None:
        self.initialize()
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM events WHERE event_id = :event_id"),
                {"event_id": event_id},
            ).mappings().first()
            if not row:
                return None
            return self._row_to_event(conn, row)

    def event_timeline(self, event_id: str) -> list[SourceItem]:
        self.initialize()
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT topic, title, url, source_id, sources, summary, zh, published_at, "
                    "event_id, confidence FROM items WHERE event_id = :event_id "
                    "ORDER BY COALESCE(published_at, '') ASC, id ASC"
                ),
                {"event_id": event_id},
            ).mappings()
            return [
                SourceItem(
                    title=row["title"],
                    url=row["url"],
                    source_id=row["source_id"] or "",
                    topic=row["topic"],
                    summary=row["summary"] or "",
                    zh=row["zh"] or "",
                    published_at=parse_datetime(row["published_at"]),
                    sources=json.loads(row["sources"] or "[]"),
                    event_id=row["event_id"],
                    confidence=row["confidence"] or "medium",
                )
                for row in rows
            ]

    @staticmethod
    def _row_to_event(conn: Any, row: Any) -> Event:
        items = []
        for item_row in conn.execute(
            text(
                "SELECT topic, title, url, source_id, sources, summary, zh, published_at, "
                "event_id, confidence FROM items WHERE event_id = :event_id "
                "ORDER BY COALESCE(published_at, '') DESC, id DESC"
            ),
            {"event_id": row["event_id"]},
        ).mappings():
            items.append(
                SourceItem(
                    title=item_row["title"],
                    url=item_row["url"],
                    source_id=item_row["source_id"] or "",
                    topic=item_row["topic"],
                    summary=item_row["summary"] or "",
                    zh=item_row["zh"] or "",
                    published_at=parse_datetime(item_row["published_at"]),
                    sources=json.loads(item_row["sources"] or "[]"),
                    event_id=item_row["event_id"],
                    confidence=item_row["confidence"] or "medium",
                )
            )
        return Event(
            event_id=row["event_id"],
            topic=row["topic"],
            title=row["title"],
            items=items,
            sources=json.loads(row["sources"] or "[]"),
            source_count=int(row["source_count"] or 0),
            confidence=row["confidence"] or "medium",
            first_seen=parse_datetime(row["first_seen"]),
            last_seen=parse_datetime(row["last_seen"]),
        )

    def source_status(self, day: date | str | None = None) -> list[dict[str, Any]]:
        self.initialize()
        day_text = _day(day) if day else self.latest_source_day()
        if not day_text:
            return []
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT source_id, source_name, topic, status, error, item_count, attempts, "
                    "elapsed_ms, fetched_at FROM source_status WHERE day = :day ORDER BY source_id"
                ),
                {"day": day_text},
            ).mappings()
            return [dict(row) for row in rows]

    def latest_source_day(self) -> str | None:
        self.initialize()
        with self.engine.connect() as conn:
            value = conn.execute(text("SELECT MAX(day) FROM source_status")).scalar()
        return str(value) if value else None

    def history(
        self,
        topic: str | None = None,
        days: int = 7,
        end_day: date | str | None = None,
    ) -> list[dict[str, Any]]:
        """按天返回条目数、事件数、提炼数与前后日增量。"""
        self.initialize()
        end = parse_datetime(end_day).date() if isinstance(end_day, str) else (end_day or date.today())
        start = end - timedelta(days=days - 1)
        previous_start = start - timedelta(days=1)
        counts = {
            day_text: self._day_counts(day_text, topic)
            for day_text in self._date_range(previous_start, end)
        }
        result: list[dict[str, Any]] = []
        current = start
        while current <= end:
            key = current.isoformat()
            previous = (current - timedelta(days=1)).isoformat()
            counts_current = counts.get(key, self._empty_counts())
            counts_previous = counts.get(previous) or self._empty_counts()
            result.append(
                {
                    "date": key,
                    "items": counts_current["items"],
                    "events": counts_current["events"],
                    "digests": counts_current["digests"],
                    "source_ok": counts_current["source_ok"],
                    "source_degraded": counts_current["source_degraded"],
                    "source_unavailable": counts_current["source_unavailable"],
                    "item_delta": counts_current["items"] - counts_previous["items"],
                    "digest_delta": counts_current["digests"] - counts_previous["digests"],
                }
            )
            current += timedelta(days=1)
        return result

    @staticmethod
    def _date_range(start: date, end: date) -> list[str]:
        days: list[str] = []
        current = start
        while current <= end:
            days.append(current.isoformat())
            current += timedelta(days=1)
        return days

    def _day_counts(self, day_text: str, topic: str | None) -> dict[str, int]:
        with self.engine.connect() as conn:
            item_sql = "SELECT COUNT(*) FROM items WHERE day = :day"
            event_sql = "SELECT COUNT(*) FROM events WHERE day = :day"
            digest_sql = "SELECT COUNT(*) FROM digests WHERE day = :day"
            source_sql = (
                "SELECT status, COUNT(*) AS total FROM source_status WHERE day = :day GROUP BY status"
            )
            params: dict[str, Any] = {"day": day_text}
            if topic:
                item_sql += " AND topic = :topic"
                event_sql += " AND topic = :topic"
                digest_sql += " AND topic = :topic"
                source_sql = (
                    "SELECT status, COUNT(*) AS total FROM source_status "
                    "WHERE day = :day AND topic = :topic GROUP BY status"
                )
                params["topic"] = topic
            counts = self._empty_counts()
            counts["items"] = int(conn.execute(text(item_sql), params).scalar_one())
            counts["events"] = int(conn.execute(text(event_sql), params).scalar_one())
            counts["digests"] = int(conn.execute(text(digest_sql), params).scalar_one())
            for row in conn.execute(text(source_sql), params):
                status = row[0]
                if status in {"ok", "degraded", "unavailable"}:
                    counts[f"source_{status}"] = int(row[1])
            return counts

    @staticmethod
    def _empty_counts() -> dict[str, int]:
        return {
            "items": 0,
            "events": 0,
            "digests": 0,
            "source_ok": 0,
            "source_degraded": 0,
            "source_unavailable": 0,
        }
