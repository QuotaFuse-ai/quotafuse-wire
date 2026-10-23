"""qfw serve：启动本地看板（默认 127.0.0.1:8790）。"""
from __future__ import annotations

import sys

import typer

from qf_wire.cli.context import AppContext
from qf_wire.core.errors import EXIT_CONFIG, EXIT_UNAVAILABLE, ConfigError


def serve_command(
    ctx: typer.Context,
    host: str = typer.Option("127.0.0.1", "--host", help="监听地址，默认仅本机"),
    port: int = typer.Option(8790, "--port", "-p", min=1, max=65535, help="监听端口"),
    with_scheduler: bool = typer.Option(False, "--with-scheduler", help="同时运行 config/schedule.yaml 中的定时任务"),
) -> int:
    app_ctx: AppContext = ctx.obj
    config = app_ctx.config()

    from qf_wire.web.server import serve_forever

    scheduler = None
    if with_scheduler:
        from qf_wire.core.jobs import build_scheduler, enabled_jobs

        try:
            scheduler, settings = build_scheduler(config, background=True)
        except ConfigError as exc:
            sys.stderr.write(f"[qfw] 定时任务配置无效: {exc}\n")
            return EXIT_CONFIG
        if not settings.enabled:
            sys.stderr.write("[qfw] schedule.enabled=false，本次不启动定时任务\n")
        else:
            scheduler.start()
            sys.stderr.write(f"[qfw] 定时任务已随看板启动：{len(enabled_jobs(settings))} 个\n")

    try:
        serve_forever(config, host=host, port=port)
    except OSError as exc:
        sys.stderr.write(f"[qfw] 无法启动看板 {host}:{port}: {exc}\n")
        return EXIT_UNAVAILABLE
    except KeyboardInterrupt:
        sys.stderr.write("[qfw] 看板已停止\n")
    finally:
        if scheduler is not None and scheduler.running:
            scheduler.shutdown(wait=False)
    return 0
