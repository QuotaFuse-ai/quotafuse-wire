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


def _request(base: str, path: str, *, method: str = "GET", payload: Any = None, signed: bool = True):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(base + path, data=body, method=method)
    if signed:
        request.add_header("X-Wire-Request", "1")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


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
