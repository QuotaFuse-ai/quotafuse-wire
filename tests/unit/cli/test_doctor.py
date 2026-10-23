"""`qfw doctor` 自检：配置、数据目录与模型通道。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from qf_wire.cli.main import cli
from qf_wire.core.errors import EXIT_CONFIG, EXIT_OK

REPO_ROOT = Path(__file__).resolve().parents[3]


def _checks(output: str) -> dict[str, dict[str, str]]:
    payload = json.loads(output)
    return {item["check"]: item for item in payload["checks"]}


def test_doctor_reports_healthy_config_and_data_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli(
        [
            "--config-dir",
            str(REPO_ROOT / "config"),
            "--data-dir",
            str(tmp_path / "data"),
            "--output",
            "json",
            "doctor",
            "--no-network",
        ]
    )
    captured = capsys.readouterr()
    assert code == EXIT_OK, captured.err
    payload = json.loads(captured.out)
    checks = _checks(captured.out)
    assert payload["ok"] is True
    assert checks["config.load"]["status"] == "ok"
    assert checks["config.files"]["status"] == "ok"
    assert checks["config.prompts"]["status"] == "ok"
    assert checks["data.dir"]["status"] == "ok"
    # 尚未运行过采集：数据库是警告而不是失败
    assert checks["data.sqlite"]["status"] == "warn"


def test_doctor_fails_with_config_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    empty = tmp_path / "empty-config"
    empty.mkdir()
    code = cli(
        [
            "--config-dir",
            str(empty),
            "--data-dir",
            str(tmp_path / "data"),
            "--output",
            "json",
            "doctor",
            "--no-network",
        ]
    )
    captured = capsys.readouterr()
    assert code == EXIT_CONFIG
    checks = _checks(captured.out)
    assert checks["config.load"]["status"] == "fail"


def test_doctor_reports_missing_prompts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for name in ("topics.yaml", "sources.yaml", "digest.yaml"):
        (config_dir / name).write_text(
            (REPO_ROOT / "config" / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    # 提示词既不在仓库根也不在包内时，doctor 必须报配置错误
    (config_dir / "digest.yaml").write_text(
        (REPO_ROOT / "config" / "digest.yaml")
        .read_text(encoding="utf-8")
        .replace("prompts/default.md", "prompts/does-not-exist.md"),
        encoding="utf-8",
    )
    code = cli(
        [
            "--config-dir",
            str(config_dir),
            "--data-dir",
            str(tmp_path / "data"),
            "--output",
            "json",
            "doctor",
            "--no-network",
        ]
    )
    captured = capsys.readouterr()
    assert code == EXIT_CONFIG
    checks = _checks(captured.out)
    assert checks["config.validate"]["status"] == "fail"
