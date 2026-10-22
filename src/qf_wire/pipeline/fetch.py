"""异步并发采集：asyncio + aiohttp，每个源独立超时、重试与降级。

并发度通过 QF_WIRE_FETCH_CONCURRENCY 配置（默认 24，范围 1..64），所有请求
共享一个 ClientSession 与一个全局限流信号量，单源失败不影响其他源。
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone

import aiohttp

from qf_wire.core.models import Source, SourceItem
from qf_wire.logging.setup import get_logger
from qf_wire.sources.base import (
    MAX_BYTES,
    USER_AGENT,
    FetchResult,
    SourceAdapter,
    SourceError,
    SourceTimeout,
)
from qf_wire.sources.registry import create_adapter

logger = get_logger(__name__)

BACKOFF_BASE_SEC = 0.2
BACKOFF_MAX_SEC = 1.0
CONCURRENCY_ENV = "QF_WIRE_FETCH_CONCURRENCY"
DEFAULT_CONCURRENCY = 24
MAX_CONCURRENCY = 64
CONNECTOR_LIMIT_PER_HOST = 4
CHUNK_SIZE = 64 * 1024


def resolve_concurrency(explicit: int | None = None) -> int:
    """解析并发度：显式参数 > 环境变量 > 默认值，统一裁剪到 1..64。"""
    value: int | None = None
    if explicit is not None:
        value = int(explicit)
    else:
        raw = os.environ.get(CONCURRENCY_ENV, "").strip()
        if raw:
            try:
                value = int(raw)
            except ValueError:
                logger.warning("%s=%r 不是整数，改用默认并发 %d", CONCURRENCY_ENV, raw, DEFAULT_CONCURRENCY)
    if value is None:
        value = DEFAULT_CONCURRENCY
    return max(1, min(value, MAX_CONCURRENCY))


async def fetch_source_async(
    source: Source,
    adapter: SourceAdapter | None = None,
    *,
    session: aiohttp.ClientSession | None = None,
    limiter: asyncio.Semaphore | None = None,
) -> FetchResult:
    """异步抓取单个源，按 retries 重试；返回带状态的 FetchResult，不抛异常。"""
    adapter = adapter or create_adapter(source)
    own_session = session is None
    if session is None:
        session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(
                limit=resolve_concurrency(), limit_per_host=CONNECTOR_LIMIT_PER_HOST
            )
        )
    semaphore = limiter or asyncio.Semaphore(resolve_concurrency())
    try:
        return await _fetch_with_retries(adapter, session, semaphore)
    finally:
        if own_session:
            await session.close()


async def _fetch_with_retries(
    adapter: SourceAdapter,
    session: aiohttp.ClientSession,
    limiter: asyncio.Semaphore,
) -> FetchResult:
    source = adapter.source
    attempts_allowed = source.retries + 1
    started = time.monotonic()
    last_error: str | None = None
    attempts = 0

    for attempt in range(1, attempts_allowed + 1):
        attempts = attempt
        try:
            items = await _fetch_once(adapter, session, limiter)
        except SourceTimeout as exc:
            last_error = f"超时: {exc}"
            logger.warning("信源 %s 第 %d 次抓取超时", source.id, attempt)
        except SourceError as exc:
            last_error = f"抓取失败: {exc}"
            logger.warning("信源 %s 第 %d 次抓取失败: %s", source.id, attempt, exc)
        except asyncio.CancelledError:
            raise
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
            await asyncio.sleep(min(BACKOFF_BASE_SEC * attempt, BACKOFF_MAX_SEC))

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


async def _fetch_once(
    adapter: SourceAdapter,
    session: aiohttp.ClientSession,
    limiter: asyncio.Semaphore,
) -> list[SourceItem]:
    if type(adapter).parse is SourceAdapter.parse:
        # 只实现 fetch() 的自定义适配器回退到线程，保证兼容
        async with limiter:
            return await asyncio.to_thread(adapter.fetch)

    source = adapter.source
    url = source.url
    headers = {"User-Agent": USER_AGENT, "Accept": adapter.accept}
    try:
        async with limiter:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=float(source.timeout_sec)),
            ) as response:
                if response.status >= 400:
                    raise SourceError(f"HTTP {response.status}: {url}")
                raw = await _read_limited(response)
    except SourceError:
        raise
    except (asyncio.TimeoutError, aiohttp.ServerTimeoutError) as exc:
        raise SourceTimeout(f"超时: {url}") from exc
    except aiohttp.ClientResponseError as exc:
        raise SourceError(f"HTTP {exc.status}: {url}") from exc
    except aiohttp.ClientError as exc:
        raise SourceError(f"网络错误: {exc}") from exc
    except OSError as exc:
        if "timed out" in str(exc).lower():
            raise SourceTimeout(f"超时: {url}") from exc
        raise SourceError(f"网络错误: {exc}") from exc
    return adapter.parse(raw)


async def _read_limited(response: aiohttp.ClientResponse) -> bytes:
    declared = response.content_length
    if declared and declared > MAX_BYTES:
        raise SourceError(f"响应过大（>{MAX_BYTES} bytes）")
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.content.iter_chunked(CHUNK_SIZE):
        total += len(chunk)
        if total > MAX_BYTES:
            raise SourceError(f"响应过大（>{MAX_BYTES} bytes）")
        chunks.append(chunk)
    return b"".join(chunks)


async def fetch_many_async(
    sources: list[Source],
    max_workers: int | None = None,
) -> list[FetchResult]:
    """异步并发抓取多个源，结果顺序与输入一致。"""
    if not sources:
        return []
    concurrency = resolve_concurrency(max_workers)
    logger.info("开始采集 %d 个信源（并发 %d）", len(sources), concurrency)
    limiter = asyncio.Semaphore(concurrency)
    connector = aiohttp.TCPConnector(limit=concurrency, limit_per_host=CONNECTOR_LIMIT_PER_HOST)
    async with aiohttp.ClientSession(connector=connector) as session:
        results = await asyncio.gather(
            *(_safe_fetch(source, session, limiter) for source in sources)
        )
    logger.info("采集完成：%s", status_summary(results))
    return results


async def _safe_fetch(
    source: Source,
    session: aiohttp.ClientSession,
    limiter: asyncio.Semaphore,
) -> FetchResult:
    try:
        return await fetch_source_async(source, session=session, limiter=limiter)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # fetch_source_async 已兜底，这里只防御
        logger.exception("信源 %s 采集任务异常", source.id)
        return FetchResult(
            source_id=source.id,
            source_name=source.name,
            topic=source.topic,
            status="unavailable",
            error=f"采集任务异常: {exc.__class__.__name__}: {exc}",
            attempts=0,
            fetched_at=datetime.now(timezone.utc),
        )


def fetch_source(source: Source, adapter: SourceAdapter | None = None) -> FetchResult:
    """同步入口：内部运行异步实现，供脚本与旧调用方使用。"""
    return _run(lambda: fetch_source_async(source, adapter))


def fetch_many(sources: list[Source], max_workers: int | None = None) -> list[FetchResult]:
    """同步入口：内部运行异步实现，结果顺序与输入一致。"""
    return _run(lambda: fetch_many_async(sources, max_workers))


def _run(factory):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    raise RuntimeError("当前已有运行中的事件循环，请直接使用 fetch_many_async()/fetch_source_async()")


def status_summary(results: list[FetchResult]) -> str:
    ok = sum(1 for item in results if item.status == "ok")
    degraded = sum(1 for item in results if item.status == "degraded")
    unavailable = sum(1 for item in results if item.status == "unavailable")
    return f"ok={ok} degraded={degraded} unavailable={unavailable}"
