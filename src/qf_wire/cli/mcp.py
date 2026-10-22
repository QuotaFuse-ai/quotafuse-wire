"""qfw mcp：M1 占位，M2 提供 MCP 工具。"""
from __future__ import annotations

import sys

import typer

from qf_wire.core.errors import EXIT_CONFIG


def mcp_command(ctx: typer.Context) -> int:
    sys.stderr.write("[qfw] qfw mcp 将在 M2 提供（M1 暂未实现），当前返回退出码 3\n")
    return EXIT_CONFIG
