"""QUOT-44 安全 PoC 公共工具。

约束：所有请求只发往 127.0.0.1 上的被测进程或本脚本自己启动的桩服务，
不访问任何外部目标，不写入真实密钥。
"""
from __future__ import annotations

import contextlib
import json
import os
import socket
import socketserver
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from qf_wire.config.loader import load_config  # noqa: E402
from qf_wire.web.server import create_server  # noqa: E402
from tests.fixtures.configs import write_config  # noqa: E402

ENV_KEYS = (
    "QF_WIRE_ENV_FILE",
    "QF_WIRE_DIGEST_PROVIDER",
    "QF_WIRE_DIGEST_MODEL",
    "QF_WIRE_API_BASE",
    "QF_WIRE_API_KEY",
    "QF_WIRE_MODEL_GATEWAY_KEY",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "QF_WIRE_API_TOKEN",
    "QF_WIRE_API_REQUIRE_TOKEN",
    "QF_WIRE_CORS_ORIGINS",
    "QF_WIRE_ALLOW_PRIVATE_NETWORK",
    "QF_WIRE_MULTIUSER",
    "QF_WIRE_USER",
    "QF_WIRE_HOST",
    "QF_WIRE_PORT",
    "QF_WIRE_MCP_HOST",
    "QF_WIRE_MCP_PORT",
)

_RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, message: str) -> None:
    _RESULTS.append((bool(ok), message))
    print(f"[{'PASS' if ok else 'FAIL'}] {message}")


def finish(title: str) -> None:
    failed = [msg for ok, msg in _RESULTS if not ok]
    print(f"\n{title}: {len(_RESULTS) - len(failed)}/{len(_RESULTS)} 复现成功")
    if failed:
        print("未复现的断言：")
        for msg in failed:
            print(f"  - {msg}")
        raise SystemExit(1)
    raise SystemExit(0)


@contextlib.contextmanager
def clean_env(env_file: Path) -> Iterator[None]:
    saved = {name: os.environ.pop(name, None) for name in ENV_KEYS}
    os.environ["QF_WIRE_ENV_FILE"] = str(env_file)
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        os.environ.setdefault("QF_WIRE_ENV_FILE", str(env_file))


class Dashboard:
    """在被测机上以 127.0.0.1 启动看板。"""

    def __init__(self, tmp_path: Path, digest: dict[str, Any] | None = None) -> None:
        self.tmp_path = tmp_path
        self.config_dir = write_config(tmp_path, digest=digest)
        self.config = load_config(self.config_dir, tmp_path / "data")
        self.server = create_server(self.config, "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = int(self.server.server_address[1])
        self.base = f"http://127.0.0.1:{self.port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def __enter__(self) -> "Dashboard":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def request(
    base: str,
    path: str,
    *,
    method: str = "GET",
    payload: Any = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10,
) -> tuple[int, dict[str, str], bytes]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(base + path, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def body_json(raw: bytes) -> dict[str, Any]:
    return json.loads(raw.decode("utf-8")) if raw else {}


class _RelayHandler(socketserver.BaseRequestHandler):
    target: tuple[str, int]

    def handle(self) -> None:
        with socket.create_connection(self.target, timeout=10) as upstream:

            def pump(src: socket.socket, dst: socket.socket) -> None:
                try:
                    while True:
                        chunk = src.recv(65536)
                        if not chunk:
                            break
                        dst.sendall(chunk)
                except OSError:
                    pass
                finally:
                    try:
                        dst.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass

            helper = threading.Thread(target=pump, args=(upstream, self.request), daemon=True)
            helper.start()
            pump(self.request, upstream)
            helper.join(timeout=10)


class LoopbackRelay:
    """在本机 127.0.0.1 上做端口转发，模拟 nginx / SSH 隧道等本地反向代理。"""

    def __init__(self, target_port: int) -> None:
        handler = type("Relay", (_RelayHandler,), {"target": ("127.0.0.1", target_port)})
        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
        self.server.daemon_threads = True
        self.port = int(self.server.server_address[1])
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class _Collector(BaseHTTPRequestHandler):
    records: list[dict[str, str]] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        type(self).records.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization") or "",
                "host": self.headers.get("Host") or "",
            }
        )
        body = b'{"summary":"poc", "key_points":[], "items":[]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        return


class Collector:
    """模拟攻击者控制的模型接口，用于观察 Wire 发出的 Authorization 头。"""

    def __init__(self) -> None:
        _Collector.records = []
        self.records = _Collector.records
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Collector)
        self.server.daemon_threads = True
        self.port = int(self.server.server_address[1])
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def __enter__(self) -> "Collector":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class _GzipBomb(BaseHTTPRequestHandler):
    payload: bytes = b""
    decompressed: int = 0

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml")
        self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(type(self).payload)))
        self.end_headers()
        self.wfile.write(type(self).payload)

    def log_message(self, *args: object) -> None:
        return


class GzipBombServer:
    def __init__(self, decompressed_bytes: int) -> None:
        import gzip

        _GzipBomb.decompressed = decompressed_bytes
        _GzipBomb.payload = gzip.compress(b"\0" * decompressed_bytes)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _GzipBomb)
        self.server.daemon_threads = True
        self.port = int(self.server.server_address[1])
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/feed.xml"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def __enter__(self) -> "GzipBombServer":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
