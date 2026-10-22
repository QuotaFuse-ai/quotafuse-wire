"""MCP Server 装配。

stdio 模式下 stdout 只承载 JSON-RPC 报文，日志一律走 stderr；
http 传输默认只监听 127.0.0.1:8791。
"""
from __future__ import annotations

from pathlib import Path

from mcp.server.mcpserver import MCPServer

from qf_wire import __version__
from qf_wire.config.loader import WireConfig
from qf_wire.mcp.tools import WireTools

SERVER_NAME = "quota-fuse-wire"
DEFAULT_HTTP_PORT = 8791

INSTRUCTIONS = (
    "QuotaFuse Wire 提供本地只读资讯能力：每日提炼、事件检索、事件时间线、信源评分。"
    "所有工具只读，不触发采集；内容仅供信息参考，不构成任何买卖建议。"
)


def create_server(
    config: WireConfig | None = None,
    *,
    config_dir: str | Path | None = None,
    data_dir: str | Path | None = None,
) -> MCPServer:
    """构建带四个只读工具的 MCP Server。"""
    server = MCPServer(
        name=SERVER_NAME,
        version=__version__,
        instructions=INSTRUCTIONS,
        log_level="WARNING",
    )
    tools = WireTools(config=config, config_dir=config_dir, data_dir=data_dir)

    @server.tool(
        name="wire_get_digest",
        description="取某赛道某日的要点与条目；date 省略时取该赛道最新可用日期。",
    )
    def wire_get_digest(topic: str, date: str | None = None) -> str:
        return tools.wire_get_digest(topic, date)

    @server.tool(
        name="wire_search_events",
        description="按关键词在时间窗口（Nd 或 Nh，默认 7d）内检索事件的多源报道。",
    )
    def wire_search_events(
        keyword: str,
        window: str | None = None,
        topic: str | None = None,
    ) -> str:
        return tools.wire_search_events(keyword, window, topic)

    @server.tool(
        name="wire_get_timeline",
        description="取单个事件的多源报道时间线，按发布时间升序。",
    )
    def wire_get_timeline(event_id: str) -> str:
        return tools.wire_get_timeline(event_id)

    @server.tool(
        name="wire_list_sources",
        description="列出信源及其质量评分，可按赛道过滤。",
    )
    def wire_list_sources(topic: str | None = None) -> str:
        return tools.wire_list_sources(topic)

    return server


def run_stdio(
    config: WireConfig | None = None,
    *,
    config_dir: str | Path | None = None,
    data_dir: str | Path | None = None,
) -> None:
    create_server(config, config_dir=config_dir, data_dir=data_dir).run("stdio")


def run_http(
    config: WireConfig | None = None,
    *,
    config_dir: str | Path | None = None,
    data_dir: str | Path | None = None,
    host: str = "127.0.0.1",
    port: int = DEFAULT_HTTP_PORT,
) -> None:
    create_server(config, config_dir=config_dir, data_dir=data_dir).run(
        "streamable-http", host=host, port=port
    )
