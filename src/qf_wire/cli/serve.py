"""qfw serve：启动本地看板（默认 127.0.0.1:8790）。"""
from __future__ import annotations

import sys

import typer

from qf_wire.cli.context import AppContext
from qf_wire.core.errors import EXIT_UNAVAILABLE


def serve_command(
    ctx: typer.Context,
    host: str = typer.Option("127.0.0.1", "--host", help="监听地址，默认仅本机"),
    port: int = typer.Option(8790, "--port", "-p", min=1, max=65535, help="监听端口"),
) -> int:
    app_ctx: AppContext = ctx.obj
    config = app_ctx.config()

    from qf_wire.web.server import serve_forever

    try:
        serve_forever(config, host=host, port=port)
    except OSError as exc:
        sys.stderr.write(f"[qfw] 无法启动看板 {host}:{port}: {exc}\n")
        return EXIT_UNAVAILABLE
    except KeyboardInterrupt:
        sys.stderr.write("[qfw] 看板已停止\n")
    return 0
