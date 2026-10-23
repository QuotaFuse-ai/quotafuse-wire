"""配置加载单元测试：赛道别名、信源查询、缺失文件、聚类阈值。"""
from __future__ import annotations

from copy import deepcopy

import pytest

from qf_wire.config.loader import load_config
from qf_wire.core.cluster import ClusterSettings
from qf_wire.core.errors import ConfigError
from tests.fixtures.configs import DEFAULT_DIGEST, write_config


def test_load_config_and_resolve_alias(tmp_path) -> None:
    config_dir = write_config(tmp_path)
    config = load_config(config_dir=config_dir)

    topic = config.topic("semiconductor")
    assert topic.id == "semi"
    assert topic.name == "半导体"
    assert [source.id for source in config.sources_for(topic)] == ["feed_a"]
    assert config.find_topic("missing") is None
    assert config.cluster == ClusterSettings()


def test_load_config_missing_yaml_raises(tmp_path) -> None:
    config_dir = write_config(tmp_path)
    (config_dir / "digest.yaml").unlink()

    with pytest.raises(ConfigError):
        load_config(config_dir=config_dir)


def test_load_config_rejects_dangling_source(tmp_path) -> None:
    topics = [
        {
            "id": "semi",
            "name": "半导体",
            "keywords": ["芯片"],
            "sources": ["ghost"],
        }
    ]
    config_dir = write_config(tmp_path, topics=topics)

    with pytest.raises(ConfigError):
        load_config(config_dir=config_dir)


def test_load_config_reads_cluster_settings(tmp_path) -> None:
    digest = deepcopy(DEFAULT_DIGEST)
    digest["cluster"] = {"similarity_threshold": 0.42, "window_hours": 12}
    config = load_config(config_dir=write_config(tmp_path, digest=digest))

    assert config.cluster.similarity_threshold == 0.42
    assert config.cluster.window_hours == 12
    assert config.cluster.simhash_threshold == ClusterSettings().simhash_threshold


def test_load_config_rejects_invalid_cluster_settings(tmp_path) -> None:
    digest = deepcopy(DEFAULT_DIGEST)
    digest["cluster"] = {"similarity_threshold": 1.4}
    config_dir = write_config(tmp_path, digest=digest)

    with pytest.raises(ConfigError, match="cluster"):
        load_config(config_dir=config_dir)


def test_openai_model_env_only_applies_to_api_provider(tmp_path, monkeypatch, isolated_env) -> None:
    for name in ("QF_WIRE_DIGEST_MODEL", "LLM_MODEL", "QF_WIRE_DIGEST_PROVIDER", "LLM_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_MODEL", "deepseek-v4.1-flash")

    claude_settings = load_config(write_config(tmp_path / "claude")).digest
    assert claude_settings.provider == "claude-cli"
    assert claude_settings.default_model == "test-model"

    api_digest = {
        "digest": {
            "version": 1,
            "provider": "api",
            "default_model": "user-model",
            "language": "zh",
            "topics": {
                "default": {"prompt_file": "prompts/default.md", "output_schema": "TopicDigest"}
            },
        }
    }
    api_settings = load_config(write_config(tmp_path / "api", digest=api_digest)).digest
    assert api_settings.provider == "api"
    assert api_settings.default_model == "deepseek-v4.1-flash"
