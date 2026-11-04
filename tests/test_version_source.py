"""QUOT-401：版本只在 pyproject.toml 写一次，代码从安装元数据读。"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = "src/qf_wire/__init__.py"


def _pyproject_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def test_dunder_version_reads_install_metadata() -> None:
    from qf_wire import __version__

    assert __version__ == _pyproject_version()


def test_version_literal_exists_only_in_init_fallback() -> None:
    version = _pyproject_version()
    hits = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src").rglob("*.py")
        if re.search(rf"""__version__\s*=\s*["']{re.escape(version)}["']""", path.read_text(encoding="utf-8"))
    ]
    assert hits == [PACKAGE_INIT], hits


def test_healthz_body_shape() -> None:
    """四个模块统一：{status, service, version}。"""
    from qf_wire import __version__

    from qf_wire.web.server import _health_body

    assert _health_body(with_generated_at=False) == {
        "status": "ok",
        "service": "quota-fuse-wire",
        "version": __version__,
    }
