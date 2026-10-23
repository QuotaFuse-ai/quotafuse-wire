"""qfw token：查看或生成多用户模式下某个用户的 API 凭据。"""
from __future__ import annotations

import typer

from qf_wire.cli.context import AppContext, emit_mapping
from qf_wire.config.loader import USER_ID_PATTERN, resolve_paths
from qf_wire.config.usertoken import ensure_user_token
from qf_wire.core.errors import EXIT_OK, ParamError


def token_command(
    ctx: typer.Context,
    user: str = typer.Option(None, "--user", help="用户 id（默认取 --user / QF_WIRE_USER）"),
    rotate: bool = typer.Option(False, "--rotate", help="重新生成，旧凭据立即失效"),
) -> int:
    app_ctx: AppContext = ctx.obj
    target = (user or app_ctx.user or "").strip()
    if not target:
        raise ParamError("请用 --user 指定用户（或 QF_WIRE_USER）")
    if not USER_ID_PATTERN.fullmatch(target):
        raise ParamError(f"用户 id 只允许字母、数字、下划线和短横线（1-64 位）: {target}")

    paths = resolve_paths(app_ctx.config_dir, app_ctx.data_dir, target)
    base_data_dir = paths.base_data_dir or paths.data_dir
    token, path, created = ensure_user_token(base_data_dir, target, rotate=rotate)
    emit_mapping(
        {"user": target, "token": token, "created": created, "path": str(path)},
        app_ctx.output,
    )
    return EXIT_OK
