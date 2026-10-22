"""读取仓库根目录的 .env / .env.local，把配置注入当前进程。

只做最小解析：KEY=VALUE、忽略注释与空行、支持引号。优先级：
真实环境变量 > .env.local > .env；空值视为未配置，交给代码里的默认值。
"""
from __future__ import annotations

import os
from collections.abc import Mapping
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


def _format_value(value: str) -> str:
    if '"' in value or "\n" in value or "\r" in value:
        raise ValueError("配置值不能包含双引号或换行")
    if value != value.strip() or any(ch in value for ch in " #'"):
        return f'"{value}"'
    return value


def write_env_file(path: Path | str, values: Mapping[str, str]) -> Path:
    """把 KEY=VALUE 合并写入文件；空字符串表示删除该键，其余行原样保留。

    看板里的 AI 设置写的就是本机 .env.local（.gitignore 已忽略）。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if target.is_file():
        lines = target.read_text(encoding="utf-8-sig").splitlines()

    pending = {key: value for key, value in values.items() if key}
    kept: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        key = ""
        if stripped and not stripped.startswith("#"):
            candidate = stripped[len("export "):].lstrip() if stripped.startswith("export ") else stripped
            key = candidate.partition("=")[0].strip()
        if key and key in pending:
            value = pending.pop(key)
            if value:
                kept.append(f"{key}={_format_value(value)}")
            continue
        kept.append(raw)
    for key, value in pending.items():
        if value:
            kept.append(f"{key}={_format_value(value)}")

    text = "\n".join(kept).strip("\n")
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(text + "\n" if text else "", encoding="utf-8")
    os.replace(temporary, target)
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return target
