"""清洗：去 HTML、统一北京时间、合规红线过滤、过期条目过滤。"""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone

from qf_wire.core.models import SourceItem

BEIJING_TZ = timezone(timedelta(hours=8))

_SCRIPT_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")

# 合规红线：只过滤明确的交易建议表述，不做立场判断。
TRADING_ADVICE_TERMS = (
    "买入评级",
    "卖出评级",
    "增持评级",
    "减持评级",
    "建议买入",
    "建议卖出",
    "目标价",
    "抄底",
    "梭哈",
    "满仓",
    "荐股",
    "买入信号",
    "卖出信号",
)


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    text = _SCRIPT_RE.sub(" ", value)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _ZERO_WIDTH_RE.sub("", text)
    return _WS_RE.sub(" ", text).strip()


def clean_text(value: str | None, max_length: int | None = None) -> str:
    text = strip_html(value)
    if max_length and len(text) > max_length:
        text = text[: max_length - 1].rstrip() + "…"
    return text


def parse_datetime(value: object) -> datetime | None:
    """尽最大努力解析信源时间，返回北京时间（aware）。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _to_beijing(value)
    if isinstance(value, (int, float)):
        return _from_timestamp(float(value))
    if not isinstance(value, str):
        return None

    raw = value.strip()
    if not raw:
        return None

    if raw.isdigit():
        return _from_timestamp(float(raw))

    iso = raw.replace("Z", "+00:00")
    try:
        return _to_beijing(datetime.fromisoformat(iso))
    except ValueError:
        pass

    try:
        from email.utils import parsedate_to_datetime

        return _to_beijing(parsedate_to_datetime(raw))
    except (TypeError, ValueError, IndexError):
        pass

    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
        "%Y年%m月%d日 %H:%M",
        "%Y年%m月%d日",
        "%d %b %Y %H:%M:%S",
        "%a, %d %b %Y %H:%M:%S",
    )
    for fmt in formats:
        try:
            return _to_beijing(datetime.strptime(raw, fmt))
        except ValueError:
            continue
    return None


def _from_timestamp(value: float) -> datetime:
    if value > 1e12:
        value /= 1000.0
    return datetime.fromtimestamp(value, tz=timezone.utc).astimezone(BEIJING_TZ)


def _to_beijing(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BEIJING_TZ)


def to_beijing(value: datetime) -> datetime:
    return _to_beijing(value)


def format_display_time(value: datetime | None) -> str:
    if value is None:
        return ""
    return _to_beijing(value).strftime("%Y-%m-%d %H:%M")


def to_timestamp_ms(value: datetime | None) -> int:
    if value is None:
        return 0
    return int(_to_beijing(value).timestamp() * 1000)


def contains_trading_advice(text: str) -> bool:
    return any(term in text for term in TRADING_ADVICE_TERMS)


def clean_item(item: SourceItem) -> SourceItem | None:
    """清洗单条；不合规或无法使用时返回 None。"""
    title = clean_text(item.title, max_length=300)
    if len(title) < 4:
        return None

    url = (item.url or "").strip()
    if not url.startswith(("http://", "https://")):
        return None

    summary = clean_text(item.summary, max_length=800)
    zh = clean_text(item.zh or title, max_length=300)
    combined = f"{title} {summary} {zh}"
    if contains_trading_advice(combined):
        return None

    return item.model_copy(
        update={
            "title": title,
            "url": url,
            "summary": summary,
            "zh": zh,
            "published_at": parse_datetime(item.published_at),
        }
    )


def clean_items(
    items: list[SourceItem],
    now: datetime | None = None,
    max_age_days: int = 30,
) -> list[SourceItem]:
    now = _to_beijing(now or datetime.now(timezone.utc))
    oldest = now - timedelta(days=max_age_days)
    newest = now + timedelta(days=2)
    cleaned: list[SourceItem] = []
    for item in items:
        value = clean_item(item)
        if value is None:
            continue
        published = value.published_at
        if published is not None:
            published = _to_beijing(published)
            if published < oldest or published > newest:
                continue
            value = value.model_copy(update={"published_at": published})
        cleaned.append(value)
    return cleaned
