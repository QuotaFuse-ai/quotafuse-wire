"""qfw event：事件列表、事件详情与多源时间线。"""
from __future__ import annotations

from datetime import date
from typing import Any

import typer

from qf_wire.cli.context import AppContext, emit_json, emit_mapping, emit_rows, parse_day
from qf_wire.core.errors import NotFoundError
from qf_wire.core.models import Event, SourceItem
from qf_wire.core.scheduler import today_beijing

event_app = typer.Typer(
    help="查看事件聚合与多源时间线",
    no_args_is_help=False,
    invoke_without_command=True,
)

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


def _event_row(event: Event) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "topic": event.topic,
        "title": event.title,
        "sources": event.source_count,
        "confidence": event.confidence,
        "last_seen": event.last_seen.isoformat() if event.last_seen else "",
    }


def _timeline_rows(items: list[SourceItem]) -> list[dict[str, Any]]:
    return [
        {
            "published_at": item.published_at.isoformat() if item.published_at else "",
            "source_id": item.source_id or ",".join(item.sources),
            "title": item.title,
            "url": item.url,
        }
        for item in items
    ]


def _list_events(app_ctx: AppContext, topic: str | None, day: str | None, limit: int) -> None:
    config = app_ctx.config()
    topic_id = config.topic(topic).id if topic else None
    target_day = parse_day(day) or today_beijing()
    store = app_ctx.open_store()
    try:
        events = store.events_for_topic(topic=topic_id, day=target_day, limit=limit)
    finally:
        store.close()

    rows = [_event_row(event) for event in events]
    if app_ctx.output == "json":
        emit_json({"date": target_day.isoformat(), "count": len(rows), "events": rows})
    else:
        emit_rows(rows, EVENT_COLUMNS, app_ctx.output)


def _require_event(store: Any, event_id: str, day: date | None = None) -> Event:
    event = store.get_event(event_id, day)
    if event is None:
        suffix = f"（{day.isoformat()}）" if day else ""
        raise NotFoundError(f"事件不存在: {event_id}{suffix}")
    return event


@event_app.callback()
def _event_root(
    ctx: typer.Context,
    topic: str = typer.Option(None, "--topic", "-t", help="列出时按赛道过滤"),
    day: str = typer.Option(None, "--date", help="列出时的日期，默认北京时间今天"),
    limit: int = typer.Option(50, "--limit", min=1, max=500, help="列出的最大条数"),
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    _list_events(ctx.obj, topic, day, limit)


@event_app.command("list")
def list_events(
    ctx: typer.Context,
    topic: str = typer.Option(None, "--topic", "-t", help="按赛道过滤"),
    day: str = typer.Option(None, "--date", help="日期，默认北京时间今天"),
    limit: int = typer.Option(50, "--limit", min=1, max=500, help="最大条数"),
) -> int:
    _list_events(ctx.obj, topic, day, limit)
    return 0


@event_app.command("show")
def show_event(
    ctx: typer.Context,
    event_id: str = typer.Argument(..., help="事件 id"),
    day: str = typer.Option(None, "--date", help="事件所属日期，默认取最近一次采集"),
) -> int:
    app_ctx: AppContext = ctx.obj
    target_day = parse_day(day)
    store = app_ctx.open_store()
    try:
        event = _require_event(store, event_id, target_day)
        reports = store.event_timeline(event_id, target_day)
    finally:
        store.close()

    rows = _timeline_rows(reports)
    if app_ctx.output == "json":
        emit_json(
            {
                "event": event.model_dump(mode="json"),
                "timeline": [item.model_dump(mode="json") for item in reports],
            }
        )
    elif app_ctx.output == "csv":
        emit_rows(rows, TIMELINE_COLUMNS, "csv")
    else:
        emit_mapping(
            {
                "event_id": event.event_id,
                "topic": event.topic,
                "title": event.title,
                "sources": ", ".join(event.sources),
                "source_count": event.source_count,
                "confidence": event.confidence,
                "merge_reason": event.explanation.summary() if event.explanation else "未记录",
                "first_seen": event.first_seen.isoformat() if event.first_seen else "",
                "last_seen": event.last_seen.isoformat() if event.last_seen else "",
            },
            "table",
        )
        emit_rows(rows, TIMELINE_COLUMNS, "table")
    return 0


@event_app.command("timeline")
def show_timeline(
    ctx: typer.Context,
    event_id: str = typer.Argument(..., help="事件 id"),
    day: str = typer.Option(None, "--date", help="事件所属日期，默认取最近一次采集"),
) -> int:
    app_ctx: AppContext = ctx.obj
    target_day = parse_day(day)
    store = app_ctx.open_store()
    try:
        _require_event(store, event_id, target_day)
        reports = store.event_timeline(event_id, target_day)
    finally:
        store.close()

    rows = _timeline_rows(reports)
    if app_ctx.output == "json":
        emit_json({"event_id": event_id, "count": len(rows), "timeline": rows})
    else:
        emit_rows(rows, TIMELINE_COLUMNS, app_ctx.output)
    return 0
