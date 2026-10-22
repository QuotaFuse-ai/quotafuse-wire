"""旧版看板入口：python server.py

旧看板默认端口 8793，委托给 qfw serve。
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        from qf_wire.cli.main import cli
    except ImportError:
        sys.stderr.write(
            "[qfw] 旧入口已升级为 QuotaFuse Wire，但 qf_wire 尚未安装。\n"
            "提示：在仓库根目录执行 `pip install -e .` 后重试。\n"
        )
        return 3

    if not any(a == "--port" or a.startswith("--port=") for a in argv):
        argv = ["--port", "8793", *argv]
    sys.stderr.write("[qfw] 旧入口已升级为 QuotaFuse Wire，正在委托 qfw serve\n")
    return cli(["serve", *argv])


if __name__ == "__main__":
    raise SystemExit(main())
