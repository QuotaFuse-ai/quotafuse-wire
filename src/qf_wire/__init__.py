"""QuotaFuse Wire —— 多源资讯采集与 AI 提炼。

本地优先：数据全程留在本机，不强制 API key，不输出交易信号。
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

# 版本唯一真源是 pyproject.toml 的 [project] version，不再手写第二份（QUOT-401）。
# 注意发现名是 `quota-fuse-wire`，导入名是 `qf_wire`，读元数据必须用发现名。
try:
    __version__ = _dist_version("quota-fuse-wire")
except PackageNotFoundError:  # 未安装：纯源码树直接 import
    __version__ = "0.0.0+source"

__all__ = ["__version__"]
