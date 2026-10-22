"""信源适配器抽象与统一抓取结果。"""
from __future__ import annotations

import gzip
import zlib
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from qf_wire.core.models import Source, SourceItem, SourceStatus

USER_AGENT = "QuotaFuse-Wire/0.1 (+https://github.com/QuotaFuse-ai/quotafuse-wire)"
MAX_BYTES = 8 * 1024 * 1024


class SourceError(RuntimeError):
    """信源抓取或解析失败的统一异常。"""


class SourceTimeout(SourceError):
    pass


class SourceAdapter(ABC):
    """所有信源适配器的基类。

    网络层与解析层分离：`fetch()` 供同步路径使用；异步采集由 fetch 管道
    通过 aiohttp 拉取字节后调用 `parse()`，避免重复实现网络代码。
    """

    source_type: ClassVar[str] = "base"
    accept: ClassVar[str] = "*/*"

    def __init__(self, source: Source) -> None:
        self.source = source

    @abstractmethod
    def fetch(self, timeout_sec: float | None = None) -> list[SourceItem]:
        """拉取并解析条目；失败时抛出 SourceError。"""

    def parse(self, raw: bytes) -> list[SourceItem]:
        """解析已下载的响应体；供异步采集复用。"""
        raise SourceError(f"适配器 {type(self).__name__} 未实现 parse()，无法用于异步采集")

    def _timeout(self, timeout_sec: float | None) -> float:
        return float(timeout_sec or self.source.timeout_sec)

    def _get(self, url: str | None = None, timeout_sec: float | None = None, accept: str = "*/*") -> bytes:
        target = url or self.source.url
        request = Request(
            target,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": accept,
                "Accept-Encoding": "gzip, deflate",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout(timeout_sec)) as response:
                raw = response.read(MAX_BYTES + 1)
                encoding = (response.headers.get("Content-Encoding") or "").lower()
        except HTTPError as exc:
            raise SourceError(f"HTTP {exc.code}: {target}") from exc
        except URLError as exc:
            reason = getattr(exc, "reason", exc)
            if "timed out" in str(reason).lower():
                raise SourceTimeout(f"超时: {target}") from exc
            raise SourceError(f"网络错误: {reason}") from exc
        except TimeoutError as exc:
            raise SourceTimeout(f"超时: {target}") from exc
        except OSError as exc:
            if "timed out" in str(exc).lower():
                raise SourceTimeout(f"超时: {target}") from exc
            raise SourceError(f"网络错误: {exc}") from exc

        if len(raw) > MAX_BYTES:
            raise SourceError(f"响应过大（>{MAX_BYTES} bytes）")
        if encoding == "gzip":
            try:
                raw = gzip.decompress(raw)
            except OSError as exc:
                raise SourceError("gzip 解压失败") from exc
        elif encoding == "deflate":
            try:
                raw = zlib.decompress(raw)
            except zlib.error:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
        return raw

    def _decode(self, raw: bytes) -> str:
        for encoding in ("utf-8", "gb18030", "big5", "latin-1"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")


class FetchResult(BaseModel):
    """单个源的采集结果，用于降级标记与看板展示。"""

    model_config = ConfigDict(extra="ignore")

    source_id: str
    source_name: str = ""
    topic: str | None = None
    status: SourceStatus = "ok"
    items: list[SourceItem] = Field(default_factory=list)
    error: str | None = None
    attempts: int = 1
    elapsed_ms: int = 0
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def item_count(self) -> int:
        return len(self.items)

    def summary(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "topic": self.topic,
            "status": self.status,
            "item_count": self.item_count,
            "attempts": self.attempts,
            "elapsed_ms": self.elapsed_ms,
            "error": self.error,
        }
