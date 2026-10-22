"""提炼策略：按赛道 prompt / model / output_schema 可配置且互相隔离。"""
from __future__ import annotations

import json
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from qf_wire.config.loader import load_config
from qf_wire.core.errors import ConfigError
from qf_wire.core.models import SourceItem
from qf_wire.pipeline import digest as digest_module
from qf_wire.pipeline.digest import build_prompt, digest_topic
from tests.fixtures.configs import write_config

DAY = date(2026, 10, 22)
NOW = datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc)

TOPICS = [
    {"id": "semi", "name": "半导体", "keywords": ["芯片"], "sources": ["feed_a"]},
    {"id": "macro", "name": "宏观", "keywords": ["利率"], "sources": ["feed_a"]},
]

DIGEST = {
    "digest": {
        "version": 1,
        "provider": "claude-cli",
        "default_model": "base-model",
        "language": "zh",
        "max_items_per_topic": 5,
        "timeout_sec": 5,
        "retries": 0,
        "output_schema": "TopicDigest",
        "topics": {
            "default": {
                "prompt_file": "prompts/default.md",
                "output_schema": "TopicDigest",
                "model": "base-model",
            },
            "semi": {
                "prompt_file": "prompts/semiconductor.md",
                "output_schema": "TopicDigest",
                "model": "semi-model",
            },
            "macro": {
                "prompt_file": "prompts/policy.md",
                "output_schema": "BriefDigest",
                "model": "macro-model",
            },
        },
    }
}


def _item(topic: str, title: str, url: str) -> SourceItem:
    return SourceItem(
        title=title,
        url=url,
        source_id="feed_a",
        topic=topic,
        summary="summary",
        published_at=NOW,
        sources=["feed_a"],
    )


@pytest.fixture()
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("QF_WIRE_ROOT", str(tmp_path))
    config_dir = write_config(tmp_path, topics=TOPICS, digest=DIGEST)
    prompts = tmp_path / "prompts"
    (prompts / "semiconductor.md").write_text("# SEMI-MARKER 先列产能与制程\n", encoding="utf-8")
    (prompts / "policy.md").write_text("# POLICY-MARKER 先列政策与时间表\n", encoding="utf-8")
    return load_config(config_dir)


@pytest.fixture()
def fake_claude(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured.setdefault("commands", []).append(command)
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(
                {
                    "summary": "模型摘要",
                    "key_points": [{"text": "模型要点", "sources": ["feed_a"]}],
                    "items": [{"title": "模型条目", "url": "https://example.com/model"}],
                },
                ensure_ascii=False,
            ),
            stderr="",
        )

    monkeypatch.setenv("QF_WIRE_CLAUDE_BIN", "fake-claude")
    monkeypatch.setattr(digest_module.subprocess, "run", fake_run)
    return captured


def test_prompts_differ_per_topic(config) -> None:
    semi = build_prompt(config, config.topic("semi"), DAY, [_item("semi", "标题", "https://e/1")])
    macro = build_prompt(config, config.topic("macro"), DAY, [_item("macro", "标题", "https://e/2")])

    assert "SEMI-MARKER" in semi
    assert "POLICY-MARKER" in macro
    assert "SEMI-MARKER" not in macro
    assert semi != macro


def test_topic_model_and_schema_are_applied(config, fake_claude: dict[str, Any]) -> None:
    semi = digest_topic(
        config.topic("semi"), DAY, [_item("semi", "Fab news", "https://e/1")], config
    )
    macro = digest_topic(
        config.topic("macro"), DAY, [_item("macro", "Rate news", "https://e/2")], config
    )

    semi_command = fake_claude["commands"][0]
    macro_command = fake_claude["commands"][1]
    assert semi_command[:3] == ["fake-claude", "--model", "semi-model"]
    assert macro_command[:3] == ["fake-claude", "--model", "macro-model"]
    assert "SEMI-MARKER" in semi_command[-1]
    assert "POLICY-MARKER" in macro_command[-1]

    assert semi.model == "semi-model"
    assert semi.items[0].title == "模型条目"
    assert macro.model == "macro-model"
    # BriefDigest 不接收条目字段，条目回落到本地采集数据
    assert macro.items[0].title == "Rate news"


def test_placeholder_model_is_not_forwarded(config, fake_claude: dict[str, Any]) -> None:
    config.digest.default_model = "user-model"
    config.digest.topics["semi"] = {
        "prompt_file": "prompts/semiconductor.md",
        "output_schema": "TopicDigest",
        "model": "user-model",
    }
    digest = digest_topic(
        config.topic("semi"), DAY, [_item("semi", "Fab news", "https://e/1")], config
    )

    command = fake_claude["commands"][0]
    assert command[0] == "fake-claude"
    assert "--model" not in command
    assert digest.model is None


def test_api_provider_requires_real_model(config, monkeypatch: pytest.MonkeyPatch) -> None:
    config.digest.provider = "api"
    config.digest.default_model = "user-model"
    config.digest.topics["semi"] = {
        "prompt_file": "prompts/semiconductor.md",
        "output_schema": "TopicDigest",
        "model": "user-model",
    }
    monkeypatch.setenv("QF_WIRE_API_KEY", "test-key")

    digest = digest_topic(
        config.topic("semi"), DAY, [_item("semi", "Fab news", "https://e/1")], config
    )

    assert digest.status == "partial"
    assert "未配置模型名" in (digest.error or "")


def test_unknown_output_schema_is_config_error(config) -> None:
    config.digest.topics["semi"] = {
        "prompt_file": "prompts/semiconductor.md",
        "output_schema": "Freeform",
    }
    with pytest.raises(ConfigError):
        digest_topic(config.topic("semi"), DAY, [_item("semi", "x", "https://e/1")], config)
