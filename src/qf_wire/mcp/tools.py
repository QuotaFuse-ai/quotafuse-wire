"""四个只读 MCP 工具：参数校验 → WireProvider → WireEnvelope JSON 文本。

参数错误统一抛 ``ToolError``，MCP 客户端会收到 ``isError: true`` 与可读的合法取值；
内部异常只暴露脱敏后的固定文案，避免泄漏绝对路径或密钥。
"""
from __future__ import annotations

from datetime import date as Date
from pathlib import Path
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from qf_wire.config.loader import WireConfig
from qf_wire.logging.setup import get_logger
from qf_wire.provider.wire_provider import WireProvider, parse_window

logger = get_logger(__name__)

INTERNAL_ERROR = "查询失败：Wire 内部错误（详情见服务端日志）"
DB_HINT = "本地数据库尚未初始化，请先执行 qfw run"


class WireTools:
    """MCP 工具实现；与传输层解耦，便于直接单测。"""

    def __init__(
        self,
        provider: WireProvider | None = None,
        *,
        config: WireConfig | None = None,
        config_dir: str | Path | None = None,
        data_dir: str | Path | None = None,
    ) -> None:
        self._provider = provider or WireProvider(
            config, config_dir=config_dir, data_dir=data_dir
        )

    @property
    def provider(self) -> WireProvider:
        return self._provider

    def close(self) -> None:
        self._provider.close()

    # ---- 四个工具 ----
    def wire_get_digest(self, topic: str, date: str | None = None) -> str:
        topic_id = self._topic(topic).id
        day = self._date(date)
        self._ensure_local_data()
        return self._run(lambda: self._provider.get_digest(topic_id, day))

    def wire_search_events(
        self,
        keyword: str,
        window: str | None = None,
        topic: str | None = None,
    ) -> str:
        text = str(keyword or "").strip()
        if not text:
            raise ToolError("keyword 不能为空")
        try:
            parse_window(window)
        except ValueError as exc:
            raise ToolError(f"{exc}（可用格式：7d、24h）") from exc
        topic_id = self._topic(topic).id if topic else None
        self._ensure_local_data()
        return self._run(
            lambda: self._provider.search_events(text, window or "7d", topic_id)
        )

    def wire_get_timeline(self, event_id: str) -> str:
        target = str(event_id or "").strip()
        if not target:
            raise ToolError("event_id 不能为空")
        self._ensure_local_data()
        return self._run(lambda: self._provider.get_timeline(target))

    def wire_list_sources(self, topic: str | None = None) -> str:
        topic_id = self._topic(topic).id if topic else None
        return self._run(lambda: self._provider.list_sources(topic_id))

    # ---- 参数与数据校验 ----
    def _topic(self, value: Any) -> Any:
        text = str(value or "").strip()
        if not text:
            raise ToolError(f"topic 不能为空（可用: {self._topic_names()}）")
        topic = self._provider.config.find_topic(text)
        if topic is None:
            raise ToolError(f"未知赛道: {text}（可用: {self._topic_names()}）")
        return topic

    def _topic_names(self) -> str:
        return "、".join(topic.id for topic in self._provider.config.topics)

    @staticmethod
    def _date(value: str | None) -> Date | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            return Date.fromisoformat(text)
        except ValueError as exc:
            raise ToolError(f"date 格式应为 YYYY-MM-DD：{text}") from exc

    def _ensure_local_data(self) -> None:
        if self._provider.db_ready or self._has_archive():
            return
        raise ToolError(DB_HINT)

    def _has_archive(self) -> bool:
        archive = self._provider.config.paths.archive_dir
        if not archive.is_dir():
            return False
        for path in archive.iterdir():
            if not path.is_dir():
                continue
            try:
                Date.fromisoformat(path.name)
            except ValueError:
                continue
            return True
        return False

    def _run(self, action: Any) -> str:
        try:
            envelope = action()
        except ToolError:
            raise
        except Exception as exc:  # noqa: BLE001 - 内部异常统一脱敏
            logger.exception("MCP 工具执行失败：%s", exc)
            raise ToolError(INTERNAL_ERROR) from exc
        return envelope.model_dump_json()
