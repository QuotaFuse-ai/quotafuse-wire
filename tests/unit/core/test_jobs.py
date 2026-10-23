"""定时任务：schedule.yaml 解析、调度器注册与任务分发。"""
from __future__ import annotations

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler

from qf_wire.config.loader import load_config
from qf_wire.core import jobs
from qf_wire.core.errors import ConfigError
from qf_wire.core.jobs import (
    ScheduleJob,
    build_scheduler,
    enabled_jobs,
    execute_job,
    parse_schedule,
)
from tests.fixtures.configs import DEFAULT_SCHEDULE, write_config


def test_parse_schedule_normalizes_jobs() -> None:
    settings = parse_schedule(DEFAULT_SCHEDULE["schedule"])

    assert settings.enabled is False
    assert settings.timezone == "Asia/Shanghai"
    assert [job.id for job in settings.jobs] == ["daily_run"]
    assert settings.jobs[0].command == "run"
    assert enabled_jobs(settings) == [settings.jobs[0]]


def test_parse_schedule_defaults_to_disabled() -> None:
    settings = parse_schedule({})
    assert settings.enabled is False
    assert settings.jobs == []


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"timezone": "Mars/Olympus"}, "时区"),
        ({"jobs": [{"id": "a", "cron": "0 7 * *", "command": "run"}]}, "cron"),
        ({"jobs": [{"id": "a", "cron": "0 7 * * *", "command": "rm -rf"}]}, "command"),
        ({"jobs": [{"id": "", "cron": "0 7 * * *", "command": "run"}]}, "id"),
        (
            {
                "jobs": [
                    {"id": "a", "cron": "0 7 * * *", "command": "run"},
                    {"id": "a", "cron": "0 8 * * *", "command": "run"},
                ]
            },
            "重复",
        ),
        ({"jobs": [{"id": "a", "cron": "0 7 * * *", "command": "run", "options": []}]}, "options"),
        ({"jobs": "daily"}, "列表"),
    ],
)
def test_parse_schedule_rejects_invalid_config(patch: dict, message: str) -> None:
    raw = {"enabled": True, **patch}
    with pytest.raises(ConfigError, match=message):
        parse_schedule(raw)


def test_build_scheduler_registers_only_enabled_jobs(tmp_path) -> None:
    schedule = {
        "schedule": {
            "version": 1,
            "enabled": True,
            "timezone": "Asia/Shanghai",
            "jobs": [
                {"id": "daily", "cron": "0 7 * * *", "command": "run"},
                {"id": "paused", "cron": "0 8 * * *", "command": "digest", "enabled": False},
            ],
        }
    }
    config = load_config(write_config(tmp_path, schedule=schedule))

    scheduler, settings = build_scheduler(config)

    assert isinstance(scheduler, BlockingScheduler)
    assert [job.id for job in settings.jobs] == ["daily", "paused"]
    assert [job.id for job in scheduler.get_jobs()] == ["daily"]


def test_build_scheduler_background_mode(tmp_path) -> None:
    schedule = {
        "schedule": {
            "enabled": True,
            "jobs": [{"id": "daily", "cron": "0 7 * * *", "command": "run"}],
        }
    }
    config = load_config(write_config(tmp_path, schedule=schedule))

    scheduler, _ = build_scheduler(config, background=True)

    assert isinstance(scheduler, BackgroundScheduler)


def test_execute_job_dispatches_and_tags_result(tmp_path, monkeypatch) -> None:
    config = load_config(write_config(tmp_path), tmp_path / "data")
    calls: list[dict] = []

    def fake_handler(cfg, options):
        calls.append(options)
        return {"status": "ok", "items": 3}

    monkeypatch.setitem(jobs._HANDLERS, "run", fake_handler)
    job = ScheduleJob(id="daily", cron="0 7 * * *", command="run", options={"topics": "all"})

    result = execute_job(config, job)

    assert calls == [{"topics": "all"}]
    assert result == {"job": "daily", "command": "run", "status": "ok", "items": 3}


def test_execute_job_catches_handler_errors(tmp_path, monkeypatch) -> None:
    config = load_config(write_config(tmp_path), tmp_path / "data")

    def boom(cfg, options):
        raise RuntimeError("网络不可用")

    monkeypatch.setitem(jobs._HANDLERS, "run", boom)
    job = ScheduleJob(id="daily", cron="0 7 * * *", command="run")

    result = execute_job(config, job)

    assert result["status"] == "error"
    assert "网络不可用" in result["error"]


def test_digest_job_requires_collected_items(tmp_path) -> None:
    config = load_config(write_config(tmp_path), tmp_path / "data")
    job = ScheduleJob(id="digest", cron="0 8 * * *", command="digest")

    result = execute_job(config, job)

    assert result["status"] == "error"
    assert "qfw run" in result["error"]
