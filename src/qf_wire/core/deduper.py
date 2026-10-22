"""去重：URL 规范化 + 标题指纹，重复条目合并来源。"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from qf_wire.core.models import Confidence, SourceItem

_TRACKING_PREFIXES = ("utm_", "spm", "from", "ref", "source", "fbclid", "gclid", "mc_")
_PUNCT_RE = re.compile(r"[\s\-_·•|:：,，.。!！?？'\"“”‘’()（）\[\]【】<>《》/\\]+")
_WS_RE = re.compile(r"\s+")

_CONFIDENCE_RANK: dict[Confidence, int] = {"low": 0, "medium": 1, "high": 2}


def canonical_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/") or "/"
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith(_TRACKING_PREFIXES)
    ]
    query.sort()
    return urlunsplit((scheme, host, path, urlencode(query), ""))


def normalize_title(title: str) -> str:
    return _PUNCT_RE.sub("", (title or "").lower()).strip()


def title_fingerprint(title: str) -> str:
    normalized = normalize_title(title)
    if not normalized:
        normalized = _WS_RE.sub("", title or "")
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def stable_hash(*parts: str, length: int = 16) -> str:
    payload = "\x1f".join(parts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:length]


def _merge(primary: SourceItem, duplicate: SourceItem) -> SourceItem:
    sources = list(dict.fromkeys([*primary.sources, *duplicate.sources, primary.source_id, duplicate.source_id]))
    sources = [value for value in sources if value]

    published_candidates = [value for value in (primary.published_at, duplicate.published_at) if value]
    published = min(published_candidates) if published_candidates else None

    primary_rank = _CONFIDENCE_RANK[primary.confidence]
    duplicate_rank = _CONFIDENCE_RANK[duplicate.confidence]
    confidence: Confidence = primary.confidence if primary_rank >= duplicate_rank else duplicate.confidence

    return primary.model_copy(
        update={
            "summary": primary.summary if len(primary.summary) >= len(duplicate.summary) else duplicate.summary,
            "zh": primary.zh or duplicate.zh,
            "sources": sources,
            "published_at": published,
            "confidence": confidence,
        }
    )


def dedupe(items: list[SourceItem]) -> list[SourceItem]:
    """按规范化 URL 与标题指纹去重，保留信息量更大的一条。"""
    ordered: list[SourceItem] = []
    by_url: dict[str, int] = {}
    by_title: dict[str, int] = {}

    for item in items:
        item = item.model_copy(
            update={"sources": list(dict.fromkeys([*item.sources, item.source_id])) if item.source_id else item.sources}
        )
        url_key = canonical_url(item.url)
        title_key = title_fingerprint(item.title)
        index = by_url.get(url_key) if url_key else None
        if index is None:
            index = by_title.get(title_key)
        if index is None:
            index = len(ordered)
            ordered.append(item)
        else:
            ordered[index] = _merge(ordered[index], item)
        if url_key:
            by_url[url_key] = index
        by_title[title_key] = index

    return ordered
