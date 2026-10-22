"""适配器注册表：类型 → 适配器类，支持自定义适配器扩展。"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Type

from qf_wire.core.models import Source, SourceType
from qf_wire.sources.api import APIAdapter
from qf_wire.sources.base import SourceAdapter, SourceError
from qf_wire.sources.html import HTMLAdapter
from qf_wire.sources.rss import RSSAdapter

_ADAPTERS: dict[str, Type[SourceAdapter]] = {}
_DISCOVERED = False


def register(source_type: str, adapter: Type[SourceAdapter]) -> None:
    _ADAPTERS[source_type] = adapter


def available_types() -> list[str]:
    _ensure_builtins()
    return sorted(_ADAPTERS)


def create_adapter(source: Source) -> SourceAdapter:
    _ensure_builtins()
    adapter = _ADAPTERS.get(source.type)
    if adapter is None:
        raise SourceError(f"未注册的信源类型: {source.type}")
    return adapter(source)


def _ensure_builtins() -> None:
    global _DISCOVERED
    if not _ADAPTERS:
        register("rss", RSSAdapter)
        register("html", HTMLAdapter)
        register("api", APIAdapter)
    if _DISCOVERED:
        return
    _DISCOVERED = True
    try:
        from qf_wire.sources import adapters as adapters_pkg

        for module_info in pkgutil.iter_modules(adapters_pkg.__path__):
            if module_info.name.startswith("_"):
                continue
            try:
                module = importlib.import_module(f"{adapters_pkg.__name__}.{module_info.name}")
            except ImportError:
                continue
            source_type = getattr(module, "SOURCE_TYPE", None)
            adapter = getattr(module, "ADAPTER", None)
            if source_type and adapter:
                register(source_type, adapter)
    except ImportError:
        return


def _reset_for_tests() -> None:
    global _DISCOVERED
    _ADAPTERS.clear()
    _DISCOVERED = False


__all__ = [
    "SourceAdapter",
    "SourceType",
    "available_types",
    "create_adapter",
    "register",
]
