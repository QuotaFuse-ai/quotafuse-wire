"""看板的本机写接口：AI 设置与生成任务。"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from qf_wire.config.loader import load_config
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
)

API_DIGEST = {
    "digest": {
        **DEFAULT_DIGEST["digest"],
        "provider": "api",
        "default_model": "user-model",
        "api_base": None,
    }
}


def _serve(tmp_path: Path, digest: dict[str, Any] | None = None):
    config_dir = write_config(tmp_path, digest=digest)
    config = load_config(config_dir, tmp_path / "data")
    server = create_server(config, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}", config


@pytest.fixture
def dashboard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_env):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("QF_WIRE_ENV_FILE", str(tmp_path / ".env.local"))
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
    server, base, config = _serve(tmp_path, API_DIGEST)
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
    headers: dict[str, str] | None = None,
):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(base + path, data=body, method=method)
    if signed:
        request.add_header("X-Wire-Request", "1")
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

    status, _ = _request(base, "/api/health")
    assert status == 200


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

    alice_status, _, alice_body = _raw_request(base, "/data.js", headers={"X-QF-User": "alice"})
    bob_status, _, bob_body = _raw_request(base, "/data.js", headers={"X-QF-User": "bob"})

    assert alice_status == bob_status == 200
    assert b"alice" in alice_body
    assert b"bob" in bob_body
    assert b"bob" not in alice_body


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
