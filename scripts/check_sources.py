"""批量校验信源可用性。

用法：
    python scripts/check_sources.py                  # 校验全部 enabled 源
    python scripts/check_sources.py --topic semiconductor
    python scripts/check_sources.py --concurrency 32 --timeout 8

输出：表格（stdout），失败明细逐条打印。退出码 0 全部可用 / 4 有源不可用。
需要项目已安装（pip install -e .）。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qf_wire.config.loader import load_sources, load_topics  # noqa: E402
from qf_wire.pipeline.fetch import fetch_source  # noqa: E402


async def _probe(source, timeout: int, sem: asyncio.Semaphore):
    async with sem:
        result = await fetch_source(source, timeout=timeout)
        return source, result


async def main_async(args: argparse.Namespace) -> int:
    sources = load_sources()
    if args.topic:
        topic = load_topics().get(args.topic)
        if topic is None:
            print(f"unknown topic: {args.topic}", file=sys.stderr)
            return 2
        allowed = set(topic["sources"])
        sources = [s for s in sources if s["id"] in allowed]
    sources = [s for s in sources if s.get("enabled", True)]

    sem = asyncio.Semaphore(args.concurrency)
    results = await asyncio.gather(
        *(_probe(s, args.timeout or s.get("timeout_sec", 15), sem) for s in sources)
    )

    ok, failed = [], []
    for source, result in results:
        if result.ok:
            ok.append((source, result))
        else:
            failed.append((source, result))

    print(f"{'SOURCE':<28}{'STATUS':<10}{'ITEMS':<8}{'MS':<8}ERROR")
    for source, result in sorted(results, key=lambda r: (not r[1].ok, r[0]["id"])):
        status = "ok" if result.ok else "fail"
        print(
            f"{source['id']:<28}{status:<10}{result.item_count:<8}"
            f"{result.elapsed_ms:<8}{result.error or ''}"
        )

    print(f"\ntotal={len(results)} ok={len(ok)} failed={len(failed)}", file=sys.stderr)
    return 0 if not failed else 4


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="批量校验 QuotaFuse Wire 信源可用性")
    p.add_argument("--topic", help="只校验某个赛道")
    p.add_argument("--concurrency", type=int, default=16)
    p.add_argument("--timeout", type=int, default=0, help="覆盖源配置里的超时（秒）")
    return p


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async(build_parser().parse_args())))
