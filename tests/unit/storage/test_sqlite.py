"""SQLite 存储单元测试：迁移、幂等写入、历史与事件。"""
from __future__ import annotations

from datetime import date, datetime, timezone

from qf_wire.core.models import DigestItem, Event, KeyPoint, SourceItem, TopicDigest
from qf_wire.sources.base import FetchResult
from qf_wire.storage.sqlite import WireStore, split_sql

DAY1 = date(2026, 10, 21)
DAY2 = date(2026, 10, 22)
NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def _item(url: str, title: str, **overrides: object) -> SourceItem:
    payload = {
        "title": title,
        "url": url,
        "source_id": "feed_a",
        "topic": "semi",
        "summary": "summary",
        "published_at": NOW,
        "sources": ["feed_a"],
        "confidence": "medium",
    }
    payload.update(overrides)
    return SourceItem(**payload)  # type: ignore[arg-type]


def _result(source_id: str, status: str, items: list[SourceItem] | None = None) -> FetchResult:
    return FetchResult(
        source_id=source_id,
        source_name=source_id.upper(),
        topic="semi",
        status=status,  # type: ignore[arg-type]
        items=items or [],
        error="HTTP 500" if status == "unavailable" else None,
        attempts=1,
    )


def test_split_sql_skips_comments() -> None:
    script = "-- leading comment\nCREATE TABLE a (id INTEGER);\n\n-- another\nSELECT 1;\n"
    statements = split_sql(script)
    assert len(statements) == 2
    assert statements[0].startswith("CREATE TABLE")
    assert statements[1] == "SELECT 1;"


def test_initialize_applies_migrations(tmp_path) -> None:
    store = WireStore(tmp_path / "wire.db")
    try:
        store.initialize()
        store.initialize()  # 幂等
        with store.engine.connect() as conn:
            versions = [row[0] for row in conn.exec_driver_sql("SELECT version FROM schema_migrations")]
        assert "0001_init" in versions
    finally:
        store.close()


def test_record_run_and_query_history(tmp_path) -> None:
    store = WireStore(tmp_path / "wire.db")
    try:
        item1 = _item("https://example.com/1", "Day one headline")
        store.record_run(
            run_id="run-1",
            day=DAY1,
            topic="semi",
            mode="sources",
            status="ok",
            exit_code=0,
            started_at=NOW,
            finished_at=NOW,
            results=[_result("feed_a", "ok", [item1])],
            items_by_topic={"semi": [item1]},
            events_by_topic={},
        )

        item2 = _item("https://example.com/2", "Day two headline", event_id="evt-1")
        item3 = _item(
            "https://example.com/3",
            "Another day two headline",
            source_id="feed_b",
            sources=["feed_b"],
            event_id="evt-1",
            confidence="high",
        )
        event = Event(
            event_id="evt-1",
            topic="semi",
            title="Clustered event",
            items=[item2, item3],
            sources=["feed_a", "feed_b"],
            source_count=2,
            confidence="high",
            first_seen=NOW,
            last_seen=NOW,
        )
        digest = TopicDigest(
            topic="semi",
            date=DAY2,
            summary="当日摘要",
            key_points=[KeyPoint(text="关键要点", sources=["feed_a"], confidence="high")],
            items=[DigestItem(title=item2.title, url=item2.url, zh="中文标题", summary="中文摘要")],
            provider="claude-cli",
            model="test-model",
            partial=True,
            status="partial",
        )
        store.record_run(
            run_id="run-2",
            day=DAY2,
            topic="semi",
            mode="sources",
            status="partial",
            exit_code=8,
            started_at=NOW,
            finished_at=NOW,
            results=[_result("feed_a", "ok", [item2]), _result("feed_b", "unavailable")],
            items_by_topic={"semi": [item2, item3]},
            events_by_topic={"semi": [event]},
            digests=[digest],
        )

        assert store.count_items(DAY1) == 1
        assert store.count_items(DAY2) == 2
        assert store.count_items(DAY2, topic="semi") == 2
        assert store.latest_day() == DAY2.isoformat()

        items = store.items_for_day(DAY2)
        assert list(items) == ["semi"]
        assert {item.title for item in items["semi"]} == {item2.title, item3.title}

        assert store.latest_source_day() == DAY2.isoformat()
        statuses = {row["source_id"]: row for row in store.source_status(DAY2)}
        assert statuses["feed_a"]["status"] == "ok"
        assert statuses["feed_b"]["status"] == "unavailable"
        assert statuses["feed_b"]["error"] == "HTTP 500"

        stored = store.get_digest("semi", DAY2)
        assert stored is not None
        assert stored.summary == "当日摘要"
        assert stored.key_points[0].text == "关键要点"
        assert stored.items[0].zh == "中文标题"
        assert stored.partial is True
        assert stored.status == "partial"
        assert set(store.digests_for_day(DAY2)) == {"semi"}

        events = store.events_for_topic(topic="semi", day=DAY2)
        assert len(events) == 1
        assert events[0].source_count == 2
        assert store.get_event("evt-1") is not None
        assert len(store.event_timeline("evt-1")) == 2

        history = store.history(topic="semi", days=2, end_day=DAY2)
        assert [row["date"] for row in history] == [DAY1.isoformat(), DAY2.isoformat()]
        assert history[0]["items"] == 1
        assert history[0]["item_delta"] == 1
        assert history[1]["items"] == 2
        assert history[1]["item_delta"] == 1
        assert history[1]["source_unavailable"] == 1
        assert history[1]["digests"] == 1
    finally:
        store.close()


def test_record_run_is_idempotent_per_day(tmp_path) -> None:
    store = WireStore(tmp_path / "wire.db")
    try:
        item = _item("https://example.com/1", "Original title")
        for run_id, title in (("run-1", "Original title"), ("run-2", "Updated title")):
            store.record_run(
                run_id=run_id,
                day=DAY2,
                topic="semi",
                mode="sources",
                status="ok",
                exit_code=0,
                started_at=NOW,
                finished_at=NOW,
                results=[_result("feed_a", "ok", [item])],
                items_by_topic={"semi": [item.model_copy(update={"title": title})]},
                events_by_topic={},
            )

        assert store.count_items(DAY2) == 1
        stored = store.items_for_day(DAY2)["semi"][0]
        assert stored.title == "Updated title"
        assert len(store.source_status(DAY2)) == 1
    finally:
        store.close()
