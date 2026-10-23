"""CLI 退出码契约：0 成功 / 2 参数错误 / 3 配置或未实现。"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from qf_wire.cli.main import cli
from qf_wire.core.errors import EXIT_OK, EXIT_PARAM


def test_version_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli(["--version"]) == EXIT_OK
    assert capsys.readouterr().out.startswith("qfw ")


def test_missing_command_is_parameter_error() -> None:
    assert cli([]) == EXIT_PARAM


def test_unknown_option_is_parameter_error() -> None:
    assert cli(["run", "--output", "json"]) == EXIT_PARAM


def test_unknown_topic_is_parameter_error() -> None:
    assert cli(["run", "--sources-only", "--topic", "nope"]) == EXIT_PARAM


def test_mcp_without_transport_lists_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli(["mcp"]) == EXIT_PARAM
    out = capsys.readouterr().out
    assert "stdio" in out
    assert "http" in out


def test_cli_import_does_not_require_mcp() -> None:
    """看板与采集只导入 CLI，不应连带加载 mcp 包。"""
    completed = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-c",
            "import sys, qf_wire.cli.main; "
            "assert 'qf_wire.mcp.server' not in sys.modules; print('ok')",
        ],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert completed.returncode == 0, completed.stderr
    assert "ok" in completed.stdout
