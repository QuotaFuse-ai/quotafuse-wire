"""日志格式化器：文本与 JSON，均只写 stderr。"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone


class TextFormatter(logging.Formatter):
    default_format = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"

    def __init__(self) -> None:
        super().__init__(fmt=self.default_format, datefmt="%H:%M:%S")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)
