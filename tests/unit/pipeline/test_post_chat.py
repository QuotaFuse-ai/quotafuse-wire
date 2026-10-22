"""模型接口调用：地址拼接与上游报错透出（密钥不落日志/报错）。"""
from __future__ import annotations

import io
import urllib.error

import pytest

from qf_wire.pipeline import digest as digest_module
from qf_wire.pipeline.digest import DigestUnavailable

URL = "http://gw.test/v1/chat/completions"


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def _http_error(status: int, body: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(URL, status, "error", {}, io.BytesIO(body.encode("utf-8")))


def test_chat_endpoint_appends_suffix_once() -> None:
    assert digest_module._chat_endpoint("http://gw.test/v1") == URL
    assert digest_module._chat_endpoint("http://gw.test/v1/") == URL
    assert digest_module._chat_endpoint(URL) == URL


def test_post_chat_surfaces_upstream_status_and_body(monkeypatch: pytest.MonkeyPatch) -> None:
    body = '{"error": "接口未实现", "request_id": "req-501"}'

    def fake_urlopen(_request, timeout=None):
        raise _http_error(501, body)

    monkeypatch.setattr(digest_module.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(DigestUnavailable) as info:
        digest_module._post_chat("http://gw.test/v1", "sk-secret-123", "p", "m", 5, label="模型接口")

    message = str(info.value)
    assert "模型接口 HTTP 501" in message
    assert "接口未实现" in message
    assert "req-501" in message


def test_post_chat_never_echoes_key(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "sk-secret-123"

    def fake_urlopen(_request, timeout=None):
        raise _http_error(401, f'{{"error": "invalid key {secret}"}}')

    monkeypatch.setattr(digest_module.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(DigestUnavailable) as info:
        digest_module._post_chat("http://gw.test/v1", secret, "p", "m", 5, label="模型接口")

    assert secret not in str(info.value)
    assert "***" in str(info.value)


def test_post_chat_uses_full_endpoint_without_duplicating(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        return _FakeResponse(b'{"choices": [{"message": {"content": "ok"}}]}')

    monkeypatch.setattr(digest_module.urllib.request, "urlopen", fake_urlopen)

    result = digest_module._post_chat(URL, "k", "p", "m", 5, label="模型接口")

    assert result == "ok"
    assert seen["url"] == URL
