"""`scripts/healthcheck.sh`：探活 + 最近一次 run 状态。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "healthcheck.sh"

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="需要 POSIX sh")


class _Handler(BaseHTTPRequestHandler):
    run: dict[str, Any] | None = None

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/health":
            self._reply({"status": "ok"})
        elif self.path == "/api/status":
            self._reply({"lastRun": self.run})
        else:
            self._reply({"error": "not found"}, status=404)

    def _reply(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: Any) -> None:
        pass


@pytest.fixture
def server():
    handler = type("Handler", (_Handler,), {"run": None})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd, handler
    finally:
        httpd.shutdown()
        httpd.server_close()


def _run(port: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(SCRIPT)],
        env={**os.environ, "QF_WIRE_HEALTH_URL": f"http://127.0.0.1:{port}"},
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_healthcheck_ok(server) -> None:
    httpd, handler = server
    handler.run = {
        "runId": "2026-10-24-abc",
        "status": "ok",
        "day": "2026-10-24",
        "itemCount": 12,
        "finishedAt": "2026-10-24T01:00:00+00:00",
    }
    result = _run(httpd.server_port)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_healthcheck_degrades_on_partial_run(server) -> None:
    httpd, handler = server
    handler.run = {"runId": "r1", "status": "partial", "day": "2026-10-24", "itemCount": 3}
    result = _run(httpd.server_port)
    assert result.returncode == 3
    assert "partial" in result.stderr


def test_healthcheck_reports_missing_run(server) -> None:
    httpd, _handler = server
    result = _run(httpd.server_port)
    assert result.returncode == 4
    assert "qfw run" in result.stderr
