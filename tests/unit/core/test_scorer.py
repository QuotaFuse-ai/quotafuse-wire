"""信源质量评分：分项权重、单调性、增量累计与低分源要点降级。"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from qf_wire.core.models import Event, KeyPoint, Source, SourceItem, TopicDigest
from qf_wire.core.scorer import (
    LOW_SCORE_THRESHOLD,
    SourceScore,
    apply_to_digest,
    score_map,
    update_scores,
)

BASE = datetime(2026, 10, 21, 8, 0, tzinfo=timezone.utc)


def _source(source_id: str) -> Source:
    return Source(
        id=source_id,
        name=source_id,
        topic="semi",
        type="rss",
        url=f"https://example.com/{source_id}.xml",
    )


def _item(source_id: str, title: str, *, hours: float, sources: list[str] | None = None) -> SourceItem:
    return SourceItem(
        title=title,
        url=f"https://example.com/{source_id}/{title.replace(' ', '-')}",
        source_id=source_id,
        topic="semi",
        published_at=BASE + timedelta(hours=hours),
        sources=sources or [source_id],
    )


def _event(event_id: str, items: list[SourceItem], sources: list[str], *, first_hour: float) -> Event:
    return Event(
        event_id=event_id,
        topic="semi",
        title=items[0].title,
        items=items,
        sources=sources,
        source_count=len(sources),
        first_seen=BASE + timedelta(hours=first_hour),
        last_seen=max(item.published_at for item in items if item.published_at),
    )


def test_recompute_applies_configured_weights() -> None:
    score = SourceScore(
        source_id="feed_a",
        items=10,
        corroborated=8,
        exclusive=2,
        timeliness_sum=9.0,
        timeliness_samples=10,
    ).recompute()

    assert score.accuracy == 0.8
    assert score.timeliness == 0.9
    assert score.uniqueness == 0.2
    assert score.score == 0.71


def test_no_samples_returns_neutral_score() -> None:
    score = SourceScore(source_id="feed_empty").recompute()

    assert (score.accuracy, score.timeliness, score.uniqueness, score.score) == (0.5, 0.5, 0.5, 0.5)


def test_more_corroboration_and_fresher_reports_score_higher() -> None:
    low = SourceScore(
        source_id="feed_low",
        items=10,
        corroborated=2,
        exclusive=0,
        timeliness_sum=3.0,
        timeliness_samples=10,
    ).recompute()
    high = SourceScore(
        source_id="feed_high",
        items=10,
        corroborated=8,
        exclusive=0,
        timeliness_sum=9.0,
        timeliness_samples=10,
    ).recompute()

    assert high.accuracy > low.accuracy
    assert high.timeliness > low.timeliness
    assert high.score > low.score


def test_more_exclusive_reports_raise_uniqueness() -> None:
    shared = SourceScore(
        source_id="feed_shared",
        items=10,
        corroborated=8,
        exclusive=2,
        timeliness_sum=5.0,
        timeliness_samples=10,
    ).recompute()
    exclusive = SourceScore(
        source_id="feed_exclusive",
        items=10,
        corroborated=2,
        exclusive=8,
        timeliness_sum=5.0,
        timeliness_samples=10,
    ).recompute()

    assert exclusive.uniqueness > shared.uniqueness


def test_update_scores_accumulates_across_runs() -> None:
    sources = [_source("feed_a"), _source("feed_b"), _source("feed_c")]
    multi = _event(
        "evt_multi",
        [
            _item("feed_a", "Chip maker reports record quarter", hours=0),
            _item("feed_b", "Chip maker reports record quarter", hours=4),
        ],
        ["feed_a", "feed_b"],
        first_hour=0,
    )
    solo = _event(
        "evt_solo",
        [_item("feed_a", "New fab breaks ground", hours=6)],
        ["feed_a"],
        first_hour=6,
    )

    first = update_scores(sources, {"semi": [multi, solo]})
    assert first["feed_a"].runs == 1
    assert first["feed_a"].items == 2
    assert first["feed_a"].corroborated == 1
    assert first["feed_a"].exclusive == 1
    assert first["feed_b"].items == 1
    assert first["feed_b"].corroborated == 1
    assert first["feed_b"].exclusive == 0
    assert first["feed_b"].timeliness == round(1 - 4 / 24, 4)
    assert "feed_c" not in first

    second = update_scores(sources, {"semi": [multi, solo]}, previous=first)
    assert second["feed_a"].runs == 2
    assert second["feed_a"].items == 4
    assert second["feed_a"].corroborated == 2
    assert second["feed_b"].items == 2


def test_low_score_sources_downgrade_key_points_only() -> None:
    digest = TopicDigest(
        topic="semi",
        date=date(2026, 10, 21),
        key_points=[
            KeyPoint(text="低分源独家", sources=["feed_low"], confidence="high"),
            KeyPoint(text="低分源中置信", sources=["feed_low"], confidence="medium"),
            KeyPoint(text="高分源背书", sources=["feed_high"], confidence="high"),
            KeyPoint(text="低分和高分混合", sources=["feed_low", "feed_high"], confidence="high"),
            KeyPoint(text="未知信源", sources=["feed_unknown"], confidence="high"),
        ],
    )
    downgraded = apply_to_digest(
        digest,
        {"feed_low": LOW_SCORE_THRESHOLD - 0.1, "feed_high": 0.9},
    )

    assert downgraded == 2
    assert [point.confidence for point in digest.key_points] == [
        "medium",
        "low",
        "high",
        "high",
        "high",
    ]


def test_score_map_flattens_scores() -> None:
    scores = {
        "feed_a": SourceScore(source_id="feed_a").recompute(),
        "feed_b": SourceScore(
            source_id="feed_b",
            items=2,
            corroborated=2,
            timeliness_sum=2.0,
            timeliness_samples=2,
        ).recompute(),
    }
    assert score_map(scores) == {"feed_a": 0.5, "feed_b": 0.8}
