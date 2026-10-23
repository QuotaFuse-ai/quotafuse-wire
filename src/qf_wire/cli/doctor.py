"""qfw doctor：部署自检——配置、数据目录、模型通道与连通性。"""
from __future__ import annotations

import shutil
import sqlite3
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

import typer

from qf_wire.cli.context import AppContext, emit_json, emit_mapping, emit_rows
from qf_wire.config.ai import read_ai_settings
from qf_wire.config.loader import WireConfig
from qf_wire.config.validator import validate_config_dir
from qf_wire.core.errors import EXIT_CONFIG, EXIT_OK, EXIT_UNAVAILABLE, ConfigError

STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"

KIND_CONFIG = "config"
KIND_RUNTIME = "runtime"

DOCTOR_COLUMNS = [
    ("check", "检查项"),
    ("status", "状态"),
    ("detail", "详情"),
]

_PROBE_TIMEOUT = 5.0


@dataclass(slots=True)
class Check:
    name: str
    status: str
    detail: str
    kind: str = KIND_RUNTIME

    def as_dict(self) -> dict[str, str]:
        return {"check": self.name, "status": self.status, "detail": self.detail}


def _config_check(name: str, status: str, detail: str) -> Check:
    return Check(name, status, detail, KIND_CONFIG)


def _check_config_files(config: WireConfig) -> list[Check]:
    paths = config.paths
    return [
        Check(
            "config.files",
            STATUS_OK,
            f"{paths.config_dir}（{len(config.topics)} 个赛道 / {len(config.sources)} 个信源）",
        )
    ]


def _check_config_valid(config: WireConfig) -> Check:
    report = validate_config_dir(config.paths.config_dir)
    errors = report.errors
    warnings = report.issues
    if errors:
        first = "; ".join(f"{issue.file}:{issue.path} {issue.message}" for issue in errors[:3])
        more = f"（另有 {len(errors) - 3} 项）" if len(errors) > 3 else ""
        return _config_check(
            "config.validate",
            STATUS_FAIL,
            f"{len(errors)} 个错误 / {len(warnings) - len(errors)} 个警告：{first}{more}",
        )
    if warnings:
        return _config_check(
            "config.validate",
            STATUS_WARN,
            f"通过，但有 {len(warnings)} 个警告",
        )
    return Check("config.validate", STATUS_OK, "schema 与引用完整")


def _check_prompts(config: WireConfig) -> Check:
    missing = [
        f"{topic.id}:{config.prompt_path(topic.id)}"
        for topic in config.topics
        if not config.prompt_path(topic.id).is_file()
    ]
    if missing:
        return _config_check(
            "config.prompts",
            STATUS_FAIL,
            "缺少提示词：" + "; ".join(missing[:3]),
        )
    return Check("config.prompts", STATUS_OK, f"{len(config.topics)} 个赛道提示词就绪")


def _check_data_dir(config: WireConfig) -> Check:
    paths = config.paths
    try:
        paths.ensure()
        probe = paths.data_dir / ".doctor-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return Check("data.dir", STATUS_FAIL, f"{paths.data_dir} 不可写：{exc}")
    return Check("data.dir", STATUS_OK, f"{paths.data_dir} 可写，归档 {paths.archive_dir}")


def _check_database(config: WireConfig) -> Check:
    db_path = config.paths.db_path
    if not db_path.is_file():
        return Check("data.sqlite", STATUS_WARN, f"{db_path} 不存在，先运行 qfw run")
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        try:
            result = conn.execute("PRAGMA quick_check").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return Check("data.sqlite", STATUS_FAIL, f"无法读取 {db_path}：{exc}")
    if not result or result[0] != "ok":
        return Check("data.sqlite", STATUS_FAIL, f"完整性检查未通过：{result[0] if result else '无结果'}")
    return Check("data.sqlite", STATUS_OK, f"{db_path} 可读，完整性检查通过")


def _probe(base_url: str, key: str | None) -> tuple[bool, str]:
    request = urllib.request.Request(
        base_url.rstrip("/") + "/models",
        headers={"Accept": "application/json", "User-Agent": "qfw-doctor"},
    )
    if key:
        request.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(request, timeout=_PROBE_TIMEOUT) as response:
            return True, f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        # 401/403/404 说明端点可达，只是鉴权或路径不同
        if exc.code in {401, 403, 404, 405}:
            return True, f"可达（HTTP {exc.code}）"
        return False, f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return False, f"连接失败：{reason}"


def _check_model(config: WireConfig, *, network: bool) -> list[Check]:
    settings = read_ai_settings(config)
    provider = settings.provider
    checks: list[Check] = []

    if provider == "api":
        if not settings.configured:
            checks.append(
                _config_check(
                    "model.provider",
                    STATUS_FAIL,
                    "provider=api，但接口地址 / 模型 / API Key 未配置完整",
                )
            )
            return checks
        checks.append(
            Check(
                "model.provider",
                STATUS_OK,
                f"api · {settings.api_base} · {settings.model} · key {settings.key_hint or '(已配置)'}",
            )
        )
        if network and settings.api_base:
            from qf_wire.config.dotenv import first_env

            key = first_env(config.digest.api_key_env, "LLM_API_KEY", "OPENAI_API_KEY")
            reachable, detail = _probe(settings.api_base, key)
            checks.append(
                Check(
                    "model.connect",
                    STATUS_OK if reachable else STATUS_WARN,
                    detail,
                )
            )
        return checks

    if provider == "claude-cli":
        binary = shutil.which("claude")
        checks.append(
            Check(
                "model.provider",
                STATUS_OK if binary else STATUS_WARN,
                f"claude-cli · {binary}" if binary else "未在 PATH 找到 claude CLI；可在看板或 .env.local 改用 api 通道",
            )
        )
        return checks

    if provider == "gateway":
        base = (config.digest.gateway_base_url or "").strip()
        from qf_wire.config.dotenv import first_env

        key = first_env(config.digest.gateway_api_key_env)
        if not base or "${" in base:
            checks.append(
                _config_check(
                    "model.provider",
                    STATUS_WARN,
                    f"provider=gateway，但未设置 {config.digest.gateway_api_key_env} 或网关地址；将回落到 claude-cli",
                )
            )
            return checks
        checks.append(
            Check(
                "model.provider",
                STATUS_OK,
                f"gateway · {base} · key {'已配置' if key else '缺失'}",
            )
        )
        if network:
            reachable, detail = _probe(base, key)
            checks.append(Check("model.connect", STATUS_OK if reachable else STATUS_WARN, detail))
        return checks

    checks.append(_config_check("model.provider", STATUS_FAIL, f"未知 provider: {provider}"))
    return checks


def _run_checks(app_ctx: AppContext, *, network: bool) -> list[Check]:
    checks: list[Check] = []
    try:
        config = app_ctx.config()
    except ConfigError as exc:
        return [_config_check("config.load", STATUS_FAIL, str(exc))]

    checks.append(Check("config.load", STATUS_OK, "topics / sources / digest / schedule 解析通过"))
    checks.extend(_check_config_files(config))
    checks.append(_check_config_valid(config))
    checks.append(_check_prompts(config))
    checks.append(_check_data_dir(config))
    checks.append(_check_database(config))
    checks.extend(_check_model(config, network=network))
    return checks


def _exit_code(checks: list[Check]) -> int:
    failures = [check for check in checks if check.status == STATUS_FAIL]
    if any(check.kind == KIND_CONFIG for check in failures):
        return EXIT_CONFIG
    if failures:
        return EXIT_UNAVAILABLE
    return EXIT_OK


def _payload(checks: list[Check]) -> dict[str, Any]:
    failures = [check for check in checks if check.status == STATUS_FAIL]
    warnings = [check for check in checks if check.status == STATUS_WARN]
    overall = STATUS_FAIL if failures else (STATUS_WARN if warnings else STATUS_OK)
    return {
        "ok": not failures,
        "status": overall,
        "failures": len(failures),
        "warnings": len(warnings),
        "checks": [check.as_dict() for check in checks],
    }


def doctor_command(
    ctx: typer.Context,
    network: bool = typer.Option(True, "--network/--no-network", help="是否探测模型接口连通性"),
) -> int:
    app_ctx: AppContext = ctx.obj
    checks = _run_checks(app_ctx, network=network)
    payload = _payload(checks)

    if app_ctx.output == "json":
        emit_json(payload)
    elif app_ctx.output == "csv":
        emit_rows(payload["checks"], DOCTOR_COLUMNS, "csv")
    else:
        emit_rows(payload["checks"], DOCTOR_COLUMNS, "table")
        emit_mapping(
            {
                "结果": {"ok": "通过", "warn": "通过（有警告）", "fail": "失败"}[payload["status"]],
                "失败": payload["failures"],
                "警告": payload["warnings"],
            },
            "table",
        )
    return _exit_code(checks)
