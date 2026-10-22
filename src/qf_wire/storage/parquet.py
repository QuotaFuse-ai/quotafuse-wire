"""可选的 Parquet 归档。

Parquet 不是 M1 的硬依赖：未安装 pyarrow 时静默降级，SQLite 仍是查询来源。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from qf_wire.logging.setup import get_logger

logger = get_logger(__name__)


def available() -> bool:
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        return False
    return True


def write_rows(path: Path, rows: Iterable[dict[str, Any]]) -> bool:
    """把字典行写成 Parquet；pyarrow 缺失或写入失败时返回 False。"""
    data = list(rows)
    if not data:
        return False
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        logger.debug("未安装 pyarrow，跳过 Parquet 归档")
        return False
    try:
        table = pa.Table.from_pylist(data)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path)
    except Exception as exc:  # 可选依赖，任何失败都不应影响主流程
        logger.warning("Parquet 写入失败 %s: %s", path, exc)
        return False
    logger.info("已写入 Parquet 归档: %s", path)
    return True
