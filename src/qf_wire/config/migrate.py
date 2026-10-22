"""旧 investment-news 配置到 Wire YAML 的一次性迁移。

规则见 docs/MIGRATION.md：
- sources.json 的行业 → topics.yaml，信源 → sources.yaml；
- llm.config.json → digest.yaml，apiKey 不落盘明文；
- 已有 YAML 只追加缺失条目，绝不覆盖用户内容；
- 以 config/.migrated 标记保证只执行一次。
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from qf_wire.core.errors import ConfigError

MIGRATED_MARKER = ".migrated"
API_KEY_ENV = "QF_WIRE_LLM_API_KEY"

# 旧行业中文键 → 规范 id。未覆盖的键走哈希回退，保证生成结果稳定。
_TOPIC_SLUGS = {
    "半导体": "semiconductor",
    "芯片": "semiconductor",
    "人工智能": "ai",
    "ai": "ai",
    "机器人": "robotics",
    "汽车": "automotive",
    "新能源汽车": "automotive",
    "能源": "energy",
    "生物医药": "biotech",
    "医药": "biotech",
    "航空航天": "aerospace",
    "网络安全": "cybersecurity",
    "科技": "tech",
    "消费": "consumer",
    "宏观": "macro",
    "宏观政策": "macro",
    "科学": "science",
}

_TYPE_ALIASES = {
    "rss": "rss",
    "html": "html",
    "web": "html",
    "webpage": "html",
    "api": "api",
    "json": "api",
}


@dataclass(slots=True)
class MigrationReport:
    lines: list[str] = field(default_factory=list)
    topic_count: int = 0
    source_count: int = 0
    written: list[str] = field(default_factory=list)
    skipped: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "skipped": self.skipped,
            "topic_count": self.topic_count,
            "source_count": self.source_count,
            "written": self.written,
            "lines": self.lines,
        }


def _slugify(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    for chinese, slug in _TOPIC_SLUGS.items():
        if lowered == chinese.lower():
            return slug
    cleaned = "".join(ch if ch.isalnum() and ch.isascii() else "_" for ch in lowered)
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    if cleaned and cleaned[0].isdigit():
        cleaned = f"t_{cleaned}"
    if cleaned:
        return cleaned
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return f"topic_{digest}"


def _unique(candidate: str, taken: set[str]) -> str:
    base = candidate or "source"
    if base not in taken:
        return base
    index = 2
    while f"{base}_{index}" in taken:
        index += 1
    return f"{base}_{index}"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"无法读取旧配置 {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"旧配置文件顶层必须是对象: {path}")
    return data


def _read_yaml_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"无法读取 {path}: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)
    path.write_text(text, encoding="utf-8")


def _industry_entries(raw: dict[str, Any]) -> list[dict[str, Any]]:
    industries = raw.get("industries")
    if isinstance(industries, list):
        return [entry for entry in industries if isinstance(entry, dict)]
    if isinstance(industries, dict):
        return [{"key": key, **(value if isinstance(value, dict) else {})} for key, value in industries.items()]
    return []


def _legacy_sources(industry: dict[str, Any]) -> list[dict[str, Any]]:
    entries = industry.get("sources")
    if isinstance(entries, list):
        return [entry for entry in entries if isinstance(entry, dict)]
    return []


def _build_topics_and_sources(
    sources_raw: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    topics: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    topic_ids: set[str] = set()
    source_ids: set[str] = set()

    for industry in _industry_entries(sources_raw):
        legacy_key = str(industry.get("key") or industry.get("id") or "").strip()
        if not legacy_key:
            continue
        base_id = _slugify(legacy_key)
        topic_id = _unique(base_id, topic_ids)
        topic_ids.add(topic_id)

        raw_sources = _legacy_sources(industry)
        topic_source_ids: list[str] = []
        for index, entry in enumerate(raw_sources, start=1):
            url = str(entry.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            hint = entry.get("hint") or entry.get("id") or entry.get("name")
            candidate = _slugify(str(hint or "")) or f"{topic_id}_{index}"
            source_id = _unique(candidate, source_ids)
            source_ids.add(source_id)
            raw_type = str(entry.get("type") or "rss").strip().lower()
            sources.append(
                {
                    "id": source_id,
                    "name": str(entry.get("name") or hint or source_id),
                    "topic": topic_id,
                    "type": _TYPE_ALIASES.get(raw_type, "rss"),
                    "url": url,
                    "enabled": bool(entry.get("enabled", True)),
                }
            )
            topic_source_ids.append(source_id)

        if not topic_source_ids:
            continue

        name = str(industry.get("name") or legacy_key)
        keywords = industry.get("keywords")
        if not isinstance(keywords, list) or not keywords:
            keywords = [name]
        topic: dict[str, Any] = {
            "id": topic_id,
            "name": name,
            "legacy_key": legacy_key,
            "aliases": [legacy_key] if legacy_key != topic_id else [],
            "keywords": [str(item) for item in keywords],
            "sources": topic_source_ids,
        }
        accent = industry.get("accent")
        if isinstance(accent, str) and accent.startswith("#"):
            topic["accent"] = accent
        topics.append(topic)

    return topics, sources


def _build_digest(llm_raw: dict[str, Any]) -> dict[str, Any]:
    provider = str(llm_raw.get("provider") or "claude-cli").strip().lower()
    if provider not in {"claude-cli", "api", "gateway"}:
        provider = "api" if provider in {"openai", "deepseek", "siliconflow", "openrouter"} else "claude-cli"
    digest: dict[str, Any] = {
        "provider": provider,
        "default_model": str(llm_raw.get("model") or "user-model"),
        "language": "zh",
        "max_items_per_topic": 12,
        "api_key_env": API_KEY_ENV,
        "topics": {
            "default": {
                "prompt_file": "prompts/default.md",
                "output_schema": "TopicDigest",
            }
        },
    }
    base_url = llm_raw.get("baseUrl") or llm_raw.get("base_url") or llm_raw.get("baseURL")
    if base_url:
        digest["api_base"] = str(base_url)
    if llm_raw.get("apiKey"):
        # 明文 key 绝不落盘，只提示用户改走环境变量。
        digest["api_key_env"] = API_KEY_ENV
    return digest


def _merge_by_id(existing: list[Any], additions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = [entry for entry in existing if isinstance(entry, dict)]
    seen = {str(entry.get("id")) for entry in merged}
    for entry in additions:
        if str(entry.get("id")) in seen:
            continue
        seen.add(str(entry.get("id")))
        merged.append(entry)
    return merged


def _make_readonly(path: Path) -> None:
    try:
        os.chmod(path, 0o444)
    except OSError:
        pass


def _legacy_candidates(legacy_dir: Path) -> tuple[Path | None, Path | None]:
    sources = legacy_dir / "sources.json"
    llm = legacy_dir / "llm.config.json"
    return (sources if sources.is_file() else None, llm if llm.is_file() else None)


def migrate_legacy(
    legacy_dir: str | Path,
    config_dir: str | Path | None = None,
    dry_run: bool = False,
) -> MigrationReport:
    """把旧 sources.json / llm.config.json 迁到 config_dir 下的 YAML。

    幂等：config_dir/.migrated 存在时直接跳过；已有 YAML 只追加缺失 id。
    """
    legacy = Path(legacy_dir).expanduser().resolve()
    config = Path(config_dir).expanduser().resolve() if config_dir else legacy / "config"
    report = MigrationReport()

    if not legacy.is_dir():
        raise ConfigError(f"旧仓库目录不存在: {legacy}")
    marker = config / MIGRATED_MARKER
    if marker.is_file():
        report.skipped = True
        report.lines.append(f"已迁移过（{marker}），跳过")
        return report

    sources_path, llm_path = _legacy_candidates(legacy)
    if sources_path is None and llm_path is None:
        report.skipped = True
        report.lines.append(f"未发现旧配置（{legacy}），无需迁移")
        return report

    new_topics: list[dict[str, Any]] = []
    new_sources: list[dict[str, Any]] = []
    if sources_path is not None:
        new_topics, new_sources = _build_topics_and_sources(_read_json(sources_path))
        report.lines.append(f"读取 {sources_path.name}: {len(new_topics)} 个行业 / {len(new_sources)} 个信源")

    digest_data: dict[str, Any] | None = None
    if llm_path is not None:
        llm_raw = _read_json(llm_path)
        digest_data = _build_digest(llm_raw)
        if llm_raw.get("apiKey"):
            report.lines.append(f"apiKey 未写入磁盘，请设置环境变量 {API_KEY_ENV}")
        report.lines.append(f"读取 {llm_path.name}: provider={digest_data.get('provider')}")

    if not dry_run:
        config.mkdir(parents=True, exist_ok=True)

    if new_topics:
        target = config / "topics.yaml"
        current = _read_yaml_file(target)
        merged = _merge_by_id(current.get("topics") or [], new_topics)
        added = len(merged) - len(current.get("topics") or [])
        report.topic_count = added
        if dry_run:
            report.lines.append(f"[dry-run] 将向 {target.name} 追加 {added} 个赛道")
        else:
            _write_yaml(target, {"version": 1, "topics": merged})
            report.written.append(str(target))
            report.lines.append(f"写入 {target.name}: 新增 {added} 个赛道")

    if new_sources:
        target = config / "sources.yaml"
        current = _read_yaml_file(target)
        merged = _merge_by_id(current.get("sources") or [], new_sources)
        added = len(merged) - len(current.get("sources") or [])
        report.source_count = added
        if dry_run:
            report.lines.append(f"[dry-run] 将向 {target.name} 追加 {added} 个信源")
        else:
            payload = dict(current)
            payload.setdefault("version", 1)
            payload.setdefault("defaults", {"timeout_sec": 15, "retries": 2, "weight": 1.0})
            payload["sources"] = merged
            _write_yaml(target, payload)
            report.written.append(str(target))
            report.lines.append(f"写入 {target.name}: 新增 {added} 个信源")

    if digest_data is not None:
        target = config / "digest.yaml"
        if target.is_file():
            report.lines.append(f"{target.name} 已存在，保留用户配置不覆盖")
        elif dry_run:
            report.lines.append(f"[dry-run] 将写入 {target.name}")
        else:
            _write_yaml(target, {"digest": {"version": 1, **digest_data}})
            report.written.append(str(target))
            report.lines.append(f"写入 {target.name}")

    if dry_run:
        report.lines.append("[dry-run] 未修改任何文件")
        return report

    marker.write_text("migrated\n", encoding="utf-8")
    for path in (sources_path, llm_path):
        if path is not None:
            _make_readonly(path)
            report.lines.append(f"{path.name} 保持只读")
    report.lines.append(f"完成，标记文件 {marker}")
    return report


def auto_migrate(search_dirs: list[Path] | None = None, config_dir: str | Path | None = None) -> MigrationReport | None:
    """首次运行时自动迁移；没有旧文件或已迁移时返回 None。"""
    if config_dir is None:
        return None
    config = Path(config_dir).expanduser().resolve()
    if (config / MIGRATED_MARKER).is_file():
        return None
    for directory in search_dirs or []:
        if not directory.is_dir():
            continue
        sources, llm = _legacy_candidates(directory)
        if sources is None and llm is None:
            continue
        try:
            return migrate_legacy(directory, config, dry_run=False)
        except ConfigError:
            return None
    return None
