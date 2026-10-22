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

from qf_wire.config.loader import load_sources, load_topics  # noqa: E402


def export(include_scores: bool = False) -> dict:
    topics = load_topics()
    sources = load_sources()
    scores: dict[str, dict] = {}
    if include_scores:
        from qf_wire.storage.sqlite import SourceScoreRepository

        scores = SourceScoreRepository().all_scores()

    payload = {
        "version": 1,
        "topics": [
            {
                "id": t["id"],
                "name": t["name"],
                "legacy_key": t.get("legacy_key"),
                "aliases": t.get("aliases", []),
                "keywords": t.get("keywords", []),
            }
            for t in topics.values()
        ],
        "sources": [
            {
                "id": s["id"],
                "name": s["name"],
                "topic": s.get("topic"),
                "type": s.get("type", "rss"),
                "url": s.get("url"),
                "weight": s.get("weight", 1.0),
                "enabled": s.get("enabled", True),
                **({"score": scores[s["id"]]} if s["id"] in scores else {}),
            }
            for s in sources
            if s.get("url")
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
