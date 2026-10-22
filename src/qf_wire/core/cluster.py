"""事件聚类：标题字符 n-gram + SimHash 相似度，规则化实体提取。

同一赛道内跨源报道折叠为同一 event_id；聚类只依赖本地规则，不调用模型。
实体提取使用关键词/别名表 + 正则，覆盖常见公司中英文名、引号标题与型号代码。
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable

from qf_wire.core.deduper import (
    canonical_url,
    normalize_title,
    stable_hash,
    title_fingerprint,
)
from qf_wire.core.models import Event, SourceItem

NGRAM_SIZE = 2
SIMILARITY_THRESHOLD = 0.56
SIMHASH_SIMILARITY_THRESHOLD = 0.86
SIMHASH_FLOOR = 0.30
ENTITY_BOOST = 0.08
EVENT_WINDOW_HOURS = 24 * 7

_LATIN_ENTITY_ALIASES = {
    "nvidia": "nvidia",
    "apple": "apple",
    "tsmc": "tsmc",
    "samsung": "samsung",
    "huawei": "huawei",
    "intel": "intel",
    "amd": "amd",
    "microsoft": "microsoft",
    "google": "google",
    "alphabet": "google",
    "deepmind": "google",
    "openai": "openai",
    "anthropic": "anthropic",
    "meta": "meta",
    "facebook": "meta",
    "tesla": "tesla",
    "byd": "byd",
    "catl": "catl",
    "smic": "smic",
    "qualcomm": "qualcomm",
    "arm": "arm",
    "asml": "asml",
    "micron": "micron",
    "amazon": "amazon",
    "alibaba": "alibaba",
    "tencent": "tencent",
    "baidu": "baidu",
    "xiaomi": "xiaomi",
    "bytedance": "bytedance",
    "spacex": "spacex",
    "starlink": "starlink",
    "boeing": "boeing",
    "airbus": "airbus",
    "deepseek": "deepseek",
    "intuitive": "intuitive",
    "boston": "boston_dynamics",
}

_CJK_ENTITY_ALIASES = {
    "英伟达": "nvidia",
    "苹果": "apple",
    "台积电": "tsmc",
    "三星": "samsung",
    "华为": "huawei",
    "英特尔": "intel",
    "超威": "amd",
    "微软": "microsoft",
    "谷歌": "google",
    "脸书": "meta",
    "特斯拉": "tesla",
    "比亚迪": "byd",
    "宁德时代": "catl",
    "中芯国际": "smic",
    "高通": "qualcomm",
    "美光": "micron",
    "亚马逊": "amazon",
    "阿里巴巴": "alibaba",
    "腾讯": "tencent",
    "百度": "baidu",
    "小米": "xiaomi",
    "字节跳动": "bytedance",
    "波音": "boeing",
    "空客": "airbus",
    "深度求索": "deepseek",
}

_LATIN_KEYWORD_RE = re.compile(
    r"(?<![a-z0-9])(?:" + "|".join(sorted(map(re.escape, _LATIN_ENTITY_ALIASES), key=len, reverse=True)) + r")(?![a-z0-9])"
)
_CODE_RE = re.compile(r"\b[A-Z]{1,6}[- ]?\d{1,5}[A-Za-z]*\b")
_QUOTED_RE = re.compile(r"《([^》]{2,40})》|“([^”]{2,40})”|\"([^\"]{2,40})\"")


@dataclass(slots=True, frozen=True)
class EntitySet:
    """规则化实体：orgs 参与冲突判定，codes 仅用于展示与相似度辅助。"""

    orgs: frozenset[str] = frozenset()
    codes: frozenset[str] = frozenset()

    def __or__(self, other: "EntitySet") -> "EntitySet":
        return EntitySet(self.orgs | other.orgs, self.codes | other.codes)


def extract_entities(title: str) -> EntitySet:
    """从标题中提取组织与型号类实体，不依赖 NER 模型。"""
    if not title:
        return EntitySet()
    lower = title.lower()
    orgs = {_LATIN_ENTITY_ALIASES[match] for match in _LATIN_KEYWORD_RE.findall(lower)}

    normalized = normalize_title(title)
    for alias, canonical in _CJK_ENTITY_ALIASES.items():
        if alias in normalized:
            orgs.add(canonical)

    for parts in _QUOTED_RE.findall(title):
        quoted = next((part for part in parts if part), "")
        quoted = normalize_title(quoted)
        if len(quoted) >= 2:
            orgs.add(f"q:{quoted}")

    codes = {match.lower().replace(" ", "") for match in _CODE_RE.findall(title)}
    return EntitySet(frozenset(orgs), frozenset(codes))


def _bigrams(title: str) -> Counter[str]:
    text = normalize_title(title)
    if len(text) < NGRAM_SIZE:
        return Counter({text: 1}) if text else Counter()
    return Counter(text[index : index + NGRAM_SIZE] for index in range(len(text) - NGRAM_SIZE + 1))


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    common = set(left) & set(right)
    if not common:
        return 0.0
    dot = sum(left[gram] * right[gram] for gram in common)
    norm_left = math.sqrt(sum(value * value for value in left.values()))
    norm_right = math.sqrt(sum(value * value for value in right.values()))
    if not norm_left or not norm_right:
        return 0.0
    return dot / (norm_left * norm_right)


def simhash(title: str, bits: int = 64) -> int:
    grams = _bigrams(title)
    if not grams:
        return 0
    vector = [0] * bits
    for gram, weight in grams.items():
        digest = int.from_bytes(
            hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest(), "big"
        )
        for bit in range(bits):
            vector[bit] += weight if (digest >> bit) & 1 else -weight
    result = 0
    for bit in range(bits):
        if vector[bit] > 0:
            result |= 1 << bit
    return result


def simhash_similarity(left: int, right: int, bits: int = 64) -> float:
    return 1.0 - (bin(left ^ right).count("1") / bits)


@dataclass(slots=True)
class _Member:
    item: SourceItem
    url_key: str
    fingerprint: str
    grams: Counter[str]
    simhash: int
    entities: EntitySet


@dataclass(slots=True)
class _Cluster:
    topic: str
    members: list[_Member] = field(default_factory=list)

    @property
    def urls(self) -> set[str]:
        return {member.url_key for member in self.members if member.url_key}

    @property
    def fingerprints(self) -> set[str]:
        return {member.fingerprint for member in self.members if member.fingerprint}

    @property
    def orgs(self) -> frozenset[str]:
        result: set[str] = set()
        for member in self.members:
            result.update(member.entities.orgs)
        return frozenset(result)

    @property
    def first_time(self) -> datetime | None:
        times = [member.item.published_at for member in self.members if member.item.published_at]
        return min(times) if times else None

    @property
    def last_time(self) -> datetime | None:
        times = [member.item.published_at for member in self.members if member.item.published_at]
        return max(times) if times else None


def _to_member(item: SourceItem) -> _Member:
    return _Member(
        item=item,
        url_key=canonical_url(item.url),
        fingerprint=title_fingerprint(item.title),
        grams=_bigrams(item.title),
        simhash=simhash(item.title),
        entities=extract_entities(item.title),
    )


def _within_window(cluster: _Cluster, item: SourceItem, window_hours: int) -> bool:
    if item.published_at is None:
        return True
    window = timedelta(hours=window_hours)
    for member in cluster.members:
        other = member.item.published_at
        if other is not None and abs(item.published_at - other) > window:
            continue
        return True
    return False


def _same_event(cluster: _Cluster, candidate: _Member, threshold: float) -> bool:
    cluster_orgs = cluster.orgs
    if candidate.entities.orgs and cluster_orgs and not (candidate.entities.orgs & cluster_orgs):
        return False
    boost = ENTITY_BOOST if candidate.entities.orgs & cluster_orgs else 0.0
    for member in cluster.members:
        score = _cosine(candidate.grams, member.grams)
        if score + boost >= threshold:
            return True
        similarity = simhash_similarity(candidate.simhash, member.simhash)
        if score >= SIMHASH_FLOOR and similarity >= SIMHASH_SIMILARITY_THRESHOLD:
            return True
    return False


def cluster_items(
    items: Iterable[SourceItem],
    *,
    threshold: float = SIMILARITY_THRESHOLD,
    window_hours: int = EVENT_WINDOW_HOURS,
) -> list[list[SourceItem]]:
    """把同一赛道的条目聚类，返回按首次出现时间升序的事件分组。"""
    ordered = sorted(
        items,
        key=lambda item: (
            item.published_at is None,
            item.published_at.timestamp() if item.published_at else 0.0,
        ),
    )
    clusters: list[_Cluster] = []
    for item in ordered:
        candidate = _to_member(item)
        target: _Cluster | None = None
        for cluster in clusters:
            if cluster.topic != item.topic:
                continue
            if candidate.url_key and candidate.url_key in cluster.urls:
                target = cluster
                break
            if candidate.fingerprint and candidate.fingerprint in cluster.fingerprints:
                target = cluster
                break
            if not _within_window(cluster, item, window_hours):
                continue
            if _same_event(cluster, candidate, threshold):
                target = cluster
                break
        if target is None:
            target = _Cluster(topic=item.topic)
            clusters.append(target)
        target.members.append(candidate)

    clusters.sort(key=lambda cluster: _time_key(cluster.first_time))
    return [[member.item for member in cluster.members] for cluster in clusters]


def _time_key(value: datetime | None) -> float:
    return value.timestamp() if value else float("inf")


def build_events(
    items: Iterable[SourceItem],
    *,
    threshold: float = SIMILARITY_THRESHOLD,
    window_hours: int = EVENT_WINDOW_HOURS,
) -> list[Event]:
    """按赛道聚类并生成事件，回填每个条目的 event_id。"""
    by_topic: dict[str, list[SourceItem]] = {}
    for item in items:
        by_topic.setdefault(item.topic, []).append(item)

    events: list[Event] = []
    for topic, group in by_topic.items():
        for members in cluster_items(group, threshold=threshold, window_hours=window_hours):
            events.append(_make_event(topic, members))
    events.sort(key=lambda event: _time_key(event.last_seen), reverse=True)
    return events


def _make_event(topic: str, members: list[SourceItem]) -> Event:
    ordered = ordered_reports(members)
    anchor = ordered[0]
    event_id = stable_hash(
        "event", topic, title_fingerprint(anchor.title) or canonical_url(anchor.url)
    )

    sources: list[str] = []
    for item in ordered:
        for source in item.sources or [item.source_id]:
            if source and source not in sources:
                sources.append(source)

    times = [item.published_at for item in ordered if item.published_at is not None]
    confidence = "high" if len(sources) >= 2 else (anchor.confidence or "medium")
    for item in ordered:
        item.event_id = event_id
        if len(sources) >= 2:
            item.confidence = "high"

    return Event(
        event_id=event_id,
        topic=topic,
        title=anchor.title,
        items=ordered,
        sources=sources,
        source_count=len(sources),
        confidence=confidence,
        first_seen=min(times) if times else None,
        last_seen=max(times) if times else None,
    )


def ordered_reports(items: Iterable[SourceItem]) -> list[SourceItem]:
    """按发布时间升序返回报道列表（无时间的置后）。"""
    return sorted(
        items,
        key=lambda item: (
            item.published_at is None,
            item.published_at.timestamp() if item.published_at else 0.0,
        ),
    )


def timeline(event: Event) -> list[dict[str, object]]:
    """事件时间线：每条报道的时间、来源与标题，按时间升序。"""
    return [
        {
            "published_at": item.published_at,
            "source": item.source_id or ",".join(item.sources),
            "title": item.title,
            "url": item.url,
        }
        for item in ordered_reports(event.items)
    ]


__all__ = [
    "EntitySet",
    "build_events",
    "cluster_items",
    "extract_entities",
    "ordered_reports",
    "simhash",
    "simhash_similarity",
    "timeline",
]
