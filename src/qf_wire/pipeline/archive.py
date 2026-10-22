"""按日期归档：data/archive/<YYYY-MM-DD>/ 下的 JSON 快照（可选 Parquet）。"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from qf_wire.core.models import Event, SourceItem, TopicDigest
from qf_wire.logging.setup import get_logger
from qf_wire.sources.base import FetchResult
from qf_wire.storage import parquet

logger = get_logger(__name__)

ARCHIVE_VERSION = 1


def archive_day(
    archive_dir: Path,
    *,
    day: date | str,
    run_id: str,
    generated_at: datetime,
    source_results: list[FetchResult],
    items_by_topic: dict[str, list[SourceItem]],
    events_by_topic: dict[str, list[Event]],
    digests: dict[str, TopicDigest],
) -> Path:
    """把一天的运行结果写入归档目录；返回目录路径。"""
    day_text = day.isoformat() if isinstance(day, date) else str(day)
    target = archive_dir / day_text
    target.mkdir(parents=True, exist_ok=True)

    all_items = [
        {"topic": topic, **item.model_dump(mode="json")}
        for topic, items in items_by_topic.items()
        for item in items
    ]
    all_events = [
        {"topic": topic, **event.model_dump(mode="json")}
        for topic, events in events_by_topic.items()
        for event in events
    ]
    sources = [result.summary() for result in source_results]
    digest_data = {topic: digest.model_dump(mode="json") for topic, digest in digests.items()}

    _write_json(target / "items.json", {"date": day_text, "items": all_items})
    _write_json(target / "events.json", {"date": day_text, "events": all_events})
    _write_json(target / "sources.json", {"date": day_text, "sources": sources})
    _write_json(target / "digests.json", {"date": day_text, "digests": digest_data})

    parquet.write_rows(target / "items.parquet", all_items)
    parquet.write_rows(target / "events.parquet", all_events)

    manifest = {
        "version": ARCHIVE_VERSION,
        "date": day_text,
        "run_id": run_id,
        "generated_at": generated_at.isoformat(),
        "counts": {
            "items": len(all_items),
            "events": len(all_events),
            "sources": len(sources),
            "digests": len(digest_data),
        },
        "files": sorted(
            path.name for path in target.iterdir() if path.is_file() and path.name != "manifest.json"
        ),
    }
    _write_json(target / "manifest.json", manifest)
    logger.info("已归档 %s：%d 条资讯", target, len(all_items))
    return target


def read_archive_day(archive_dir: Path, day: date | str) -> dict[str, Any] | None:
    """读取某天的归档快照；不存在返回 None。"""
    day_text = day.isoformat() if isinstance(day, date) else str(day)
    target = archive_dir / day_text
    if not target.is_dir():
        return None
    result: dict[str, Any] = {}
    for name in ("items", "events", "sources", "digests", "manifest"):
        path = target / f"{name}.json"
        if path.exists():
            result[name] = json.loads(path.read_text(encoding="utf-8"))
    return result


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)
