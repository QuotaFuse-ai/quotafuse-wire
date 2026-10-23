"""`qfw config migrate` 必须在干净的配置目录上可用（QUOT-43 P1-2 / P1-3）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from qf_wire.cli.main import cli
from qf_wire.core.errors import EXIT_OK

LEGACY_SOURCES = {
    "industries": [
        {
            "key": "半导体",
            "name": "半导体",
            "keywords": ["芯片"],
            "sources": [
                {"hint": "semi", "name": "Semi Feed", "type": "rss", "url": "https://example.com/semi.xml"}
            ],
        }
    ]
}

LEGACY_LLM = {
    "provider": "openai",
    "baseUrl": "https://api.example.com/v1",
    "model": "gpt-4o-mini",
}


def _write_legacy(root: Path) -> Path:
    legacy = root / "legacy"
    legacy.mkdir(parents=True)
    (legacy / "sources.json").write_text(json.dumps(LEGACY_SOURCES, ensure_ascii=False), encoding="utf-8")
    (legacy / "llm.config.json").write_text(json.dumps(LEGACY_LLM), encoding="utf-8")
    return legacy


def test_config_migrate_runs_on_clean_config_dir(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    legacy = _write_legacy(tmp_path)
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    base = ["--config-dir", str(config_dir), "--data-dir", str(data_dir)]

    assert cli([*base, "config", "migrate", "--legacy-dir", str(legacy)]) == EXIT_OK
    assert (config_dir / "topics.yaml").is_file()
    assert (config_dir / "sources.yaml").is_file()
    assert (config_dir / "digest.yaml").is_file()
    # 迁移生成的 digest.yaml 引用 prompts/default.md，提示词必须一并落盘
    assert (tmp_path / "prompts" / "default.md").is_file()

    assert cli([*base, "config", "validate"]) == EXIT_OK
