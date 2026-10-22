"""统一日志：结果走 stdout，日志只走 stderr。"""
from __future__ import annotations

import logging
import os
import sys

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
    root.setLevel(getattr(logging, resolved, logging.INFO))
    root.propagate = False

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name if name.startswith("qf_wire") else f"qf_wire.{name}")
