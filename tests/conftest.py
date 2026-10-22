"""pytest 公共配置：未安装包时也能直接从 src 导入。"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tests.fixtures.council_stub import council_data_access  # noqa: E402,F401 - 全局可用的 Council 桩 fixture
