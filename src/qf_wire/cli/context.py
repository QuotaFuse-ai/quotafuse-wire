"""CLI 共享上下文与输出格式。"""
from __future__ import annotations

import csv
import json
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from qf_wire.config.loader import WireConfig, load_config
from qf_wire.core.errors import NotFoundError, ParamError
from qf_wire.storage.sqlite import WireStore

OUTPUT_FORMATS = ("json", "table", "csv")
DEFAULT_OUTPUT = "table"


@dataclass(slots=True)
class AppContext:
    output: str = DEFAULT_OUTPUT
    config_dir: Path | None = None
    data_dir: Path | None = None
    user: str | None = None
    _config: WireConfig | None = field(default=None, repr=False)

    def config(self) -> WireConfig:
        if self._config is None:
            self._config = load_config(self.config_dir, self.data_dir, user=self.user)
        return self._config

    def open_store(self) -> WireStore:
        paths = self.config().paths
        if not paths.db_path.is_file():
            raise NotFoundError(f"未找到数据库 {paths.db_path}，请先运行 qfw run")
        store = WireStore(paths.db_path)
        store.initialize()
        return store


def _json_default(value: object) -> object:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return str(value)


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=_json_default)
    return str(value)


def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _width(text))


def emit_json(payload: Any) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n")


def emit_rows(rows: Iterable[dict[str, Any]], columns: Sequence[tuple[str, str]], fmt: str) -> None:
    materialized = [dict(row) for row in rows]
    if fmt == "json":
        emit_json(materialized)
        return
    if fmt == "csv":
        writer = csv.writer(sys.stdout, lineterminator="\n")
        writer.writerow([label for _, label in columns])
        for row in materialized:
            writer.writerow([_cell(row.get(key)) for key, _ in columns])
        return

    headers = [label for _, label in columns]
    body = [[_cell(row.get(key)) for key, _ in columns] for row in materialized]
    widths = [max(_width(header), *(_width(line[index]) for line in body)) if body else _width(header) for index, header in enumerate(headers)]
    sys.stdout.write("  ".join(_pad(header, widths[index]) for index, header in enumerate(headers)).rstrip() + "\n")
    sys.stdout.write("  ".join("-" * widths[index] for index in range(len(headers))) + "\n")
    for line in body:
        sys.stdout.write("  ".join(_pad(value, widths[index]) for index, value in enumerate(line)).rstrip() + "\n")


def emit_mapping(payload: dict[str, Any], fmt: str) -> None:
    if fmt in {"json", "csv"}:
        emit_json(payload)
        return
    width = max((_width(str(key)) for key in payload), default=0)
    for key, value in payload.items():
        sys.stdout.write(f"{_pad(str(key), width)}  {_cell(value)}\n")


def emit_lines(lines: Iterable[str]) -> None:
    for line in lines:
        sys.stdout.write(line + "\n")


def parse_day(value: str | None, *, label: str = "日期") -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ParamError(f"{label}格式应为 YYYY-MM-DD: {value}") from exc
