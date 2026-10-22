"""兼容性测试：旧 sources.json / llm.config.json 自动迁移为 YAML。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from qf_wire.config.loader import load_config
from qf_wire.config.migrate import MIGRATED_MARKER, migrate_legacy
from qf_wire.config.validator import validate_config_dir

LEGACY_SOURCES: dict[str, Any] = {
    "industries": [
        {
            "key": "半导体",
            "name": "半导体",
            "accent": "#4F46E5",
            "keywords": ["芯片", "晶圆"],
            "sources": [
                {"hint": "semi_feed", "name": "Semi Feed", "type": "rss", "url": "https://example.com/semi.xml"},
                {"hint": "semi_web", "name": "Semi Web", "type": "web", "url": "https://example.com/semi"},
            ],
        },
        {
            "key": "人工智能",
            "name": "人工智能",
            "sources": [
                {"hint": "ai_feed", "name": "AI Feed", "type": "rss", "url": "https://example.com/ai.xml"}
            ],
        },
    ]
}

LEGACY_LLM: dict[str, Any] = {
    "provider": "openai",
    "baseUrl": "https://api.example.com/v1",
    "model": "gpt-4o-mini",
    "apiKey": "sk-test-secret-123",
}


def _write_legacy(root: Path) -> Path:
    legacy = root / "legacy"
    legacy.mkdir(parents=True)
    (legacy / "sources.json").write_text(json.dumps(LEGACY_SOURCES, ensure_ascii=False), encoding="utf-8")
    (legacy / "llm.config.json").write_text(json.dumps(LEGACY_LLM, ensure_ascii=False), encoding="utf-8")
    return legacy


def _prepare_prompt(root: Path) -> None:
    prompts = root / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    (prompts / "default.md").write_text("# 默认提炼提示词\n", encoding="utf-8")


def _read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_migrates_legacy_files_to_valid_yaml(tmp_path: Path) -> None:
    legacy = _write_legacy(tmp_path)
    config_dir = tmp_path / "config"
    _prepare_prompt(tmp_path)

    report = migrate_legacy(legacy, config_dir=config_dir)

    assert not report.skipped
    assert report.topic_count == 2
    assert report.source_count == 3
    assert (config_dir / MIGRATED_MARKER).is_file()

    topics = _read_yaml(config_dir / "topics.yaml")["topics"]
    semiconductor = next(item for item in topics if item["id"] == "semiconductor")
    assert semiconductor["legacy_key"] == "半导体"
    assert semiconductor["aliases"] == ["半导体"]
    assert semiconductor["name"] == "半导体"
    assert semiconductor["accent"] == "#4F46E5"
    assert semiconductor["keywords"] == ["芯片", "晶圆"]
    assert sorted(semiconductor["sources"]) == ["semi_feed", "semi_web"]
    assert len({item["id"] for item in topics}) == len(topics)

    sources = _read_yaml(config_dir / "sources.yaml")
    assert sources["version"] == 1
    by_id = {item["id"]: item for item in sources["sources"]}
    assert by_id["semi_feed"]["topic"] == "semiconductor"
    assert by_id["semi_feed"]["url"] == "https://example.com/semi.xml"
    assert by_id["semi_web"]["type"] == "html"
    assert by_id["ai_feed"]["topic"] == "ai"

    digest = _read_yaml(config_dir / "digest.yaml")["digest"]
    assert digest["provider"] == "api"
    assert digest["default_model"] == "gpt-4o-mini"
    assert digest["api_base"] == "https://api.example.com/v1"
    assert digest["api_key_env"] == "QF_WIRE_LLM_API_KEY"
    assert digest["topics"]["default"]["prompt_file"] == "prompts/default.md"

    for path in config_dir.rglob("*.yaml"):
        assert "sk-test-secret-123" not in path.read_text(encoding="utf-8")

    report_validation = validate_config_dir(config_dir)
    assert report_validation.ok, report_validation.as_dict()

    config = load_config(config_dir=config_dir, data_dir=tmp_path / "data")
    assert config.topic("半导体").id == "semiconductor"
    assert config.topic("semiconductor").id == "semiconductor"
    assert [source.id for source in config.sources_for(config.topic("半导体"))] == ["semi_feed", "semi_web"]


def test_second_migration_is_skipped(tmp_path: Path) -> None:
    legacy = _write_legacy(tmp_path)
    config_dir = tmp_path / "config"
    _prepare_prompt(tmp_path)

    migrate_legacy(legacy, config_dir=config_dir)
    topics_path = config_dir / "topics.yaml"
    before = topics_path.read_text(encoding="utf-8")

    second = migrate_legacy(legacy, config_dir=config_dir)

    assert second.skipped
    assert any("跳过" in line for line in second.lines)
    assert topics_path.read_text(encoding="utf-8") == before


def test_existing_yaml_is_preserved_and_extended(tmp_path: Path) -> None:
    legacy = _write_legacy(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _prepare_prompt(tmp_path)

    (config_dir / "topics.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "topics": [
                    {
                        "id": "semiconductor",
                        "name": "用户自定义半导体",
                        "keywords": ["自定义关键词"],
                        "sources": ["semi_feed"],
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config_dir / "digest.yaml").write_text(
        yaml.safe_dump(
            {"digest": {"version": 1, "provider": "claude-cli", "default_model": "user-model", "topics": {
                "default": {"prompt_file": "prompts/default.md", "output_schema": "TopicDigest"}
            }}},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    digest_before = (config_dir / "digest.yaml").read_text(encoding="utf-8")

    report = migrate_legacy(legacy, config_dir=config_dir)

    topics = _read_yaml(config_dir / "topics.yaml")["topics"]
    kept = next(item for item in topics if item["id"] == "semiconductor")
    assert kept["name"] == "用户自定义半导体"
    assert [item["id"] for item in topics if item["id"] == "semiconductor"] == ["semiconductor"]
    assert any(item["id"] == "ai" for item in topics)
    assert report.topic_count == 1
    assert (config_dir / "digest.yaml").read_text(encoding="utf-8") == digest_before
