"""采集并发稳定性：本地 100+ 端点，验证并发上限、超时标记与资源释放。"""
from __future__ import annotations

import gc
import threading
import time
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from qf_wire.core.models import Source
from qf_wire.pipeline.fetch import fetch_many, status_summary
from tests.fixtures.configs import SAMPLE_RSS

FAST_COUNT = 104
SLOW_COUNT = 8
BROKEN_COUNT = 2
CONCURRENCY = 16
FAST_DELAY = 0.02
SLOW_DELAY = 1.5
TIMEOUT_SEC = 1


@pytest.fixture()
def big_feed_server():
    state = {"active": 0, "peak": 0, "lock": threading.Lock()}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802
            with state["lock"]:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            try:
                body = SAMPLE_RSS.format(base=self.server.base_url).encode("utf-8")  # type: ignore[attr-defined]
                if self.path.startswith("/slow/"):
                    time.sleep(SLOW_DELAY)
                    self._send(200, body)
                elif self.path.startswith("/broken/"):
                    self._send(500, b"boom")
                else:
                    time.sleep(FAST_DELAY)
                    self._send(200, body)
            except OSError:
                # 客户端超时后会主动断开，服务端写回失败属于预期
                pass
            finally:
                with state["lock"]:
                    state["active"] -= 1

        def _send(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/rss+xml; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    class QuietServer(ThreadingHTTPServer):
        """客户端超时断开会留下被遗弃的连接，服务端不必打印这些堆栈。"""

        def handle_error(self, request, client_address) -> None:
            pass

    server = QuietServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.request_queue_size = 256
    host, port = server.server_address
    server.base_url = f"http://{host}:{port}"  # type: ignore[attr-defined]
    server.state = state  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _source(source_id: str, url: str, *, timeout_sec: int = 3, retries: int = 0) -> Source:
    return Source(
        id=source_id,
        name=source_id,
        topic="semi",
        type="rss",
        url=url,
        timeout_sec=timeout_sec,
        retries=retries,
    )


def _build_sources(base: str) -> list[Source]:
    # 错误源排在最前，避免被慢源占满同主机连接后误判为超时
    sources = [
        _source(f"broken_{index}", f"{base}/broken/{index}.xml")
        for index in range(BROKEN_COUNT)
    ]
    sources += [_source(f"fast_{index:03d}", f"{base}/feed/{index}.xml") for index in range(FAST_COUNT)]
    sources += [
        _source(f"slow_{index}", f"{base}/slow/{index}.xml", timeout_sec=TIMEOUT_SEC)
        for index in range(SLOW_COUNT)
    ]
    return sources


def _drain_threads(baseline: int, timeout: float = SLOW_DELAY + 3.0) -> int:
    deadline = time.monotonic() + timeout
    while threading.active_count() > baseline + 1 and time.monotonic() < deadline:
        time.sleep(0.05)
    return threading.active_count()


def test_hundred_sources_fetch_concurrently(big_feed_server) -> None:
    base = big_feed_server.base_url
    sources = _build_sources(base)
    baseline_threads = threading.active_count()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        started = time.monotonic()
        results = fetch_many(sources, max_workers=CONCURRENCY)
        elapsed = time.monotonic() - started
        gc.collect()

    by_id = {result.source_id: result for result in results}
    assert [result.source_id for result in results] == [source.id for source in sources]
    assert len(results) == FAST_COUNT + SLOW_COUNT + BROKEN_COUNT

    for index in range(FAST_COUNT):
        result = by_id[f"fast_{index:03d}"]
        assert result.status == "ok"
        assert result.item_count == 2
        assert result.error is None

    for index in range(SLOW_COUNT):
        result = by_id[f"slow_{index}"]
        assert result.status == "unavailable"
        assert "超时" in (result.error or "")
        assert result.attempts == 1

    for index in range(BROKEN_COUNT):
        result = by_id[f"broken_{index}"]
        assert result.status == "unavailable"
        assert "HTTP 500" in (result.error or "")

    assert status_summary(results) == (
        f"ok={FAST_COUNT} degraded=0 unavailable={SLOW_COUNT + BROKEN_COUNT}"
    )

    # 串行至少需要 SLOW_COUNT * TIMEOUT_SEC 秒，并发应远低于该下界
    serial_lower_bound = SLOW_COUNT * TIMEOUT_SEC
    assert elapsed < serial_lower_bound
    assert elapsed < serial_lower_bound / 2

    # 服务端同时处理的请求数包含已被客户端放弃、仍在 sleep 的慢请求线程，
    # 因此只验证确实发生了并行，不把该计数当作连接池上限。
    peak = big_feed_server.state["peak"]
    assert 2 <= peak <= CONCURRENCY

    unclosed = [
        str(warning.message)
        for warning in caught
        if "Unclosed client session" in str(warning.message)
        or "Unclosed connector" in str(warning.message)
    ]
    assert unclosed == []

    remaining = _drain_threads(baseline_threads)
    assert remaining <= baseline_threads + 1


def test_repeated_runs_keep_same_results(big_feed_server) -> None:
    base = big_feed_server.base_url
    sources = [source for source in _build_sources(base) if source.id.startswith("fast_")][:40]

    first = fetch_many(sources, max_workers=CONCURRENCY)
    second = fetch_many(sources, max_workers=CONCURRENCY)

    assert [(item.source_id, item.status, item.item_count) for item in first] == [
        (item.source_id, item.status, item.item_count) for item in second
    ]
    assert all(item.status == "ok" for item in second)
