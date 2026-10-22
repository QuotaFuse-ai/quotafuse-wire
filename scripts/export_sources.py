"""导出生态共享的信源清单。

用法：
    python scripts/export_sources.py                      # 输出到 stdout
    python scripts/export_sources.py --output sources.json
    python scripts/export_sources.py --include-scores     # 附带历史评分（需已有 wire.db）

输出结构为生态共享格式：
{"version": 1, "topics": [...], "sources": [...]}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qf_wire.config.loader import load_config  # noqa: E402
from qf_wire.storage.sqlite import WireStore  # noqa: E402


def export(include_scores: bool = False) -> dict:
    config = load_config()
    scores: dict[str, dict] = {}
    if include_scores and config.paths.db_path.is_file():
        store = WireStore(config.paths.db_path)
        try:
            scores = {str(entry["source_id"]): entry for entry in store.source_scores()}
        finally:
            store.close()

    def topic_of(source_id: str, fallback: str | None) -> str | None:
        if fallback:
            return fallback
        for topic in config.topics:
            if source_id in topic.sources:
                return topic.id
        return None

    payload = {
        "version": 1,
        "topics": [
            {
                "id": topic.id,
                "name": topic.name,
                "legacy_key": topic.legacy_key,
                "aliases": topic.aliases,
                "keywords": topic.keywords,
            }
            for topic in config.topics
        ],
        "sources": [
            {
                "id": source.id,
                "name": source.name,
                "topic": topic_of(source.id, source.topic),
                "type": source.type,
                "url": source.url,
                "weight": source.weight,
                "enabled": source.enabled,
                **({"score": scores[source.id]} if source.id in scores else {}),
            }
            for source in config.sources
        ],
    }
    return payload


def main() -> int:
    p = argparse.ArgumentParser(description="导出生态共享信源清单")
    p.add_argument("--output", "-o", help="输出文件，缺省写 stdout")
    p.add_argument("--include-scores", action="store_true")
    p.add_argument("--pretty", action="store_true", help="缩进输出")
    args = p.parse_args()

    data = export(args.include_scores)
    text = json.dumps(data, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(f"exported {len(data['sources'])} sources -> {args.output}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
