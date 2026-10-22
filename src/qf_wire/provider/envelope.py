"""WireEnvelope ↔ Council DataEnvelope 转换。

只依赖字典契约，不 import Council 的包，避免双向依赖。
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
from typing import Any

from qf_wire.core.models import WireEnvelope

_MISSING = object()


def to_data_envelope(envelope: WireEnvelope) -> dict[str, Any]:
    """把 WireEnvelope 转换为 Council 可直接校验的 DataEnvelope 字典。"""
    return {
        "domain": envelope.domain,
        "scope": {"topic": envelope.topic, "event_id": envelope.event_id},
        "data_as_of": envelope.data_as_of.isoformat(),
        "payload": envelope.payload,
        "source": envelope.source,
        "source_detail": envelope.source_detail,
        "fetched_at": envelope.fetched_at.isoformat(),
        "freshness": envelope.freshness,
        "confidence": envelope.confidence,
        "source_status": envelope.source_status,
    }


def from_data_envelope(data: Mapping[str, Any] | object) -> WireEnvelope:
    """把 Council DataEnvelope（字典或对象）还原为 WireEnvelope。"""
    scope = _get(data, "scope") or {}
    return WireEnvelope(
        domain=_get(data, "domain"),
        topic=_get(scope, "topic") or "",
        event_id=_get(scope, "event_id"),
        data_as_of=_as_date(_get(data, "data_as_of")),
        payload=_get(data, "payload") or {},
        source=_get(data, "source") or "wire",
        source_detail=_get(data, "source_detail") or "",
        fetched_at=_as_datetime(_get(data, "fetched_at")),
        freshness=_get(data, "freshness") or "realtime",
        confidence=_get(data, "confidence") or "medium",
        source_status=_get(data, "source_status") or "ok",
    )


def _get(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        return date.fromisoformat(value[:10])
    raise ValueError("DataEnvelope 缺少有效的 data_as_of")


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    raise ValueError("DataEnvelope 缺少有效的 fetched_at")
