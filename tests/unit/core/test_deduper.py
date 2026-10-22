"""去重单元测试：URL 规范化、标题指纹、多源合并。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from qf_wire.core.deduper import (
    canonical_url,
    dedupe,
    normalize_title,
    stable_hash,
    title_fingerprint,
)
from qf_wire.core.models import SourceItem


def _item(**overrides: object) -> SourceItem:
    payload = {
        "title": "Chip maker reports record quarter",
        "url": "https://example.com/news/1",
        "source_id": "feed_a",
        "topic": "semi",
        "summary": "short",
    }
    payload.update(overrides)
    return SourceItem(**payload)  # type: ignore[arg-type]


def test_canonical_url_strips_tracking_and_fragment() -> None:
    url = "https://www.Example.com/a/?utm_source=x&b=2&a=1#frag"
    assert canonical_url(url) == "https://example.com/a?a=1&b=2"


def test_canonical_url_keeps_path_and_handles_empty() -> None:
    assert canonical_url("https://example.com/news/1/") == "https://example.com/news/1"
    assert canonical_url("") == ""


def test_normalize_title_and_fingerprint() -> None:
    assert normalize_title("Chip Maker: Record Quarter!") == "chipmakerrecordquarter"
    assert title_fingerprint("Chip Maker: Record Quarter!") == title_fingerprint(
        "chip maker record quarter"
    )


def test_stable_hash_is_deterministic() -> None:
    first = stable_hash("semi", "https://example.com/1")
    assert first == stable_hash("semi", "https://example.com/1")
    assert first != stable_hash("semi", "https://example.com/2")
    assert len(first) == 16


def test_dedupe_merges_same_canonical_url() -> None:
    older = datetime(2026, 10, 20, 8, tzinfo=timezone.utc)
    newer = datetime(2026, 10, 21, 8, tzinfo=timezone.utc)
    first = _item(
        url="https://example.com/news/1?utm_source=a",
        source_id="feed_a",
        sources=["feed_a"],
        summary="short",
        published_at=newer,
        confidence="low",
    )
    second = _item(
        title="Chip maker reports record quarter (updated)",
        url="https://www.example.com/news/1/",
        source_id="feed_b",
        sources=["feed_b"],
        summary="a much longer summary from another source",
        published_at=older,
        confidence="high",
    )

    merged = dedupe([first, second])

    assert len(merged) == 1
    assert merged[0].sources == ["feed_a", "feed_b"]
    assert merged[0].summary == "a much longer summary from another source"
    assert merged[0].published_at == older
    assert merged[0].confidence == "high"


def test_dedupe_merges_same_title_across_urls() -> None:
    first = _item(url="https://a.example.com/x", title="Chip maker reports record quarter")
    second = _item(
        url="https://b.example.com/y",
        title="chip maker reports record quarter!",
        source_id="feed_b",
        sources=["feed_b"],
    )

    merged = dedupe([first, second])

    assert len(merged) == 1
    assert set(merged[0].sources) == {"feed_a", "feed_b"}


def test_dedupe_keeps_distinct_items() -> None:
    items = [
        _item(url="https://example.com/1", title="First headline"),
        _item(url="https://example.com/2", title="Second headline"),
    ]
    assert len(dedupe(items)) == 2
