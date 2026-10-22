"""测试用配置与 RSS fixture。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_TOPICS: list[dict[str, Any]] = [
    {
        "id": "semi",
        "name": "半导体",
        "legacy_key": "semi",
        "aliases": ["semiconductor"],
        "keywords": ["芯片"],
        "sources": ["feed_a"],
    }
]

DEFAULT_SOURCES: list[dict[str, Any]] = [
    {
        "id": "feed_a",
        "name": "Feed A",
        "topic": "semi",
        "type": "rss",
        "url": "http://127.0.0.1:1/feed.xml",
        "timeout_sec": 1,
        "retries": 0,
    }
]

DEFAULT_DIGEST: dict[str, Any] = {
    "digest": {
        "version": 1,
        "provider": "claude-cli",
        "default_model": "test-model",
        "language": "zh",
        "max_items_per_topic": 5,
        "topics": {
            "default": {
                "prompt_file": "prompts/default.md",
                "output_schema": "TopicDigest",
                "model": "test-model",
            }
        },
    }
}

DEFAULT_SCHEDULE: dict[str, Any] = {
    "schedule": {
        "version": 1,
        "enabled": False,
        "timezone": "Asia/Shanghai",
        "jobs": [
            {"id": "daily_run", "cron": "0 7 * * *", "command": "run", "options": {}, "enabled": True}
        ],
    }
}

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Fixture Feed</title>
    <item>
      <title>Fixture chip maker reports record quarter</title>
      <link>{base}/news/1</link>
      <description>Record revenue driven by advanced packaging demand.</description>
      <pubDate>Wed, 21 Oct 2026 07:28:00 GMT</pubDate>
    </item>
    <item>
      <title>New fab breaks ground in the region</title>
      <link>{base}/news/2</link>
      <description>Construction scheduled to finish next year.</description>
      <pubDate>Wed, 21 Oct 2026 08:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


def write_config(
    tmp_path: Path,
    *,
    topics: list[dict[str, Any]] | None = None,
    sources: list[dict[str, Any]] | None = None,
    digest: dict[str, Any] | None = None,
    schedule: dict[str, Any] | None = None,
) -> Path:
    """在 tmp_path 下写出最小可用配置目录，并返回 config_dir。"""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "prompts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prompts" / "default.md").write_text("# test prompt\n", encoding="utf-8")

    documents = {
        "topics.yaml": {"version": 1, "topics": topics if topics is not None else DEFAULT_TOPICS},
        "sources.yaml": {
            "version": 1,
            "defaults": {"timeout_sec": 15, "retries": 2},
            "sources": sources if sources is not None else DEFAULT_SOURCES,
        },
        "digest.yaml": digest if digest is not None else DEFAULT_DIGEST,
        "schedule.yaml": schedule if schedule is not None else DEFAULT_SCHEDULE,
    }
    for name, payload in documents.items():
        (config_dir / name).write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    return config_dir
