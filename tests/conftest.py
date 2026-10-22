"""pytest 公共配置：未安装包时也能直接从 src 导入。"""
from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def isolated_env() -> Iterator[None]:
    """恢复测试期间新增或修改的环境变量。

    monkeypatch 只回滚它自己改过的键；业务代码直接写 os.environ 时，
    原本不存在的键会泄漏到后面的测试。
    """
    saved = dict(os.environ)
    yield
    for name in [name for name in os.environ if name not in saved]:
        del os.environ[name]
    for name, value in saved.items():
        if os.environ.get(name) != value:
            os.environ[name] = value
