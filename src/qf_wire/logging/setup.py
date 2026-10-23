"""统一日志：结果走 stdout，日志只走 stderr。"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

from qf_wire.logging.formatters import JsonFormatter, TextFormatter

_CONFIGURED = False


def setup_logging(level: str | None = None, force: bool = False) -> None:
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    resolved = (level or os.environ.get("QF_WIRE_LOG_LEVEL") or "INFO").upper()
    handler = logging.StreamHandler(stream=sys.stderr)
    if os.environ.get("QF_WIRE_LOG_FORMAT", "text").lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter())

    root = logging.getLogger("qf_wire")
    root.handlers.clear()
    root.addHandler(handler)
    log_file = (os.environ.get("QF_WIRE_LOG_FILE") or "").strip()
    if log_file:
        try:
            path = Path(log_file).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
            file_handler.setFormatter(handler.formatter)
            root.addHandler(file_handler)
        except OSError as exc:  # 写不了文件也不能影响主流程
            sys.stderr.write(f"[qfw] 无法写入日志文件 {log_file}: {exc}\n")
    root.setLevel(getattr(logging, resolved, logging.INFO))
    root.propagate = False

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name if name.startswith("qf_wire") else f"qf_wire.{name}")
