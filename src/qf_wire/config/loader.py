"""配置加载：topics.yaml / sources.yaml / digest.yaml / schedule.yaml。

所有路径都可以通过环境变量覆盖，默认以仓库根目录为基准：
    QF_WIRE_CONFIG_DIR  配置目录（默认 <root>/config）
    QF_WIRE_DATA_DIR    数据目录（默认 <root>/data）
    QF_WIRE_PROMPTS_DIR 提示词目录（默认 <config>/../prompts）
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from qf_wire.core.errors import ConfigError, ParamError
from qf_wire.core.models import Source, Topic

CONFIG_FILES = {
    "topics": "topics.yaml",
    "sources": "sources.yaml",
    "digest": "digest.yaml",
    "schedule": "schedule.yaml",
}


@dataclass(slots=True)
class Paths:
    root: Path
    config_dir: Path
    data_dir: Path
    prompts_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "wire.db"

    @property
    def archive_dir(self) -> Path:
        return self.data_dir / "archive"

    @property
    def data_js(self) -> Path:
        return self.data_dir / "data.js"

    def ensure(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)


@dataclass(slots=True)
class DigestSettings:
    provider: str = "claude-cli"
    default_model: str = "user-model"
    language: str = "zh"
    max_items: int = 12
    timeout_sec: int = 180
    retries: int = 2
    output_schema: str = "TopicDigest"
    topics: dict[str, dict[str, Any]] = field(default_factory=dict)
    api_base: str | None = None
    api_key_env: str = "QF_WIRE_API_KEY"
    gateway_base_url: str | None = None
    gateway_api_key_env: str = "QF_WIRE_MODEL_GATEWAY_KEY"

    def for_topic(self, topic_id: str) -> dict[str, Any]:
        """合并 default 与赛道专属配置。"""
        merged = dict(self.topics.get("default", {}))
        merged.update(self.topics.get(topic_id, {}))
        merged.setdefault("prompt_file", "prompts/default.md")
        merged.setdefault("output_schema", self.output_schema)
        merged.setdefault("model", self.default_model)
        return merged


@dataclass(slots=True)
class WireConfig:
    paths: Paths
    topics: list[Topic]
    sources: list[Source]
    digest: DigestSettings
    schedule: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    # ---- 查询 ----
    def topic(self, name: str | None) -> Topic:
        if not name:
            raise ParamError("缺少赛道")
        target = name.strip().lower()
        for topic in self.topics:
            if target in topic.all_names():
                return topic
        known = ", ".join(t.id for t in self.topics)
        raise ParamError(f"未知赛道: {name}（可用: {known}）")

    def find_topic(self, name: str | None) -> Topic | None:
        try:
            return self.topic(name)
        except ParamError:
            return None

    def source(self, source_id: str) -> Source:
        for source in self.sources:
            if source.id == source_id:
                return source
        raise ConfigError(f"topics.yaml 引用了不存在的信源: {source_id}")

    def sources_for(self, topic: Topic, include_disabled: bool = False) -> list[Source]:
        result = []
        for source_id in topic.sources:
            source = self.source(source_id)
            if source.enabled or include_disabled:
                result.append(source)
        return result

    def enabled_sources(self) -> list[Source]:
        return [source for source in self.sources if source.enabled]

    def prompt_path(self, topic_id: str) -> Path:
        settings = self.digest.for_topic(topic_id)
        relative = str(settings.get("prompt_file") or "prompts/default.md")
        candidate = Path(relative)
        if candidate.is_absolute():
            return candidate
        direct = self.paths.root / candidate
        if direct.exists():
            return direct
        return self.paths.prompts_dir / candidate.name

    def read_prompt(self, topic_id: str) -> str:
        path = self.prompt_path(topic_id)
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"无法读取提示词文件 {path}: {exc}") from exc


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"缺少配置文件: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML 解析失败 {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件 {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"配置文件顶层必须是对象: {path}")
    return data


def _resolve_root() -> Path:
    env_root = os.environ.get("QF_WIRE_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    cwd = Path.cwd()
    if (cwd / "config" / "topics.yaml").is_file():
        return cwd
    package_root = Path(__file__).resolve().parents[3]
    if (package_root / "config" / "topics.yaml").is_file():
        return package_root
    for parent in cwd.parents:
        if (parent / "config" / "topics.yaml").is_file():
            return parent
    return package_root


def resolve_paths(config_dir: str | Path | None = None, data_dir: str | Path | None = None) -> Paths:
    root = _resolve_root()
    config = Path(config_dir or os.environ.get("QF_WIRE_CONFIG_DIR") or root / "config").expanduser().resolve()
    data = Path(data_dir or os.environ.get("QF_WIRE_DATA_DIR") or root / "data").expanduser().resolve()
    prompts_env = os.environ.get("QF_WIRE_PROMPTS_DIR")
    if prompts_env:
        prompts = Path(prompts_env).expanduser().resolve()
    else:
        prompts = config.parent / "prompts"
        if not prompts.is_dir():
            prompts = root / "prompts"
    return Paths(root=root, config_dir=config, data_dir=data, prompts_dir=prompts)


def _parse_sources(raw: dict[str, Any]) -> list[Source]:
    defaults = raw.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ConfigError("sources.yaml defaults 必须是对象")
    entries = raw.get("sources")
    if not isinstance(entries, list) or not entries:
        raise ConfigError("sources.yaml 缺少 sources 列表")
    sources: list[Source] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ConfigError(f"sources.yaml 第 {index + 1} 项必须是对象")
        merged = {**defaults, **entry}
        try:
            source = Source.model_validate(merged)
        except ValidationError as exc:
            label = entry.get("id", f"index {index}")
            raise ConfigError(f"信源 {label} 配置无效: {_format_validation(exc)}") from exc
        if source.id in seen:
            raise ConfigError(f"sources.yaml 存在重复信源 id: {source.id}")
        seen.add(source.id)
        sources.append(source)
    return sources


def _parse_topics(raw: dict[str, Any]) -> list[Topic]:
    entries = raw.get("topics")
    if not isinstance(entries, list) or not entries:
        raise ConfigError("topics.yaml 缺少 topics 列表")
    topics: list[Topic] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ConfigError(f"topics.yaml 第 {index + 1} 项必须是对象")
        try:
            topic = Topic.model_validate(entry)
        except ValidationError as exc:
            label = entry.get("id", f"index {index}")
            raise ConfigError(f"赛道 {label} 配置无效: {_format_validation(exc)}") from exc
        if topic.id in seen:
            raise ConfigError(f"topics.yaml 存在重复赛道 id: {topic.id}")
        seen.add(topic.id)
        topics.append(topic)
    return topics


def _parse_digest(raw: dict[str, Any]) -> DigestSettings:
    data = raw.get("digest")
    if not isinstance(data, dict):
        raise ConfigError("digest.yaml 缺少 digest 配置")
    topics = data.get("topics") or {}
    if not isinstance(topics, dict):
        raise ConfigError("digest.yaml digest.topics 必须是对象")
    gateway = data.get("gateway") or {}
    if not isinstance(gateway, dict):
        raise ConfigError("digest.yaml digest.gateway 必须是对象")
    try:
        return DigestSettings(
            provider=str(data.get("provider") or "claude-cli"),
            default_model=str(data.get("default_model") or "user-model"),
            language=str(data.get("language") or "zh"),
            max_items=int(data.get("max_items_per_topic") or 12),
            timeout_sec=int(data.get("timeout_sec") or 180),
            retries=int(data.get("retries") or 0),
            output_schema=str(data.get("output_schema") or "TopicDigest"),
            topics={str(key): dict(value) for key, value in topics.items() if isinstance(value, dict)},
            api_base=data.get("api_base"),
            api_key_env=str(data.get("api_key_env") or "QF_WIRE_API_KEY"),
            gateway_base_url=_expand_env(gateway.get("base_url")),
            gateway_api_key_env=str(gateway.get("api_key_env") or "QF_WIRE_MODEL_GATEWAY_KEY"),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"digest.yaml 配置无效: {exc}") from exc


_ENV_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value: Any) -> str | None:
    """展开 ``${VAR}``；变量未设置时保留占位符，由调用方报“未配置”。"""
    if value is None:
        return None
    return _ENV_PLACEHOLDER.sub(
        lambda match: os.environ.get(match.group(1), match.group(0)),
        str(value),
    )


def _format_validation(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error.get("loc", ()))
        parts.append(f"{location}: {error.get('msg')}")
    return "; ".join(parts)


def load_config(config_dir: str | Path | None = None, data_dir: str | Path | None = None) -> WireConfig:
    """加载并解析全部配置；结构问题抛 ConfigError。"""
    paths = resolve_paths(config_dir, data_dir)
    raw_topics = _read_yaml(paths.config_dir / CONFIG_FILES["topics"])
    raw_sources = _read_yaml(paths.config_dir / CONFIG_FILES["sources"])
    raw_digest = _read_yaml(paths.config_dir / CONFIG_FILES["digest"])
    raw_schedule: dict[str, Any] = {}
    schedule_path = paths.config_dir / CONFIG_FILES["schedule"]
    if schedule_path.exists():
        raw_schedule = _read_yaml(schedule_path)

    topics = _parse_topics(raw_topics)
    sources = _parse_sources(raw_sources)
    source_ids = {source.id for source in sources}
    for topic in topics:
        missing = [item for item in topic.sources if item not in source_ids]
        if missing:
            raise ConfigError(f"赛道 {topic.id} 引用了不存在的信源: {', '.join(missing)}")

    return WireConfig(
        paths=paths,
        topics=topics,
        sources=sources,
        digest=_parse_digest(raw_digest),
        schedule=raw_schedule.get("schedule") or {},
        raw={"topics": raw_topics, "sources": raw_sources, "digest": raw_digest, "schedule": raw_schedule},
    )
