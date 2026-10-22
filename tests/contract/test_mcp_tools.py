"""MCP 契约测试：真实 stdio / http 子进程完成 initialize → tools/list → tools/call。"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import LATEST_PROTOCOL_VERSION

from qf_wire.mcp.server import DEFAULT_HTTP_PORT, SERVER_NAME
from tests.fixtures.configs import write_config
from tests.fixtures.wire_data import EVENT_ID, KEYWORD, seed_wire_data

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
TOOL_NAMES = {"wire_get_digest", "wire_search_events", "wire_get_timeline", "wire_list_sources"}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": LATEST_PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "wire-contract-test", "version": "0.1"},
    },
}
TOOL_CALLS: list[tuple[str, dict[str, Any]]] = [
    ("wire_get_digest", {"topic": "semiconductor"}),
    ("wire_search_events", {"keyword": KEYWORD}),
    ("wire_get_timeline", {"event_id": EVENT_ID}),
    ("wire_list_sources", {"topic": "semiconductor"}),
]


def test_http_defaults_match_contract() -> None:
    assert SERVER_NAME == "quota-fuse-wire"
    assert DEFAULT_HTTP_PORT == 8791


@pytest.fixture
def seeded_dirs(tmp_path: Path) -> tuple[Path, Path]:
    config_dir = write_config(tmp_path)
    data_dir = tmp_path / "data"
    seed_wire_data(data_dir)
    return config_dir, data_dir


def _env(config_dir: Path, data_dir: Path) -> dict[str, str]:
    entries = [str(SRC)]
    for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep):
        if not entry:
            continue
        path = Path(entry)
        entries.append(str(path if path.is_absolute() else ROOT / path))
    entries.append(str(ROOT))
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": os.pathsep.join(dict.fromkeys(entries)),
            "QF_WIRE_CONFIG_DIR": str(config_dir),
            "QF_WIRE_DATA_DIR": str(data_dir),
            "QF_WIRE_ROOT": str(ROOT),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
    )
    return env


def _stdio_params(config_dir: Path, data_dir: Path) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "qf_wire", "mcp", "stdio"],
        env=_env(config_dir, data_dir),
        cwd=str(config_dir.parent),
    )


def _tool_content_text(result: Any) -> str:
    return "".join(block.text for block in result.content if block.type == "text")


def _tool_text(result: Any) -> str:
    assert result.is_error is False
    return _tool_content_text(result)


def _tool_payload(result: Any) -> dict[str, Any]:
    return json.loads(_tool_text(result))


async def test_stdio_client_lists_and_calls_all_four_tools(
    seeded_dirs: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    config_dir, data_dir = seeded_dirs
    params = _stdio_params(config_dir, data_dir)
    log_path = tmp_path / "stdio-server.log"

    with log_path.open("w", encoding="utf-8", errors="replace") as errlog:
        async with stdio_client(params, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), 30)
                listed = await asyncio.wait_for(session.list_tools(), 30)
                assert {tool.name for tool in listed.tools} == TOOL_NAMES

                digest = _tool_payload(
                    await asyncio.wait_for(
                        session.call_tool("wire_get_digest", {"topic": "semiconductor"}), 30
                    )
                )
                assert digest["domain"] == "news"
                assert digest["topic"] == "semi"
                assert digest["freshness"] == "archive"
                assert digest["payload"]["items"]

                events = _tool_payload(
                    await asyncio.wait_for(
                        session.call_tool("wire_search_events", {"keyword": KEYWORD}), 30
                    )
                )
                assert events["payload"]["events"][0]["event_id"] == EVENT_ID
                assert events["payload"]["events"][0]["source_count"] == 2

                timeline = _tool_payload(
                    await asyncio.wait_for(
                        session.call_tool("wire_get_timeline", {"event_id": EVENT_ID}), 30
                    )
                )
                assert timeline["event_id"] == EVENT_ID
                assert len(timeline["payload"]["timeline"]) == 2

                sources = _tool_payload(
                    await asyncio.wait_for(session.call_tool("wire_list_sources", {}), 30)
                )
                assert sources["payload"]["sources"]
                assert sources["payload"]["sources"][0]["id"] == "feed_a"


async def test_stdio_param_errors_are_reported_as_tool_errors(
    seeded_dirs: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    config_dir, data_dir = seeded_dirs
    params = _stdio_params(config_dir, data_dir)
    log_path = tmp_path / "stdio-errors.log"

    with log_path.open("w", encoding="utf-8", errors="replace") as errlog:
        async with stdio_client(params, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), 30)

                async def call(name: str, arguments: dict[str, Any]) -> Any:
                    return await asyncio.wait_for(session.call_tool(name, arguments), 30)

                unknown = await call("wire_get_digest", {"topic": "no-such"})
                bad_date = await call("wire_get_digest", {"topic": "semi", "date": "2026/10/22"})
                bad_window = await call(
                    "wire_search_events", {"keyword": KEYWORD, "window": "7 天"}
                )
                blank = await call("wire_search_events", {"keyword": " "})

    for result, expected in (
        (unknown, "semi"),
        (bad_date, "YYYY-MM-DD"),
        (bad_window, "7d"),
        (blank, "keyword"),
    ):
        assert result.is_error is True
        assert expected in _tool_content_text(result)


async def test_stdio_stdout_is_pure_jsonrpc(
    seeded_dirs: tuple[Path, Path],
) -> None:
    config_dir, data_dir = seeded_dirs
    env = _env(config_dir, data_dir)
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "qf_wire",
        "mcp",
        "stdio",
        env=env,
        cwd=str(config_dir.parent),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    seen: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
        await proc.stdin.drain()

    async def response(request_id: int) -> dict[str, Any]:
        assert proc.stdout is not None
        while True:
            line = await asyncio.wait_for(proc.stdout.readline(), 30)
            assert line, "服务端提前关闭了 stdout"
            text = line.decode("utf-8").strip()
            if not text:
                continue
            message = json.loads(text)  # 任何非 JSON 行都会在这里失败
            assert message.get("jsonrpc") == "2.0"
            seen.append(message)
            if message.get("id") == request_id and ("result" in message or "error" in message):
                return message

    try:
        await send(INITIALIZE)
        init = await response(1)
        assert "result" in init

        await send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        await send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        listed = await response(2)
        assert {tool["name"] for tool in listed["result"]["tools"]} == TOOL_NAMES

        for index, (name, arguments) in enumerate(TOOL_CALLS, start=3):
            await send(
                {
                    "jsonrpc": "2.0",
                    "id": index,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                }
            )
            called = await response(index)
            assert called["result"].get("isError") in (False, None)
            envelope = json.loads(called["result"]["content"][0]["text"])
            assert envelope["domain"] == "news"
            assert envelope["source"] == "wire"
            assert envelope["freshness"] == "archive"
            assert envelope["payload"]
    finally:
        assert proc.stdin is not None
        proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), 15)
        except asyncio.TimeoutError:  # pragma: no cover - 仅异常清理
            proc.terminate()
            await proc.wait()
        stderr = b""
        if proc.stderr is not None:
            stderr = await proc.stderr.read()
        assert proc.returncode == 0, stderr.decode("utf-8", errors="replace")

    assert seen


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _wait_http(port: int, proc: asyncio.subprocess.Process, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.returncode is not None:
            stderr = b""
            if proc.stderr is not None:
                stderr = await proc.stderr.read()
            raise AssertionError(f"HTTP 服务提前退出: {stderr.decode('utf-8', errors='replace')}")
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
            return
        except OSError:
            await asyncio.sleep(0.2)
    raise AssertionError("HTTP 服务未在超时前就绪")


async def test_http_transport_serves_all_four_tools(seeded_dirs: tuple[Path, Path]) -> None:
    config_dir, data_dir = seeded_dirs
    port = _free_port()
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "qf_wire",
        "mcp",
        "http",
        "--port",
        str(port),
        env=_env(config_dir, data_dir),
        cwd=str(config_dir.parent),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await _wait_http(port, proc)
        # trust_env=False：绕开系统代理，127.0.0.1 必须直连
        async with httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(30.0)) as client:
            async with streamable_http_client(
                f"http://127.0.0.1:{port}/mcp", http_client=client
            ) as (read, write):
                async with ClientSession(read, write) as session:
                    await asyncio.wait_for(session.initialize(), 30)
                    listed = await asyncio.wait_for(session.list_tools(), 30)
                    assert {tool.name for tool in listed.tools} == TOOL_NAMES
                    digest = _tool_payload(
                        await asyncio.wait_for(
                            session.call_tool("wire_get_digest", {"topic": "semi"}), 30
                        )
                    )
                    assert digest["payload"]["items"]
                    sources = _tool_payload(
                        await asyncio.wait_for(
                            session.call_tool("wire_list_sources", {}), 30
                        )
                    )
                    assert sources["payload"]["sources"]
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()
