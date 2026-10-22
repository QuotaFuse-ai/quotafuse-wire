"""模型网关：provider=gateway 的调用、降级链与密钥保密。"""
from __future__ import annotations

import json
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from qf_wire.config.loader import load_config
from qf_wire.core.models import SourceItem
from qf_wire.pipeline import digest as digest_module
from qf_wire.pipeline.digest import DigestUnavailable, digest_topic
from tests.fixtures.configs import write_config

DAY = date(2026, 10, 22)
NOW = datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc)
GATEWAY_KEY = "gw-secret-9f3a"

TOPICS = [{"id": "semi", "name": "半导体", "keywords": ["芯片"], "sources": ["feed_a"]}]


def _digest_config(provider: str = "gateway", base_url: str = "http://gateway.test/v1") -> dict[str, Any]:
    return {
        "digest": {
            "version": 1,
            "provider": provider,
            "default_model": "gw-model",
            "language": "zh",
            "max_items_per_topic": 5,
            "timeout_sec": 5,
            "retries": 0,
            "output_schema": "TopicDigest",
            "gateway": {
                "base_url": base_url,
                "api_key_env": "QF_WIRE_MODEL_GATEWAY_KEY",
            },
            "topics": {
                "default": {
                    "prompt_file": "prompts/default.md",
                    "output_schema": "TopicDigest",
                    "model": "gw-model",
                }
            },
        }
    }


def _item() -> SourceItem:
    return SourceItem(
        title="Fab news",
        url="https://example.com/1",
        source_id="feed_a",
        topic="semi",
        summary="summary",
        published_at=NOW,
        sources=["feed_a"],
    )


MODEL_OUTPUT = json.dumps(
    {
        "summary": "网关摘要",
        "key_points": [{"text": "网关要点", "sources": ["feed_a"]}],
        "items": [{"title": "网关条目", "url": "https://example.com/gw"}],
    },
    ensure_ascii=False,
)


@pytest.fixture()
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("QF_WIRE_ROOT", str(tmp_path))
    config_dir = write_config(tmp_path, topics=TOPICS, digest=_digest_config())
    monkeypatch.delenv("QF_WIRE_CLAUDE_BIN", raising=False)
    monkeypatch.delenv("QF_WIRE_MODEL_GATEWAY_URL", raising=False)
    monkeypatch.delenv("QF_WIRE_MODEL_GATEWAY_KEY", raising=False)
    return load_config(config_dir)


def _capture_post(monkeypatch: pytest.MonkeyPatch, result: str | Exception) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_post(base: str, key: str, prompt: str, model: str | None, timeout_sec: int, *, label: str) -> str:
        captured.update(base=base, key=key, prompt=prompt, model=model, timeout=timeout_sec, label=label)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(digest_module, "_post_chat", fake_post)
    return captured


def test_gateway_success_uses_env_key(config, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QF_WIRE_MODEL_GATEWAY_KEY", GATEWAY_KEY)
    captured = _capture_post(monkeypatch, MODEL_OUTPUT)

    digest = digest_topic(config.topic("semi"), DAY, [_item()], config)

    assert digest.status == "ok"
    assert digest.items[0].title == "网关条目"
    assert captured["base"] == "http://gateway.test/v1"
    assert captured["key"] == GATEWAY_KEY
    assert captured["model"] == "gw-model"
    assert captured["label"] == "模型网关"


def test_gateway_never_logs_key(config, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QF_WIRE_MODEL_GATEWAY_KEY", GATEWAY_KEY)
    _capture_post(monkeypatch, DigestUnavailable("模型网关 HTTP 502"))
    logged: list[str] = []
    monkeypatch.setattr(digest_module.logger, "warning", lambda msg, *args: logged.append(msg % args))
    monkeypatch.setattr(digest_module.shutil, "which", lambda _name: None)

    digest = digest_topic(config.topic("semi"), DAY, [_item()], config)

    assert digest.status == "partial"
    assert digest.fallback is True
    assert logged, "降级过程应有日志"
    assert all(GATEWAY_KEY not in message for message in logged)
    assert GATEWAY_KEY not in (digest.error or "")


def test_gateway_falls_back_to_claude_cli(config, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QF_WIRE_MODEL_GATEWAY_KEY", GATEWAY_KEY)
    _capture_post(monkeypatch, DigestUnavailable("模型网关 HTTP 503"))
    monkeypatch.setattr(digest_module.shutil, "which", lambda _name: "fake-claude")
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=MODEL_OUTPUT, stderr="")

    monkeypatch.setattr(digest_module.subprocess, "run", fake_run)

    digest = digest_topic(config.topic("semi"), DAY, [_item()], config)

    assert digest.status == "ok"
    assert commands and commands[0][0] == "fake-claude"
    assert digest.items[0].title == "网关条目"


def test_gateway_and_claude_both_fail_is_partial(config, monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_post(monkeypatch, DigestUnavailable("模型网关不可达"))
    monkeypatch.setattr(digest_module.shutil, "which", lambda _name: None)

    digest = digest_topic(config.topic("semi"), DAY, [_item()], config)

    assert digest.status == "partial"
    assert digest.fallback is True
    assert digest.key_points == []
    assert digest.items[0].title == "Fab news"
    assert digest.error


def test_unresolved_gateway_placeholder_degrades(config, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QF_WIRE_ROOT", str(config.paths.root))
    config.digest.topics["default"]["gateway_base_url"] = "${QF_WIRE_MODEL_GATEWAY_URL}"
    monkeypatch.setattr(digest_module.shutil, "which", lambda _name: None)
    logged: list[str] = []
    monkeypatch.setattr(digest_module.logger, "warning", lambda msg, *args: logged.append(msg % args))

    digest = digest_topic(config.topic("semi"), DAY, [_item()], config)

    assert digest.status == "partial"
    assert any("模型网关地址" in message for message in logged)


def test_gateway_config_expands_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QF_WIRE_ROOT", str(tmp_path))
    monkeypatch.setenv("QF_WIRE_MODEL_GATEWAY_URL", "http://gw.local/v1")
    config_dir = write_config(
        tmp_path,
        topics=TOPICS,
        digest=_digest_config(base_url="${QF_WIRE_MODEL_GATEWAY_URL}"),
    )

    settings = load_config(config_dir).digest

    assert settings.gateway_base_url == "http://gw.local/v1"
    assert settings.gateway_api_key_env == "QF_WIRE_MODEL_GATEWAY_KEY"
