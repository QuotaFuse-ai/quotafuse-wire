"""看板「AI 与生成」页的配置读写：写入 .env.local、校验、密钥掩码。"""
from __future__ import annotations

from pathlib import Path

import pytest

from qf_wire.config.ai import (
    env_file_path,
    mask_key,
    read_ai_settings,
    resolve_provider,
    save_ai_settings,
)
from qf_wire.config.loader import load_config
from qf_wire.core.errors import ParamError
from tests.fixtures.configs import write_config

ENV_KEYS = (
    "QF_WIRE_ENV_FILE",
    "QF_WIRE_DIGEST_PROVIDER",
    "QF_WIRE_DIGEST_MODEL",
    "QF_WIRE_API_BASE",
    "QF_WIRE_API_KEY",
    "QF_WIRE_API_KEY_ENV",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
)


@pytest.fixture
def ai_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_env):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    env_file = tmp_path / ".env.local"
    monkeypatch.setenv("QF_WIRE_ENV_FILE", str(env_file))
    config_dir = write_config(tmp_path)
    config = load_config(config_dir, tmp_path / "data")
    return config, env_file


def test_env_file_path_follows_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QF_WIRE_ENV_FILE", str(tmp_path / "custom.env"))
    assert env_file_path() == tmp_path / "custom.env"


def test_mask_key_never_returns_plain_secret() -> None:
    assert mask_key("") == ""
    assert mask_key("short") == "*****"
    assert mask_key("sk-abcdefghijklmn") == "sk-…klmn"


def test_resolve_provider_auto_prefers_api_when_key_present() -> None:
    assert resolve_provider("auto", None, "sk-x") == "api"
    assert resolve_provider("auto", None, None) == "claude-cli"


def test_save_api_settings_writes_env_local(ai_env) -> None:
    config, env_file = ai_env

    settings = save_ai_settings(
        config,
        provider="api",
        api_base="https://api.example.com/",
        api_key="sk-secret-value",
        model="gpt-4o-mini",
    )

    text = env_file.read_text(encoding="utf-8")
    assert "QF_WIRE_DIGEST_PROVIDER=api" in text
    assert "QF_WIRE_API_BASE=https://api.example.com/v1" in text
    assert "QF_WIRE_DIGEST_MODEL=gpt-4o-mini" in text
    assert "QF_WIRE_API_KEY=sk-secret-value" in text
    assert settings.configured is True
    assert settings.key_hint == "sk-…alue"
    assert "sk-secret-value" not in str(settings.as_dict())


def test_saved_settings_visible_after_reload(ai_env) -> None:
    config, _ = ai_env
    save_ai_settings(
        config,
        provider="api",
        api_base="https://api.example.com/v1",
        api_key="sk-secret-value",
        model="gpt-4o-mini",
    )

    reloaded = load_config(config.paths.config_dir, config.paths.data_dir)
    settings = read_ai_settings(reloaded)

    assert settings.provider == "api"
    assert settings.api_base == "https://api.example.com/v1"
    assert settings.model == "gpt-4o-mini"
    assert settings.has_key is True
    assert settings.configured is True


def test_save_requires_key_for_api_provider(ai_env) -> None:
    config, env_file = ai_env

    with pytest.raises(ParamError):
        save_ai_settings(config, provider="api", api_base="https://api.example.com", api_key="", model="gpt-4o-mini")
    assert not env_file.exists()


def test_save_rejects_placeholder_model(ai_env) -> None:
    config, _ = ai_env

    with pytest.raises(ParamError):
        save_ai_settings(config, provider="api", api_base="https://api.example.com", api_key="sk-x", model="user-model")


def test_claude_cli_needs_no_key(ai_env) -> None:
    config, _ = ai_env

    settings = save_ai_settings(config, provider="claude-cli", api_base="", api_key="", model="")

    assert settings.configured is True
    assert read_ai_settings(config).configured is True


def test_save_rejects_unknown_provider(ai_env) -> None:
    config, _ = ai_env

    with pytest.raises(ParamError):
        save_ai_settings(config, provider="openai", api_base="", api_key="", model="")
