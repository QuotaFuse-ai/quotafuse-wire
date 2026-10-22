"""WireEnvelope 契约测试：必填字段、枚举边界与序列化往返。"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from qf_wire.core.models import WireEnvelope

FIELD_NAMES = {
    "domain",
    "topic",
    "event_id",
    "data_as_of",
    "payload",
    "source",
    "source_detail",
    "fetched_at",
    "freshness",
    "confidence",
    "source_status",
}


def make_envelope(**overrides: object) -> WireEnvelope:
    payload = {
        "domain": "news",
        "topic": "semiconductor",
        "event_id": None,
        "data_as_of": date(2026, 10, 22),
        "payload": {"summary": "测试"},
        "source": "wire",
        "source_detail": "feed_a,feed_b",
        "fetched_at": datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc),
        "freshness": "archive",
        "confidence": "medium",
        "source_status": "ok",
    }
    payload.update(overrides)
    return WireEnvelope(**payload)


def test_contract_has_exactly_the_documented_fields() -> None:
    # 所有文档（README / REQUIREMENTS / MCP_TOOLS / PROVIDER_INTEGRATION）列出的
    # 具名字段均为这 11 个；规格正文里的“12 字段”为计数笔误。
    assert set(WireEnvelope.model_fields) == FIELD_NAMES


@pytest.mark.parametrize("missing", ["domain", "topic", "data_as_of", "fetched_at"])
def test_required_fields_are_enforced(missing: str) -> None:
    data = make_envelope().model_dump()
    data.pop(missing)
    with pytest.raises(ValidationError):
        WireEnvelope(**data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("domain", "sports"),
        ("domain", ""),
        ("freshness", "live"),
        ("confidence", "certain"),
        ("source_status", "unavailable"),
    ],
)
def test_enum_violations_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make_envelope(**{field: value})


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        make_envelope(unexpected="x")


def test_naive_fetched_at_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_envelope(fetched_at=datetime(2026, 10, 22, 8, 0))


def test_serialization_round_trip() -> None:
    envelope = make_envelope()
    restored = WireEnvelope.model_validate_json(envelope.model_dump_json())
    assert restored == envelope
    data = restored.model_dump(mode="json")
    assert data["data_as_of"] == "2026-10-22"
    assert data["fetched_at"].startswith("2026-10-22T08:00:00")
    assert data["source"] == "wire"


@pytest.mark.parametrize("status", ["ok", "degraded", "partial"])
def test_all_documented_source_status_values_are_accepted(status: str) -> None:
    assert make_envelope(source_status=status).source_status == status


def test_empty_topic_allows_cross_topic_aggregate() -> None:
    assert make_envelope(topic="").topic == ""
