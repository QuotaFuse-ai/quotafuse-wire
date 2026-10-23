"""打包回归：wheel 必须携带运行期依赖的数据文件。

QUOT-43 实测 wheel 只包含 `qf_wire/web/static/*`，导致干净安装后：
- `storage/migrations/*.sql` 缺失 → run 报 `no such table: source_scores`；
- `config/schema/*.schema.json` 在包外 → config validate 报缺少 schema；
- `prompts/*.md` 未打包 → 提炼无法读取提示词。
"""
from __future__ import annotations

import fnmatch
from pathlib import Path

import pytest

import qf_wire
from qf_wire import __version__
from qf_wire.config.validator import SCHEMA_DIR

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = Path(qf_wire.__file__).resolve().parent


def _package_data_patterns() -> list[str]:
    tomllib = pytest.importorskip("tomllib")
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return list(data["tool"]["setuptools"]["package-data"]["qf_wire"])


def test_version_is_set():
    assert __version__


def test_package_data_includes_sql_migrations() -> None:
    patterns = _package_data_patterns()
    migrations = sorted((REPO_ROOT / "src" / "qf_wire" / "storage" / "migrations").glob("*.sql"))

    assert migrations
    for path in migrations:
        relative = path.relative_to(REPO_ROOT / "src" / "qf_wire").as_posix()
        assert any(fnmatch.fnmatch(relative, pattern) for pattern in patterns), relative


def test_prompts_live_inside_package() -> None:
    prompts = sorted((REPO_ROOT / "prompts").glob("*.md"))
    packaged = PACKAGE_ROOT / "prompts"

    assert prompts
    assert packaged.is_dir()
    assert sorted(packaged.glob("*.md"))


def test_schema_lives_inside_package() -> None:
    resolved = SCHEMA_DIR.resolve()
    assert PACKAGE_ROOT in resolved.parents
    assert sorted(resolved.glob("*.schema.json"))
