"""定时任务：解析 config/schedule.yaml，用 APScheduler 触发采集与提炼。

只做本地调度：没有云端账户、没有队列，进程退出即停止。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from qf_wire.config.loader import WireConfig
from qf_wire.core.errors import ConfigError, WireError
from qf_wire.core.scheduler import RunOptions, digest_day, run, today_beijing
from qf_wire.logging.setup import get_logger
from qf_wire.pipeline.fetch import fetch_many
from qf_wire.storage.sqlite import WireStore

logger = get_logger(__name__)

DEFAULT_TIMEZONE = "Asia/Shanghai"
COMMANDS = ("run", "digest", "sources validate")
_MISFIRE_GRACE_SEC = 3600
DEFAULT_RETRIES = 1
DEFAULT_RETRY_DELAY_SEC = 5.0
MAX_RETRIES = 5


@dataclass(frozen=True, slots=True)
class ScheduleJob:
    id: str
    cron: str
    command: str
    options: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


@dataclass(slots=True)
class ScheduleSettings:
    enabled: bool = False
    timezone: str = DEFAULT_TIMEZONE
    jobs: list[ScheduleJob] = field(default_factory=list)


def parse_schedule(raw: dict[str, Any] | None) -> ScheduleSettings:
    data = raw or {}
    if not isinstance(data, dict):
        raise ConfigError("schedule.yaml 的 schedule 必须是对象")
    timezone = str(data.get("timezone") or DEFAULT_TIMEZONE)
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"schedule.yaml 时区无效: {timezone}") from exc

    entries = data.get("jobs") or []
    if not isinstance(entries, list):
        raise ConfigError("schedule.yaml 的 jobs 必须是列表")
    jobs: list[ScheduleJob] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise ConfigError(f"schedule.yaml 第 {index} 个任务必须是对象")
        job_id = str(entry.get("id") or "").strip()
        if not job_id:
            raise ConfigError(f"schedule.yaml 第 {index} 个任务缺少 id")
        if job_id in seen:
            raise ConfigError(f"schedule.yaml 存在重复任务 id: {job_id}")
        seen.add(job_id)
        cron = " ".join(str(entry.get("cron") or "").split())
        if not cron:
            raise ConfigError(f"定时任务 {job_id} 缺少 cron")
        try:
            CronTrigger.from_crontab(cron, timezone=timezone)
        except ValueError as exc:
            raise ConfigError(f"定时任务 {job_id} 的 cron 无效: {cron}（{exc}）") from exc
        command = " ".join(str(entry.get("command") or "run").split())
        if command not in COMMANDS:
            raise ConfigError(f"定时任务 {job_id} 的 command 不支持: {command}（可用: {', '.join(COMMANDS)}）")
        options = entry.get("options")
        if options is None:
            options = {}
        if not isinstance(options, dict):
            raise ConfigError(f"定时任务 {job_id} 的 options 必须是对象")
        jobs.append(
            ScheduleJob(
                id=job_id,
                cron=cron,
                command=command,
                options=dict(options),
                enabled=bool(entry.get("enabled", True)),
            )
        )
    return ScheduleSettings(enabled=bool(data.get("enabled", False)), timezone=timezone, jobs=jobs)


def _topics_for(config: WireConfig, options: dict[str, Any]) -> list:
    value = options.get("topics") or options.get("topic") or "all"
    if isinstance(value, str):
        if value.strip().lower() in {"", "all", "*"}:
            return list(config.topics)
        return [config.topic(value)]
    if isinstance(value, (list, tuple)):
        return [config.topic(str(item)) for item in value]
    raise ConfigError(f"定时任务的 topics 必须是列表或 all: {value}")


def _job_run(config: WireConfig, options: dict[str, Any]) -> dict[str, Any]:
    sources_only = bool(options.get("sources_only")) or options.get("digest") is False
    result = run(
        config,
        RunOptions(
            topics=_topics_for(config, options),
            sources_only=sources_only,
            max_workers=int(options["max_workers"]) if options.get("max_workers") else None,
        ),
    )
    return {
        "status": result.status,
        "exit_code": result.exit_code,
        "day": result.day.isoformat(),
        "items": result.item_count,
    }


def _job_digest(config: WireConfig, options: dict[str, Any]) -> dict[str, Any]:
    day = today_beijing()
    store = WireStore(config.paths.db_path)
    store.initialize()
    try:
        if store.count_items(day) == 0:
            raise ConfigError(f"{day.isoformat()} 还没有采集数据，请先运行 qfw run")
        digests = digest_day(config, store, day, _topics_for(config, options), render=True)
    finally:
        store.close()
    partial_count = sum(1 for digest in digests.values() if digest.status != "ok")
    return {
        "status": "ok" if partial_count == 0 else "partial",
        "day": day.isoformat(),
        "topics": len(digests),
    }


def _job_sources_validate(config: WireConfig, options: dict[str, Any]) -> dict[str, Any]:
    update: dict[str, Any] = {"retries": 0}
    if options.get("timeout_sec"):
        update["timeout_sec"] = int(options["timeout_sec"])
    probes = [source.model_copy(update=update) for source in config.enabled_sources()]
    results = fetch_many(probes, max_workers=int(options.get("max_workers") or 8))
    unavailable = [result.source_id for result in results if result.status == "unavailable"]
    return {
        "status": "ok" if not unavailable else "partial",
        "sources": len(results),
        "unavailable": unavailable,
    }


_HANDLERS: dict[str, Callable[[WireConfig, dict[str, Any]], dict[str, Any]]] = {
    "run": _job_run,
    "digest": _job_digest,
    "sources validate": _job_sources_validate,
}


def _retry_settings(options: dict[str, Any]) -> tuple[int, float]:
    try:
        retries = int(options.get("retries", DEFAULT_RETRIES))
    except (TypeError, ValueError):
        retries = DEFAULT_RETRIES
    try:
        delay = float(options.get("retry_delay", DEFAULT_RETRY_DELAY_SEC))
    except (TypeError, ValueError):
        delay = DEFAULT_RETRY_DELAY_SEC
    return max(0, min(MAX_RETRIES, retries)), max(0.0, delay)


def execute_job(config: WireConfig, job: ScheduleJob) -> dict[str, Any]:
    handler = _HANDLERS[job.command]
    retries, delay = _retry_settings(job.options)
    max_attempts = retries + 1
    attempt = 0
    while True:
        attempt += 1
        logger.info("定时任务 %s 开始（第 %d/%d 次）：%s", job.id, attempt, max_attempts, job.command)
        try:
            outcome = handler(config, job.options)
        except WireError as exc:  # 配置/参数问题重试也不会好，直接回给调度器
            logger.warning("定时任务 %s 失败（配置错误）: %s", job.id, exc)
            return {"job": job.id, "command": job.command, "status": "error", "error": str(exc), "attempts": attempt}
        except Exception as exc:  # 单次失败不终止调度进程，按配置重试
            if attempt >= max_attempts:
                logger.warning("定时任务 %s 失败，已重试 %d 次: %s", job.id, attempt - 1, exc)
                return {
                    "job": job.id,
                    "command": job.command,
                    "status": "error",
                    "error": str(exc),
                    "attempts": attempt,
                }
            logger.warning("定时任务 %s 第 %d 次失败，%.1fs 后重试: %s", job.id, attempt, delay, exc)
            if delay:
                time.sleep(delay)
            continue
        logger.info("定时任务 %s 完成：%s", job.id, outcome.get("status"))
        result = {"job": job.id, "command": job.command, **outcome}
        if attempt > 1:
            result["attempts"] = attempt
        return result


def build_scheduler(
    config: WireConfig,
    *,
    background: bool = False,
) -> tuple[BlockingScheduler | BackgroundScheduler, ScheduleSettings]:
    """按配置创建调度器（未 start，由调用方决定阻塞或后台运行）。"""
    settings = parse_schedule(config.schedule)
    scheduler: BlockingScheduler | BackgroundScheduler = (
        BackgroundScheduler(timezone=settings.timezone) if background else BlockingScheduler(timezone=settings.timezone)
    )
    for job in settings.jobs:
        if not job.enabled:
            continue
        scheduler.add_job(
            partial(execute_job, config, job),
            CronTrigger.from_crontab(job.cron, timezone=settings.timezone),
            id=job.id,
            name=f"{job.command} ({job.cron})",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=_MISFIRE_GRACE_SEC,
        )
    return scheduler, settings


def enabled_jobs(settings: ScheduleSettings) -> list[ScheduleJob]:
    return [job for job in settings.jobs if job.enabled]
