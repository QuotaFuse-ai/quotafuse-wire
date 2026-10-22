"""qfw topics：查看与新增赛道。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import typer
import yaml
from pydantic import ValidationError

from qf_wire.cli.context import AppContext, emit_json, emit_mapping, emit_rows
from qf_wire.core.errors import ConfigError, ParamError
from qf_wire.core.models import Topic

topics_app = typer.Typer(help="赛道列表与新增", no_args_is_help=True)

TOPIC_COLUMNS = [
    ("id", "id"),
    ("name", "名称"),
    ("legacy_key", "legacy_key"),
    ("aliases", "别名"),
    ("keywords", "关键词"),
    ("sources", "信源数"),
]


@topics_app.command("list")
def list_topics(ctx: typer.Context) -> int:
    app_ctx: AppContext = ctx.obj
    config = app_ctx.config()
    rows = [
        {
            "id": topic.id,
            "name": topic.name,
            "legacy_key": topic.legacy_key or "",
            "aliases": ", ".join(topic.aliases),
            "keywords": ", ".join(topic.keywords),
            "sources": len(topic.sources),
            "accent": topic.accent or "",
        }
        for topic in config.topics
    ]
    if app_ctx.output == "json":
        emit_json({"count": len(rows), "topics": rows})
    else:
        emit_rows(rows, TOPIC_COLUMNS, app_ctx.output)
    return 0


def _load_topic_file(path: Path) -> list[Topic]:
    if not path.is_file():
        raise ParamError(f"文件不存在: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ParamError(f"无法解析 {path}: {exc}") from exc
    entries: list[Any]
    if isinstance(data, dict) and "topics" in data:
        raw = data["topics"]
        entries = raw if isinstance(raw, list) else [raw]
    elif isinstance(data, dict):
        entries = [data]
    elif isinstance(data, list):
        entries = data
    else:
        raise ParamError("赛道文件必须是对象或对象列表")
    topics: list[Topic] = []
    for index, entry in enumerate(entries, start=1):
        try:
            topics.append(Topic.model_validate(entry))
        except ValidationError as exc:
            raise ParamError(f"第 {index} 个赛道配置无效: {exc}") from exc
    return topics


@topics_app.command("add")
def add_topic(
    ctx: typer.Context,
    file: Path = typer.Option(..., "--file", "-f", exists=True, dir_okay=False, help="赛道 YAML 文件"),
) -> int:
    app_ctx: AppContext = ctx.obj
    config = app_ctx.config()
    additions = _load_topic_file(file)
    existing = {topic.id for topic in config.topics}
    source_ids = {source.id for source in config.sources}

    for topic in additions:
        if topic.id in existing:
            raise ParamError(f"赛道已存在: {topic.id}")
        missing = [source_id for source_id in topic.sources if source_id not in source_ids]
        if missing:
            raise ConfigError(f"赛道 {topic.id} 引用了不存在的信源: {', '.join(missing)}")

    target = config.paths.config_dir / "topics.yaml"
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"无法读取 {target}: {exc}") from exc
    entries = raw.get("topics") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        raise ConfigError(f"{target} 缺少 topics 列表")

    entries.extend(topic.model_dump(exclude_none=True) for topic in additions)
    payload = dict(raw)
    payload["topics"] = entries
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    os.replace(temp, target)

    added = [topic.id for topic in additions]
    if app_ctx.output == "json":
        emit_json({"added": added, "file": str(target)})
    elif app_ctx.output == "csv":
        emit_rows([{"added": ";".join(added), "file": str(target)}], [("added", "added"), ("file", "file")], "csv")
    else:
        emit_mapping({"added": ", ".join(added), "file": str(target)}, "table")
    return 0
