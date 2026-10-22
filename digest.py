"""旧入口根跳转：python digest.py 仍可用，实际委托 qfw digest。"""
from __future__ import annotations

from compatibility.digest import main

if __name__ == "__main__":
    raise SystemExit(main())
