"""CLI 退出码契约：0 成功 / 2 参数错误 / 3 配置或未实现。"""
from __future__ import annotations

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
