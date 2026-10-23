"""qfw schedule 的三种模式：dry-run、未启用、立即执行。"""
from __future__ import annotations

import json

import pytest

import qf_wire.cli.schedule as schedule_cli
from qf_wire.cli.main import cli
from qf_wire.core.errors import EXIT_CONFIG, EXIT_OK, EXIT_PARTIAL
from tests.fixtures.configs import DEFAULT_SCHEDULE, write_config


def _schedule(enabled: bool, command: str = "run") -> dict:
    return {
        "schedule": {
            **DEFAULT_SCHEDULE["schedule"],
            "enabled": enabled,
            "jobs": [
                {"id": "daily_run", "cron": "0 7 * * *", "command": command, "options": {}}
            ],
        }
    }


def _run(tmp_path, *args: str) -> int:
    return cli(
        [
            "--config-dir",
            str(tmp_path / "config"),
            "--data-dir",
            str(tmp_path / "data"),
            *args,
        ]
    )


def test_dry_run_lists_jobs(tmp_path, capsys: pytest.CaptureFixture[str], isolated_env) -> None:
    write_config(tmp_path)
    code = _run(tmp_path, "--output", "json", "schedule", "--dry-run")

    assert code == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["enabled"] is False
    assert payload["timezone"] == "Asia/Shanghai"
    assert payload["jobs"][0]["id"] == "daily_run"
    assert payload["jobs"][0]["cron"] == "0 7 * * *"


def test_disabled_schedule_exits_with_config_error(
    tmp_path, capsys: pytest.CaptureFixture[str], isolated_env
) -> None:
    write_config(tmp_path)
    code = _run(tmp_path, "schedule")

    assert code == EXIT_CONFIG
    assert "schedule.enabled" in capsys.readouterr().err


def test_once_runs_enabled_jobs(tmp_path, capsys: pytest.CaptureFixture[str], monkeypatch, isolated_env) -> None:
    write_config(tmp_path, schedule=_schedule(True))
    calls: list[str] = []

    def fake_execute(config, job):
        calls.append(job.id)
        return {"job": job.id, "command": job.command, "status": "ok"}

    monkeypatch.setattr(schedule_cli, "execute_job", fake_execute)
    code = _run(tmp_path, "--output", "json", "schedule", "--once")

    assert code == EXIT_OK
    assert calls == ["daily_run"]
    payload = json.loads(capsys.readouterr().out)
    assert payload["jobs"][0]["status"] == "ok"


def test_once_reports_partial_when_job_fails(
    tmp_path, capsys: pytest.CaptureFixture[str], monkeypatch, isolated_env
) -> None:
    write_config(tmp_path, schedule=_schedule(True))

    def fake_execute(config, job):
        return {"job": job.id, "command": job.command, "status": "error", "error": "网络不可用"}

    monkeypatch.setattr(schedule_cli, "execute_job", fake_execute)
    code = _run(tmp_path, "--output", "json", "schedule", "--once")

    assert code == EXIT_PARTIAL
    payload = json.loads(capsys.readouterr().out)
    assert payload["jobs"][0]["error"] == "网络不可用"


def test_serve_with_scheduler_rejects_bad_cron(
    tmp_path, capsys: pytest.CaptureFixture[str], isolated_env
) -> None:
    bad = {
        "schedule": {
            "enabled": True,
            "jobs": [{"id": "daily", "cron": "every morning", "command": "run"}],
        }
    }
    write_config(tmp_path, schedule=bad)

    code = _run(tmp_path, "serve", "--with-scheduler", "--port", "8799")

    assert code == EXIT_CONFIG
    assert "定时任务配置无效" in capsys.readouterr().err
