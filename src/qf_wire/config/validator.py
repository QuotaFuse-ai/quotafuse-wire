"""配置校验：JSON Schema + 引用完整性 + 提示词与 cron 检查。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft7Validator

from qf_wire.config.loader import CONFIG_FILES, _read_yaml, resolve_paths

PACKAGE_DIR = Path(__file__).resolve().parents[1]
SCHEMA_DIR = PACKAGE_DIR / "schema"
BUNDLED_PROMPTS_DIR = PACKAGE_DIR / "prompts"


@dataclass(slots=True)
class ValidationIssue:
    level: str
    file: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"level": self.level, "file": self.file, "path": self.path, "message": self.message}


@dataclass(slots=True)
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.level == "error" for issue in self.issues)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.level == "error"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": len(self.errors),
            "warnings": len(self.issues) - len(self.errors),
            "issues": [issue.as_dict() for issue in self.issues],
        }


def schema_path(name: str, schema_dir: Path | None = None) -> Path:
    return (schema_dir or SCHEMA_DIR) / f"{name}.schema.json"


def validate_config_dir(config_dir: str | Path, schema_dir: Path | None = None) -> ValidationReport:
    paths = resolve_paths(config_dir=config_dir)
    report = ValidationReport()
    resolved_schema_dir = schema_dir or (paths.config_dir / "schema")
    if not resolved_schema_dir.is_dir():
        resolved_schema_dir = schema_dir or SCHEMA_DIR

    documents: dict[str, dict[str, Any]] = {}
    for name in ("topics", "sources", "digest"):
        file_path = paths.config_dir / CONFIG_FILES[name]
        try:
            document = _read_yaml(file_path)
        except Exception as exc:  # loader 抛 ConfigError，统一转成校验问题
            report.issues.append(ValidationIssue("error", file_path.name, "", str(exc)))
            continue
        documents[name] = document
        schema_file = schema_path(name, resolved_schema_dir)
        if not schema_file.exists():
            report.issues.append(
                ValidationIssue("error", schema_file.name, "", f"缺少 schema 文件: {schema_file}")
            )
            continue
        schema = yaml.safe_load(schema_file.read_text(encoding="utf-8"))
        validator = Draft7Validator(schema)
        for error in sorted(validator.iter_errors(document), key=lambda item: list(item.path)):
            path = "/".join(str(part) for part in error.absolute_path)
            report.issues.append(
                ValidationIssue("error", file_path.name, path, error.message)
            )

    _check_references(documents, paths.prompts_dir, paths.root, report)
    _check_schedule(paths.config_dir / CONFIG_FILES["schedule"], report)
    report.issues.sort(key=lambda issue: (issue.level != "error", issue.file, issue.path))
    return report


def _check_references(
    documents: dict[str, dict[str, Any]],
    prompts_dir: Path,
    root: Path,
    report: ValidationReport,
) -> None:
    topics_raw = documents.get("topics", {}).get("topics") or []
    sources_raw = documents.get("sources", {}).get("sources") or []
    digest_raw = (documents.get("digest", {}).get("digest") or {}) if "digest" in documents else {}

    topic_ids = [item.get("id") for item in topics_raw if isinstance(item, dict)]
    source_ids = [item.get("id") for item in sources_raw if isinstance(item, dict)]
    _check_duplicates(topic_ids, "topics.yaml", "topics", report)
    _check_duplicates(source_ids, "sources.yaml", "sources", report)

    known_sources = set(source_ids)
    known_topics = set(topic_ids)
    for topic in topics_raw:
        if not isinstance(topic, dict):
            continue
        for source_id in topic.get("sources") or []:
            if source_id not in known_sources:
                report.issues.append(
                    ValidationIssue(
                        "error",
                        "topics.yaml",
                        f"topics/{topic.get('id')}/sources",
                        f"引用了不存在的信源: {source_id}",
                    )
                )
    for source in sources_raw:
        if not isinstance(source, dict):
            continue
        topic_id = source.get("topic")
        if topic_id and topic_id not in known_topics:
            report.issues.append(
                ValidationIssue(
                    "warning",
                    "sources.yaml",
                    f"sources/{source.get('id')}/topic",
                    f"信源 topic 未在 topics.yaml 中定义: {topic_id}",
                )
            )

    for topic_id, settings in (digest_raw.get("topics") or {}).items():
        if not isinstance(settings, dict):
            continue
        prompt_file = settings.get("prompt_file")
        if not prompt_file:
            continue
        candidates = [
            root / prompt_file,
            prompts_dir / Path(prompt_file).name,
            BUNDLED_PROMPTS_DIR / Path(prompt_file).name,
        ]
        if not any(candidate.exists() for candidate in candidates):
            report.issues.append(
                ValidationIssue(
                    "error",
                    "digest.yaml",
                    f"digest/topics/{topic_id}/prompt_file",
                    f"提示词文件不存在: {prompt_file}",
                )
            )
    if topic_ids and "default" not in (digest_raw.get("topics") or {}):
        report.issues.append(
            ValidationIssue(
                "warning",
                "digest.yaml",
                "digest/topics",
                "未配置 default 提炼策略，未覆盖的赛道将回落到内置默认值",
            )
        )


def _check_duplicates(ids: list[Any], file_name: str, path: str, report: ValidationReport) -> None:
    seen: set[Any] = set()
    for value in ids:
        if value in seen:
            report.issues.append(
                ValidationIssue("error", file_name, path, f"重复 id: {value}")
            )
        seen.add(value)


def _check_schedule(path: Path, report: ValidationReport) -> None:
    if not path.exists():
        return
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        report.issues.append(ValidationIssue("error", path.name, "", f"YAML 解析失败: {exc}"))
        return
    if not isinstance(document, dict):
        report.issues.append(ValidationIssue("error", path.name, "", "顶层必须是对象"))
        return
    schedule = document.get("schedule") or {}
    if not isinstance(schedule, dict):
        report.issues.append(ValidationIssue("error", path.name, "schedule", "必须是对象"))
        return
    jobs = schedule.get("jobs") or []
    seen: set[str] = set()
    for job in jobs:
        if not isinstance(job, dict):
            report.issues.append(ValidationIssue("error", path.name, "schedule/jobs", "任务必须是对象"))
            continue
        job_id = str(job.get("id") or "")
        if job_id in seen:
            report.issues.append(
                ValidationIssue("error", path.name, "schedule/jobs", f"重复任务 id: {job_id}")
            )
        seen.add(job_id)
        cron = str(job.get("cron") or "").strip()
        if len(cron.split()) != 5:
            report.issues.append(
                ValidationIssue(
                    "error",
                    path.name,
                    f"schedule/jobs/{job_id}/cron",
                    f"cron 需要 5 个字段: {cron or '(空)'}",
                )
            )
