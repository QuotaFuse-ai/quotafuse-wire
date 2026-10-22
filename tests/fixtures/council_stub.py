"""最小化的 Council 侧桩：只复刻 DataEnvelope 契约与 DataAccessLayer 注册方式。

真实 Council 的包不参与测试，Wire 与 Council 之间只按字典契约对齐。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable, Literal

import pytest
from pydantic import BaseModel, ConfigDict, field_validator


class EnvelopeScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = ""
    event_id: str | None = None


class CouncilDataEnvelope(BaseModel):
    """对齐 docs/PROVIDER_INTEGRATION.md 映射表的 DataEnvelope 最小复刻。"""

    model_config = ConfigDict(extra="forbid")

    domain: Literal["news", "policy", "industry"]
    scope: EnvelopeScope
    data_as_of: date
    payload: dict[str, Any]
    source: str = "wire"
    source_detail: str = ""
    fetched_at: datetime
    freshness: Literal["realtime", "cached", "archive"]
    confidence: Literal["high", "medium", "low"]
    source_status: Literal["ok", "degraded", "partial"]

    @field_validator("fetched_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("fetched_at 必须带时区")
        return value


class DataAccessLayer:
    """复刻 Council 的注册/取数流程：provider 只按鸭子类型使用。"""

    def __init__(self, mapper: Callable[[Any], dict[str, Any]]) -> None:
        self._mapper = mapper
        self._providers: dict[str, Any] = {}

    def register(self, provider: Any) -> None:
        self._providers[provider.name] = provider

    def get(
        self,
        name: str,
        *,
        domain: str,
        topic: str,
        date: date | None = None,
    ) -> CouncilDataEnvelope:
        provider = self._providers[name]
        if domain not in provider.domains:
            raise KeyError(f"{name} 不提供 domain={domain}")
        envelope = provider.get_digest(topic, date)
        if envelope.domain != domain:
            raise ValueError(f"{name} 返回的 domain 与请求不一致: {envelope.domain}")
        return CouncilDataEnvelope.model_validate(self._mapper(envelope))


@pytest.fixture
def council_data_access() -> DataAccessLayer:
    from qf_wire.provider.envelope import to_data_envelope

    return DataAccessLayer(mapper=to_data_envelope)
