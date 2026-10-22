"""旧入口根跳转：python server.py 仍可用，默认端口 8793，委托 qfw serve。"""
from __future__ import annotations

from compatibility.server import main

if __name__ == "__main__":
    raise SystemExit(main())
