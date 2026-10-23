"""安全 PoC 5：监听面与默认值。

复现：
1. 文档/示例中的 QF_WIRE_HOST 并不生效，create_server 仍绑定 127.0.0.1。
2. 监听 0.0.0.0 时启动日志只有 1 条 INFO，没有任何「已暴露到局域网」的告警。
3. ThreadingHTTPServer 只有 AF_INET，--host ::1 在 Linux 上绑定失败（IPv6 回环不可用）。
4. MCP streamable-http 没有鉴权参数；对 /mcp 的 initialize 请求不会返回 401。

运行：python tests/security/poc_network_binding.py
"""
from __future__ import annotations

import inspect
import logging
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from _harness import ROOT, Dashboard, check, clean_env, finish, request

import qf_wire.web.server as web
from qf_wire.mcp.server import run_http


def wait_for_port(port: int, timeout: float = 10) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="qf-poc-net-") as raw_tmp:
        tmp = Path(raw_tmp)
        with clean_env(tmp / ".env.local"), Dashboard(tmp) as dash:
            config = dash.config

            os.environ["QF_WIRE_HOST"] = "0.0.0.0"
            os.environ["QF_WIRE_PORT"] = "18790"
            server = web.create_server(config)
            try:
                bound = str(server.server_address[0])
            finally:
                server.server_close()
            check(bound == "127.0.0.1", "QF_WIRE_HOST=0.0.0.0 被忽略，仍只绑定 127.0.0.1")

            logs: list[tuple[int, str]] = []

            class Capture(logging.Handler):
                def emit(self, record: logging.LogRecord) -> None:
                    logs.append((record.levelno, record.getMessage()))

            logger = logging.getLogger("qf_wire.web.server")
            logger.setLevel(logging.DEBUG)
            handler = Capture()
            logger.addHandler(handler)

            exposed = web.create_server(config, "0.0.0.0", 0)
            original = web.create_server
            web.create_server = lambda *args, **kwargs: exposed  # type: ignore[assignment]
            thread = threading.Thread(
                target=web.serve_forever,
                args=(config,),
                kwargs={"host": "0.0.0.0", "port": 0},
                daemon=True,
            )
            try:
                thread.start()
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and not any(
                    "看板已启动" in message for _, message in logs
                ):
                    time.sleep(0.05)
            finally:
                exposed.shutdown()
                exposed.server_close()
                web.create_server = original  # type: ignore[assignment]
                logger.removeHandler(handler)
                thread.join(timeout=5)

            check(
                any("看板已启动" in message for _, message in logs),
                "监听 0.0.0.0 时启动了看板",
            )
            warnings = [
                message
                for level, message in logs
                if level >= logging.WARNING and ("0.0.0.0" in message or "暴露" in message or "风险" in message)
            ]
            check(not warnings, "监听 0.0.0.0 时没有任何非回环暴露告警")

            ipv6_ok = False
            try:
                ipv6 = web.create_server(config, "::1", 0)
            except OSError as exc:
                check(True, f"--host ::1 绑定失败（AF_INET server 不支持 IPv6 回环）: {exc}")
            else:
                ipv6_ok = True
                ipv6.server_close()
                check(True, "本平台 --host ::1 可用（与其他平台不一致）")

            params = inspect.signature(run_http).parameters
            check(
                not any("auth" in name or "token" in name for name in params),
                "MCP run_http 没有鉴权参数（默认仅靠 127.0.0.1 监听）",
            )

            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
            probe.close()

            env = {name: value for name, value in os.environ.items() if not name.startswith("QF_WIRE_")}
            env["PYTHONPATH"] = str(ROOT / "src")
            process = subprocess.Popen(
                [sys.executable, "-m", "qf_wire", "mcp", "http", "--port", str(port)],
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            try:
                if not wait_for_port(port):
                    print("[SKIP] MCP http 未在超时内启动，跳过活的鉴权探测")
                else:
                    payload = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-03-26",
                            "capabilities": {},
                            "clientInfo": {"name": "poc", "version": "1"},
                        },
                    }
                    try:
                        status, headers, _ = request(
                            f"http://127.0.0.1:{port}",
                            "/mcp",
                            method="POST",
                            payload=payload,
                            headers={"Accept": "application/json, text/event-stream"},
                        )
                    except Exception as exc:
                        check(False, f"MCP 探测请求失败：{type(exc).__name__}: {exc}")
                    else:
                        check(
                            status != 401 and "WWW-Authenticate" not in headers,
                            f"未携带任何凭据访问 MCP /mcp 未被要求认证（HTTP {status}）",
                        )
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()

            check(
                sys.platform != "linux" or not ipv6_ok,
                "IPv4/IPv6 双回环未同时覆盖（requirements 要求两者默认仅本机）",
            )

    finish("poc_network_binding")


if __name__ == "__main__":
    main()
