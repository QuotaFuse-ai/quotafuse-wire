"""旧入口根跳转：python fetch.py 仍可用，实际委托 qfw run --sources-only。"""
from __future__ import annotations

from compatibility.fetch import main

if __name__ == "__main__":
    raise SystemExit(main())
