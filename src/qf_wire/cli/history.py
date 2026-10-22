"""qfw history：按天查看归档数量与前后日增量。"""
from __future__ import annotations

from typing import Any

import typer

from qf_wire.cli.context import AppContext, emit_json, emit_mapping, emit_rows, parse_day
from qf_wire.core.errors import NotFoundError

HISTORY_COLUMNS = [
    ("date", "日期"),
    ("items", "条目"),
    ("events", "事件"),
    ("digests", "提炼"),
    ("source_ok", "源可用"),
    ("source_degraded", "源降级"),
    ("source_unavailable", "源不可用"),
    ("item_delta", "条目增量"),
    ("digest_delta", "提炼增量"),
]


def history_command(
    ctx: typer.Context,
    topic: str = typer.Option(None, "--topic", "-t", help="赛道 id 或别名；缺省为全部"),
    days: int = typer.Option(7, "--days", "-d", min=1, max=365, help="回溯天数"),
    end: str = typer.Option(None, "--date", help="截止日期，默认最新归档日"),
) -> int:
    app_ctx: AppContext = ctx.obj
    config = app_ctx.config()
    topic_id = config.topic(topic).id if topic else None
    target_day = parse_day(end)

    store = app_ctx.open_store()
    try:
        if target_day is None:
            latest = store.latest_day()
            if not latest:
                raise NotFoundError("暂无归档数据，请先运行 qfw run")
            target_day = parse_day(latest)
        rows = store.history(topic=topic_id, days=days, end_day=target_day)
    finally:
        store.close()

    totals = {
        "items": sum(row["items"] for row in rows),
        "events": sum(row["events"] for row in rows),
        "digests": sum(row["digests"] for row in rows),
        "item_delta": sum(row["item_delta"] for row in rows),
        "digest_delta": sum(row["digest_delta"] for row in rows),
    }
    payload: dict[str, Any] = {
        "topic": topic_id,
        "end_date": target_day.isoformat(),
        "days": days,
        "totals": totals,
        "history": rows,
    }

    if app_ctx.output == "json":
        emit_json(payload)
    elif app_ctx.output == "csv":
        emit_rows(rows, HISTORY_COLUMNS, "csv")
    else:
        emit_mapping(
            {
                "赛道": topic_id or "全部",
                "截止日期": target_day.isoformat(),
                "天数": days,
                "条目合计": totals["items"],
                "条目增量": totals["item_delta"],
            },
            "table",
        )
        emit_rows(rows, HISTORY_COLUMNS, "table")
    return 0
