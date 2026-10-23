"""跨日重复采集：事件按天隔离，历史事件、时间线与 Provider 结果不缩水。"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from qf_wire.config.loader import load_config
from qf_wire.core.models import Event, SourceItem
from qf_wire.core.scheduler import today_beijing
from qf_wire.provider.wire_provider import WireProvider
from qf_wire.sources.base import FetchResult
from qf_wire.storage.sqlite import WireStore
from qf_wire.web.server import create_server
from tests.fixtures.configs import write_config

NOW = datetime.now(timezone.utc)
# 事件按北京日历日分区，data_as_of 也取时间戳的北京日期；CI 跑在 UTC 上，必须用产品同款时钟
DAY2 = today_beijing()
DAY1 = DAY2 - timedelta(days=1)
EVENT_ID = "evt-stable"
URL_A = "https://example.com/1"
URL_B = "https://example.com/2"


def _item(url: str, title: str, source_id: str = "feed_a") -> SourceItem:
    return SourceItem(
        title=title,
        url=url,
        source_id=source_id,
        topic="semi",
        summary="summary",
        published_at=NOW,
        sources=[source_id],
        event_id=EVENT_ID,
        confidence="high",
    )


def _result(source_id: str, items: list[SourceItem]) -> FetchResult:
    return FetchResult(
        source_id=source_id,
        source_name=source_id.upper(),
        topic="semi",
        status="ok",
        items=items,
        attempts=1,
    )


def _event(items: list[SourceItem]) -> Event:
    sources = sorted({item.source_id for item in items})
    return Event(
        event_id=EVENT_ID,
        topic="semi",
        title="Chip maker breaks ground",
        items=items,
        sources=sources,
        source_count=len(sources),
        confidence="high",
        first_seen=NOW,
        last_seen=NOW,
    )


def _seed(config) -> None:
    day1 = [_item(URL_A, "Chip maker breaks ground")]
    day2 = [
        _item(URL_A, "Chip maker breaks ground"),
        _item(URL_B, "Chip maker expands fab", source_id="feed_b"),
    ]
    store = WireStore(config.paths.db_path)
    try:
        for index, (day, items) in enumerate(((DAY1, day1), (DAY2, day2)), start=1):
            store.record_run(
                run_id=f"run-{index}",
                day=day,
                topic="semi",
                mode="sources",
                status="ok",
                exit_code=0,
                started_at=NOW,
                finished_at=NOW,
                results=[_result("feed_a", items)],
                items_by_topic={"semi": items},
                events_by_topic={"semi": [_event(items)]},
            )
    finally:
        store.close()


def test_provider_dedupes_event_and_serves_latest_timeline(tmp_path: Path) -> None:
    config_dir = write_config(tmp_path)
    config = load_config(config_dir, tmp_path / "data")
    _seed(config)

    provider = WireProvider(config)
    try:
        envelope = provider.search_events("chip")
        events = envelope.payload["events"]
        assert [event["event_id"] for event in events] == [EVENT_ID]
        assert len(events[0]["items"]) == 2
        assert envelope.data_as_of == DAY2

        timeline = provider.get_timeline(EVENT_ID)
        assert timeline.data_as_of == DAY2
        assert len(timeline.payload["timeline"]) == 2
    finally:
        provider.close()


def _get(base: str, path: str) -> tuple[int, dict]:
    request = urllib.request.Request(base + path, headers={"X-Wire-Request": "1"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


@pytest.fixture
def dashboard_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_env):
    for key in (
        "QF_WIRE_API_TOKEN",
        "QF_WIRE_API_REQUIRE_TOKEN",
        "QF_WIRE_MULTIUSER",
        "QF_WIRE_USER",
        "QF_WIRE_CORS_ORIGINS",
        "QF_WIRE_ALLOW_PRIVATE_NETWORK",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("QF_WIRE_ENV_FILE", str(tmp_path / ".env.local"))


def test_dashboard_event_api_scopes_by_date(tmp_path: Path, dashboard_env) -> None:
    config_dir = write_config(tmp_path)
    config = load_config(config_dir, tmp_path / "data")
    _seed(config)
    server = create_server(config, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, body = _get(base, f"/api/event?id={EVENT_ID}&date={DAY1.isoformat()}")
        assert status == 200
        assert [item["url"] for item in body["timeline"]] == [URL_A]

        status, body = _get(base, f"/api/event?id={EVENT_ID}")
        assert status == 200
        assert len(body["timeline"]) == 2

        status, body = _get(base, f"/api/event?id={EVENT_ID}&date=2020-01-01")
        assert status == 404

        status, body = _get(base, f"/api/event?id={EVENT_ID}&date=2020/01/01")
        assert status == 400
        assert "YYYY-MM-DD" in body["error"]

        status, body = _get(base, f"/api/events?date={DAY1.isoformat()}")
        assert status == 200
        assert body["date"] == DAY1.isoformat()
        assert [event["event_id"] for event in body["events"]] == [EVENT_ID]
    finally:
        server.shutdown()
        server.server_close()
