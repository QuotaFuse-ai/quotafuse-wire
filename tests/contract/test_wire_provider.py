"""WireProvider 契约测试：只读归档、别名解析与降级路径。"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from qf_wire.provider.wire_provider import WireProvider, parse_window
from tests.fixtures.configs import write_config
from tests.fixtures.wire_data import EVENT_ID, KEYWORD, seed_wire_data


def _seeded(tmp_path: Path) -> tuple[WireProvider, dict[str, str]]:
    config_dir = write_config(tmp_path)
    data_dir = tmp_path / "data"
    seeded = seed_wire_data(data_dir)
    return WireProvider(config_dir=config_dir, data_dir=data_dir), seeded


def _empty(tmp_path: Path) -> WireProvider:
    config_dir = write_config(tmp_path)
    return WireProvider(config_dir=config_dir, data_dir=tmp_path / "empty-data")


def test_provider_declares_council_protocol_surface() -> None:
    provider = WireProvider.__new__(WireProvider)
    assert provider.name == "wire"
    assert provider.domains == ("news", "policy", "industry")
    for method in ("get_digest", "search_events", "get_timeline", "list_sources", "close"):
        assert callable(getattr(provider, method))


def test_get_digest_resolves_alias_and_returns_non_empty_payload(tmp_path: Path) -> None:
    provider, seeded = _seeded(tmp_path)
    try:
        envelope = provider.get_digest("semiconductor")
    finally:
        provider.close()
    assert envelope.topic == "semi"
    assert envelope.payload["summary"]
    assert envelope.payload["items"]
    assert envelope.data_as_of == date.fromisoformat(seeded["day"])
    assert envelope.freshness == "archive"
    assert envelope.source == "wire"
    assert envelope.event_id is None
    assert envelope.confidence == "high"
    assert envelope.source_status == "ok"
    assert "feed_a" in envelope.source_detail


def test_get_digest_accepts_explicit_date(tmp_path: Path) -> None:
    provider, seeded = _seeded(tmp_path)
    try:
        envelope = provider.get_digest("semi", date.fromisoformat(seeded["day"]))
    finally:
        provider.close()
    assert envelope.payload["items"]


def test_unknown_topic_returns_empty_archive_envelope(tmp_path: Path) -> None:
    provider, _ = _seeded(tmp_path)
    try:
        envelope = provider.get_digest("no-such-topic")
    finally:
        provider.close()
    assert envelope.payload == {}
    assert envelope.freshness == "archive"
    assert envelope.confidence == "low"
    assert envelope.topic == "no-such-topic"


def test_uninitialized_database_degrades_without_creating_files(tmp_path: Path) -> None:
    provider = _empty(tmp_path)
    try:
        assert provider.db_ready is False
        envelope = provider.get_digest("semiconductor")
        events = provider.search_events(KEYWORD)
        timeline = provider.get_timeline(EVENT_ID)
        sources = provider.list_sources()
    finally:
        provider.close()
    for result in (envelope, events, timeline, sources):
        assert result.freshness == "archive"
    assert envelope.payload == {}
    assert events.payload["events"] == []
    assert timeline.payload == {}
    assert sources.payload["sources"]
    assert not provider.config.paths.db_path.exists()


def test_search_events_finds_multi_source_event(tmp_path: Path) -> None:
    provider, _ = _seeded(tmp_path)
    try:
        envelope = provider.search_events(KEYWORD)
    finally:
        provider.close()
    assert envelope.freshness == "archive"
    assert envelope.payload["query"] == KEYWORD
    events = envelope.payload["events"]
    assert len(events) == 1
    assert events[0]["event_id"] == EVENT_ID
    assert events[0]["source_count"] == 2
    assert envelope.confidence == "high"
    assert "feed_a" in envelope.source_detail


def test_search_events_filters_by_topic_alias(tmp_path: Path) -> None:
    provider, _ = _seeded(tmp_path)
    try:
        envelope = provider.search_events(KEYWORD, window="24h", topic="semiconductor")
    finally:
        provider.close()
    assert envelope.topic == "semi"
    assert len(envelope.payload["events"]) == 1


def test_search_events_without_hits_is_empty_not_error(tmp_path: Path) -> None:
    provider, _ = _seeded(tmp_path)
    try:
        envelope = provider.search_events("完全不存在的关键词")
    finally:
        provider.close()
    assert envelope.payload["events"] == []
    assert envelope.confidence == "low"


def test_search_events_unknown_topic_returns_empty_payload(tmp_path: Path) -> None:
    provider, _ = _seeded(tmp_path)
    try:
        envelope = provider.search_events(KEYWORD, topic="no-such-topic")
    finally:
        provider.close()
    assert envelope.payload["events"] == []
    assert envelope.topic == "no-such-topic"


@pytest.mark.parametrize("window", ["7d", "24h"])
def test_parse_window_accepts_documented_units(window: str) -> None:
    assert parse_window(window).total_seconds() > 0


@pytest.mark.parametrize("window", ["7", "d7", "0d", "-1d", "1w"])
def test_parse_window_rejects_invalid_values(window: str) -> None:
    with pytest.raises(ValueError):
        parse_window(window)


def test_parse_window_defaults_to_seven_days() -> None:
    assert parse_window("").days == 7
    assert parse_window(None).days == 7


def test_search_events_rejects_blank_keyword(tmp_path: Path) -> None:
    provider, _ = _seeded(tmp_path)
    try:
        with pytest.raises(ValueError):
            provider.search_events("  ")
    finally:
        provider.close()


def test_get_timeline_orders_sources_by_publish_time(tmp_path: Path) -> None:
    provider, _ = _seeded(tmp_path)
    try:
        envelope = provider.get_timeline(EVENT_ID)
    finally:
        provider.close()
    assert envelope.event_id == EVENT_ID
    assert envelope.topic == "semi"
    assert envelope.payload["event"]["source_count"] == 2
    timeline = envelope.payload["timeline"]
    assert [entry["source"] for entry in timeline] == ["feed_a", "feed_b"]
    assert all(entry["url"] for entry in timeline)


def test_get_timeline_missing_event_returns_empty_envelope(tmp_path: Path) -> None:
    provider, _ = _seeded(tmp_path)
    try:
        envelope = provider.get_timeline("evt-not-found")
    finally:
        provider.close()
    assert envelope.payload == {}
    assert envelope.event_id == "evt-not-found"
    assert envelope.freshness == "archive"
    assert envelope.confidence == "low"


def test_get_timeline_rejects_blank_event_id(tmp_path: Path) -> None:
    provider, _ = _seeded(tmp_path)
    try:
        with pytest.raises(ValueError):
            provider.get_timeline("")
    finally:
        provider.close()


def test_list_sources_returns_scores_and_status(tmp_path: Path) -> None:
    provider, _ = _seeded(tmp_path)
    try:
        envelope = provider.list_sources("semiconductor")
    finally:
        provider.close()
    assert envelope.topic == "semi"
    sources = envelope.payload["sources"]
    assert [source["id"] for source in sources] == ["feed_a"]
    entry = sources[0]
    assert entry["status"] == "ok"
    assert set(entry) >= {"id", "name", "topic", "type", "weight", "score", "accuracy", "timeliness", "duplication"}
    assert entry["score"] >= 0.0
    assert envelope.freshness == "archive"


def test_list_sources_unknown_topic_is_empty(tmp_path: Path) -> None:
    provider, _ = _seeded(tmp_path)
    try:
        envelope = provider.list_sources("no-such-topic")
    finally:
        provider.close()
    assert envelope.payload["sources"] == []
    assert envelope.confidence == "low"
