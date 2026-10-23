"""R3.3 回归：同一信源被多个赛道引用时，事件时间线不应丢失。

QUOT-43 实测：信源被赛道 A、B 共用时，`pipeline.process` 会就地改写
`SourceItem.topic` / `SourceItem.event_id`，后处理的赛道覆盖前一赛道；
items 表按 (day, url) upsert，最终只保留后一赛道的 event_id，
前一赛道的事件存在但 `event_timeline()` 为空。
"""
from __future__ import annotations

import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from qf_wire.config.loader import load_config
from qf_wire.core.scheduler import RunOptions, run
from qf_wire.storage.sqlite import WireStore
from tests.fixtures.configs import SAMPLE_RSS, write_config

SHARED_TOPICS = [
    {
        "id": "semi",
        "name": "半导体",
        "legacy_key": "semi",
        "aliases": ["semiconductor"],
        "keywords": ["芯片"],
        "sources": ["shared"],
    },
    {
        "id": "energy",
        "name": "能源",
        "legacy_key": "energy",
        "aliases": ["energy"],
        "keywords": ["能源"],
        "sources": ["shared"],
    },
]


@pytest.fixture()
def feed_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            base_url = self.server.base_url  # type: ignore[attr-defined]
            body = SAMPLE_RSS.format(base=base_url).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    host, port = server.server_address
    server.base_url = f"http://{host}:{port}"  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.xfail(
    reason="QUOT-43 P1：共用信源时后一赛道覆盖 event_id，前一赛道时间线为空",
    strict=False,
)
def test_shared_source_keeps_timeline_for_every_topic(feed_server, tmp_path) -> None:
    sources = [
        {
            "id": "shared",
            "name": "Shared Feed",
            "topic": "semi",
            "type": "rss",
            "url": f"{feed_server.base_url}/feed.xml",
            "timeout_sec": 3,
            "retries": 0,
        }
    ]
    config_dir = write_config(tmp_path, topics=SHARED_TOPICS, sources=sources)
    config = load_config(config_dir, tmp_path / "data")

    result = run(
        config,
        RunOptions(
            topics=config.topics,
            day=date(2026, 10, 21),
            sources_only=True,
            render=False,
            archive=False,
        ),
    )

    assert set(result.events_by_topic) == {"semi", "energy"}
    store = WireStore(config.paths.db_path)
    try:
        for topic_id, events in result.events_by_topic.items():
            assert events, f"{topic_id} 没有生成事件"
            for event in events:
                assert store.event_timeline(event.event_id), (
                    f"赛道 {topic_id} 的事件 {event.event_id} 时间线为空"
                )
    finally:
        store.close()
