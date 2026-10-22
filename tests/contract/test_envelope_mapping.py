"""WireEnvelope ↔ Council DataEnvelope 映射契约测试。"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from qf_wire.core.models import WireEnvelope
from qf_wire.provider.envelope import from_data_envelope, to_data_envelope
from qf_wire.provider.wire_provider import WireProvider
from tests.fixtures.configs import write_config
from tests.fixtures.council_stub import CouncilDataEnvelope, DataAccessLayer
from tests.fixtures.wire_data import EVENT_ID, seed_wire_data


def make_wire_envelope(**overrides: object) -> WireEnvelope:
    payload = {
        "domain": "news",
        "topic": "semi",
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
    return WireEnvelope(**payload)  # type: ignore[arg-type]


def _provider(tmp_path: Path) -> WireProvider:
    config_dir = write_config(tmp_path)
    data_dir = tmp_path / "data"
    seed_wire_data(data_dir)
    return WireProvider(config_dir=config_dir, data_dir=data_dir)


def test_mapping_matches_documented_table() -> None:
    envelope = make_wire_envelope(event_id="evt-1")
    data = to_data_envelope(envelope)
    assert set(data) == {
        "domain",
        "scope",
        "data_as_of",
        "payload",
        "source",
        "source_detail",
        "fetched_at",
        "freshness",
        "confidence",
        "source_status",
    }
    assert data["domain"] == "news"
    assert data["scope"] == {"topic": "semi", "event_id": "evt-1"}
    assert data["data_as_of"] == "2026-10-22"
    assert data["fetched_at"].startswith("2026-10-22T08:00:00")
    assert data["source"] == "wire"


def test_council_stub_accepts_digest_envelope(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    try:
        envelope = provider.get_digest("semiconductor")
    finally:
        provider.close()
    assert envelope.payload["items"]

    data = to_data_envelope(envelope)
    validated = CouncilDataEnvelope.model_validate(data)
    assert validated.domain == "news"
    assert validated.scope.topic == "semi"
    assert validated.scope.event_id is None
    assert validated.payload["items"]


def test_council_stub_accepts_timeline_envelope(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    try:
        envelope = provider.get_timeline(EVENT_ID)
    finally:
        provider.close()
    validated = CouncilDataEnvelope.model_validate(to_data_envelope(envelope))
    assert validated.scope.event_id == EVENT_ID
    assert validated.payload["timeline"]


def test_round_trip_preserves_all_fields() -> None:
    envelope = make_wire_envelope(event_id="evt-1")
    restored = from_data_envelope(to_data_envelope(envelope))
    assert restored == envelope


def test_from_data_envelope_accepts_council_object() -> None:
    envelope = make_wire_envelope()
    council = CouncilDataEnvelope.model_validate(to_data_envelope(envelope))
    assert from_data_envelope(council) == envelope


def test_from_data_envelope_requires_data_as_of() -> None:
    data = to_data_envelope(make_wire_envelope())
    data.pop("data_as_of")
    with pytest.raises(ValueError, match="data_as_of"):
        from_data_envelope(data)


def test_registered_provider_is_reachable_through_data_access(
    tmp_path: Path,
    council_data_access: DataAccessLayer,
) -> None:
    provider = _provider(tmp_path)
    try:
        council_data_access.register(provider)
        envelope = council_data_access.get("wire", domain="news", topic="semiconductor")
        assert envelope.source == "wire"
        assert envelope.scope.topic == "semi"
        assert envelope.payload["items"]
        assert "feed_a" in envelope.source_detail
    finally:
        provider.close()
