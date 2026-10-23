"""看板投影：今日要点的状态与模型名回落。"""
from __future__ import annotations

from datetime import date, datetime, timezone

from qf_wire.config.loader import DigestSettings
from qf_wire.core.models import Event, EventExplanation, SourceItem, Topic, TopicDigest
from qf_wire.pipeline.digest import _resolve_model
from qf_wire.pipeline.render import build_dashboard_payload

TOPIC = Topic(id="ai", name="AI", keywords=["大模型"], sources=["feed_a"])


def _state(digest: TopicDigest | None) -> str:
    payload = build_dashboard_payload([TOPIC], {"ai": []}, {"ai": digest} if digest else {})
    return payload["industries"][0]["digest_state"]


def test_digest_state_missing_without_digest() -> None:
    assert _state(None) == "missing"


def test_digest_state_partial_for_fallback() -> None:
    digest = TopicDigest(
        topic="ai",
        date=date(2026, 10, 23),
        summary="共采集 3 条资讯；模型当前不可用，未生成要点。",
        partial=True,
        fallback=True,
        error="模型接口不可达",
    )
    payload = build_dashboard_payload([TOPIC], {"ai": []}, {"ai": digest})
    industry = payload["industries"][0]

    assert industry["digest_state"] == "partial"
    assert "模型接口不可达" in industry["digest_error"]


def test_digest_state_ok_and_missing_for_empty_success() -> None:
    ok = TopicDigest(topic="ai", date=date(2026, 10, 23), summary="有内容")
    assert _state(ok) == "ok"
    assert _state(TopicDigest(topic="ai", date=date(2026, 10, 23))) == "missing"


def test_digest_generated_at_is_projected() -> None:
    moment = datetime(2026, 10, 23, 2, 14, 49, tzinfo=timezone.utc)
    digest = TopicDigest(topic="ai", date=date(2026, 10, 23), summary="有内容", generated_at=moment)
    payload = build_dashboard_payload([TOPIC], {"ai": []}, {"ai": digest})

    industry = payload["industries"][0]
    assert industry["digest_generated_at"] == moment.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    assert _state(None) == "missing"


def test_resolve_model_falls_back_to_default() -> None:
    settings = DigestSettings(default_model="deepseek-chat")

    assert _resolve_model(settings, {"model": "user-model"}) == "deepseek-chat"
    assert _resolve_model(settings, {"model": "semi-model"}) == "semi-model"
    assert _resolve_model(DigestSettings(default_model="user-model"), {}) is None


def test_event_explanations_are_projected_for_the_dashboard() -> None:
    item = SourceItem(
        title="TSMC expands 2nm capacity",
        url="https://example.com/1",
        source_id="feed_a",
        topic="ai",
        event_id="evt-1",
        sources=["feed_a"],
    )
    event = Event(
        event_id="evt-1",
        topic="ai",
        title=item.title,
        items=[item],
        sources=["feed_a", "feed_b"],
        source_count=2,
        confidence="high",
        explanation=EventExplanation(
            reason="shared_entity",
            shared_entities=["tsmc"],
            title_similarity=0.7,
        ),
    )
    payload = build_dashboard_payload(
        [TOPIC], {"ai": [item]}, events_by_topic={"ai": [event]}
    )

    industry = payload["industries"][0]
    explanation = industry["event_explanations"]["evt-1"]
    assert explanation["reason"] == "shared_entity"
    assert "共同实体：tsmc" in explanation["summary"]
    assert industry["items"][0]["source_count"] == 2
