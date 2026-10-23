"""只读 API 鉴权：回环、内网、token 三种路径。"""
from __future__ import annotations

import email.message
import http
from typing import Any

import pytest

from qf_wire.web import server as web_server


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, isolated_env) -> pytest.MonkeyPatch:
    for name in (
        "QF_WIRE_API_TOKEN",
        "QF_WIRE_API_REQUIRE_TOKEN",
        "QF_WIRE_ALLOW_PRIVATE_NETWORK",
        "QF_WIRE_CORS_ORIGINS",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _guard(path: str, client: str, headers: dict[str, str] | None = None) -> tuple[bool, dict[str, Any]]:
    handler = object.__new__(web_server.DashboardHandler)
    handler.path = path
    message = email.message.Message()
    for key, value in (headers or {}).items():
        message[key] = value
    handler.headers = message
    handler.client_address = (client, 50000)
    sent: dict[str, Any] = {}

    def fake_send(payload: Any, status: http.HTTPStatus = http.HTTPStatus.OK) -> None:
        sent["payload"] = payload
        sent["status"] = status

    handler._send_json = fake_send  # type: ignore[method-assign]
    return handler._guard_read(), sent


def test_loopback_can_read_without_token() -> None:
    allowed, _ = _guard("/api/digest", "127.0.0.1")
    assert allowed is True


def test_public_client_is_rejected_without_token() -> None:
    allowed, sent = _guard("/api/digest", "203.0.113.9")
    assert allowed is False
    assert sent["status"] == http.HTTPStatus.FORBIDDEN


def test_private_network_needs_explicit_opt_in(clean_env) -> None:
    allowed, sent = _guard("/api/sources", "192.168.1.20")
    assert allowed is False
    assert sent["status"] == http.HTTPStatus.FORBIDDEN

    clean_env.setenv("QF_WIRE_ALLOW_PRIVATE_NETWORK", "true")
    allowed, _ = _guard("/api/sources", "192.168.1.20")
    assert allowed is True


def test_health_is_always_public(clean_env) -> None:
    allowed, _ = _guard("/api/health", "203.0.113.9")
    assert allowed is True


def test_non_api_paths_are_not_guarded() -> None:
    allowed, _ = _guard("/", "203.0.113.9")
    assert allowed is True


def test_token_required_for_external_client(clean_env) -> None:
    clean_env.setenv("QF_WIRE_API_TOKEN", "s3cret")

    allowed, sent = _guard("/api/digest", "203.0.113.9")
    assert allowed is False
    assert sent["status"] == http.HTTPStatus.UNAUTHORIZED

    allowed, _ = _guard(
        "/api/digest", "203.0.113.9", {"Authorization": "Bearer wrong"}
    )
    assert allowed is False

    allowed, _ = _guard(
        "/api/digest", "203.0.113.9", {"Authorization": "Bearer s3cret"}
    )
    assert allowed is True


def test_loopback_bypasses_token_unless_forced(clean_env) -> None:
    clean_env.setenv("QF_WIRE_API_TOKEN", "s3cret")

    allowed, _ = _guard("/data.js", "127.0.0.1")
    assert allowed is True

    clean_env.setenv("QF_WIRE_API_REQUIRE_TOKEN", "true")
    allowed, sent = _guard("/data.js", "127.0.0.1")
    assert allowed is False
    assert sent["status"] == http.HTTPStatus.UNAUTHORIZED

    allowed, _ = _guard(
        "/data.js", "127.0.0.1", {"Authorization": "Bearer s3cret"}
    )
    assert allowed is True


def test_bearer_scheme_is_case_insensitive(clean_env) -> None:
    clean_env.setenv("QF_WIRE_API_TOKEN", "s3cret")
    allowed, _ = _guard(
        "/api/digest", "203.0.113.9", {"Authorization": "bearer s3cret"}
    )
    assert allowed is True


def test_cors_origins_are_parsed(clean_env) -> None:
    clean_env.setenv("QF_WIRE_CORS_ORIGINS", "https://a.example, https://b.example/")
    assert web_server._cors_origins() == {"https://a.example", "https://b.example"}
