"""SQLite 存储单元测试：迁移、幂等写入、历史与事件。"""
from __future__ import annotations

from datetime import date, datetime, timezone

from qf_wire.core.models import (
    DigestItem,
    Event,
    EventExplanation,
    KeyPoint,
    SourceItem,
    TopicDigest,
)
from qf_wire.sources.base import FetchResult
from qf_wire.storage.sqlite import MIGRATIONS_DIR, WireStore, split_sql

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
        assert "0005_events_explanation" in versions
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


def _event(items: list[SourceItem]) -> Event:
    return Event(
        event_id="evt-stable",
        topic="semi",
        title="Clustered event",
        items=items,
        sources=["feed_a"],
        source_count=1,
        confidence="medium",
        first_seen=NOW,
        last_seen=NOW,
    )


def test_cross_day_recollection_keeps_previous_day_events(tmp_path) -> None:
    store = WireStore(tmp_path / "wire.db")
    day1_items = [_item("https://example.com/1", "Chip maker reports record quarter", event_id="evt-stable")]
    day2_items = [
        _item("https://example.com/1", "Chip maker reports record quarter", event_id="evt-stable"),
        _item("https://example.com/2", "Follow-up coverage", event_id="evt-stable"),
    ]
    try:
        for run_id, day, items in (
            ("run-1", DAY1, day1_items),
            ("run-2", DAY2, day2_items),
            ("run-3", DAY2, day2_items),
        ):
            store.record_run(
                run_id=run_id,
                day=day,
                topic="semi",
                mode="sources",
                status="ok",
                exit_code=0,
                started_at=NOW,
                finished_at=NOW,
                results=[_result("feed_a", "ok", items)],
                items_by_topic={"semi": items},
                events_by_topic={"semi": [_event(items)]},
            )

        with store.engine.connect() as conn:
            rows = conn.exec_driver_sql(
                "SELECT day FROM events WHERE event_id = 'evt-stable' ORDER BY day"
            ).all()
        assert [row[0] for row in rows] == [DAY1.isoformat(), DAY2.isoformat()]

        assert len(store.events_for_topic(topic="semi", day=DAY1)) == 1
        assert len(store.events_for_topic(topic="semi", day=DAY2)) == 1
        assert len(store.events_for_topic(topic="semi")) == 1  # 未指定日期时按 event_id 去重

        day1_event = store.get_event("evt-stable", DAY1)
        assert day1_event is not None
        assert len(day1_event.items) == 1
        assert [item.url for item in store.event_timeline("evt-stable", DAY1)] == [
            "https://example.com/1"
        ]
        assert len(store.event_timeline("evt-stable", DAY2)) == 2
        assert len(store.event_timeline("evt-stable")) == 2  # 默认取最近一天

        history = store.history(topic="semi", days=2, end_day=DAY2)
        assert [row["events"] for row in history] == [1, 1]
        assert [row["event_delta"] for row in history] == [1, 0]

        for item in store.items_for_day(DAY1)["semi"]:
            assert store.get_event(item.event_id, DAY1) is not None
            assert any(
                entry.url == item.url
                for entry in store.event_timeline(item.event_id, DAY1)
            )
    finally:
        store.close()


def test_event_explanation_round_trip(tmp_path) -> None:
    store = WireStore(tmp_path / "wire.db")
    try:
        item = _item("https://example.com/1", "TSMC expands 2nm capacity", event_id="evt-1")
        explanation = EventExplanation(
            reason="shared_entity",
            shared_entities=["tsmc"],
            title_similarity=0.71,
            simhash_similarity=0.93,
            threshold=0.56,
            window_hours=168,
        )
        event = Event(
            event_id="evt-1",
            topic="semi",
            title=item.title,
            items=[item],
            sources=["feed_a"],
            source_count=1,
            confidence="high",
            first_seen=NOW,
            last_seen=NOW,
            explanation=explanation,
        )
        store.record_run(
            run_id="run-1",
            day=DAY1,
            topic="semi",
            mode="sources",
            status="ok",
            exit_code=0,
            started_at=NOW,
            finished_at=NOW,
            results=[_result("feed_a", "ok", [item])],
            items_by_topic={"semi": [item]},
            events_by_topic={"semi": [event]},
        )

        stored = store.get_event("evt-1", DAY1)
        assert stored is not None
        assert stored.explanation == explanation
        assert stored.explanation is not None
        assert "共同实体：tsmc" in stored.explanation.summary()
    finally:
        store.close()


def test_migration_0004_preserves_existing_events(tmp_path) -> None:
    store = WireStore(tmp_path / "wire.db")
    try:
        with store.engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            for version in ("0001_init", "0002_source_scores", "0003_items_topic_url"):
                script = (MIGRATIONS_DIR / f"{version}.sql").read_text(encoding="utf-8")
                for statement in split_sql(script):
                    conn.exec_driver_sql(statement)
                conn.exec_driver_sql(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (version, "2026-10-22T00:00:00+00:00"),
                )
            conn.exec_driver_sql(
                "INSERT INTO events (event_id, topic, day, title, sources, source_count, "
                "confidence, first_seen, last_seen, updated_at) VALUES "
                "('evt-old', 'semi', '2026-10-21', 'Old event', '[\"feed_a\"]', 1, 'medium', "
                "'2026-10-21T00:00:00+00:00', '2026-10-21T00:00:00+00:00', "
                "'2026-10-21T00:00:00+00:00')"
            )

        store.initialize()

        assert store.get_event("evt-old") is not None
        assert store.get_event("evt-old", DAY1) is not None
        with store.engine.connect() as conn:
            columns = {row[1]: row[5] for row in conn.exec_driver_sql("PRAGMA table_info(events)")}
            indexes = {row[1] for row in conn.exec_driver_sql("PRAGMA index_list(events)")}
        assert columns["event_id"] == 1
        assert columns["day"] == 2
        assert "idx_events_topic_day" in indexes
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
