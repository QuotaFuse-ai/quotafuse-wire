"""写入一份可查询的本地归档，供 Provider / MCP 契约测试复用。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from qf_wire.core.models import DigestItem, Event, KeyPoint, SourceItem, TopicDigest
from qf_wire.sources.base import FetchResult
from qf_wire.storage.sqlite import WireStore

EVENT_ID = "evt_20261022_1a2b3c"
KEYWORD = "芯片"


def seed_wire_data(data_dir: Path, *, topic: str = "semi") -> dict[str, str]:
    """写入两条条目、一个双源事件和一条提炼结果，返回关键 id。"""
    data_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    day = now.date()
    item_a = SourceItem(
        title="晶圆厂宣布扩产",
        url="https://example.com/news/a",
        source_id="feed_a",
        topic=topic,
        summary="芯片产能继续扩张",
        zh="晶圆厂宣布扩产",
        published_at=now - timedelta(hours=2),
        sources=["feed_a"],
        event_id=EVENT_ID,
        confidence="high",
    )
    item_b = SourceItem(
        title="设备商确认新增订单",
        url="https://example.com/news/b",
        source_id="feed_b",
        topic=topic,
        summary="芯片设备订单增加",
        zh="设备商确认新增订单",
        published_at=now - timedelta(hours=1),
        sources=["feed_b"],
        event_id=EVENT_ID,
        confidence="high",
    )
    event = Event(
        event_id=EVENT_ID,
        topic=topic,
        title="晶圆厂扩产带动芯片设备订单",
        sources=["feed_a", "feed_b"],
        source_count=2,
        confidence="high",
        first_seen=item_a.published_at,
        last_seen=item_b.published_at,
    )
    digest = TopicDigest(
        topic=topic,
        date=day,
        summary="两家信源确认芯片扩产与设备订单。",
        key_points=[
            KeyPoint(
                text="晶圆厂扩产带动设备订单",
                sources=["feed_a", "feed_b"],
                confidence="high",
                event_id=EVENT_ID,
            )
        ],
        items=[
            DigestItem(
                title=item_a.title,
                url=item_a.url,
                source="feed_a",
                published_at=item_a.published_at,
                zh=item_a.zh,
                summary=item_a.summary,
                event_id=EVENT_ID,
            )
        ],
        generated_at=now,
        provider="claude-cli",
        model="test-model",
        status="ok",
    )

    store = WireStore(data_dir / "wire.db")
    try:
        store.record_run(
            run_id=f"run-{day.isoformat()}",
            day=day,
            topic=topic,
            mode="full",
            status="ok",
            exit_code=0,
            started_at=now,
            finished_at=now,
            results=[
                FetchResult(source_id="feed_a", source_name="Feed A", topic=topic, status="ok", items=[item_a]),
                FetchResult(source_id="feed_b", source_name="Feed B", topic=topic, status="ok", items=[item_b]),
            ],
            items_by_topic={topic: [item_a, item_b]},
            events_by_topic={topic: [event]},
            digests=[digest],
        )
    finally:
        store.close()
    return {"event_id": EVENT_ID, "day": day.isoformat()}
