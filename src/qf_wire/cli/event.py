"""qfw event：查看事件聚合与多源时间线（M1 轻量版）。"""
from __future__ import annotations

from typing import Any

import typer

from qf_wire.cli.context import AppContext, emit_json, emit_mapping, emit_rows, parse_day
from qf_wire.core.errors import NotFoundError
from qf_wire.core.scheduler import today_beijing

EVENT_COLUMNS = [
    ("event_id", "event_id"),
    ("topic", "赛道"),
    ("title", "标题"),
    ("sources", "信源数"),
    ("confidence", "置信度"),
    ("last_seen", "最近时间"),
]

TIMELINE_COLUMNS = [
    ("published_at", "时间"),
    ("source_id", "信源"),
    ("title", "标题"),
    ("url", "URL"),
]


def event_command(
    ctx: typer.Context,
    event_id: str = typer.Argument(None, help="事件 id；缺省时列出当天事件"),
    topic: str = typer.Option(None, "--topic", "-t", help="列出时按赛道过滤"),
    day: str = typer.Option(None, "--date", help="列出时的日期，默认北京时间今天"),
    limit: int = typer.Option(50, "--limit", min=1, max=500),
) -> int:
    app_ctx: AppContext = ctx.obj
    config = app_ctx.config()
    store = app_ctx.open_store()
    try:
        if event_id:
            event = store.get_event(event_id)
            if event is None:
                raise NotFoundError(f"事件不存在: {event_id}")
            timeline = store.event_timeline(event_id)
            payload: dict[str, Any] = {
                "event": event.model_dump(mode="json"),
                "timeline": [item.model_dump(mode="json") for item in timeline],
            }
            timeline_rows = [
                {
                    "published_at": item.published_at.isoformat() if item.published_at else "",
                    "source_id": item.source_id,
                    "title": item.title,
                    "url": item.url,
                }
                for item in timeline
            ]
            if app_ctx.output == "json":
                emit_json(payload)
            elif app_ctx.output == "csv":
                emit_rows(timeline_rows, TIMELINE_COLUMNS, "csv")
            else:
                emit_mapping(
                    {
                        "event_id": event.event_id,
                        "topic": event.topic,
                        "title": event.title,
                        "sources": event.source_count,
                        "confidence": event.confidence,
                    },
                    "table",
                )
                emit_rows(timeline_rows, TIMELINE_COLUMNS, "table")
            return 0

        target_day = parse_day(day) or today_beijing()
        topic_id = config.topic(topic).id if topic else None
        events = store.events_for_topic(topic=topic_id, day=target_day, limit=limit)
    finally:
        store.close()

    rows = [
        {
            "event_id": event.event_id,
            "topic": event.topic,
            "title": event.title,
            "sources": event.source_count,
            "confidence": event.confidence,
            "last_seen": event.last_seen.isoformat() if event.last_seen else "",
        }
        for event in events
    ]
    if app_ctx.output == "json":
        emit_json({"date": target_day.isoformat(), "count": len(rows), "events": rows})
    else:
        emit_rows(rows, EVENT_COLUMNS, app_ctx.output)
    return 0
