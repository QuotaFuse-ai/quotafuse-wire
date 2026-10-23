"""qfw schedule：按 config/schedule.yaml 执行定时采集与提炼。"""
from __future__ import annotations

import sys

import typer

from qf_wire.cli.context import AppContext, emit_json, emit_rows
from qf_wire.core.errors import EXIT_CONFIG, EXIT_OK, EXIT_PARTIAL
from qf_wire.core.jobs import build_scheduler, enabled_jobs, execute_job, parse_schedule

JOB_COLUMNS = [
    ("id", "任务"),
    ("enabled", "启用"),
    ("cron", "cron"),
    ("command", "命令"),
]


def schedule_command(
    ctx: typer.Context,
    once: bool = typer.Option(False, "--once", help="立即执行全部启用的任务后退出"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只打印任务列表，不执行"),
) -> int:
    app_ctx: AppContext = ctx.obj
    config = app_ctx.config()
    settings = parse_schedule(config.schedule)
    active = enabled_jobs(settings)

    if dry_run:
        rows = [
            {
                "id": job.id,
                "enabled": job.enabled,
                "cron": job.cron,
                "command": job.command,
                "options": job.options,
            }
            for job in settings.jobs
        ]
        if app_ctx.output == "json":
            emit_json(
                {
                    "enabled": settings.enabled,
                    "timezone": settings.timezone,
                    "jobs": rows,
                }
            )
        else:
            emit_rows(rows, JOB_COLUMNS, app_ctx.output)
            sys.stdout.write(
                f"调度总开关: {'开启' if settings.enabled else '关闭'}"
                f"，时区 {settings.timezone}，启用 {len(active)} 个任务\n"
            )
        return EXIT_OK

    if not settings.enabled:
        sys.stderr.write("[qfw] 定时调度未启用：把 config/schedule.yaml 的 schedule.enabled 改成 true 后重试\n")
        return EXIT_CONFIG
    if not active:
        sys.stderr.write("[qfw] 没有启用的定时任务，检查 config/schedule.yaml 的 jobs[].enabled\n")
        return EXIT_CONFIG

    if once:
        results = [execute_job(config, job) for job in active]
        if app_ctx.output == "json":
            emit_json({"jobs": results})
        else:
            for item in results:
                detail = item.get("error") or item.get("status")
                sys.stdout.write(f"{item['job']}（{item['command']}）：{detail}\n")
        return EXIT_PARTIAL if any(item.get("status") == "error" for item in results) else EXIT_OK

    scheduler, _ = build_scheduler(config)
    for job in active:
        sys.stderr.write(f"[qfw] 已注册 {job.id}：{job.command} @ {job.cron}\n")
    sys.stderr.write("[qfw] 定时调度已启动，Ctrl+C 退出\n")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        sys.stderr.write("[qfw] 定时调度已停止\n")
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
    return EXIT_OK
