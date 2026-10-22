"""qfw digest：对指定日期的归档数据重新提炼。"""
from __future__ import annotations

from typing import Any

import typer

from qf_wire.cli.context import AppContext, emit_json, emit_rows, parse_day
from qf_wire.core.errors import NotFoundError
from qf_wire.core.scheduler import digest_day, today_beijing
from qf_wire.storage.sqlite import WireStore

DIGEST_COLUMNS = [
    ("topic", "赛道"),
    ("status", "状态"),
    ("fallback", "降级"),
    ("items", "条目"),
    ("summary", "摘要"),
]


def digest_command(
    ctx: typer.Context,
    topic: str = typer.Option(None, "--topic", "-t", help="只提炼指定赛道"),
    day: str = typer.Option(None, "--date", help="归档日期，默认北京时间今天"),
    no_render: bool = typer.Option(False, "--no-render", help="不刷新 data/data.js"),
) -> int:
    app_ctx: AppContext = ctx.obj
    config = app_ctx.config()
    target_day = parse_day(day) or today_beijing()
    topics = [config.topic(topic)] if topic else config.topics

    store: WireStore = app_ctx.open_store()
    try:
        if store.count_items(target_day) == 0:
            raise NotFoundError(f"{target_day.isoformat()} 没有归档条目，请先运行 qfw run --date {target_day}")
        digests = digest_day(config, store, target_day, topics, render=not no_render)
    finally:
        store.close()

    payload: dict[str, Any] = {
        "date": target_day.isoformat(),
        "digests": {topic_id: digest.model_dump(mode="json") for topic_id, digest in digests.items()},
    }
    fmt = app_ctx.output
    if fmt == "json":
        emit_json(payload)
    else:
        rows = [
            {
                "topic": topic_id,
                "status": digest.status,
                "fallback": digest.fallback,
                "items": len(digest.items),
                "summary": (digest.summary or "").replace("\n", " ")[:80],
            }
            for topic_id, digest in digests.items()
        ]
        emit_rows(rows, DIGEST_COLUMNS, fmt)
    return 0
