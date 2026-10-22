"""读取仓库根目录的 .env / .env.local，把配置注入当前进程。

只做最小解析：KEY=VALUE、忽略注释与空行、支持引号。优先级：
真实环境变量 > .env.local > .env；空值视为未配置，交给代码里的默认值。
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_FILENAME = ".env"
LOCAL_FILENAME = ".env.local"
ENV_OVERRIDE = "QF_WIRE_ENV_FILE"


def parse_dotenv(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        else:
            marker = value.find(" #")
            if marker != -1:
                value = value[:marker].rstrip()
        if value:
            values[key] = value
    return values


def find_dotenv(start: Path | None = None) -> Path | None:
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        candidate = Path(override).expanduser()
        return candidate if candidate.is_file() else None
    base = (start or Path.cwd()).resolve()
    for directory in (base, *base.parents):
        for filename in (LOCAL_FILENAME, ENV_FILENAME):
            candidate = directory / filename
            if candidate.is_file():
                return candidate
    return None


def _read_values(path: Path) -> dict[str, str]:
    try:
        return parse_dotenv(path.read_text(encoding="utf-8-sig"))
    except OSError:
        return {}


def load_dotenv(path: Path | str | None = None) -> Path | None:
    """加载 .env / .env.local 并返回实际使用的路径；未找到时返回 None。"""
    override = os.environ.get(ENV_OVERRIDE)
    explicit = Path(path or override).expanduser() if (path or override) else None
    anchor = explicit or find_dotenv()
    if anchor is None or not anchor.is_file():
        return None

    values: dict[str, str] = {}
    if explicit is None:
        environment = anchor.with_name(ENV_FILENAME)
        if environment.is_file():
            values.update(_read_values(environment))
        local = anchor.with_name(LOCAL_FILENAME)
        if local.is_file():
            values.update(_read_values(local))
    else:
        values.update(_read_values(explicit))

    for key, value in values.items():
        os.environ.setdefault(key, value)
    return anchor


def first_env(*names: str) -> str | None:
    """按顺序返回第一个非空环境变量值。"""
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None
