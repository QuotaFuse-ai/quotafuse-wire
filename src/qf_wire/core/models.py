"""数据契约：配置模型、条目、事件、提炼结果与 WireEnvelope。

所有跨模块传递的数据都使用这里的 Pydantic v2 模型，避免字典漂移。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SourceType = Literal["rss", "html", "api"]
SourceStatus = Literal["ok", "degraded", "unavailable"]
EnvelopeDomain = Literal["news", "policy", "industry"]
EnvelopeSourceStatus = Literal["ok", "degraded", "partial"]
Freshness = Literal["realtime", "cached", "archive"]
Confidence = Literal["high", "medium", "low"]
DigestStatus = Literal["ok", "partial", "skipped", "failed"]


class Source(BaseModel):
    """信源配置（sources.yaml 中的一项）。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]*$")
    name: str = Field(min_length=1)
    topic: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_]*$")
    type: SourceType = "rss"
    url: str
    timeout_sec: int = Field(default=15, ge=1, le=120)
    retries: int = Field(default=2, ge=0, le=5)
    weight: float = Field(default=1.0, ge=0, le=10)
    enabled: bool = True

    @field_validator("url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("url 必须是 http(s) 地址")
        return value


class Topic(BaseModel):
    """赛道配置（topics.yaml 中的一项）。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]*$")
    name: str = Field(min_length=1)
    accent: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    legacy_key: str | None = Field(default=None, min_length=1)
    aliases: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(min_length=1)
    sources: list[str] = Field(min_length=1)

    def all_names(self) -> set[str]:
        names = {self.id}
        if self.legacy_key:
            names.add(self.legacy_key)
        names.update(self.aliases)
        return names


class SourceItem(BaseModel):
    """单个信源返回的一条资讯。"""

    model_config = ConfigDict(extra="ignore")

    title: str
    url: str
    source_id: str = ""
    topic: str = ""
    summary: str = ""
    zh: str = ""
    published_at: datetime | None = None
    sources: list[str] = Field(default_factory=list)
    event_id: str | None = None
    confidence: Confidence = "medium"

    def source_key(self) -> str:
        return self.source_id or ",".join(self.sources)


class KeyPoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    sources: list[str] = Field(default_factory=list)
    confidence: Confidence = "medium"
    event_id: str | None = None


class DigestItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    url: str = ""
    source: str = ""
    published_at: datetime | None = None
    zh: str = ""
    summary: str = ""
    event_id: str | None = None


class TopicDigest(BaseModel):
    """某一赛道某一天的提炼结果。"""

    model_config = ConfigDict(extra="ignore")

    topic: str
    date: date
    summary: str = ""
    key_points: list[KeyPoint] = Field(default_factory=list)
    items: list[DigestItem] = Field(default_factory=list)
    generated_at: datetime | None = None
    provider: str | None = None
    model: str | None = None
    partial: bool = False
    status: DigestStatus = "ok"
    error: str | None = None
    fallback: bool = False


MergeReason = Literal["shared_entity", "title_similarity", "simhash", "duplicate", "single"]


class EventExplanation(BaseModel):
    """事件归并依据：说明多条报道为什么被折叠到同一事件。"""

    model_config = ConfigDict(extra="ignore")

    reason: MergeReason = "single"
    shared_entities: list[str] = Field(default_factory=list)
    title_similarity: float = 0.0
    simhash_similarity: float = 0.0
    threshold: float = 0.0
    window_hours: int = 0

    def summary(self) -> str:
        if self.reason == "single":
            return "单篇报道"
        if self.reason == "duplicate":
            return "同链接或同标题转载"
        parts: list[str] = []
        if self.shared_entities:
            parts.append("共同实体：" + "、".join(self.shared_entities))
        if self.title_similarity:
            parts.append(f"标题相似度 {self.title_similarity:.2f}")
        if self.reason == "simhash":
            parts.append(f"SimHash 相似度 {self.simhash_similarity:.2f}")
        return "；".join(parts) or "多篇报道归并"


class Event(BaseModel):
    """同一事件的多源报道聚合。M1 仅做轻量分组，M2 增强。"""

    model_config = ConfigDict(extra="ignore")

    event_id: str
    topic: str
    title: str
    items: list[SourceItem] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    source_count: int = 0
    confidence: Confidence = "medium"
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    explanation: EventExplanation | None = None


class WireEnvelope(BaseModel):
    """与 Council DataEnvelope 对齐的信封。

    字段与 `docs/PROVIDER_INTEGRATION.md` 的映射表一一对应；枚举越界直接拒绝。
    `topic` 允许空串，表示跨赛道聚合结果（如全量信源列表）。
    """

    model_config = ConfigDict(extra="forbid")

    domain: EnvelopeDomain
    topic: str
    event_id: str | None = None
    data_as_of: date
    payload: dict[str, Any] = Field(default_factory=dict)
    source: str = "wire"
    source_detail: str = ""
    fetched_at: datetime
    freshness: Freshness = "realtime"
    confidence: Confidence = "medium"
    source_status: EnvelopeSourceStatus = "ok"

    @field_validator("fetched_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("fetched_at 必须带时区")
        return value
