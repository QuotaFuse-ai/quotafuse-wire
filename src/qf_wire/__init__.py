"""QuotaFuse Wire —— 多源资讯采集与 AI 提炼。

本地优先：数据全程留在本机，不强制 API key，不输出交易信号。
"""

from importlib.metadata import PackageNotFoundError, version as _dist_version

try:
    __version__ = _dist_version("quota-fuse-wire")
except PackageNotFoundError:  # 未安装（直接跑源码树）时退回 pyproject 的版本
    __version__ = "0.1.1"
__all__ = ["__version__"]
