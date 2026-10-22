"""看板投影：生成兼容 investment-news 的 data/data.js。"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from qf_wire.core.cleaner import format_display_time, to_timestamp_ms
from qf_wire.core.models import Event, SourceItem, Topic, TopicDigest
from qf_wire.logging.setup import get_logger
from qf_wire.sources.base import FetchResult

logger = get_logger(__name__)

DEFAULT_ACCENT = "#64748b"


def build_dashboard_payload(
    topics: Iterable[Topic],
    items_by_topic: dict[str, list[SourceItem]],
    digests: dict[str, TopicDigest] | None = None,
    events_by_topic: dict[str, list[Event]] | None = None,
    source_results: list[FetchResult] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    """把采集/提炼结果投影为旧看板可读的 window.DATA 结构。"""
    digests = digests or {}
    events_by_topic = events_by_topic or {}
    generated_at = generated_at or datetime.now(timezone.utc)

    industries = []
    for topic in topics:
        items = items_by_topic.get(topic.id, [])
        digest = digests.get(topic.id)
        item_map = _digest_item_map(digest)
        source_count = {
            event.event_id: event.source_count for event in events_by_topic.get(topic.id, [])
        }
        projected = [_project_item(item, item_map, source_count) for item in items]
        industries.append(
            {
                "key": topic.legacy_key or topic.id,
                "id": topic.id,
                "name": topic.name,
                "accent": topic.accent or DEFAULT_ACCENT,
                "summary": digest.summary if digest else "",
                "key_points": [
                    {
                        "text": point.text,
                        "sources": point.sources,
                        "confidence": point.confidence,
                        "event_id": point.event_id,
                    }
                    for point in (digest.key_points if digest else [])
                ],
                "items": projected,
            }
        )

    payload: dict[str, object] = {
        "generatedAt": generated_at.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        "industries": industries,
    }
    if source_results is not None:
        payload["sourceStatus"] = [
            {
                "id": result.source_id,
                "name": result.source_name,
                "topic": result.topic,
                "status": result.status,
                "error": result.error,
                "itemCount": result.item_count,
                "attempts": result.attempts,
                "elapsedMs": result.elapsed_ms,
            }
            for result in source_results
        ]
        unavailable = [result for result in source_results if result.status == "unavailable"]
        if unavailable:
            payload["sourceNotice"] = [
                f"{result.source_name or result.source_id}：该源今日不可用" for result in unavailable
            ]
    return payload


def _digest_item_map(digest: TopicDigest | None) -> dict[str, dict[str, str]]:
    if digest is None:
        return {}
    result: dict[str, dict[str, str]] = {}
    for item in digest.items:
        value = {"zh": item.zh, "summary": item.summary}
        if item.url:
            result[item.url] = value
        if item.title:
            result[f"title:{item.title}"] = value
    return result


def _project_item(
    item: SourceItem,
    digest_map: dict[str, dict[str, str]],
    source_count: dict[str | None, int],
) -> dict[str, object]:
    enrichment = digest_map.get(item.url) or digest_map.get(f"title:{item.title}") or {}
    return {
        "title": item.title,
        "url": item.url,
        "time": format_display_time(item.published_at),
        "ts": to_timestamp_ms(item.published_at),
        "summary": enrichment.get("summary") or item.summary,
        "source": item.source_id or ",".join(item.sources),
        "zh": enrichment.get("zh") or item.zh,
        "event_id": item.event_id,
        "source_count": source_count.get(item.event_id, len(item.sources) or 1),
        "confidence": item.confidence,
    }


def render_data_js(payload: dict[str, object]) -> str:
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"window.DATA = {body};\n"


def write_data_js(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(render_data_js(payload), encoding="utf-8")
    os.replace(temp, path)
    logger.info("已写入看板数据: %s", path)
    return path
