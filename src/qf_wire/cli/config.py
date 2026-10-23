"""qfw config：配置校验与旧配置迁移。"""
from __future__ import annotations

from pathlib import Path

import typer

from qf_wire.cli.context import AppContext, emit_json, emit_lines, emit_mapping, emit_rows
from qf_wire.config.loader import resolve_paths
from qf_wire.config.migrate import migrate_legacy
from qf_wire.config.validator import validate_config_dir
from qf_wire.core.errors import EXIT_CONFIG, EXIT_OK, ConfigError

config_app = typer.Typer(help="配置校验与迁移", no_args_is_help=True)

ISSUE_COLUMNS = [
    ("level", "级别"),
    ("file", "文件"),
    ("path", "位置"),
    ("message", "说明"),
]


@config_app.command("validate")
def validate_config(ctx: typer.Context) -> int:
    app_ctx: AppContext = ctx.obj
    paths = app_ctx.config().paths
    report = validate_config_dir(paths.config_dir)
    payload = report.as_dict()

    if app_ctx.output == "json":
        emit_json(payload)
    elif app_ctx.output == "csv":
        emit_rows(payload["issues"], ISSUE_COLUMNS, "csv")
    else:
        if payload["issues"]:
            emit_rows(payload["issues"], ISSUE_COLUMNS, "table")
        emit_mapping(
            {
                "结果": "通过" if report.ok else "失败",
                "错误": payload["errors"],
                "警告": payload["warnings"],
            },
            "table",
        )
    return EXIT_OK if report.ok else EXIT_CONFIG


@config_app.command("migrate")
def migrate_config(
    ctx: typer.Context,
    legacy_dir: Path = typer.Option(None, "--legacy-dir", exists=True, file_okay=False, help="旧仓库根目录"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只打印计划，不写文件"),
) -> int:
    app_ctx: AppContext = ctx.obj
    source = legacy_dir or Path.cwd()
    if not source.is_dir():
        raise ConfigError(f"旧仓库目录不存在: {source}")
    # 迁移的目标目录可能还不存在，不能走 app_ctx.config()（会要求 topics.yaml 已就绪）
    paths = resolve_paths(app_ctx.config_dir, app_ctx.data_dir, user=app_ctx.user)
    report = migrate_legacy(source, paths.config_dir, dry_run=dry_run)

    if app_ctx.output == "json":
        emit_json(report.as_dict())
    else:
        emit_lines(report.lines)
    return EXIT_OK
