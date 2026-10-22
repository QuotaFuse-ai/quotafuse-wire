"""qfw mcp：stdio（客户端拉起）与 streamable http（默认仅本机 8791）。"""
from __future__ import annotations

import sys

import typer

from qf_wire.cli.context import AppContext
from qf_wire.core.errors import EXIT_UNAVAILABLE
from qf_wire.mcp.server import DEFAULT_HTTP_PORT

mcp_app = typer.Typer(
    help="MCP Server：向 Agent 暴露四个只读资讯工具",
    no_args_is_help=True,
)


@mcp_app.command("stdio")
def stdio_command(ctx: typer.Context) -> int:
    app_ctx: AppContext = ctx.obj
    config = app_ctx.config()

    from qf_wire.mcp.server import run_stdio

    run_stdio(config)
    return 0


@mcp_app.command("http")
def http_command(
    ctx: typer.Context,
    host: str = typer.Option("127.0.0.1", "--host", help="监听地址，默认仅本机"),
    port: int = typer.Option(DEFAULT_HTTP_PORT, "--port", "-p", min=1, max=65535, help="监听端口"),
) -> int:
    app_ctx: AppContext = ctx.obj
    config = app_ctx.config()

    from qf_wire.mcp.server import run_http

    try:
        run_http(config, host=host, port=port)
    except OSError as exc:
        sys.stderr.write(f"[qfw] 无法启动 MCP http {host}:{port}: {exc}\n")
        return EXIT_UNAVAILABLE
    except KeyboardInterrupt:
        sys.stderr.write("[qfw] MCP http 已停止\n")
    return 0
