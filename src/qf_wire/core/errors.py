"""退出码与领域异常，与升级文档保持同一契约。"""
from __future__ import annotations

EXIT_OK = 0
EXIT_PARAM = 2
EXIT_CONFIG = 3
EXIT_UNAVAILABLE = 4
EXIT_NOT_FOUND = 6
EXIT_PARTIAL = 8

EXIT_DESCRIPTIONS = {
    EXIT_OK: "成功",
    EXIT_PARAM: "参数错误",
    EXIT_CONFIG: "配置错误",
    EXIT_UNAVAILABLE: "信源不可用",
    EXIT_NOT_FOUND: "对象不存在",
    EXIT_PARTIAL: "部分源失败",
}


class WireError(RuntimeError):
    """可预期错误，CLI 将其转换为对应退出码。"""

    exit_code = EXIT_CONFIG


class ParamError(WireError):
    exit_code = EXIT_PARAM


class ConfigError(WireError):
    exit_code = EXIT_CONFIG


class SourcesUnavailableError(WireError):
    exit_code = EXIT_UNAVAILABLE


class NotFoundError(WireError):
    exit_code = EXIT_NOT_FOUND
