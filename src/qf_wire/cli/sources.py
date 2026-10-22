"""qfw sources：列出与探测信源。"""
from __future__ import annotations

import sys
from typing import Any

import typer

from qf_wire.cli.context import AppContext, emit_json, emit_mapping, emit_rows
from qf_wire.core.errors import EXIT_OK, EXIT_PARTIAL, EXIT_UNAVAILABLE
from qf_wire.core.models import Source
from qf_wire.pipeline.fetch import fetch_many, status_summary
from qf_wire.sources.registry import available_types

sources_app = typer.Typer(help="信源列表与可用性探测", no_args_is_help=True)

LIST_COLUMNS = [
    ("id", "id"),
    ("name", "名称"),
    ("topic", "赛道"),
    ("type", "类型"),
    ("url", "URL"),
    ("timeout_sec", "超时s"),
    ("retries", "重试"),
    ("enabled", "启用"),
]

CHECK_COLUMNS = [
    ("id", "id"),
    ("name", "名称"),
    ("type", "类型"),
    ("status", "状态"),
    ("items", "条目"),
    ("elapsed_ms", "耗时ms"),
    ("error", "错误"),
]


def _select_sources(app_ctx: AppContext, topic: str | None, enabled_only: bool) -> list[Source]:
    config = app_ctx.config()
    if topic:
        return config.sources_for(config.topic(topic))
    return config.enabled_sources() if enabled_only else list(config.sources)


@sources_app.command("list")
def list_sources(
    ctx: typer.Context,
    topic: str = typer.Option(None, "--topic", "-t", help="按赛道过滤"),
    enabled_only: bool = typer.Option(False, "--enabled-only", help="只看启用的源"),
) -> int:
    app_ctx: AppContext = ctx.obj
    sources = _select_sources(app_ctx, topic, enabled_only)
    rows: list[dict[str, Any]] = [
        {
            "id": source.id,
            "name": source.name,
            "topic": source.topic or "",
            "type": source.type,
            "url": source.url,
            "timeout_sec": source.timeout_sec,
            "retries": source.retries,
            "enabled": source.enabled,
        }
        for source in sources
    ]
    if app_ctx.output == "json":
        emit_json({"count": len(rows), "sources": rows, "types": available_types()})
    else:
        emit_rows(rows, LIST_COLUMNS, app_ctx.output)
    return EXIT_OK


@sources_app.command("validate")
def validate_sources(
    ctx: typer.Context,
    topic: str = typer.Option(None, "--topic", "-t", help="只探测指定赛道"),
    timeout: int = typer.Option(None, "--timeout", min=1, max=120, help="覆盖每个源的超时秒数"),
    workers: int = typer.Option(8, "--workers", min=1, max=32, help="并发探测数"),
) -> int:
    app_ctx: AppContext = ctx.obj
    sources = _select_sources(app_ctx, topic, enabled_only=True)
    if not sources:
        emit_json({"count": 0, "sources": []}) if app_ctx.output == "json" else sys.stdout.write("没有启用的信源\n")
        return EXIT_UNAVAILABLE

    update: dict[str, Any] = {"retries": 0}
    if timeout:
        update["timeout_sec"] = timeout
    probes = [source.model_copy(update=update) for source in sources]
    results = fetch_many(probes, max_workers=workers)
    rows = [
        {
            "id": result.source_id,
            "name": result.source_name,
            "type": next((source.type for source in sources if source.id == result.source_id), ""),
            "status": result.status,
            "items": result.item_count,
            "elapsed_ms": result.elapsed_ms,
            "error": result.error,
        }
        for result in results
    ]
    if app_ctx.output == "json":
        emit_json(
            {
                "count": len(rows),
                "summary": {
                    "ok": sum(1 for result in results if result.status == "ok"),
                    "degraded": sum(1 for result in results if result.status == "degraded"),
                    "unavailable": sum(1 for result in results if result.status == "unavailable"),
                },
                "sources": rows,
            }
        )
    elif app_ctx.output == "csv":
        emit_rows(rows, CHECK_COLUMNS, "csv")
    else:
        emit_mapping(
            {
                "总数": len(results),
                "可用": sum(1 for result in results if result.status == "ok"),
                "降级": sum(1 for result in results if result.status == "degraded"),
                "不可用": sum(1 for result in results if result.status == "unavailable"),
            },
            "table",
        )
        emit_rows(rows, CHECK_COLUMNS, "table")
        sys.stdout.write(status_summary(results) + "\n")

    unavailable = [result for result in results if result.status == "unavailable"]
    if not unavailable:
        return EXIT_OK
    if len(unavailable) == len(results):
        return EXIT_UNAVAILABLE
    return EXIT_PARTIAL
