"""清洗单元测试：HTML、时间、合规红线、过期过滤。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from qf_wire.core.cleaner import (
    BEIJING_TZ,
    clean_item,
    clean_items,
    clean_text,
    contains_trading_advice,
    format_display_time,
    parse_datetime,
    strip_html,
    to_timestamp_ms,
)
from qf_wire.core.models import SourceItem


def _item(**overrides: object) -> SourceItem:
    payload = {
        "title": "A valid headline about chips",
        "url": "https://example.com/news/1",
        "source_id": "feed_a",
        "topic": "semi",
        "summary": "summary",
    }
    payload.update(overrides)
    return SourceItem(**payload)  # type: ignore[arg-type]


def test_strip_html_removes_tags_and_scripts() -> None:
    raw = '<p>Hello&nbsp;<b>World</b></p><script>alert("x")</script>'
    assert strip_html(raw) == "Hello World"


def test_strip_html_handles_empty_values() -> None:
    assert strip_html(None) == ""
    assert strip_html("") == ""


def test_clean_text_truncates_with_ellipsis() -> None:
    value = clean_text("abcdefghij", max_length=5)
    assert value == "abcd…"
    assert len(value) == 5


def test_parse_datetime_rfc822_converts_to_beijing() -> None:
    parsed = parse_datetime("Wed, 21 Oct 2026 07:28:00 GMT")
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(hours=8)
    assert parsed.strftime("%Y-%m-%d %H:%M") == "2026-10-21 15:28"


def test_parse_datetime_iso_and_naive() -> None:
    iso = parse_datetime("2026-10-21T07:28:00Z")
    naive = parse_datetime(datetime(2026, 10, 21, 7, 28))
    assert iso is not None and naive is not None
    assert iso == naive
    assert naive.tzinfo == BEIJING_TZ


def test_parse_datetime_epoch_seconds_and_milliseconds() -> None:
    seconds = parse_datetime(0)
    milliseconds = parse_datetime(0)
    assert seconds is not None and milliseconds is not None
    assert seconds.hour == 8  # 北京时间 1970-01-01 08:00


def test_parse_datetime_invalid_returns_none() -> None:
    assert parse_datetime("not a date") is None
    assert parse_datetime(None) is None
    assert parse_datetime([]) is None


def test_format_and_timestamp_helpers() -> None:
    value = parse_datetime("2026-10-21T07:28:00Z")
    assert format_display_time(value) == "2026-10-21 15:28"
    assert format_display_time(None) == ""
    assert to_timestamp_ms(value) == int(value.timestamp() * 1000)
    assert to_timestamp_ms(None) == 0


def test_contains_trading_advice() -> None:
    assert contains_trading_advice("机构给出目标价 100 元")
    assert not contains_trading_advice("公司发布季度财报")


def test_clean_item_rejects_short_title_bad_url_and_advice() -> None:
    assert clean_item(_item(title="abc")) is None
    assert clean_item(_item(url="ftp://example.com/1")) is None
    assert clean_item(_item(title="建议买入这家公司的股票")) is None


def test_clean_item_normalizes_fields() -> None:
    cleaned = clean_item(
        _item(
            title="<b>Chip maker</b> reports record quarter",
            summary="<p>Revenue &amp; profit up</p>",
            zh="",
            published_at=parse_datetime("Wed, 21 Oct 2026 07:28:00 GMT"),
        )
    )
    assert cleaned is not None
    assert cleaned.title == "Chip maker reports record quarter"
    assert cleaned.summary == "Revenue & profit up"
    assert cleaned.zh == cleaned.title
    assert cleaned.published_at is not None
    assert cleaned.published_at.strftime("%H:%M") == "15:28"


def test_clean_items_filters_stale_and_future_items() -> None:
    now = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
    fresh = _item(url="https://example.com/fresh", published_at=now - timedelta(days=1))
    stale = _item(url="https://example.com/stale", published_at=now - timedelta(days=60))
    future = _item(url="https://example.com/future", published_at=now + timedelta(days=5))
    undated = _item(url="https://example.com/undated", published_at=None)

    cleaned = clean_items([fresh, stale, future, undated], now=now, max_age_days=30)

    assert [item.url for item in cleaned] == [
        "https://example.com/fresh",
        "https://example.com/undated",
    ]
