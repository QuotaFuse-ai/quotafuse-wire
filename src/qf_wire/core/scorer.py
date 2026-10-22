"""信源质量评分：准确率代理、时效性、重复率，输出 0–1 综合分。

每次运行增量累积统计（计数与时间差之和），不保存条目明文，只保留聚合值。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from qf_wire.core.models import Event, Source

TIMELINESS_WINDOW_HOURS = 24.0
ACCURACY_WEIGHT = 0.5
TIMELINESS_WEIGHT = 0.3
UNIQUENESS_WEIGHT = 0.2
NEUTRAL_SCORE = 0.5
LOW_SCORE_THRESHOLD = 0.45


@dataclass(slots=True)
class SourceScore:
    """单个信源的累计统计与分项得分。"""

    source_id: str
    runs: int = 0
    items: int = 0
    corroborated: int = 0
    exclusive: int = 0
    timeliness_sum: float = 0.0
    timeliness_samples: int = 0
    accuracy: float = NEUTRAL_SCORE
    timeliness: float = NEUTRAL_SCORE
    uniqueness: float = NEUTRAL_SCORE
    score: float = NEUTRAL_SCORE
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def recompute(self) -> "SourceScore":
        self.accuracy = _ratio(self.corroborated, self.items)
        self.timeliness = _ratio(self.timeliness_sum, self.timeliness_samples, digits=4)
        self.uniqueness = _ratio(self.exclusive, self.items)
        self.score = round(
            ACCURACY_WEIGHT * self.accuracy
            + TIMELINESS_WEIGHT * self.timeliness
            + UNIQUENESS_WEIGHT * self.uniqueness,
            4,
        )
        return self

    def summary(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "score": self.score,
            "accuracy": self.accuracy,
            "timeliness": self.timeliness,
            "uniqueness": self.uniqueness,
            "items": self.items,
            "corroborated": self.corroborated,
            "exclusive": self.exclusive,
            "runs": self.runs,
            "updated_at": _iso(self.updated_at),
        }


def _ratio(numerator: float, denominator: int, *, digits: int = 4) -> float:
    if denominator <= 0:
        return NEUTRAL_SCORE
    return round(max(0.0, min(numerator / denominator, 1.0)), digits)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@dataclass(slots=True)
class _Counters:
    items: int = 0
    corroborated: int = 0
    exclusive: int = 0
    timeliness_sum: float = 0.0
    timeliness_samples: int = 0


def collect_counters(events: Iterable[Event]) -> dict[str, _Counters]:
    """统计每个信源在本批次事件中的被采纳、独家与时效表现。"""
    counters: dict[str, _Counters] = {}
    for event in events:
        multi_source = event.source_count >= 2
        for item in event.items:
            contributors = list(dict.fromkeys(item.sources or [item.source_id]))
            contributors = [source for source in contributors if source]
            timeliness: float | None = None
            if multi_source and event.first_seen is not None and item.published_at is not None:
                delay_hours = (item.published_at - event.first_seen).total_seconds() / 3600
                timeliness = max(0.0, min(1.0, 1.0 - delay_hours / TIMELINESS_WINDOW_HOURS))
            for source_id in contributors:
                counter = counters.setdefault(source_id, _Counters())
                counter.items += 1
                if multi_source or len(contributors) >= 2:
                    counter.corroborated += 1
                else:
                    counter.exclusive += 1
                if timeliness is not None:
                    counter.timeliness_sum += timeliness
                    counter.timeliness_samples += 1
    return counters


def update_scores(
    sources: Iterable[Source],
    events_by_topic: dict[str, list[Event]],
    previous: dict[str, SourceScore] | None = None,
) -> dict[str, SourceScore]:
    """把本批次统计累加到历史分数上，返回更新后的全部信源分数。"""
    previous = previous or {}
    events = [event for group in events_by_topic.values() for event in group]
    counters = collect_counters(events)
    now = datetime.now(timezone.utc)

    updated: dict[str, SourceScore] = {}
    for source in sources:
        counter = counters.get(source.id)
        if counter is None:
            continue
        prior = previous.get(source.id)
        base = SourceScore(
            source_id=source.id,
            runs=prior.runs if prior else 0,
            items=prior.items if prior else 0,
            corroborated=prior.corroborated if prior else 0,
            exclusive=prior.exclusive if prior else 0,
            timeliness_sum=prior.timeliness_sum if prior else 0.0,
            timeliness_samples=prior.timeliness_samples if prior else 0,
        )
        base.runs += 1
        base.items += counter.items
        base.corroborated += counter.corroborated
        base.exclusive += counter.exclusive
        base.timeliness_sum += counter.timeliness_sum
        base.timeliness_samples += counter.timeliness_samples
        base.updated_at = now
        updated[source.id] = base.recompute()
    return updated


def apply_to_digest(digest, scores: dict[str, float]) -> int:
    """低分信源单独支撑的要点降级置信度，返回降级条数。"""
    if not scores:
        return 0
    downgraded = 0
    for point in digest.key_points:
        values = [scores[source] for source in point.sources if source in scores]
        if not values or max(values) >= LOW_SCORE_THRESHOLD:
            continue
        point.confidence = "medium" if point.confidence == "high" else "low"
        downgraded += 1
    return downgraded


def score_map(scores: dict[str, SourceScore]) -> dict[str, float]:
    return {source_id: item.score for source_id, item in scores.items()}


__all__ = [
    "LOW_SCORE_THRESHOLD",
    "SourceScore",
    "apply_to_digest",
    "collect_counters",
    "score_map",
    "update_scores",
]
