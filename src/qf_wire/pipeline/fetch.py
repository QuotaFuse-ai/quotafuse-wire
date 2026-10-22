"""并发采集：每个源独立超时、重试与降级，单源失败不影响其他源。"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from qf_wire.core.models import Source
from qf_wire.logging.setup import get_logger
from qf_wire.sources.base import FetchResult, SourceAdapter, SourceError, SourceTimeout
from qf_wire.sources.registry import create_adapter

logger = get_logger(__name__)

BACKOFF_BASE_SEC = 0.2
BACKOFF_MAX_SEC = 1.0


def fetch_source(source: Source, adapter: SourceAdapter | None = None) -> FetchResult:
    """抓取单个源，按 retries 重试；返回带状态的 FetchResult，不抛异常。"""
    adapter = adapter or create_adapter(source)
    attempts_allowed = source.retries + 1
    started = time.monotonic()
    last_error: str | None = None
    attempts = 0

    for attempt in range(1, attempts_allowed + 1):
        attempts = attempt
        try:
            items = adapter.fetch()
        except SourceTimeout as exc:
            last_error = f"超时: {exc}"
            logger.warning("信源 %s 第 %d 次抓取超时", source.id, attempt)
        except SourceError as exc:
            last_error = f"抓取失败: {exc}"
            logger.warning("信源 %s 第 %d 次抓取失败: %s", source.id, attempt, exc)
        except Exception as exc:  # 适配器不应抛出未包装异常，兜底保证全局不中断
            last_error = f"适配器异常: {exc.__class__.__name__}: {exc}"
            logger.exception("信源 %s 第 %d 次抓取出现未预期异常", source.id, attempt)
        else:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            status = "ok" if attempt == 1 else "degraded"
            if status == "degraded":
                logger.info("信源 %s 重试 %d 次后成功（degraded）", source.id, attempt - 1)
            return FetchResult(
                source_id=source.id,
                source_name=source.name,
                topic=source.topic,
                status=status,
                items=items,
                attempts=attempt,
                elapsed_ms=elapsed_ms,
                fetched_at=datetime.now(timezone.utc),
            )

        if attempt < attempts_allowed:
            time.sleep(min(BACKOFF_BASE_SEC * attempt, BACKOFF_MAX_SEC))

    elapsed_ms = int((time.monotonic() - started) * 1000)
    logger.warning("信源 %s 不可用: %s", source.id, last_error)
    return FetchResult(
        source_id=source.id,
        source_name=source.name,
        topic=source.topic,
        status="unavailable",
        items=[],
        error=last_error,
        attempts=attempts,
        elapsed_ms=elapsed_ms,
        fetched_at=datetime.now(timezone.utc),
    )


def fetch_many(sources: list[Source], max_workers: int = 12) -> list[FetchResult]:
    """并发抓取多个源，结果顺序与输入一致。"""
    if not sources:
        return []
    workers = max(1, min(max_workers, len(sources)))
    results: list[FetchResult | None] = [None] * len(sources)
    logger.info("开始采集 %d 个信源（并发 %d）", len(sources), workers)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="qf-fetch") as pool:
        futures = {
            pool.submit(fetch_source, source): index
            for index, source in enumerate(sources)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception as exc:  # fetch_source 已兜底，这里只防御
                source = sources[index]
                logger.exception("信源 %s 采集线程异常", source.id)
                results[index] = FetchResult(
                    source_id=source.id,
                    source_name=source.name,
                    topic=source.topic,
                    status="unavailable",
                    error=f"采集线程异常: {exc}",
                    attempts=0,
                    fetched_at=datetime.now(timezone.utc),
                )
    final = [item for item in results if item is not None]
    logger.info("采集完成：%s", status_summary(final))
    return final


def status_summary(results: list[FetchResult]) -> str:
    ok = sum(1 for item in results if item.status == "ok")
    degraded = sum(1 for item in results if item.status == "degraded")
    unavailable = sum(1 for item in results if item.status == "unavailable")
    return f"ok={ok} degraded={degraded} unavailable={unavailable}"
