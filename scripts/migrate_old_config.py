"""从早期版本配置（sources.json / llm.config.json）迁移到 Wire YAML。

用法：
    python scripts/migrate_old_config.py --legacy-dir ../old-wire --dry-run
    python scripts/migrate_old_config.py --legacy-dir ../old-wire

等价于 `qfw config migrate`，供未安装 CLI 时使用。迁移幂等，不覆盖已编辑的 YAML。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qf_wire.config.migrate import migrate_legacy  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="迁移早期版本配置")
    p.add_argument("--legacy-dir", required=True, help="旧仓库根目录（含 sources.json / llm.config.json）")
    p.add_argument("--config-dir", help="输出配置目录，缺省 config/")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    legacy = Path(args.legacy_dir).expanduser().resolve()
    if not legacy.is_dir():
        print(f"legacy dir not found: {legacy}", file=sys.stderr)
        return 2

    report = migrate_legacy(legacy, Path(args.config_dir) if args.config_dir else None, dry_run=args.dry_run)
    for line in report.lines:
        print(line)
    print(
        f"topics={report.topic_count} sources={report.source_count} "
        f"skipped={report.skipped} dry_run={args.dry_run}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
