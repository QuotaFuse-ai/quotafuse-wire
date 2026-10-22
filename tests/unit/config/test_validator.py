"""配置校验单元测试：JSON Schema、引用完整性、cron。"""
from __future__ import annotations

import copy

from qf_wire.config.validator import validate_config_dir
from tests.fixtures.configs import DEFAULT_SOURCES, DEFAULT_TOPICS, write_config


def _messages(report) -> list[str]:
    return [issue.message for issue in report.issues]


def test_valid_config_passes(tmp_path) -> None:
    config_dir = write_config(tmp_path)
    report = validate_config_dir(config_dir)

    assert report.ok, report.as_dict()
    assert report.errors == []


def test_unknown_source_reference_is_error(tmp_path) -> None:
    topics = copy.deepcopy(DEFAULT_TOPICS)
    topics[0]["sources"] = ["ghost_feed"]
    config_dir = write_config(tmp_path, topics=topics)

    report = validate_config_dir(config_dir)

    assert not report.ok
    assert any("引用了不存在的信源: ghost_feed" in message for message in _messages(report))


def test_duplicate_source_ids_are_errors(tmp_path) -> None:
    sources = copy.deepcopy(DEFAULT_SOURCES)
    sources.append({**copy.deepcopy(DEFAULT_SOURCES[0]), "url": "https://example.com/other.xml"})
    config_dir = write_config(tmp_path, sources=sources)

    report = validate_config_dir(config_dir)

    assert not report.ok
    assert any("重复 id" in message for message in _messages(report))


def test_schema_rejects_invalid_timeout_and_type(tmp_path) -> None:
    sources = copy.deepcopy(DEFAULT_SOURCES)
    sources[0]["timeout_sec"] = 0
    sources[0]["type"] = "ftp"
    config_dir = write_config(tmp_path, sources=sources)

    report = validate_config_dir(config_dir)

    assert not report.ok
    messages = " ".join(_messages(report))
    assert "timeout_sec" in messages or "0" in messages
    assert "ftp" in messages


def test_bad_cron_is_error(tmp_path) -> None:
    schedule = {
        "schedule": {
            "version": 1,
            "jobs": [{"id": "daily", "cron": "0 7 * *", "command": "run"}],
        }
    }
    config_dir = write_config(tmp_path, schedule=schedule)

    report = validate_config_dir(config_dir)

    assert not report.ok
    assert any("cron 需要 5 个字段" in message for message in _messages(report))


def test_missing_prompt_file_is_error(tmp_path) -> None:
    digest = {
        "digest": {
            "provider": "claude-cli",
            "default_model": "test-model",
            "topics": {
                "default": {
                    "prompt_file": "prompts/does_not_exist.md",
                    "output_schema": "TopicDigest",
                }
            },
        }
    }
    config_dir = write_config(tmp_path, digest=digest)

    report = validate_config_dir(config_dir)

    assert not report.ok
    assert any("提示词文件不存在" in message for message in _messages(report))


def test_missing_source_topic_is_warning(tmp_path) -> None:
    sources = copy.deepcopy(DEFAULT_SOURCES)
    sources[0]["topic"] = "unknown_topic"
    config_dir = write_config(tmp_path, sources=sources)

    report = validate_config_dir(config_dir)

    assert report.ok
    assert any("未在 topics.yaml 中定义" in message for message in _messages(report))
