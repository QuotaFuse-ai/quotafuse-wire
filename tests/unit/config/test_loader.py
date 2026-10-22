"""配置加载单元测试：赛道别名、信源查询、缺失文件。"""
from __future__ import annotations

import pytest

from qf_wire.config.loader import load_config
from qf_wire.core.errors import ConfigError
from tests.fixtures.configs import write_config


def test_load_config_and_resolve_alias(tmp_path) -> None:
    config_dir = write_config(tmp_path)
    config = load_config(config_dir=config_dir)

    topic = config.topic("semiconductor")
    assert topic.id == "semi"
    assert topic.name == "半导体"
    assert [source.id for source in config.sources_for(topic)] == ["feed_a"]
    assert config.find_topic("missing") is None


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
