"""qfw 命令入口。

`cli(argv) -> int` 是兼容层的硬契约：compatibility/*.py 直接调用并透传退出码。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import click
import typer

from qf_wire import __version__
from qf_wire.cli.config import config_app
from qf_wire.cli.context import OUTPUT_FORMATS, AppContext
from qf_wire.cli.digest import digest_command
from qf_wire.cli.event import event_app
from qf_wire.cli.history import history_command
from qf_wire.cli.mcp import mcp_app
from qf_wire.cli.run import run_command
from qf_wire.cli.schedule import schedule_command
from qf_wire.cli.serve import serve_command
from qf_wire.cli.sources import sources_app
from qf_wire.cli.topics import topics_app
from qf_wire.config.dotenv import load_dotenv
from qf_wire.config.loader import resolve_paths
from qf_wire.config.migrate import auto_migrate
from qf_wire.core.errors import EXIT_CONFIG, EXIT_PARAM, WireError
from qf_wire.logging.setup import setup_logging

app = typer.Typer(
    name="qfw",
    help="QuotaFuse Wire —— 多源资讯采集与 AI 提炼（本地优先）",
    no_args_is_help=True,
    add_completion=False,
)

app.add_typer(sources_app, name="sources")
app.add_typer(topics_app, name="topics")
app.add_typer(config_app, name="config")
app.add_typer(event_app, name="event")
app.add_typer(mcp_app, name="mcp")


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    output: str = typer.Option(
        os.environ.get("QF_WIRE_OUTPUT", "table"),
        "--output",
        "-o",
        help="结果输出格式：json | table | csv",
    ),
    config_dir: Path = typer.Option(None, "--config-dir", help="配置目录（默认 <root>/config）"),
    data_dir: Path = typer.Option(None, "--data-dir", help="数据目录（默认 <root>/data）"),
    user: str = typer.Option(None, "--user", help="多用户模式下的用户 id（也可用 QF_WIRE_USER）"),
    log_level: str = typer.Option(None, "--log-level", help="日志级别（stderr）"),
    version: bool = typer.Option(False, "--version", help="打印版本号"),
) -> None:
    if version:
        typer.echo(f"qfw {__version__}")
        raise typer.Exit(0)
    fmt = (output or "table").lower()
    if fmt not in OUTPUT_FORMATS:
        raise typer.BadParameter(f"--output 只支持 {', '.join(OUTPUT_FORMATS)}")
    setup_logging(log_level)
    ctx.obj = AppContext(output=fmt, config_dir=config_dir, data_dir=data_dir, user=user)

    paths = resolve_paths(config_dir, data_dir, user)
    report = auto_migrate([Path.cwd(), paths.data_dir.parent], paths.config_dir)
    if report is not None:
        for line in report.lines:
            click.echo(f"[qfw] {line}", err=True)

    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        raise typer.Exit(EXIT_PARAM)


app.command("run")(run_command)
app.command("digest")(digest_command)
app.command("serve")(serve_command)
app.command("schedule")(schedule_command)
app.command("history")(history_command)


def cli(argv: list[str] | None = None) -> int:
    """执行一次 CLI 调用并返回进程退出码。"""
    load_dotenv()
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        result = app(args=args, standalone_mode=False)
    except (click.exceptions.Exit, typer.Exit) as exc:
        return int(exc.exit_code)
    except (click.ClickException, typer.TyperException) as exc:
        show = getattr(exc, "show", None)
        if callable(show):
            show(file=sys.stderr)
        else:
            sys.stderr.write(f"[qfw] {exc}\n")
        return int(getattr(exc, "exit_code", EXIT_PARAM) or EXIT_PARAM)
    except WireError as exc:
        sys.stderr.write(f"[qfw] {exc}\n")
        return int(exc.exit_code)
    except KeyboardInterrupt:
        sys.stderr.write("[qfw] 已中断\n")
        return 130
    except BrokenPipeError:
        return 0
    except Exception as exc:  # 未预期错误：保留可诊断信息，但给出统一退出码
        if os.environ.get("QF_WIRE_DEBUG"):
            raise
        sys.stderr.write(f"[qfw] 内部错误: {exc}\n")
        return EXIT_CONFIG
    return int(result or 0)


def main() -> None:
    raise SystemExit(cli())


if __name__ == "__main__":
    main()
