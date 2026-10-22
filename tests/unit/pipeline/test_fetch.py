"""并发度解析：显式参数 > 环境变量 > 默认值，范围裁剪到 1..64。"""
from __future__ import annotations

from qf_wire.pipeline.fetch import (
    CONCURRENCY_ENV,
    DEFAULT_CONCURRENCY,
    MAX_CONCURRENCY,
    resolve_concurrency,
)


def test_resolve_concurrency_precedence(monkeypatch) -> None:
    monkeypatch.delenv(CONCURRENCY_ENV, raising=False)
    assert resolve_concurrency() == DEFAULT_CONCURRENCY

    monkeypatch.setenv(CONCURRENCY_ENV, "8")
    assert resolve_concurrency() == 8
    assert resolve_concurrency(2) == 2


def test_resolve_concurrency_clips_to_range(monkeypatch) -> None:
    monkeypatch.setenv(CONCURRENCY_ENV, "500")
    assert resolve_concurrency() == MAX_CONCURRENCY

    assert resolve_concurrency(0) == 1
    assert resolve_concurrency(MAX_CONCURRENCY + 1) == MAX_CONCURRENCY


def test_resolve_concurrency_ignores_invalid_env(monkeypatch) -> None:
    monkeypatch.setenv(CONCURRENCY_ENV, "many")
    assert resolve_concurrency() == DEFAULT_CONCURRENCY
