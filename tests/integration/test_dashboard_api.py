"""看板的本机写接口：AI 设置与生成任务。"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from qf_wire.config.loader import load_config
from qf_wire.core.models import Event, SourceItem
from qf_wire.sources.base import FetchResult
from qf_wire.storage.sqlite import WireStore
from qf_wire.web.server import create_server
from tests.fixtures.configs import DEFAULT_DIGEST, write_config

ENV_KEYS = (
    "QF_WIRE_ENV_FILE",
    "QF_WIRE_DIGEST_PROVIDER",
    "QF_WIRE_DIGEST_MODEL",
    "QF_WIRE_API_BASE",
    "QF_WIRE_API_KEY",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "QF_WIRE_API_TOKEN",
    "QF_WIRE_API_REQUIRE_TOKEN",
    "QF_WIRE_CORS_ORIGINS",
    "QF_WIRE_ALLOW_PRIVATE_NETWORK",
    "QF_WIRE_MULTIUSER",
    "QF_WIRE_USER",
    "QF_WIRE_WRITE_TOKEN",
)

TEST_WRITE_TOKEN = "test-write-token"

API_DIGEST = {
    "digest": {
        **DEFAULT_DIGEST["digest"],
        "provider": "api",
        "default_model": "user-model",
        "api_base": None,
    }
}


def _serve(tmp_path: Path, digest: dict[str, Any] | None = None, user: str | None = None):
    config_dir = write_config(tmp_path, digest=digest)
    config = load_config(config_dir, tmp_path / "data", user=user)
    server = create_server(config, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}", config


@pytest.fixture
def dashboard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_env):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("QF_WIRE_ENV_FILE", str(tmp_path / ".env.local"))
    monkeypatch.setenv("QF_WIRE_WRITE_TOKEN", TEST_WRITE_TOKEN)
    server, base, config = _serve(tmp_path)
    try:
        yield base, config, tmp_path
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def api_dashboard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_env):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("QF_WIRE_ENV_FILE", str(tmp_path / ".env.local"))
    monkeypatch.setenv("QF_WIRE_WRITE_TOKEN", TEST_WRITE_TOKEN)
    server, base, config = _serve(tmp_path, API_DIGEST)
    try:
        yield base, config, tmp_path
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def bound_dashboard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_env):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("QF_WIRE_ENV_FILE", str(tmp_path / ".env.local"))
    monkeypatch.setenv("QF_WIRE_MULTIUSER", "true")
    server, base, config = _serve(tmp_path, user="alice")
    try:
        yield base, config, tmp_path
    finally:
        server.shutdown()
        server.server_close()


def _request(
    base: str,
    path: str,
    *,
    method: str = "GET",
    payload: Any = None,
    signed: bool = True,
    write_token: bool = True,
    headers: dict[str, str] | None = None,
):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(base + path, data=body, method=method)
    if signed:
        request.add_header("X-Wire-Request", "1")
        if write_token:
            request.add_header("X-QF-Write-Token", TEST_WRITE_TOKEN)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
            return response.status, json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, json.loads(raw.decode("utf-8")) if raw else {}


def test_settings_read_defaults(dashboard) -> None:
    base, _, _ = dashboard

    status, body = _request(base, "/api/settings")

    assert status == 200
    assert body["provider"] == "claude-cli"
    assert body["hasKey"] is False
    assert body["keyHint"] == ""
    assert "apiKey" not in body


def test_settings_write_requires_local_header(dashboard) -> None:
    base, _, _ = dashboard

    status, body = _request(base, "/api/settings", method="POST", payload={"provider": "claude-cli"}, signed=False)

    assert status == 403
    assert "本机" in body["error"]


def test_settings_write_persists_and_masks_key(dashboard) -> None:
    base, _, tmp_path = dashboard

    status, body = _request(
        base,
        "/api/settings",
        method="POST",
        payload={
            "provider": "api",
            "apiBase": "https://api.example.com",
            "model": "gpt-4o-mini",
            "apiKey": "sk-secret-value",
        },
    )

    assert status == 200
    assert body["configured"] is True
    assert body["apiBase"] == "https://api.example.com/v1"
    assert body["hasKey"] is True
    assert "sk-secret-value" not in json.dumps(body)

    saved = (tmp_path / ".env.local").read_text(encoding="utf-8")
    assert "QF_WIRE_DIGEST_PROVIDER=api" in saved
    assert "QF_WIRE_API_KEY=sk-secret-value" in saved

    status, refreshed = _request(base, "/api/settings")
    assert status == 200
    assert refreshed["model"] == "gpt-4o-mini"
    assert refreshed["configured"] is True


def test_settings_write_rejects_missing_key(dashboard) -> None:
    base, _, tmp_path = dashboard

    status, body = _request(
        base,
        "/api/settings",
        method="POST",
        payload={"provider": "api", "apiBase": "https://api.example.com", "model": "gpt-4o-mini", "apiKey": ""},
    )

    assert status == 400
    assert "API Key" in body["error"]
    assert not (tmp_path / ".env.local").exists()


def test_digest_run_requires_configuration(api_dashboard) -> None:
    base, _, _ = api_dashboard

    status, body = _request(base, "/api/digest/run", method="POST", payload={})

    assert status == 400
    assert "配置" in body["error"]


def test_digest_job_starts_idle(dashboard) -> None:
    base, _, _ = dashboard

    status, body = _request(base, "/api/digest/job")

    assert status == 200
    assert body["job"]["state"] == "idle"


def _raw_request(base: str, path: str, *, method: str = "GET", headers: dict[str, str] | None = None):
    request = urllib.request.Request(base + path, method=method)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def test_token_required_when_forced_on_loopback(dashboard, monkeypatch: pytest.MonkeyPatch) -> None:
    base, _, _ = dashboard
    monkeypatch.setenv("QF_WIRE_API_TOKEN", "s3cret")
    monkeypatch.setenv("QF_WIRE_API_REQUIRE_TOKEN", "true")

    status, body = _request(base, "/api/settings")
    assert status == 401
    assert "Bearer" in body["error"]

    status, _ = _request(base, "/api/settings", headers={"Authorization": "Bearer wrong"})
    assert status == 401

    status, body = _request(base, "/api/settings", headers={"Authorization": "Bearer s3cret"})
    assert status == 200
    assert body["provider"] == "claude-cli"

    # 强制鉴权时 health 也必须在鉴权之后
    status, _ = _request(base, "/api/health")
    assert status == 401
    status, body = _request(base, "/api/health", headers={"Authorization": "Bearer s3cret"})
    assert status == 200
    assert body["status"] == "ok"


def test_token_not_required_for_local_browser(dashboard, monkeypatch: pytest.MonkeyPatch) -> None:
    base, _, _ = dashboard
    monkeypatch.setenv("QF_WIRE_API_TOKEN", "s3cret")

    status, _ = _request(base, "/api/settings")

    assert status == 200


def test_cors_preflight_allows_configured_origin(dashboard, monkeypatch: pytest.MonkeyPatch) -> None:
    base, _, _ = dashboard
    monkeypatch.setenv("QF_WIRE_CORS_ORIGINS", "https://board.example")

    status, headers, body = _raw_request(
        base,
        "/api/digest",
        method="OPTIONS",
        headers={
            "Origin": "https://board.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert status == 204
    assert headers.get("Access-Control-Allow-Origin") == "https://board.example"
    assert "Authorization" in headers.get("Access-Control-Allow-Headers", "")
    assert body == b""


def test_cors_preflight_rejects_unknown_origin(dashboard, monkeypatch: pytest.MonkeyPatch) -> None:
    base, _, _ = dashboard
    monkeypatch.setenv("QF_WIRE_CORS_ORIGINS", "https://board.example")

    status, _, _ = _raw_request(
        base, "/api/digest", method="OPTIONS", headers={"Origin": "https://evil.example"}
    )

    assert status == 403


def test_cors_header_on_actual_response(dashboard, monkeypatch: pytest.MonkeyPatch) -> None:
    base, _, _ = dashboard
    monkeypatch.setenv("QF_WIRE_CORS_ORIGINS", "https://board.example")

    status, headers, _ = _raw_request(
        base, "/api/health", headers={"Origin": "https://board.example"}
    )

    assert status == 200
    assert headers.get("Access-Control-Allow-Origin") == "https://board.example"


def test_multiuser_header_selects_separate_data_dirs(dashboard, monkeypatch: pytest.MonkeyPatch) -> None:
    base, _, tmp_path = dashboard
    monkeypatch.setenv("QF_WIRE_MULTIUSER", "true")
    alice = tmp_path / "data" / "users" / "alice"
    bob = tmp_path / "data" / "users" / "bob"
    alice.mkdir(parents=True)
    bob.mkdir(parents=True)
    (alice / "data.js").write_text('window.DATA = {"owner": "alice"};', encoding="utf-8")
    (bob / "data.js").write_text('window.DATA = {"owner": "bob"};', encoding="utf-8")
    (alice / "api.token").write_text("alice-token\n", encoding="utf-8")
    (bob / "api.token").write_text("bob-token\n", encoding="utf-8")

    alice_status, _, alice_body = _raw_request(
        base, "/data.js", headers={"X-QF-User": "alice", "X-QF-User-Token": "alice-token"}
    )
    bob_status, _, bob_body = _raw_request(
        base, "/data.js", headers={"X-QF-User": "bob", "X-QF-User-Token": "bob-token"}
    )

    assert alice_status == bob_status == 200
    assert b"alice" in alice_body
    assert b"bob" in bob_body
    assert b"bob" not in alice_body


def test_multiuser_switch_requires_target_user_token(dashboard, monkeypatch: pytest.MonkeyPatch) -> None:
    base, _, tmp_path = dashboard
    monkeypatch.setenv("QF_WIRE_MULTIUSER", "true")
    alice = tmp_path / "data" / "users" / "alice"
    alice.mkdir(parents=True)
    (alice / "api.token").write_text("alice-token\n", encoding="utf-8")

    status, body = _request(base, "/api/settings", headers={"X-QF-User": "alice"})
    assert status == 401
    assert "X-QF-User-Token" in body["error"]

    status, _ = _request(base, "/api/settings", headers={"X-QF-User": "alice", "X-QF-User-Token": "wrong"})
    assert status == 401

    status, _ = _request(
        base, "/api/settings", headers={"X-QF-User": "alice", "X-QF-User-Token": "alice-token"}
    )
    assert status == 200


def test_bound_instance_rejects_switching_user(bound_dashboard) -> None:
    base, _, tmp_path = bound_dashboard
    alice = tmp_path / "data" / "users" / "alice"
    alice.mkdir(parents=True, exist_ok=True)
    (alice / "data.js").write_text('window.DATA = {"owner": "alice"};', encoding="utf-8")

    status, body = _request(base, "/data.js", headers={"X-QF-User": "bob"})
    assert status == 403
    assert "只服务用户 alice" in body["error"]

    status, _, raw = _raw_request(base, "/data.js", headers={"X-QF-User": "alice"})
    assert status == 200
    assert b"alice" in raw


def test_write_requires_page_token(dashboard) -> None:
    base, _, _ = dashboard

    status, body = _request(
        base, "/api/settings", method="POST", payload={"provider": "claude-cli"}, write_token=False
    )

    assert status == 403
    assert "X-QF-Write-Token" in body["error"]


def test_page_embeds_write_token(dashboard) -> None:
    base, _, _ = dashboard

    status, _, body = _raw_request(base, "/")

    assert status == 200
    assert b"window.QF_WRITE_TOKEN" in body
    assert TEST_WRITE_TOKEN.encode() in body


def test_foreign_host_header_rejected(dashboard) -> None:
    base, _, _ = dashboard

    status, body = _request(base, "/api/health", headers={"Host": "evil.example"})

    assert status == 403
    assert "Host" in body["error"]


def test_multiuser_rejects_traversal_header(dashboard, monkeypatch: pytest.MonkeyPatch) -> None:
    base, _, _ = dashboard
    monkeypatch.setenv("QF_WIRE_MULTIUSER", "true")

    status, body = _request(base, "/api/settings", headers={"X-QF-User": "../escape"})

    assert status == 400
    assert "用户 id" in body["error"]


def test_multiuser_requires_user_header(dashboard, monkeypatch: pytest.MonkeyPatch) -> None:
    base, _, _ = dashboard
    monkeypatch.setenv("QF_WIRE_MULTIUSER", "true")

    status, body = _request(base, "/api/settings")

    assert status == 400
    assert "QF_WIRE_USER" in body["error"]


def test_history_invalid_date_returns_400(dashboard) -> None:
    base, _, _ = dashboard

    status, body = _request(base, "/api/history?date=2026-13-99")

    assert status == 400
    assert "date" in body.get("error", "").lower() or "日期" in body.get("error", "")


# ---- 只读 API：状态、事件检索与多用户隔离 ----
def _event(event_id: str, title: str, *, source_id: str = "feed_a") -> Event:
    now = datetime.now(timezone.utc)
    item = SourceItem(
        title=title,
        url=f"https://example.com/{event_id}",
        source_id=source_id,
        topic="semi",
        summary=title,
        zh="",
        published_at=now,
        sources=[source_id],
        event_id=event_id,
        confidence="high",
    )
    return Event(
        event_id=event_id,
        topic="semi",
        title=title,
        items=[item],
        sources=[source_id],
        source_count=1,
        confidence="high",
        first_seen=now,
        last_seen=now,
    )


def _seed_db(
    db_path: Path,
    *,
    run_id: str,
    events: list[Event],
    results: list[FetchResult] | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    store = WireStore(db_path)
    store.initialize()
    try:
        store.record_run(
            run_id=run_id,
            day=now.date(),
            topic=None,
            mode="all",
            status="ok",
            exit_code=0,
            started_at=now,
            finished_at=now,
            results=results or [],
            items_by_topic={"semi": [item for event in events for item in event.items]},
            events_by_topic={"semi": events},
        )
    finally:
        store.close()


def test_status_cold_start(dashboard) -> None:
    base, _, _ = dashboard

    status, body = _request(base, "/api/status")

    assert status == 200
    assert body["lastRun"] is None
    assert body["sources"] == []
    assert body["degradedSources"] == []
    assert body["archiveDays"] == 0


def test_status_reports_last_run_and_degraded(dashboard) -> None:
    base, config, tmp_path = dashboard
    results = [
        FetchResult(source_id="feed_a", source_name="Feed A", topic="semi", status="ok"),
        FetchResult(
            source_id="feed_b",
            source_name="Feed B",
            topic="semi",
            status="unavailable",
            error="HTTP 503",
        ),
    ]
    _seed_db(config.paths.db_path, run_id="run-1", events=[_event("evt-status", "Chip news")], results=results)
    archive = tmp_path / "data" / "archive" / "2026-10-23"
    archive.mkdir(parents=True)
    (archive / "manifest.json").write_text("{}", encoding="utf-8")

    status, body = _request(base, "/api/status")

    assert status == 200
    assert body["lastRun"]["runId"] == "run-1"
    assert body["lastRun"]["sourceTotal"] == 2
    assert body["sourceDate"]
    assert {row["source_id"] for row in body["sources"]} == {"feed_a", "feed_b"}
    assert [item["sourceId"] for item in body["degradedSources"]] == ["feed_b"]
    assert body["degradedSources"][0]["error"] == "HTTP 503"
    assert body["archiveDays"] == 1


def test_events_keyword_and_window(dashboard) -> None:
    base, config, _ = dashboard
    _seed_db(
        config.paths.db_path,
        run_id="run-2",
        events=[
            _event("evt-packaging", "Advanced packaging demand surges"),
            _event("evt-earnings", "Unrelated earnings report"),
        ],
    )

    status, body = _request(base, "/api/events?keyword=packaging&window=7d")
    assert status == 200
    assert [event["event_id"] for event in body["events"]] == ["evt-packaging"]
    assert body["keyword"] == "packaging"
    assert body["window"] == "7d"

    status, body = _request(base, "/api/events?keyword=packaging&window=7d&topic=semi")
    assert status == 200
    assert body["topic"] == "semi"
    assert len(body["events"]) == 1

    status, body = _request(base, "/api/events?keyword=packaging&window=7d&topic=unknown")
    assert status == 200
    assert body["events"] == []

    status, body = _request(base, "/api/events?keyword=packaging&window=oops")
    assert status == 400
    assert "window" in body["error"]


def test_event_detail_by_path(dashboard) -> None:
    base, config, _ = dashboard
    _seed_db(config.paths.db_path, run_id="run-3", events=[_event("evt-detail", "Detail event")])

    status, body = _request(base, "/api/events/evt-detail")
    assert status == 200
    assert body["event"]["event_id"] == "evt-detail"
    assert [item["title"] for item in body["timeline"]] == ["Detail event"]

    status, body = _request(base, "/api/events/missing")
    assert status == 404
    assert "不存在" in body["error"]


def test_multiuser_db_isolation(dashboard, monkeypatch: pytest.MonkeyPatch) -> None:
    base, config, _ = dashboard
    monkeypatch.setenv("QF_WIRE_MULTIUSER", "true")
    users_dir = config.paths.base_data_dir / "users"
    alice = users_dir / "alice"
    bob = users_dir / "bob"
    alice.mkdir(parents=True)
    bob.mkdir(parents=True)
    _seed_db(alice / "wire.db", run_id="alice-run", events=[_event("alice-evt", "Alice chip news")])
    _seed_db(bob / "wire.db", run_id="bob-run", events=[_event("bob-evt", "Bob chip news")])

    status, _ = _request(base, "/api/events/alice-evt", headers={"X-QF-User": "alice"})
    assert status == 200
    status, _ = _request(base, "/api/events/alice-evt", headers={"X-QF-User": "bob"})
    assert status == 404
    status, _ = _request(base, "/api/events/bob-evt", headers={"X-QF-User": "bob"})
    assert status == 200
    status, _ = _request(base, "/api/events/bob-evt", headers={"X-QF-User": "alice"})
    assert status == 404

    _, alice_status = _request(base, "/api/status", headers={"X-QF-User": "alice"})
    _, bob_status = _request(base, "/api/status", headers={"X-QF-User": "bob"})
    assert alice_status["lastRun"]["runId"] == "alice-run"
    assert bob_status["lastRun"]["runId"] == "bob-run"


def test_multiuser_config_error_does_not_leak_paths(
    dashboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, config, tmp_path = dashboard
    monkeypatch.setenv("QF_WIRE_MULTIUSER", "true")
    user_config = config.paths.base_data_dir / "users" / "alice" / "config"
    user_config.mkdir(parents=True)
    for name in ("sources.yaml", "digest.yaml", "schedule.yaml"):
        (user_config / name).write_bytes((config.paths.config_dir / name).read_bytes())
    (user_config / "topics.yaml").write_text("topics: [unclosed\n", encoding="utf-8")

    status, body = _request(base, "/api/status", headers={"X-QF-User": "alice"})

    assert status == 400
    error = body["error"]
    assert str(tmp_path) not in error
    assert str(user_config) not in error
    assert "<path>" in error
