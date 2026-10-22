"""qfw run：采集、处理、提炼、落库、归档与看板渲染。"""
from __future__ import annotations

import sys
from typing import Any

import typer

from qf_wire.cli.context import AppContext, emit_json, emit_mapping, emit_rows, parse_day
from qf_wire.core.scheduler import RunOptions, run
from qf_wire.pipeline.fetch import status_summary

SOURCE_COLUMNS = [
    ("id", "id"),
    ("name", "名称"),
    ("topic", "赛道"),
    ("status", "状态"),
    ("items", "条目"),
    ("attempts", "尝试"),
    ("elapsed_ms", "耗时ms"),
    ("error", "错误"),
]


def run_command(
    ctx: typer.Context,
    topic: str = typer.Option(None, "--topic", "-t", help="只运行指定赛道（支持别名）"),
    sources_only: bool = typer.Option(False, "--sources-only", help="只采集，不调用模型提炼"),
    day: str = typer.Option(None, "--date", help="归档日期，默认北京时间今天"),
    max_workers: int | None = typer.Option(
        None,
        "--max-workers",
        min=1,
        max=64,
        help="并发采集数；缺省读取 QF_WIRE_FETCH_CONCURRENCY（默认 24）",
    ),
    no_render: bool = typer.Option(False, "--no-render", help="不写 data/data.js"),
    no_archive: bool = typer.Option(False, "--no-archive", help="不写 data/archive/<date>/"),
    no_persist: bool = typer.Option(False, "--no-persist", help="不写 SQLite"),
) -> int:
    app_ctx: AppContext = ctx.obj
    config = app_ctx.config()
    target_day = parse_day(day)
    topics = [config.topic(topic)] if topic else config.topics

    result = run(
        config,
        RunOptions(
            topics=topics,
            sources_only=sources_only,
            day=target_day,
            max_workers=max_workers,
            render=not no_render,
            archive=not no_archive,
            persist=not no_persist,
        ),
    )

    payload: dict[str, Any] = result.summary()
    payload["sources"] = [
        {
            "id": item.source_id,
            "name": item.source_name,
            "topic": item.topic,
            "status": item.status,
            "items": item.item_count,
            "attempts": item.attempts,
            "elapsed_ms": item.elapsed_ms,
            "error": item.error,
        }
        for item in result.sources
    ]

    fmt = app_ctx.output
    if fmt == "json":
        emit_json(payload)
    elif fmt == "csv":
        emit_rows(payload["sources"], SOURCE_COLUMNS, "csv")
    else:
        emit_mapping({key: value for key, value in payload.items() if key != "sources"}, "table")
        if result.sources:
            sys.stdout.write("\n" + status_summary(result.sources) + "\n")
            emit_rows(payload["sources"], SOURCE_COLUMNS, "table")
        for result_item in result.unavailable_sources:
            sys.stdout.write(f"注意：{result_item.source_name or result_item.source_id}：该源今日不可用\n")

    return result.exit_code
