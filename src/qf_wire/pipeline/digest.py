"""AI 提炼：使用用户自己的模型（Claude CLI 或 OpenAI 兼容 API）。

模型不可用时不中断流程，产出一条 status=partial 的降级结果。
"""
from __future__ import annotations

import json
import locale
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from typing import Any

from qf_wire.config.dotenv import first_env
from qf_wire.config.loader import DigestSettings, WireConfig
from qf_wire.core.cleaner import contains_trading_advice
from qf_wire.core.errors import ConfigError
from qf_wire.core.models import (
    DigestItem,
    KeyPoint,
    SourceItem,
    Topic,
    TopicDigest,
)
from qf_wire.logging.setup import get_logger

logger = get_logger(__name__)

MAX_ERROR_LEN = 240
# `user-model` 是“用用户自己配置的默认模型”的占位符，不能当成真实模型名传给 provider
MODEL_SENTINELS = frozenset({"", "user-model"})
SUPPORTED_SCHEMAS: dict[str, tuple[str, ...]] = {
    "TopicDigest": ("summary", "key_points", "items"),
    "BriefDigest": ("summary", "key_points"),
}


class DigestUnavailable(RuntimeError):
    """模型或 provider 当前不可用。"""


def digest_topic(
    topic: Topic,
    day: date,
    items: list[SourceItem],
    config: WireConfig,
) -> TopicDigest:
    settings = config.digest
    per_topic = settings.for_topic(topic.id)
    schema = str(per_topic.get("output_schema") or settings.output_schema)
    if schema not in SUPPORTED_SCHEMAS:
        raise ConfigError(
            f"赛道 {topic.id} 的 output_schema 不支持: {schema}（可用: {', '.join(SUPPORTED_SCHEMAS)}）"
        )
    selected = items[: settings.max_items]
    base = {
        "topic": topic.id,
        "date": day,
        "provider": settings.provider,
        "model": _resolve_model(settings, per_topic),
    }

    if not selected:
        logger.warning("赛道 %s 无可用条目，跳过提炼", topic.id)
        return TopicDigest(
            **base,
            status="skipped",
            partial=True,
            fallback=True,
            error="无可用条目",
            generated_at=datetime.now(timezone.utc),
        )

    prompt = build_prompt(config, topic, day, selected, schema=schema)
    last_error: str | None = None
    for attempt in range(1, settings.retries + 2):
        try:
            raw = _call_provider(prompt, settings, per_topic)
            payload = extract_json(raw)
            digest = _to_digest(payload, base, selected, schema=schema)
            logger.info("赛道 %s 提炼完成：%d 条要点", topic.id, len(digest.key_points))
            return digest
        except DigestUnavailable as exc:
            last_error = str(exc)
            logger.warning("赛道 %s 提炼失败（第 %d 次）：%s", topic.id, attempt, exc)
            if attempt < settings.retries + 1:
                continue
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            last_error = f"模型输出无法解析: {exc}"
            logger.warning("赛道 %s 模型输出解析失败：%s", topic.id, exc)
            break

    logger.warning("赛道 %s 使用降级输出（模型不可用）", topic.id)
    return _fallback_digest(base, selected, last_error or "模型不可用")


def build_prompt(
    config: WireConfig,
    topic: Topic,
    day: date,
    items: list[SourceItem],
    *,
    schema: str = "TopicDigest",
) -> str:
    template = config.read_prompt(topic.id)
    payload = [
        {
            "title": item.title,
            "url": item.url,
            "source": item.source_id,
            "sources": item.sources or [item.source_id],
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "summary": item.summary,
            "zh": item.zh,
            "event_id": item.event_id,
        }
        for item in items
    ]
    return (
        f"{template.rstrip()}\n\n"
        f"## 输出要求\n\n"
        f"schema: {schema}\n"
        f"fields: {', '.join(SUPPORTED_SCHEMAS[schema])}\n\n"
        f"## 输入\n\n"
        f"topic: {topic.id}\n"
        f"date: {day.isoformat()}\n"
        f"items:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
    )


def _resolve_model(settings: DigestSettings, per_topic: dict[str, Any]) -> str | None:
    """返回真实模型名；赛道占位符回落到 default_model，仍为空时返回 None。"""
    for candidate in (per_topic.get("model"), settings.default_model):
        model = str(candidate or "").strip()
        if model not in MODEL_SENTINELS:
            return model
    return None


def _call_provider(prompt: str, settings: DigestSettings, per_topic: dict[str, Any]) -> str:
    provider = str(per_topic.get("provider") or settings.provider)
    model = _resolve_model(settings, per_topic)
    if provider == "claude-cli":
        return _call_claude_cli(prompt, settings, model)
    if provider == "api":
        if not model:
            raise DigestUnavailable("未配置模型名：请在 digest.yaml 的 default_model 或赛道 model 填写真实模型")
        return _call_openai_compatible(prompt, settings, per_topic, model)
    if provider == "gateway":
        try:
            return _call_gateway(prompt, settings, per_topic, model)
        except DigestUnavailable as exc:
            logger.warning("模型网关不可用，降级 claude-cli：%s", exc)
            return _call_claude_cli(prompt, settings, model)
    raise ConfigError(f"未知提炼 provider: {provider}")


def _call_gateway(
    prompt: str,
    settings: DigestSettings,
    per_topic: dict[str, Any],
    model: str | None,
) -> str:
    base = str(
        per_topic.get("gateway_base_url")
        or settings.gateway_base_url
        or os.environ.get("QF_WIRE_MODEL_GATEWAY_URL")
        or ""
    ).strip()
    if not base or "${" in base:
        raise DigestUnavailable("未配置模型网关地址（digest.yaml gateway.base_url 或 QF_WIRE_MODEL_GATEWAY_URL）")
    key_env = str(per_topic.get("gateway_api_key_env") or settings.gateway_api_key_env)
    key = os.environ.get(key_env)
    if not key:
        raise DigestUnavailable(f"未配置模型网关密钥（环境变量 {key_env}）")
    return _post_chat(base, key, prompt, model, settings.timeout_sec, label="模型网关")


def decode_output(raw: bytes | str | None) -> str:
    """CLI 输出在 Windows 上可能不是 UTF-8，先按 UTF-8 解，失败再按系统编码。"""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    seen: set[str] = set()
    # -X utf8 下系统编码会报 utf-8，所以中文 Windows 的 GBK 输出要单独兜底
    for encoding in ("utf-8", locale.getpreferredencoding(False), "gbk"):
        if not encoding or encoding.lower() in seen:
            continue
        seen.add(encoding.lower())
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _call_claude_cli(prompt: str, settings: DigestSettings, model: str | None = None) -> str:
    binary = os.environ.get("QF_WIRE_CLAUDE_BIN") or shutil.which("claude")
    if not binary:
        raise DigestUnavailable("未找到 claude CLI，可通过 QF_WIRE_CLAUDE_BIN 指定路径")
    command = [binary]
    if model:
        command.extend(["--model", model])
    command.extend(["-p", prompt])
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=settings.timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DigestUnavailable(f"claude CLI 超时（{settings.timeout_sec}s）") from exc
    except OSError as exc:
        raise DigestUnavailable(f"claude CLI 无法执行: {exc}") from exc
    stdout_text = decode_output(completed.stdout).strip()
    stderr_text = decode_output(completed.stderr).strip()
    if completed.returncode != 0:
        detail = (stderr_text or stdout_text)[:MAX_ERROR_LEN]
        raise DigestUnavailable(f"claude CLI 退出码 {completed.returncode}: {detail}")
    output = stdout_text
    if not output:
        raise DigestUnavailable("claude CLI 返回空输出")
    return output


def _call_openai_compatible(
    prompt: str,
    settings: DigestSettings,
    per_topic: dict[str, Any],
    model: str,
) -> str:
    base = (
        per_topic.get("api_base")
        or settings.api_base
        or os.environ.get("QF_WIRE_API_BASE")
        or os.environ.get("OPENAI_BASE_URL")
        or "https://api.openai.com/v1"
    ).rstrip("/")
    key = first_env(settings.api_key_env, "LLM_API_KEY", "OPENAI_API_KEY")
    if not key:
        raise DigestUnavailable(
            f"未配置 API key（环境变量 {settings.api_key_env}、LLM_API_KEY 或 OPENAI_API_KEY）"
        )
    return _post_chat(base, key, prompt, model, settings.timeout_sec, label="模型接口")


def _post_chat(
    base: str,
    key: str,
    prompt: str,
    model: str | None,
    timeout_sec: int,
    *,
    label: str,
) -> str:
    """POST OpenAI 兼容的 chat/completions；错误信息只带状态码，绝不带密钥。"""
    body: dict[str, Any] = {
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    if model:
        body["model"] = model
    request = urllib.request.Request(
        _chat_endpoint(base),
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        raise DigestUnavailable(f"{label} HTTP {exc.code}{_error_detail(exc, key)}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DigestUnavailable(f"{label}不可达: {exc}") from exc
    try:
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DigestUnavailable(f"{label}返回结构不符合预期") from exc


CHAT_SUFFIX = "/chat/completions"


def _chat_endpoint(base: str) -> str:
    """地址里已经写了完整端点时不再重复拼接 /chat/completions。"""
    cleaned = base.strip().rstrip("/")
    if cleaned.endswith(CHAT_SUFFIX):
        return cleaned
    return f"{cleaned}{CHAT_SUFFIX}"


def _error_detail(exc: urllib.error.HTTPError, key: str, limit: int = 160) -> str:
    """附一小段上游原始报错用于定位；密钥一律抹掉。"""
    try:
        raw = exc.read(limit * 8)
    except OSError:
        return ""
    text = " ".join(raw.decode("utf-8", "replace").split())
    if key:
        text = text.replace(key, "***")
    if not text:
        return ""
    return "：" + text[:limit]


def extract_json(text: str) -> dict[str, Any]:
    """从模型输出中提取 JSON，容忍代码块和前后说明文字。"""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        if start < 0:
            raise
        end = _matching_brace(stripped, start)
        if end < 0:
            raise
        value = json.loads(stripped[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("模型输出 JSON 顶层必须是对象")
    return value


def _matching_brace(text: str, start: int) -> int:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _to_digest(
    payload: dict[str, Any],
    base: dict[str, Any],
    selected: list[SourceItem],
    *,
    schema: str = "TopicDigest",
) -> TopicDigest:
    key_points: list[KeyPoint] = []
    for raw in payload.get("key_points") or []:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text or contains_trading_advice(text):
            continue
        key_points.append(
            KeyPoint(
                text=text,
                sources=[str(item) for item in raw.get("sources") or [] if item],
                confidence=raw.get("confidence") if raw.get("confidence") in {"high", "medium", "low"} else "medium",
                event_id=raw.get("event_id") or None,
            )
        )

    items: list[DigestItem] = []
    model_items = payload.get("items") if "items" in SUPPORTED_SCHEMAS[schema] else None
    for raw in model_items or []:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        if not title:
            continue
        items.append(
            DigestItem(
                title=title,
                url=str(raw.get("url") or ""),
                source=str(raw.get("source") or ""),
                zh=str(raw.get("zh") or ""),
                summary=str(raw.get("summary") or ""),
                event_id=raw.get("event_id") or None,
            )
        )
    if not items:
        items = _items_from_sources(selected)

    summary = str(payload.get("summary") or "").strip()
    if contains_trading_advice(summary):
        summary = ""

    return TopicDigest(
        **base,
        summary=summary,
        key_points=key_points,
        items=items,
        generated_at=datetime.now(timezone.utc),
        status="ok",
    )


def _fallback_digest(base: dict[str, Any], selected: list[SourceItem], error: str) -> TopicDigest:
    return TopicDigest(
        **base,
        summary=f"共采集 {len(selected)} 条资讯；模型当前不可用，未生成要点。",
        key_points=[],
        items=_items_from_sources(selected),
        generated_at=datetime.now(timezone.utc),
        partial=True,
        status="partial",
        error=error[:MAX_ERROR_LEN],
        fallback=True,
    )


def _items_from_sources(items: list[SourceItem]) -> list[DigestItem]:
    return [
        DigestItem(
            title=item.title,
            url=item.url,
            source=item.source_id,
            published_at=item.published_at,
            zh=item.zh,
            summary=item.summary,
            event_id=item.event_id,
        )
        for item in items
    ]
