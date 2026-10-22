"""AI 提炼设置的读写。

看板「AI 与生成」页和 CLI 共用同一份配置：写入仓库根目录的 .env.local
（已被 .gitignore 忽略），接口只返回密钥掩码，不返回明文。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from qf_wire.config.dotenv import (
    ENV_OVERRIDE,
    LOCAL_FILENAME,
    find_dotenv,
    first_env,
    write_env_file,
)
from qf_wire.config.loader import WireConfig
from qf_wire.core.errors import ParamError

PROVIDERS = ("api", "claude-cli")
DEFAULT_BASE = "https://api.openai.com/v1"
MODEL_SENTINELS = frozenset({"", "user-model"})


@dataclass(slots=True)
class AISettings:
    provider: str
    api_base: str
    model: str
    env_file: str
    has_key: bool = False
    key_hint: str = ""
    configured: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "apiBase": self.api_base,
            "model": self.model,
            "envFile": self.env_file,
            "hasKey": self.has_key,
            "keyHint": self.key_hint,
            "configured": self.configured,
        }


def env_file_path() -> Path:
    """页面设置写到哪里：沿用 CLI 的 .env 查找规则，写到同目录的 .env.local。"""
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        return Path(override).expanduser()
    found = find_dotenv()
    return (found.parent if found is not None else Path.cwd()) / LOCAL_FILENAME


def mask_key(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:3]}…{value[-4:]}"


def resolve_provider(provider: str, api_base: str | None, key: str | None) -> str:
    if provider == "auto":
        return "api" if (key or api_base) else "claude-cli"
    return provider or "api"


def read_ai_settings(config: WireConfig) -> AISettings:
    digest = config.digest
    key = first_env(digest.api_key_env, "LLM_API_KEY", "OPENAI_API_KEY") or ""
    provider = resolve_provider(digest.provider, digest.api_base, key)
    model = "" if digest.default_model.strip() in MODEL_SENTINELS else digest.default_model.strip()
    api_base = (digest.api_base or "").strip()
    configured = bool(key and api_base and model) if provider == "api" else True
    return AISettings(
        provider=provider,
        api_base=api_base,
        model=model,
        env_file=LOCAL_FILENAME,
        has_key=bool(key),
        key_hint=mask_key(key),
        configured=configured,
    )


def save_ai_settings(
    config: WireConfig,
    *,
    provider: str | None,
    api_base: str | None,
    api_key: str | None,
    model: str | None,
) -> AISettings:
    """校验并写入 .env.local，同时更新当前进程的环境变量。"""
    provider_value = (provider or "api").strip()
    if provider_value not in PROVIDERS:
        raise ParamError(f"provider 只支持 {', '.join(PROVIDERS)}")
    base_value = (api_base or "").strip().rstrip("/")
    if base_value and not urlparse(base_value).path.strip("/"):
        base_value += "/v1"
    model_value = (model or "").strip()
    key_value = (api_key or "").strip()

    for label, value in (("接口地址", base_value), ("模型名", model_value), ("API Key", key_value)):
        if "\n" in value or "\r" in value or '"' in value:
            raise ParamError(f"{label}不能包含换行或双引号")

    key_var = config.digest.api_key_env or "QF_WIRE_API_KEY"
    existing_key = first_env(key_var, "LLM_API_KEY", "OPENAI_API_KEY") or ""
    effective_key = key_value or existing_key

    if provider_value == "api":
        if model_value in MODEL_SENTINELS:
            raise ParamError("请填写真实模型名，例如 gpt-4o-mini")
        if not base_value.startswith(("http://", "https://")):
            raise ParamError("接口地址需要以 http:// 或 https:// 开头，例如 " + DEFAULT_BASE)
        if not effective_key:
            raise ParamError("请填写 API Key")
    elif model_value in MODEL_SENTINELS:
        model_value = ""

    values = {
        "QF_WIRE_DIGEST_PROVIDER": provider_value,
        "QF_WIRE_API_BASE": base_value,
        "QF_WIRE_DIGEST_MODEL": model_value,
    }
    if key_value:
        values[key_var] = key_value

    write_env_file(env_file_path(), values)
    for name, value in values.items():
        if value:
            os.environ[name] = value
        else:
            os.environ.pop(name, None)

    return AISettings(
        provider=provider_value,
        api_base=base_value,
        model=model_value,
        env_file=LOCAL_FILENAME,
        has_key=bool(effective_key),
        key_hint=mask_key(effective_key),
        configured=(provider_value != "api") or bool(effective_key and base_value and model_value),
    )
