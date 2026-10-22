"""python -m qf_wire 入口，等价于 qfw。"""
from __future__ import annotations

import sys

from qf_wire.cli.main import cli

if __name__ == "__main__":
    raise SystemExit(cli(sys.argv[1:]))
