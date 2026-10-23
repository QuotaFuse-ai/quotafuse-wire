"""多用户隔离：目录布局与非法用户 id 拒绝。"""
from __future__ import annotations

import shutil

import pytest

from qf_wire.config.loader import load_config, resolve_paths
from qf_wire.core.errors import ConfigError
from tests.fixtures.configs import write_config

ENV_NAMES = (
    "QF_WIRE_MULTIUSER",
    "QF_WIRE_USER",
    "QF_WIRE_CONFIG_DIR",
    "QF_WIRE_DATA_DIR",
    "QF_WIRE_PROMPTS_DIR",
    "QF_WIRE_ROOT",
)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, isolated_env) -> pytest.MonkeyPatch:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_disabled_ignores_user_argument(env, tmp_path) -> None:
    config_dir = write_config(tmp_path)

    paths = resolve_paths(config_dir, tmp_path / "data", user="alice")

    assert paths.user == ""
    assert paths.data_dir == (tmp_path / "data").resolve()
    assert paths.db_path == (tmp_path / "data" / "wire.db").resolve()
    assert paths.config_dir == config_dir.resolve()


def test_enabled_uses_per_user_data_dir(env, tmp_path) -> None:
    config_dir = write_config(tmp_path)
    env.setenv("QF_WIRE_MULTIUSER", "true")

    alice = resolve_paths(config_dir, tmp_path / "data", user="alice")
    bob = resolve_paths(config_dir, tmp_path / "data", user="bob")

    assert alice.user == "alice"
    assert alice.data_dir == (tmp_path / "data" / "users" / "alice").resolve()
    assert bob.data_dir == (tmp_path / "data" / "users" / "bob").resolve()
    assert alice.db_path != bob.db_path
    # 基础配置与提示词共用，数据互不可见
    assert alice.config_dir == config_dir.resolve()
    assert alice.prompts_dir == (tmp_path / "prompts").resolve()


def test_enabled_reads_user_from_env(env, tmp_path) -> None:
    config_dir = write_config(tmp_path)
    env.setenv("QF_WIRE_MULTIUSER", "true")
    env.setenv("QF_WIRE_USER", "carol")

    paths = resolve_paths(config_dir, tmp_path / "data")

    assert paths.user == "carol"
    assert paths.data_dir == (tmp_path / "data" / "users" / "carol").resolve()


def test_enabled_requires_user(env, tmp_path) -> None:
    env.setenv("QF_WIRE_MULTIUSER", "true")
    with pytest.raises(ConfigError, match="QF_WIRE_USER"):
        resolve_paths(tmp_path / "config", tmp_path / "data")


@pytest.mark.parametrize(
    "user",
    ["../outside", "a/b", "..", "a b", "alice/../bob", "x" * 65, "\u4e2d\u6587"],
)
def test_rejects_unsafe_user_ids(env, tmp_path, user: str) -> None:
    env.setenv("QF_WIRE_MULTIUSER", "true")
    with pytest.raises(ConfigError):
        resolve_paths(tmp_path / "config", tmp_path / "data", user=user)
    # 不让非法 id 落到 user 目录之外
    assert not (tmp_path / "outside").exists()


def test_user_config_dir_wins_when_complete(env, tmp_path) -> None:
    config_dir = write_config(tmp_path)
    user_config = tmp_path / "data" / "users" / "alice" / "config"
    shutil.copytree(config_dir, user_config)
    env.setenv("QF_WIRE_MULTIUSER", "true")

    paths = resolve_paths(config_dir, tmp_path / "data", user="alice")
    config = load_config(config_dir, tmp_path / "data", user="alice")

    assert paths.config_dir == user_config.resolve()
    assert config.paths.config_dir == user_config.resolve()
    assert config.paths.db_path == (tmp_path / "data" / "users" / "alice" / "wire.db").resolve()
    assert config.paths.base_config_dir == config_dir.resolve()


def test_incomplete_user_config_is_ignored(env, tmp_path) -> None:
    config_dir = write_config(tmp_path)
    user_config = tmp_path / "data" / "users" / "alice" / "config"
    user_config.mkdir(parents=True)
    shutil.copy(config_dir / "topics.yaml", user_config / "topics.yaml")
    env.setenv("QF_WIRE_MULTIUSER", "true")

    paths = resolve_paths(config_dir, tmp_path / "data", user="alice")

    assert paths.config_dir == config_dir.resolve()


def test_user_archive_and_data_js_stay_inside_user_dir(env, tmp_path) -> None:
    config_dir = write_config(tmp_path)
    env.setenv("QF_WIRE_MULTIUSER", "true")

    paths = resolve_paths(config_dir, tmp_path / "data", user="alice")

    assert paths.archive_dir == (tmp_path / "data" / "users" / "alice" / "archive").resolve()
    assert paths.data_js == (tmp_path / "data" / "users" / "alice" / "data.js").resolve()
