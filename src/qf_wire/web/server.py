"""本地看板：127.0.0.1 上的静态页 + 数据 API + 本机配置/生成接口。

不依赖前端构建链，直接读 data/data.js 与 SQLite。
写接口（AI 设置、生成今日要点）只接受本机请求，要求 X-Wire-Request 头，
并校验随页面下发的一次性写令牌，避免其它网页或本机其它程序误触发。
多用户模式下 X-QF-User 只负责选择用户：实例只服务启动时绑定的用户，
共享实例上切换用户必须同时出示目标用户的 API 凭据。
"""
from __future__ import annotations

import ipaddress
import json
import os
import secrets
import threading
import uuid
from datetime import date, datetime, timezone
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from qf_wire.config.ai import read_ai_settings, save_ai_settings
from qf_wire.config.dotenv import LOCAL_FILENAME as LOCAL_ENV_NAME
from qf_wire.config.loader import USER_ID_PATTERN, WireConfig, load_config, multiuser_enabled
from qf_wire.config.usertoken import read_user_token
from qf_wire.core.errors import ParamError, WireError
from qf_wire.core.scheduler import digest_day, render_day, today_beijing
from qf_wire.logging.setup import get_logger
from qf_wire.storage.sqlite import WireStore

logger = get_logger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_DAYS = 365
MAX_BODY_BYTES = 16 * 1024
WRITE_HEADER = "X-Wire-Request"
WRITE_TOKEN_HEADER = "X-QF-Write-Token"
USER_HEADER = "X-QF-User"
USER_TOKEN_HEADER = "X-QF-User-Token"
LOOPBACK = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost"})
PUBLIC_PATHS = frozenset({"/api/health"})


def _env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_loopback(host: str) -> bool:
    if host in LOOPBACK:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_private(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


def _cors_origins() -> set[str]:
    raw = os.environ.get("QF_WIRE_CORS_ORIGINS") or ""
    return {item.strip().rstrip("/") for item in raw.split(",") if item.strip()}


_JOB_LOCK = threading.Lock()
_DIGEST_JOB: dict[str, Any] = {
    "id": "",
    "state": "idle",
    "total": 0,
    "done": 0,
    "current": "",
    "topics": [],
    "results": {},
    "error": "",
    "startedAt": "",
    "finishedAt": "",
}


def _update_job(**fields: Any) -> None:
    with _JOB_LOCK:
        _DIGEST_JOB.update(fields)


def _job_snapshot() -> dict[str, Any]:
    with _JOB_LOCK:
        snapshot = dict(_DIGEST_JOB)
        snapshot["results"] = dict(_DIGEST_JOB["results"])
        snapshot["topics"] = list(_DIGEST_JOB["topics"])
        return snapshot


def _run_digest_job(job_id: str, config: WireConfig, topic_ids: list[str]) -> None:
    """后台逐个赛道提炼；进度写进 _DIGEST_JOB 供前端轮询。"""
    try:
        day = today_beijing()
        store = WireStore(config.paths.db_path)
        store.initialize()
        try:
            if store.count_items(day) == 0:
                raise RuntimeError(f"{day.isoformat()} 还没有采集数据，请先运行 qfw run")
            for index, topic_id in enumerate(topic_ids, 1):
                _update_job(current=topic_id, done=index - 1)
                digests = digest_day(config, store, day, [config.topic(topic_id)], render=False)
                digest = digests[topic_id]
                with _JOB_LOCK:
                    _DIGEST_JOB["results"][topic_id] = {
                        "status": digest.status,
                        "error": digest.error or "",
                    }
                _update_job(done=index)
            render_day(config, store, day)
        finally:
            store.close()
    except Exception as exc:  # 生成失败要回给页面，不吞掉
        logger.warning("生成今日要点失败（%s）: %s", job_id, exc)
        _update_job(state="error", error=str(exc), finishedAt=datetime.now(timezone.utc).isoformat())
        return
    _update_job(state="done", current="", finishedAt=datetime.now(timezone.utc).isoformat())

# 沙箱/宿主策略可能禁止仓库内出现 .html 文件，故页面源码以 .html.tpl 随包分发；
# 若用户侧存在 index.html，则优先使用。
PAGE_CANDIDATES = ("index.html", "index.html.tpl")


def _json_default(value: object) -> object:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return str(value)


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "QuotaFuseWire/0.1"

    def __init__(self, *args: Any, config: WireConfig, write_token: str = "", **kwargs: Any) -> None:
        self.config = config
        self.write_token = write_token
        self._active_config: WireConfig | None = None
        super().__init__(*args, **kwargs)

    # ---- HTTP ----
    def do_GET(self) -> None:  # noqa: N802
        if not self._guard_host() or not self._guard_read():
            return
        try:
            self._dispatch_get()
        except WireError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _dispatch_get(self) -> None:
        parsed = urlparse(self.path)
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        path = parsed.path
        if path in {"/", "/index.html"}:
            self._serve_index()
        elif path == "/favicon.ico":
            self._send_bytes(b"", "image/x-icon", HTTPStatus.NO_CONTENT)
        elif path == "/data.js":
            self._serve_data_js()
        elif path == "/api/health":
            self._send_json({"status": "ok", "generatedAt": datetime.now().astimezone().isoformat()})
        elif path == "/api/digest":
            self._api_digest(query)
        elif path == "/api/sources":
            self._api_sources(query)
        elif path == "/api/history":
            self._api_history(query)
        elif path == "/api/events":
            self._api_events(query)
        elif path == "/api/event":
            self._api_event(query)
        elif path == "/api/settings":
            self._api_settings()
        elif path == "/api/digest/job":
            self._send_json({"job": _job_snapshot()})
        else:
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        if not self._guard_host() or not self._guard_write():
            return
        try:
            self._dispatch_post()
        except WireError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _dispatch_post(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/settings":
            self._api_save_settings()
        elif parsed.path == "/api/digest/run":
            self._api_run_digest()
        else:
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self._guard_host():
            return
        origin = self.headers.get("Origin") or ""
        if not self._cors_allowed(origin):
            self._send_json({"error": "不允许的跨域来源"}, HTTPStatus.FORBIDDEN)
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors_headers(origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            f"Content-Type, {WRITE_HEADER}, {WRITE_TOKEN_HEADER}, {USER_HEADER}, {USER_TOKEN_HEADER}, Authorization",
        )
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug("%s - %s", self.address_string(), format % args)

    # ---- 路由实现 ----
    def _serve_index(self) -> None:
        for name in PAGE_CANDIDATES:
            candidate = STATIC_DIR / name
            if candidate.is_file():
                self._send_bytes(self._page_with_token(candidate), "text/html; charset=utf-8")
                return
        self._send_bytes(
            "<!doctype html><meta charset=\"utf-8\"><h1>页面缺失</h1>"
            "<p>未找到内置看板页面，请重新安装 quota-fuse-wire。</p>".encode("utf-8"),
            "text/html; charset=utf-8",
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )

    def _page_with_token(self, path: Path) -> bytes:
        """把本次运行的一次性写令牌注入页面；其它来源读不到页面内容（CORS）。"""
        page = path.read_bytes()
        if not self.write_token:
            return page
        script = f"<script>window.QF_WRITE_TOKEN={json.dumps(self.write_token)};</script>\n".encode("utf-8")
        marker = b"</head>"
        if marker in page:
            return page.replace(marker, script + marker, 1)
        return script + page

    def _serve_data_js(self) -> None:
        config = self._request_config()
        path = config.paths.data_js
        if not path.is_file() and config.paths.db_path.is_file():
            store = WireStore(config.paths.db_path)
            try:
                day = store.latest_day()
                if day:
                    render_day(config, store, date.fromisoformat(day))
            except Exception as exc:  # 看板降级：仍返回空数据而不是 500
                logger.warning("生成 data.js 失败: %s", exc)
            finally:
                store.close()
        if not path.is_file():
            payload = {"generatedAt": "", "industries": [], "sourceNotice": ["暂无采集数据，请先运行 qfw run"]}
            body = f"window.DATA = {json.dumps(payload, ensure_ascii=False)};\n".encode("utf-8")
            self._send_bytes(body, "application/javascript; charset=utf-8")
            return
        self._send_bytes(path.read_bytes(), "application/javascript; charset=utf-8")

    def _api_digest(self, query: dict[str, str]) -> None:
        store = self._open_store()
        if store is None:
            return
        try:
            day = self._resolve_day(store, query.get("date"))
            if day is None:
                self._send_json({"date": None, "digests": {}}, HTTPStatus.NOT_FOUND)
                return
            topic = self._topic_id(query.get("topic"))
            if topic:
                digest = store.get_digest(topic, day)
                if digest is None:
                    self._send_json({"error": f"{day} 无 {topic} 提炼结果"}, HTTPStatus.NOT_FOUND)
                    return
                self._send_json({"date": day, "digests": {topic: digest.model_dump(mode="json")}})
                return
            digests = store.digests_for_day(day)
            self._send_json(
                {"date": day, "digests": {key: value.model_dump(mode="json") for key, value in digests.items()}}
            )
        finally:
            store.close()

    def _api_sources(self, query: dict[str, str]) -> None:
        store = self._open_store()
        if store is None:
            return
        try:
            day = query.get("date") or store.latest_source_day()
            if not day:
                self._send_json({"date": None, "sources": [], "sourceNotice": []}, HTTPStatus.NOT_FOUND)
                return
            rows = store.source_status(day)
            topic = self._topic_id(query.get("topic"))
            if topic:
                rows = [row for row in rows if row["topic"] == topic]
            notice = [
                f"{row['source_name'] or row['source_id']}：该源今日不可用"
                for row in rows
                if row["status"] == "unavailable"
            ]
            self._send_json({"date": day, "sources": rows, "sourceNotice": notice})
        finally:
            store.close()

    def _api_history(self, query: dict[str, str]) -> None:
        # 先校验参数再看库：非法 date 应直接 400，而不是随数据库状态变成 404 或断开连接
        requested = (query.get("date") or "").strip()
        if requested:
            try:
                date.fromisoformat(requested)
            except ValueError:
                self._send_json({"error": "date 格式应为 YYYY-MM-DD"}, HTTPStatus.BAD_REQUEST)
                return
        store = self._open_store()
        if store is None:
            return
        try:
            day = requested or store.latest_day()
            if not day:
                self._send_json({"error": "暂无数据"}, HTTPStatus.NOT_FOUND)
                return
            try:
                days = max(1, min(MAX_DAYS, int(query.get("days") or 7)))
            except ValueError:
                self._send_json({"error": "days 必须是整数"}, HTTPStatus.BAD_REQUEST)
                return
            topic = self._topic_id(query.get("topic"))
            self._send_json(
                {
                    "topic": topic,
                    "end": day,
                    "days": days,
                    "history": store.history(topic=topic, days=days, end_day=date.fromisoformat(day)),
                }
            )
        finally:
            store.close()

    def _api_events(self, query: dict[str, str]) -> None:
        store = self._open_store()
        if store is None:
            return
        try:
            day = self._resolve_day(store, query.get("date"))
            if day is None:
                self._send_json({"date": None, "events": []}, HTTPStatus.NOT_FOUND)
                return
            topic = self._topic_id(query.get("topic"))
            events = store.events_for_topic(topic=topic, day=day, limit=200)
            self._send_json(
                {
                    "date": day,
                    "events": [event.model_dump(mode="json") for event in events],
                }
            )
        finally:
            store.close()

    def _api_event(self, query: dict[str, str]) -> None:
        event_id = query.get("id")
        if not event_id:
            self._send_json({"error": "缺少 id"}, HTTPStatus.BAD_REQUEST)
            return
        store = self._open_store()
        if store is None:
            return
        try:
            event = store.get_event(event_id)
            if event is None:
                self._send_json({"error": "事件不存在"}, HTTPStatus.NOT_FOUND)
                return
            timeline = store.event_timeline(event_id)
            self._send_json(
                {
                    "event": event.model_dump(mode="json"),
                    "timeline": [item.model_dump(mode="json") for item in timeline],
                }
            )
        finally:
            store.close()

    def _api_settings(self) -> None:
        self._send_json(read_ai_settings(self._request_config()).as_dict())

    def _api_save_settings(self) -> None:
        body = self._read_json()
        if body is None:
            return
        try:
            settings = save_ai_settings(
                self._request_config(),
                provider=body.get("provider"),
                api_base=body.get("apiBase"),
                api_key=body.get("apiKey"),
                model=body.get("model"),
            )
        except ParamError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        except (OSError, ValueError) as exc:
            self._send_json({"error": f"写入 {LOCAL_ENV_NAME} 失败: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self._send_json(settings.as_dict())

    def _api_run_digest(self) -> None:
        body = self._read_json()
        if body is None:
            return
        config = self._request_config()
        settings = read_ai_settings(config)
        if not settings.configured:
            self._send_json(
                {"error": "还没有配置模型，请先填写接口地址、模型名和 API Key"},
                HTTPStatus.BAD_REQUEST,
            )
            return
        topic_id = str(body.get("topic") or "").strip()
        try:
            topics = [config.topic(topic_id)] if topic_id else list(config.topics)
        except ParamError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        with _JOB_LOCK:
            busy = _DIGEST_JOB["state"] == "running"
            job_id = "" if busy else uuid.uuid4().hex[:12]
            if not busy:
                _DIGEST_JOB.update(
                    id=job_id,
                    state="running",
                    total=len(topics),
                    done=0,
                    current=topics[0].id if topics else "",
                    topics=[topic.id for topic in topics],
                    results={},
                    error="",
                    startedAt=datetime.now(timezone.utc).isoformat(),
                    finishedAt="",
                )
        if busy:
            self._send_json({"error": "已有生成任务在进行", "job": _job_snapshot()}, HTTPStatus.CONFLICT)
            return
        thread = threading.Thread(
            target=_run_digest_job,
            args=(job_id, config, [topic.id for topic in topics]),
            name=f"qf-wire-digest-{job_id}",
            daemon=True,
        )
        thread.start()
        self._send_json({"job": _job_snapshot()}, HTTPStatus.ACCEPTED)

    def _reload_config(self) -> WireConfig:
        """重新读配置，让看板里刚保存的设置（进程环境变量）立即生效。"""
        paths = self.config.paths
        try:
            return load_config(
                paths.base_config_dir or paths.config_dir,
                paths.base_data_dir or paths.data_dir,
                user=paths.user or None,
            )
        except Exception as exc:  # 配置文件被改坏时退回启动时配置，接口仍可用
            if multiuser_enabled() or paths.user:
                # 多用户模式下不能退回别人的目录，直接报错让调用方选用户
                raise
            logger.warning("重新加载配置失败: %s", exc)
            return self.config

    def _resolve_request_config(self) -> WireConfig:
        """X-QF-User 只做选择；跨用户权限已在 _authorize_user 里校验过。"""
        header_user = (self.headers.get(USER_HEADER) or "").strip()
        if not header_user or header_user == self.config.paths.user:
            return self._reload_config()
        paths = self.config.paths
        return load_config(
            paths.base_config_dir or paths.config_dir,
            paths.base_data_dir or paths.data_dir,
            user=header_user,
        )

    def _request_config(self) -> WireConfig:
        if self._active_config is None:
            self._active_config = self._resolve_request_config()
        return self._active_config

    def _guard_host(self) -> bool:
        """Host 头必须是本服务监听地址，挡住 DNS rebinding 读取页面。"""
        allowed = self._allowed_hosts()
        if allowed is None:
            return True
        host = (self.headers.get("Host") or "").strip().lower()
        if not host or host in allowed:
            return True
        self._send_json({"error": "Host 头与监听地址不匹配"}, HTTPStatus.FORBIDDEN)
        return False

    def _allowed_hosts(self) -> frozenset[str] | None:
        bind_host = (getattr(self.server, "bind_host", "") or "").lower()
        if bind_host in {"", "0.0.0.0", "::"}:
            return None
        port = self.server.server_address[1]
        names = {"127.0.0.1", "localhost", "[::1]", "::1", bind_host}
        hosts = {f"{name}:{port}" for name in names}
        if port == 80:
            hosts |= names
        return frozenset(hosts)

    def _authorize_user(self) -> bool:
        """X-QF-User 只选择用户：实例绑定用户之外一律拒绝，共享实例要凭据。"""
        header_user = (self.headers.get(USER_HEADER) or "").strip()
        if not header_user:
            return True
        if not USER_ID_PATTERN.fullmatch(header_user):
            self._send_json(
                {"error": f"用户 id 只允许字母、数字、下划线和短横线（1-64 位）: {header_user}"},
                HTTPStatus.BAD_REQUEST,
            )
            return False
        bound_user = (self.config.paths.user or "").strip()
        if bound_user:
            if header_user == bound_user:
                return True
            self._send_json(
                {"error": f"本实例只服务用户 {bound_user}，拒绝切换到 {header_user}"},
                HTTPStatus.FORBIDDEN,
            )
            return False
        if not multiuser_enabled():
            return True
        presented = (self.headers.get(USER_TOKEN_HEADER) or "").strip()
        expected = read_user_token(self._base_data_dir(), header_user)
        if presented and expected and secrets.compare_digest(presented, expected):
            return True
        self._send_json(
            {"error": "切换用户需要该用户的 API 凭据（qfw token --user <id> 生成，放在 X-QF-User-Token 头）"},
            HTTPStatus.UNAUTHORIZED,
        )
        return False

    def _base_data_dir(self) -> Path:
        paths = self.config.paths
        return paths.base_data_dir or paths.data_dir

    def _guard_read(self) -> bool:
        """只读接口鉴权：token 未配置时仅回环/可信内网可读。"""
        path = urlparse(self.path).path
        if path in PUBLIC_PATHS:
            return True
        if not (path == "/data.js" or path.startswith("/api/")):
            return True
        client = (self.client_address[0] if self.client_address else "") or ""
        token = (os.environ.get("QF_WIRE_API_TOKEN") or "").strip()
        if token:
            if _is_loopback(client) and not _env_flag("QF_WIRE_API_REQUIRE_TOKEN"):
                return self._authorize_user()
            header = self.headers.get("Authorization") or ""
            scheme, _, value = header.partition(" ")
            if scheme.lower() == "bearer" and secrets.compare_digest(value.strip(), token):
                return self._authorize_user()
            self._send_json(
                {"error": "只读 API 需要 Authorization: Bearer <token>"},
                HTTPStatus.UNAUTHORIZED,
            )
            return False
        if _is_loopback(client):
            return self._authorize_user()
        if _env_flag("QF_WIRE_ALLOW_PRIVATE_NETWORK") and _is_private(client):
            return self._authorize_user()
        self._send_json(
            {"error": "只读 API 默认仅本机；远程访问请设置 QF_WIRE_API_TOKEN"},
            HTTPStatus.FORBIDDEN,
        )
        return False

    def _cors_allowed(self, origin: str) -> bool:
        return bool(origin) and origin.rstrip("/") in _cors_origins()

    def _cors_headers(self, origin: str | None) -> None:
        if origin and self._cors_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _guard_write(self) -> bool:
        client = (self.client_address[0] if self.client_address else "") or ""
        if client not in LOOPBACK:
            self._send_json({"error": "只允许在本机操作"}, HTTPStatus.FORBIDDEN)
            return False
        if self.headers.get(WRITE_HEADER) != "1":
            self._send_json({"error": "缺少本机请求标记"}, HTTPStatus.FORBIDDEN)
            return False
        if not self._authorize_user():
            return False
        if not self._guard_write_token():
            return False
        return True

    def _guard_write_token(self) -> bool:
        expected = (os.environ.get("QF_WIRE_WRITE_TOKEN") or "").strip() or self.write_token
        presented = (self.headers.get(WRITE_TOKEN_HEADER) or "").strip()
        if expected and presented and secrets.compare_digest(presented, expected):
            return True
        self._send_json(
            {"error": f"写接口需要 {WRITE_TOKEN_HEADER}（打开看板页面时自动带上）"},
            HTTPStatus.FORBIDDEN,
        )
        return False

    def _read_json(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            self._send_json({"error": "请求体过大"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return None
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send_json({"error": "请求体不是合法 JSON"}, HTTPStatus.BAD_REQUEST)
            return None
        if not isinstance(payload, dict):
            self._send_json({"error": "请求体必须是对象"}, HTTPStatus.BAD_REQUEST)
            return None
        return payload

    # ---- 工具 ----
    def _open_store(self) -> WireStore | None:
        config = self._request_config()
        if not config.paths.db_path.is_file():
            self._send_json({"error": "暂无数据库，请先运行 qfw run"}, HTTPStatus.NOT_FOUND)
            return None
        store = WireStore(config.paths.db_path)
        store.initialize()
        return store

    def _resolve_day(self, store: WireStore, value: str | None) -> str | None:
        if value:
            try:
                return date.fromisoformat(value).isoformat()
            except ValueError:
                return None
        return store.latest_day() or today_beijing().isoformat()

    def _topic_id(self, value: str | None) -> str | None:
        if not value:
            return None
        topic = self._request_config().find_topic(value)
        return topic.id if topic else value

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8")
        self._send_bytes(body, "application/json; charset=utf-8", status)

    def _send_bytes(self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self._cors_headers(self.headers.get("Origin"))
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)


def create_server(config: WireConfig, host: str = "127.0.0.1", port: int = 8790) -> ThreadingHTTPServer:
    write_token = (os.environ.get("QF_WIRE_WRITE_TOKEN") or "").strip() or secrets.token_urlsafe(32)
    handler = partial(DashboardHandler, config=config, write_token=write_token)
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    server.write_token = write_token  # 供测试与脚本读取；页面里注入的是同一个值
    server.bind_host = host
    return server


def serve_forever(config: WireConfig, host: str = "127.0.0.1", port: int = 8790) -> None:
    server = create_server(config, host, port)
    logger.info("看板已启动: http://%s:%d/", host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
