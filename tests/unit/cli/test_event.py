"""CLI 事件查看与历史事件维度：show / timeline / list / exit code 6。"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from qf_wire.cli.main import cli
from qf_wire.core.errors import EXIT_NOT_FOUND, EXIT_OK, EXIT_PARAM
from qf_wire.core.models import Event, SourceItem
from qf_wire.core.scheduler import today_beijing
from qf_wire.sources.base import FetchResult
from qf_wire.storage.sqlite import WireStore
from tests.fixtures.configs import write_config

NOW = datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def _item(
    url: str,
    title: str,
    source_id: str,
    published_at: datetime,
    event_id: str | None = "evt-1",
) -> SourceItem:
    return SourceItem(
        title=title,
        url=url,
        source_id=source_id,
        topic="semi",
        summary="summary",
        published_at=published_at,
        sources=[source_id],
        event_id=event_id,
        confidence="high",
    )


def _result(source_id: str, items: list[SourceItem]) -> FetchResult:
    return FetchResult(
        source_id=source_id,
        source_name=source_id.upper(),
        topic="semi",
        status="ok",
        items=items,
        attempts=1,
    )


@pytest.fixture()
def seeded(tmp_path: Path) -> tuple[Path, Path]:
    config_dir = write_config(tmp_path)
    data_dir = tmp_path / "data"
    day = today_beijing()
    early = _item("https://example.com/a", "Fab breaks ground", "feed_a", NOW)
    late = _item("https://example.com/b", "New fab construction starts", "feed_b", LATER)
    event = Event(
        event_id="evt-1",
        topic="semi",
        title=early.title,
        items=[early, late],
        sources=["feed_a", "feed_b"],
        source_count=2,
        confidence="high",
        first_seen=NOW,
        last_seen=LATER,
    )
    store = WireStore(data_dir / "wire.db")
    try:
        store.record_run(
            run_id="run-1",
            day=day,
            topic="semi",
            mode="sources",
            status="ok",
            exit_code=0,
            started_at=NOW,
            finished_at=LATER,
            results=[_result("feed_a", [early]), _result("feed_b", [late])],
            items_by_topic={"semi": [early, late]},
            events_by_topic={"semi": [event]},
        )
    finally:
        store.close()
    return config_dir, data_dir


def _run(config_dir: Path, data_dir: Path, *args: str) -> int:
    return cli(
        [
            "--config-dir",
            str(config_dir),
            "--data-dir",
            str(data_dir),
            *args,
        ]
    )


def test_event_show_json(seeded: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    config_dir, data_dir = seeded
    assert _run(config_dir, data_dir, "--output", "json", "event", "show", "evt-1") == EXIT_OK
    payload = capsys.readouterr().out
    assert '"event_id": "evt-1"' in payload
    assert '"source_count": 2' in payload
    assert payload.index("Fab breaks ground") < payload.index("New fab construction starts")


def test_event_timeline_csv_is_ascending(
    seeded: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    config_dir, data_dir = seeded
    assert _run(config_dir, data_dir, "--output", "csv", "event", "timeline", "evt-1") == EXIT_OK
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == "时间,信源,标题,URL"
    assert len(lines) == 3
    assert "feed_a" in lines[1] and "feed_b" in lines[2]


def test_event_list_defaults_to_today(
    seeded: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    config_dir, data_dir = seeded
    assert _run(config_dir, data_dir, "--output", "json", "event") == EXIT_OK
    payload = capsys.readouterr().out
    assert '"count": 1' in payload
    assert "evt-1" in payload


def test_event_list_csv(seeded: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    config_dir, data_dir = seeded
    assert _run(config_dir, data_dir, "--output", "csv", "event", "list") == EXIT_OK
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0].startswith("event_id,赛道,标题,信源数")
    assert len(lines) == 2


def test_missing_event_show_exits_6(seeded: tuple[Path, Path]) -> None:
    config_dir, data_dir = seeded
    assert _run(config_dir, data_dir, "event", "show", "missing") == EXIT_NOT_FOUND


def test_missing_event_timeline_exits_6(seeded: tuple[Path, Path]) -> None:
    config_dir, data_dir = seeded
    assert _run(config_dir, data_dir, "event", "timeline", "missing") == EXIT_NOT_FOUND


def test_event_unknown_subcommand_is_parameter_error(seeded: tuple[Path, Path]) -> None:
    config_dir, data_dir = seeded
    assert _run(config_dir, data_dir, "event", "nope") == EXIT_PARAM


def test_history_exposes_event_dimension(
    seeded: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    config_dir, data_dir = seeded
    day = today_beijing().isoformat()
    assert (
        _run(config_dir, data_dir, "--output", "json", "history", "--days", "1", "--date", day)
        == EXIT_OK
    )
    payload = capsys.readouterr().out
    assert '"events": 1' in payload
    assert '"multi_source": 1' in payload
    assert '"event_delta"' in payload

    assert (
        _run(config_dir, data_dir, "--output", "csv", "history", "--days", "1", "--date", day)
        == EXIT_OK
    )
    header = capsys.readouterr().out.splitlines()[0]
    assert "多源事件" in header
    assert "事件增量" in header
