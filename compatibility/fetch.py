"""旧版采集入口：python fetch.py

保留以兼容既有部署，实际委托给 qfw run --sources-only。
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

    sys.stderr.write("[qfw] 旧入口已升级为 QuotaFuse Wire，正在委托 qfw run --sources-only\n")
    return cli(["run", "--sources-only", *argv])


if __name__ == "__main__":
    raise SystemExit(main())
