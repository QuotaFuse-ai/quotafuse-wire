"""采集容错集成测试：本地 HTTP fixture，不访问外网。"""
from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from qf_wire.core.models import Source
from qf_wire.pipeline.fetch import fetch_many, fetch_source, status_summary
from tests.fixtures.configs import SAMPLE_RSS


@pytest.fixture()
def feed_server():
    state = {"flaky_calls": 0, "slow_delay": 2.5}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            base_url = self.server.base_url  # type: ignore[attr-defined]
            body = SAMPLE_RSS.format(base=base_url).encode("utf-8")
            if self.path.startswith("/slow"):
                time.sleep(state["slow_delay"])
                self._send(200, body)
            elif self.path.startswith("/flaky"):
                state["flaky_calls"] += 1
                if state["flaky_calls"] == 1:
                    self._send(500, b"boom")
                else:
                    self._send(200, body)
            elif self.path.startswith("/broken"):
                self._send(500, b"boom")
            else:
                self._send(200, body)

        def _send(self, status: int, body: bytes) -> None:
            self.send_response(status)
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


def _source(source_id: str, url: str, *, timeout_sec: int = 2, retries: int = 0) -> Source:
    return Source(
        id=source_id,
        name=f"Source {source_id}",
        topic="semi",
        type="rss",
        url=url,
        timeout_sec=timeout_sec,
        retries=retries,
    )


def test_slow_source_does_not_block_others(feed_server) -> None:
    base = feed_server.base_url
    sources = [
        _source("slow", f"{base}/slow.xml", timeout_sec=1),
        _source("fast_a", f"{base}/a.xml"),
        _source("fast_b", f"{base}/b.xml"),
    ]
    started = time.monotonic()
    results = fetch_many(sources)
    elapsed = time.monotonic() - started

    by_id = {result.source_id: result for result in results}
    assert len(results) == 3
    assert by_id["slow"].status == "unavailable"
    assert "超时" in (by_id["slow"].error or "")
    for source_id in ("fast_a", "fast_b"):
        assert by_id[source_id].status == "ok"
        assert by_id[source_id].item_count == 2
    # 慢源不应拖住其他源：总耗时远小于逐个串行等待的 1 + 2.5 秒
    assert elapsed < 5
    assert status_summary(results) == "ok=2 degraded=0 unavailable=1"


def test_retry_success_marks_degraded(feed_server) -> None:
    source = _source("flaky", f"{feed_server.base_url}/flaky.xml", timeout_sec=3, retries=1)
    result = fetch_source(source)

    assert result.status == "degraded"
    assert result.attempts == 2
    assert result.item_count == 2
    assert result.error is None


def test_all_attempts_failed_marks_unavailable(feed_server) -> None:
    source = _source("broken", f"{feed_server.base_url}/broken.xml", timeout_sec=3, retries=1)
    result = fetch_source(source)

    assert result.status == "unavailable"
    assert result.attempts == 2
    assert result.item_count == 0
    assert "HTTP 500" in (result.error or "")
