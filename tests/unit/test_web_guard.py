"""只读 API 鉴权：回环、内网、token、用户身份四条路径。"""
from __future__ import annotations

import email.message
import http
import types
from pathlib import Path
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
        "QF_WIRE_MULTIUSER",
        "QF_WIRE_WRITE_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _handler(
    path: str,
    client: str,
    headers: dict[str, str] | None = None,
    *,
    user: str = "",
    base_data: Path | None = None,
    write_token: str = "write-token",
) -> tuple[web_server.DashboardHandler, dict[str, Any]]:
    handler = object.__new__(web_server.DashboardHandler)
    handler.path = path
    message = email.message.Message()
    for key, value in (headers or {}).items():
        message[key] = value
    handler.headers = message
    handler.client_address = (client, 50000)
    handler.config = types.SimpleNamespace(  # type: ignore[assignment]
        paths=types.SimpleNamespace(user=user, base_data_dir=base_data, data_dir=base_data)
    )
    handler.write_token = write_token
    handler.server = types.SimpleNamespace(  # type: ignore[assignment]
        bind_host="127.0.0.1", server_address=("127.0.0.1", 8790)
    )
    sent: dict[str, Any] = {}

    def fake_send(payload: Any, status: http.HTTPStatus = http.HTTPStatus.OK) -> None:
        sent["payload"] = payload
        sent["status"] = status

    handler._send_json = fake_send  # type: ignore[method-assign]
    return handler, sent


def _guard(path: str, client: str, headers: dict[str, str] | None = None) -> tuple[bool, dict[str, Any]]:
    handler, sent = _handler(path, client, headers)
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


def test_bound_instance_rejects_other_user(clean_env) -> None:
    handler, sent = _handler("/api/settings", "127.0.0.1", {"X-QF-User": "bob"}, user="alice")

    assert handler._guard_read() is False
    assert sent["status"] == http.HTTPStatus.FORBIDDEN
    assert "alice" in sent["payload"]["error"]


def test_bound_instance_accepts_own_user(clean_env) -> None:
    handler, _ = _handler("/api/settings", "127.0.0.1", {"X-QF-User": "alice"}, user="alice")

    assert handler._guard_read() is True


def test_shared_instance_requires_target_user_token(clean_env, tmp_path: Path) -> None:
    clean_env.setenv("QF_WIRE_MULTIUSER", "true")
    token_dir = tmp_path / "users" / "bob"
    token_dir.mkdir(parents=True)
    (token_dir / "api.token").write_text("bob-token\n", encoding="utf-8")

    handler, sent = _handler("/api/settings", "127.0.0.1", {"X-QF-User": "bob"}, base_data=tmp_path)
    assert handler._guard_read() is False
    assert sent["status"] == http.HTTPStatus.UNAUTHORIZED

    handler, _ = _handler(
        "/api/settings",
        "127.0.0.1",
        {"X-QF-User": "bob", "X-QF-User-Token": "bob-token"},
        base_data=tmp_path,
    )
    assert handler._guard_read() is True


def test_write_requires_page_token(clean_env) -> None:
    handler, sent = _handler("/api/settings", "127.0.0.1", {"X-Wire-Request": "1"})

    assert handler._guard_write() is False
    assert sent["status"] == http.HTTPStatus.FORBIDDEN


def test_write_accepts_page_token(clean_env) -> None:
    handler, _ = _handler(
        "/api/settings", "127.0.0.1", {"X-Wire-Request": "1", "X-QF-Write-Token": "write-token"}
    )

    assert handler._guard_write() is True


def test_write_token_from_env_overrides_page_token(clean_env) -> None:
    clean_env.setenv("QF_WIRE_WRITE_TOKEN", "env-token")
    handler, _ = _handler(
        "/api/settings", "127.0.0.1", {"X-Wire-Request": "1", "X-QF-Write-Token": "env-token"}
    )

    assert handler._guard_write() is True


def test_host_guard_rejects_foreign_host(clean_env) -> None:
    handler, sent = _handler("/api/health", "127.0.0.1", {"Host": "evil.example"})

    assert handler._guard_host() is False
    assert sent["status"] == http.HTTPStatus.FORBIDDEN


def test_host_guard_allows_listening_address(clean_env) -> None:
    handler, _ = _handler("/api/health", "127.0.0.1", {"Host": "localhost:8790"})

    assert handler._guard_host() is True

