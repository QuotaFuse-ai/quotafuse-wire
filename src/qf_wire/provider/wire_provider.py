"""Council Provider 协议实现：只读本地归档，不触发任何采集。"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from qf_wire.config.loader import WireConfig, load_config
from qf_wire.core.models import Event, SourceItem, Topic, WireEnvelope
from qf_wire.logging.setup import get_logger
from qf_wire.pipeline.archive import read_archive_day
from qf_wire.storage.sqlite import WireStore

logger = get_logger(__name__)

WINDOW_PATTERN = re.compile(r"^(\d+)([dh])$")
DEFAULT_WINDOW = "7d"
MAX_EVENTS = 500


class WireProvider:
    """把本地归档包装成 Council 可注册的资讯 Provider。

    所有方法只读；没有数据时返回空 payload 与 ``freshness=archive``，不抛异常。
    参数本身非法（如空关键词、无法解析的窗口）仍抛 ``ValueError``，由 MCP 层转成参数错误。
    """

    name = "wire"
    domains = ("news", "policy", "industry")

    def __init__(
        self,
        config: WireConfig | None = None,
        *,
        config_dir: str | Path | None = None,
        data_dir: str | Path | None = None,
    ) -> None:
        self._config = config
        self._config_dir = config_dir
        self._data_dir = data_dir
        self._store: WireStore | None = None

    @property
    def config(self) -> WireConfig:
        if self._config is None:
            self._config = load_config(self._config_dir, self._data_dir)
        return self._config

    @property
    def db_ready(self) -> bool:
        return self.config.paths.db_path.is_file()

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None

    # ---- 四个只读接口 ----
    def get_digest(self, topic: str, date: date | None = None) -> WireEnvelope:
        requested = str(topic or "").strip()
        resolved = self.config.find_topic(requested)
        if resolved is None:
            return self._empty(domain="news", topic=requested)

        day = date or self._latest_day(resolved.id)
        if day is None:
            return self._empty(domain="news", topic=resolved.id)

        digest = self._digest_for(resolved.id, day)
        items = self._items_for(resolved.id, day)
        if digest is None and not items:
            return self._empty(domain="news", topic=resolved.id, data_as_of=day)

        payload = digest if digest is not None else self._digest_from_items(resolved.id, day, items)
        source_ids = _source_ids(payload)
        status = self._source_status(day, resolved.id)
        if digest is not None and payload.get("status") in {"partial", "failed"}:
            status = "partial"
        return self._make(
            domain="news",
            topic=resolved.id,
            data_as_of=day,
            payload=payload,
            source_detail=",".join(source_ids),
            fetched_at=_payload_fetched_at(payload),
            confidence=self._confidence(resolved.id, day, bool(payload), digest),
            source_status=status,
        )

    def search_events(
        self,
        keyword: str,
        window: str = DEFAULT_WINDOW,
        topic: str | None = None,
    ) -> WireEnvelope:
        text = str(keyword or "").strip()
        if not text:
            raise ValueError("keyword 不能为空")
        delta = parse_window(window)
        resolved = self.config.find_topic(topic) if topic else None
        if topic and resolved is None:
            return self._make(
                domain="news",
                topic=str(topic),
                data_as_of=date.today(),
                payload={"query": text, "events": []},
                confidence="low",
            )

        cutoff = datetime.now(timezone.utc) - delta
        events = [
            event
            for event in self._load_events(resolved.id if resolved else None)
            if _event_matches(event, text) and _event_time(event) >= cutoff
        ]
        events.sort(key=_event_time, reverse=True)
        payload = {
            "query": text,
            "events": [_event_payload(event) for event in events[:MAX_EVENTS]],
        }
        return self._make(
            domain="news",
            topic=resolved.id if resolved else "",
            data_as_of=_latest_event_day(events),
            payload=payload,
            source_detail=",".join(sorted({source for event in events for source in event.sources})),
            fetched_at=_latest_event_time(events),
            confidence="high" if any(event.source_count >= 2 for event in events) else ("medium" if events else "low"),
            source_status=self._source_status(_latest_event_day(events), resolved.id if resolved else None),
        )

    def get_timeline(self, event_id: str) -> WireEnvelope:
        target = str(event_id or "").strip()
        if not target:
            raise ValueError("event_id 不能为空")
        event = self._load_event(target)
        if event is None:
            return self._empty(domain="news", topic="", event_id=target)
        timeline = [
            {
                "published_at": _iso(item.published_at),
                "source": item.source_id or ",".join(item.sources),
                "title": item.title,
                "url": item.url,
                "zh": item.zh,
            }
            for item in sorted(event.items, key=lambda value: value.published_at or datetime.min.replace(tzinfo=timezone.utc))
        ]
        day = _event_time(event).date()
        return self._make(
            domain="news",
            topic=event.topic,
            event_id=event.event_id,
            data_as_of=day,
            payload={"event": _event_summary(event), "timeline": timeline},
            source_detail=",".join(event.sources),
            fetched_at=_event_time(event),
            confidence=event.confidence,
            source_status=self._source_status(day, event.topic),
        )

    def list_sources(self, topic: str | None = None) -> WireEnvelope:
        resolved = self.config.find_topic(topic) if topic else None
        if topic and resolved is None:
            return self._make(
                domain="news",
                topic=str(topic),
                data_as_of=date.today(),
                payload={"sources": []},
                confidence="low",
            )

        sources = self.config.sources_for(resolved, include_disabled=True) if resolved else list(self.config.sources)
        scores = self._scores()
        statuses = self._source_status_map(resolved.id if resolved else None)
        payload_sources = [
            {
                "id": source.id,
                "name": source.name,
                "topic": source.topic,
                "type": source.type,
                "weight": source.weight,
                "score": _score_value(scores.get(source.id), "score"),
                "accuracy": _score_value(scores.get(source.id), "accuracy"),
                "timeliness": _score_value(scores.get(source.id), "timeliness"),
                "duplication": round(1.0 - _score_value(scores.get(source.id), "uniqueness"), 4),
                "status": statuses.get(source.id, "unknown"),
            }
            for source in sources
        ]
        payload_sources.sort(key=lambda item: (-float(item["score"]), str(item["id"])))
        fetched = max(
            (value for value in (scores.get(source.id) for source in sources) if value),
            key=lambda value: value.get("updated_at") or "",
            default=None,
        )
        return self._make(
            domain="news",
            topic=resolved.id if resolved else "",
            data_as_of=self._latest_source_day(),
            payload={"sources": payload_sources},
            source_detail=",".join(item["id"] for item in payload_sources),
            fetched_at=_parse_datetime(fetched.get("updated_at")) if fetched else None,
            confidence="high" if any(scores.get(source.id) for source in sources) else "low",
            source_status=_aggregate_status(statuses.values()),
        )

    # ---- 数据读取 ----
    @property
    def store(self) -> WireStore | None:
        if self._store is None:
            path = self.config.paths.db_path
            if not path.is_file():
                return None
            self._store = WireStore(path)
        return self._store

    def _latest_day(self, topic: str) -> date | None:
        store = self.store
        if store is not None:
            value = store.latest_day(topic)
            if value:
                return date.fromisoformat(value)
        archive = self.config.paths.archive_dir
        if archive.is_dir():
            for path in sorted(archive.iterdir(), reverse=True):
                if path.is_dir() and _is_day(path.name):
                    day = date.fromisoformat(path.name)
                    if self._digest_for(topic, day) is not None or self._items_for(topic, day):
                        return day
        return None

    def _digest_for(self, topic: str, day: date) -> dict[str, Any] | None:
        store = self.store
        if store is not None:
            digest = store.get_digest(topic, day)
            if digest is not None:
                return digest.model_dump(mode="json")
        archive = read_archive_day(self.config.paths.archive_dir, day)
        if archive:
            digests = (archive.get("digests") or {}).get("digests") or {}
            entry = digests.get(topic)
            if isinstance(entry, dict):
                return entry
        return None

    def _items_for(self, topic: str, day: date) -> list[dict[str, Any]]:
        store = self.store
        if store is not None:
            items = store.items_for_day(day, topic).get(topic, [])
            if items:
                return [item.model_dump(mode="json") for item in items]
        archive = read_archive_day(self.config.paths.archive_dir, day)
        if archive:
            entries = (archive.get("items") or {}).get("items") or []
            return [entry for entry in entries if entry.get("topic") == topic]
        return []

    def _load_events(self, topic: str | None) -> list[Event]:
        store = self.store
        if store is not None:
            return store.events_for_topic(topic=topic, limit=MAX_EVENTS)
        events: list[Event] = []
        archive = self.config.paths.archive_dir
        if archive.is_dir():
            for path in sorted(archive.iterdir(), reverse=True):
                if not path.is_dir() or not _is_day(path.name):
                    continue
                data = read_archive_day(archive, path.name)
                for raw in (data or {}).get("events", {}).get("events", []):
                    if topic and raw.get("topic") != topic:
                        continue
                    try:
                        events.append(Event.model_validate(raw))
                    except Exception:  # noqa: BLE001 - 归档里的坏记录不应中断查询
                        logger.warning("跳过无法解析的归档事件：%s", raw.get("event_id"))
        return events

    def _load_event(self, event_id: str) -> Event | None:
        store = self.store
        if store is not None:
            event = store.get_event(event_id)
            if event is not None:
                return event
        for event in self._load_events(None):
            if event.event_id == event_id:
                return event
        return None

    def _scores(self) -> dict[str, dict[str, Any]]:
        store = self.store
        if store is None:
            return {}
        return {str(item["source_id"]): item for item in store.source_scores()}

    def _source_rows(self, day: date | None) -> list[dict[str, Any]]:
        store = self.store
        if store is None or day is None:
            return []
        return store.source_status(day)

    def _source_status_map(self, topic: str | None) -> dict[str, str]:
        rows = self._source_rows(self._latest_source_day())
        return {
            str(row["source_id"]): _status_value(row.get("status"))
            for row in rows
            if not topic or row.get("topic") == topic
        }

    def _source_status(self, day: date, topic: str | None) -> str:
        store = self.store
        if store is not None:
            rows = [row for row in store.source_status(day) if not topic or row.get("topic") == topic]
            return _aggregate_status(row.get("status") for row in rows)
        archive = read_archive_day(self.config.paths.archive_dir, day)
        entries = (archive or {}).get("sources", {}).get("sources") or []
        return _aggregate_status(
            entry.get("status") for entry in entries if not topic or entry.get("topic") == topic
        )

    def _latest_source_day(self) -> date | None:
        store = self.store
        if store is not None:
            value = store.latest_source_day()
            if value:
                return date.fromisoformat(value)
        return date.today()

    def _confidence(
        self,
        topic: str,
        day: date,
        has_payload: bool,
        digest: dict[str, Any] | None,
    ) -> str:
        if not has_payload:
            return "low"
        if digest is not None and digest.get("status") in {"partial", "failed", "skipped"}:
            return "medium"
        store = self.store
        if store is not None and any(event.source_count >= 2 for event in store.events_for_topic(topic, day)):
            return "high"
        return "medium"

    def _digest_from_items(self, topic: str, day: date, items: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "topic": topic,
            "date": day.isoformat(),
            "summary": f"共采集 {len(items)} 条资讯。",
            "key_points": [],
            "items": [
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "source": item.get("source_id", ""),
                    "published_at": item.get("published_at"),
                    "zh": item.get("zh", ""),
                    "summary": item.get("summary", ""),
                    "event_id": item.get("event_id"),
                }
                for item in items
            ],
            "status": "partial",
            "partial": True,
            "fallback": True,
        }

    # ---- 信封构造 ----
    def _make(
        self,
        *,
        domain: str,
        topic: str,
        data_as_of: date,
        payload: dict[str, Any],
        source_detail: str = "",
        fetched_at: datetime | None = None,
        freshness: str = "archive",
        confidence: str = "medium",
        source_status: str = "ok",
        event_id: str | None = None,
    ) -> WireEnvelope:
        return WireEnvelope(
            domain=domain,
            topic=topic,
            event_id=event_id,
            data_as_of=data_as_of,
            payload=payload,
            source="wire",
            source_detail=source_detail,
            fetched_at=fetched_at or datetime.now(timezone.utc),
            freshness=freshness,
            confidence=confidence,
            source_status=source_status,
        )

    def _empty(
        self,
        *,
        domain: str,
        topic: str,
        data_as_of: date | None = None,
        event_id: str | None = None,
    ) -> WireEnvelope:
        return self._make(
            domain=domain,
            topic=topic,
            event_id=event_id,
            data_as_of=data_as_of or date.today(),
            payload={},
            confidence="low",
        )


def parse_window(window: str | None) -> timedelta:
    text = str(window or DEFAULT_WINDOW).strip().lower()
    match = WINDOW_PATTERN.match(text)
    if not match:
        raise ValueError(f"window 格式应为 Nd 或 Nh: {window}")
    amount = int(match.group(1))
    if amount <= 0:
        raise ValueError(f"window 必须大于 0: {window}")
    return timedelta(hours=amount) if match.group(2) == "h" else timedelta(days=amount)


def _is_day(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _event_time(event: Event) -> datetime:
    return event.last_seen or event.first_seen or datetime.min.replace(tzinfo=timezone.utc)


def _event_matches(event: Event, keyword: str) -> bool:
    needle = keyword.lower()
    haystacks = [event.title, *event.sources]
    for item in event.items:
        haystacks.extend([item.title, item.summary, item.zh])
    return any(needle in (value or "").lower() for value in haystacks)


def _event_summary(event: Event) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "topic": event.topic,
        "title": event.title,
        "first_seen": _iso(event.first_seen),
        "last_seen": _iso(event.last_seen),
        "source_count": event.source_count,
        "sources": event.sources,
        "confidence": event.confidence,
    }


def _event_payload(event: Event) -> dict[str, Any]:
    payload = _event_summary(event)
    payload["items"] = [
        {
            "title": item.title,
            "url": item.url,
            "source": item.source_id,
            "published_at": _iso(item.published_at),
            "zh": item.zh,
            "summary": item.summary,
        }
        for item in event.items
    ]
    return payload


def _latest_event_day(events: list[Event]) -> date:
    if not events:
        return date.today()
    return max(_event_time(event) for event in events).date()


def _latest_event_time(events: list[Event]) -> datetime:
    return max((_event_time(event) for event in events), default=datetime.now(timezone.utc))


def _source_ids(payload: dict[str, Any]) -> list[str]:
    values: set[str] = set()
    for item in payload.get("items") or []:
        if isinstance(item, dict):
            source = str(item.get("source") or "").strip()
            if source:
                values.update(part.strip() for part in source.split(",") if part.strip())
    return sorted(values)


def _payload_fetched_at(payload: dict[str, Any]) -> datetime:
    return _parse_datetime(payload.get("generated_at")) or datetime.now(timezone.utc)


def _status_value(value: Any) -> str:
    return "degraded" if value in {"degraded", "unavailable"} else ("ok" if value == "ok" else "unknown")


def _aggregate_status(values: Any) -> str:
    statuses = list(values)
    if any(status == "unavailable" for status in statuses):
        return "partial"
    if any(status == "degraded" for status in statuses):
        return "degraded"
    return "ok"


def _score_value(score: dict[str, Any] | None, key: str) -> float:
    if not score:
        return 0.0
    try:
        return float(score.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0
