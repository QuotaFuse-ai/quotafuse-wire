"""事件聚类：同事件跨源折叠、实体冲突隔离、时间线与稳定 event_id。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from qf_wire.core.cluster import (
    build_events,
    cluster_items,
    extract_entities,
    timeline,
)
from qf_wire.core.models import SourceItem

BASE = datetime(2026, 10, 21, 8, 0, tzinfo=timezone.utc)

SAME_EVENT_TITLES = [
    "TSMC starts mass production of 2nm chips",
    "TSMC begins mass production of 2nm chips",
    "TSMC starts mass production for 2nm chips",
    "TSMC starts mass production of 2nm chips ahead of schedule",
    "TSMC starts mass production of 2nm chips at Hsinchu fab",
]

UNRELATED_TITLES = [
    "Oil prices climb as OPEC meets in Vienna",
    "Samsung unveils new foldable phone lineup",
]


def _item(source_id: str, title: str, *, hours: float = 0, topic: str = "semi") -> SourceItem:
    return SourceItem(
        title=title,
        url=f"https://example.com/{source_id}/{abs(hours)}-{len(title)}",
        source_id=source_id,
        topic=topic,
        summary=title,
        published_at=BASE + timedelta(hours=hours),
    )


def _same_event_items() -> list[SourceItem]:
    return [
        _item(f"feed_{index}", title, hours=index)
        for index, title in enumerate(SAME_EVENT_TITLES)
    ]


def test_five_same_event_titles_fold_into_one_group() -> None:
    items = _same_event_items() + [
        _item("feed_x", UNRELATED_TITLES[0], hours=1),
        _item("feed_y", UNRELATED_TITLES[1], hours=2),
    ]
    groups = cluster_items(items)

    multi = [group for group in groups if len(group) >= 3]
    assert len(multi) == 1
    assert {item.source_id for item in multi[0]} == {f"feed_{index}" for index in range(5)}
    assert len(groups) == 3


def test_build_events_marks_multisource_event_with_ascending_timeline() -> None:
    events = build_events(_same_event_items() + [
        _item("feed_x", UNRELATED_TITLES[0], hours=1),
        _item("feed_y", UNRELATED_TITLES[1], hours=2),
    ])

    multi = [event for event in events if event.source_count >= 2]
    assert len(multi) == 1
    event = multi[0]
    assert event.source_count == 5
    assert set(event.sources) == {f"feed_{index}" for index in range(5)}
    assert event.confidence == "high"
    assert event.first_seen == BASE
    assert event.last_seen == BASE + timedelta(hours=4)
    assert all(item.event_id == event.event_id for item in event.items)

    rows = timeline(event)
    times = [row["published_at"] for row in rows]
    assert times == sorted(times)
    assert [row["source"] for row in rows] == [f"feed_{index}" for index in range(5)]


def test_event_id_is_stable_across_rebuilds() -> None:
    first = {event.title: event.event_id for event in build_events(_same_event_items())}
    second = {event.title: event.event_id for event in build_events(_same_event_items())}
    assert first == second
    assert len(first) == 1


def test_entity_conflict_prevents_merge() -> None:
    tsmc = _item("feed_a", "TSMC starts mass production of 2nm chips")
    samsung = _item("feed_b", "Samsung starts mass production of 2nm chips", hours=1)

    assert extract_entities(tsmc.title).orgs == frozenset({"tsmc"})
    assert extract_entities(samsung.title).orgs == frozenset({"samsung"})

    groups = cluster_items([tsmc, samsung])
    assert len(groups) == 2


def test_reports_outside_window_stay_separate() -> None:
    early = _item("feed_a", "TSMC starts mass production of 2nm chips")
    late = _item("feed_b", "TSMC begins mass production of 2nm chips", hours=24 * 8)

    groups = cluster_items([early, late])
    assert len(groups) == 2
