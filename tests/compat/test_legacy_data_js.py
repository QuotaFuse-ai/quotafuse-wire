"""兼容性测试：data.js 继续输出旧看板的 window.DATA 结构。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from qf_wire.core.models import KeyPoint, SourceItem, Topic, TopicDigest
from qf_wire.pipeline.render import build_dashboard_payload, render_data_js, write_data_js
from qf_wire.sources.base import FetchResult


def _topic() -> Topic:
    return Topic(
        id="semi",
        name="半导体",
        legacy_key="半导体",
        aliases=["semiconductor"],
        keywords=["芯片"],
        sources=["feed_a"],
    )


def _item() -> SourceItem:
    return SourceItem(
        title="某芯片厂商发布新品",
        url="https://example.com/news/1",
        source_id="feed_a",
        topic="semi",
        summary="新品发布",
        zh="某芯片厂商发布新品",
        published_at=datetime(2026, 10, 21, 7, 0, tzinfo=timezone.utc),
        sources=["feed_a", "feed_b"],
        event_id="evt-1",
        confidence="high",
    )


def _digest() -> TopicDigest:
    return TopicDigest(
        topic="semi",
        date=datetime(2026, 10, 21).date(),
        summary="今日要点",
        key_points=[KeyPoint(text="要点一", sources=["feed_a"], confidence="high", event_id="evt-1")],
        generated_at=datetime(2026, 10, 21, 8, 0, tzinfo=timezone.utc),
    )


def _payload() -> dict:
    return build_dashboard_payload(
        [_topic()],
        {"semi": [_item()]},
        digests={"semi": _digest()},
        source_results=[
            FetchResult(source_id="feed_a", source_name="Feed A", topic="semi", status="ok", items=[_item()]),
            FetchResult(
                source_id="broken",
                source_name="Broken Feed",
                topic="semi",
                status="unavailable",
                error="超时: https://example.com/broken",
            ),
        ],
        generated_at=datetime(2026, 10, 21, 8, 30, tzinfo=timezone.utc),
    )


def test_legacy_window_data_shape() -> None:
    payload = _payload()
    industry = payload["industries"][0]

    assert industry["key"] == "半导体"
    assert industry["id"] == "semi"
    assert industry["name"] == "半导体"
    assert isinstance(industry["accent"], str) and industry["accent"].startswith("#")
    assert industry["summary"] == "今日要点"
    assert industry["key_points"][0]["text"] == "要点一"

    item = industry["items"][0]
    for field in ("title", "url", "time", "ts", "summary", "source", "zh"):
        assert field in item
    assert item["url"] == "https://example.com/news/1"
    assert item["source"] == "feed_a"
    assert item["ts"] > 0
    # 新增字段只增不改
    assert item["event_id"] == "evt-1"
    assert item["source_count"] == 2
    assert item["confidence"] == "high"

    assert payload["sourceNotice"] == ["Broken Feed：该源今日不可用"]
    assert [entry["status"] for entry in payload["sourceStatus"]] == ["ok", "unavailable"]


def test_render_data_js_is_parseable_js_assignment() -> None:
    text = render_data_js(_payload())

    assert text.startswith("window.DATA = ")
    assert text.rstrip().endswith(";")
    data = json.loads(text[len("window.DATA = ") :].strip().rstrip(";"))
    assert data["industries"][0]["key"] == "半导体"
    assert "generatedAt" in data


def test_write_data_js_is_atomic_and_utf8(tmp_path: Path) -> None:
    target = tmp_path / "data" / "data.js"
    write_data_js(target, _payload())

    text = target.read_text(encoding="utf-8")
    assert "半导体" in text
    assert not list(target.parent.glob("*.tmp"))
