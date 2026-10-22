"""通用 JSON API 适配器：兼容常见的 items/data/articles 返回结构。"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urljoin

from qf_wire.core.cleaner import parse_datetime
from qf_wire.core.models import SourceItem
from qf_wire.sources.base import SourceAdapter, SourceError

MAX_ITEMS = 80
_TITLE_KEYS = ("title", "headline", "name")
_URL_KEYS = ("url", "link", "href", "web_url", "webUrl")
_SUMMARY_KEYS = ("summary", "description", "abstract", "snippet", "content", "digest")
_TIME_KEYS = (
    "published_at",
    "publishedAt",
    "pubDate",
    "pubdate",
    "published",
    "date",
    "created_at",
    "createdAt",
    "time",
    "timestamp",
)
_ZH_KEYS = ("zh", "title_zh", "titleZh", "chinese_title")


def _pick(entry: dict[str, Any], keys: tuple[str, ...]) -> Any:
    lowered = {str(key).lower(): value for key, value in entry.items()}
    for key in keys:
        value = entry.get(key)
        if value in (None, ""):
            value = lowered.get(key.lower())
        if value not in (None, ""):
            return value
    return None


def _find_entries(payload: Any, depth: int = 0) -> list[dict[str, Any]]:
    if depth > 3:
        return []
    if isinstance(payload, list):
        return [entry for entry in payload if isinstance(entry, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "data", "articles", "results", "entries", "list", "news"):
        if key in payload:
            found = _find_entries(payload[key], depth + 1)
            if found:
                return found
    for value in payload.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value
    return []


class APIAdapter(SourceAdapter):
    source_type = "api"

    def fetch(self, timeout_sec: float | None = None) -> list[SourceItem]:
        raw = self._get(timeout_sec=timeout_sec, accept="application/json, */*")
        text = self._decode(raw).strip()
        if not text:
            raise SourceError("空响应")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SourceError(f"JSON 解析失败: {exc}") from exc

        entries = _find_entries(payload)
        if not entries:
            raise SourceError("响应中未找到条目数组")

        items: list[SourceItem] = []
        for entry in entries:
            title = _pick(entry, _TITLE_KEYS)
            url = _pick(entry, _URL_KEYS)
            if not title or not url:
                continue
            items.append(
                SourceItem(
                    title=str(title),
                    url=urljoin(self.source.url, str(url)),
                    source_id=self.source.id,
                    topic=self.source.topic or "",
                    summary=str(_pick(entry, _SUMMARY_KEYS) or ""),
                    zh=str(_pick(entry, _ZH_KEYS) or ""),
                    published_at=parse_datetime(_pick(entry, _TIME_KEYS)),
                    sources=[self.source.id],
                )
            )
            if len(items) >= MAX_ITEMS:
                break

        if not items:
            raise SourceError("条目缺少 title/url 字段")
        return items
