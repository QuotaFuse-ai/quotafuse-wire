"""本地看板：127.0.0.1 上的静态页 + 数据 API + 本机配置/生成接口。

不依赖前端构建链，直接读 data/data.js 与 SQLite。
写接口（AI 设置、生成今日要点）只接受本机请求，且要求前端带 X-Wire-Request 头，
避免其它网页用表单跨站触发。
"""
from __future__ import annotations

import json
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
from qf_wire.config.loader import WireConfig, load_config
from qf_wire.core.errors import ParamError
from qf_wire.core.scheduler import digest_day, render_day, today_beijing
from qf_wire.logging.setup import get_logger
from qf_wire.storage.sqlite import WireStore

logger = get_logger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_DAYS = 365
MAX_BODY_BYTES = 16 * 1024
WRITE_HEADER = "X-Wire-Request"
LOOPBACK = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost"})

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


def _run_digest_job(job_id: str, config_dir: Path, data_dir: Path, topic_ids: list[str]) -> None:
    """后台逐个赛道提炼；进度写进 _DIGEST_JOB 供前端轮询。"""
    try:
        config = load_config(config_dir, data_dir)
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

    def __init__(self, *args: Any, config: WireConfig, **kwargs: Any) -> None:
        self.config = config
        super().__init__(*args, **kwargs)

    # ---- HTTP ----
    def do_GET(self) -> None:  # noqa: N802
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
        parsed = urlparse(self.path)
        if not self._guard_write():
            return
        if parsed.path == "/api/settings":
            self._api_save_settings()
        elif parsed.path == "/api/digest/run":
            self._api_run_digest()
        else:
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug("%s - %s", self.address_string(), format % args)

    # ---- 路由实现 ----
    def _serve_index(self) -> None:
        for name in PAGE_CANDIDATES:
            candidate = STATIC_DIR / name
            if candidate.is_file():
                self._send_file(candidate, "text/html; charset=utf-8")
                return
        self._send_bytes(
            "<!doctype html><meta charset=\"utf-8\"><h1>页面缺失</h1>"
            "<p>未找到内置看板页面，请重新安装 quota-fuse-wire。</p>".encode("utf-8"),
            "text/html; charset=utf-8",
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )

    def _serve_data_js(self) -> None:
        path = self.config.paths.data_js
        if not path.is_file() and self.config.paths.db_path.is_file():
            store = WireStore(self.config.paths.db_path)
            try:
                day = store.latest_day()
                if day:
                    render_day(self.config, store, date.fromisoformat(day))
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
        store = self._open_store()
        if store is None:
            return
        try:
            day = query.get("date") or store.latest_day()
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
        self._send_json(read_ai_settings(self._reload_config()).as_dict())

    def _api_save_settings(self) -> None:
        body = self._read_json()
        if body is None:
            return
        try:
            settings = save_ai_settings(
                self._reload_config(),
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
        config = self._reload_config()
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
            args=(job_id, config.paths.config_dir, config.paths.data_dir, [topic.id for topic in topics]),
            name=f"qf-wire-digest-{job_id}",
            daemon=True,
        )
        thread.start()
        self._send_json({"job": _job_snapshot()}, HTTPStatus.ACCEPTED)

    def _reload_config(self) -> WireConfig:
        """重新读配置，让看板里刚保存的设置（进程环境变量）立即生效。"""
        try:
            return load_config(self.config.paths.config_dir, self.config.paths.data_dir)
        except Exception as exc:  # 配置文件被改坏时退回启动时配置，接口仍可用
            logger.warning("重新加载配置失败: %s", exc)
            return self.config

    def _guard_write(self) -> bool:
        client = (self.client_address[0] if self.client_address else "") or ""
        if client not in LOOPBACK:
            self._send_json({"error": "只允许在本机操作"}, HTTPStatus.FORBIDDEN)
            return False
        if self.headers.get(WRITE_HEADER) != "1":
            self._send_json({"error": "缺少本机请求标记"}, HTTPStatus.FORBIDDEN)
            return False
        return True

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
        if not self.config.paths.db_path.is_file():
            self._send_json({"error": "暂无数据库，请先运行 qfw run"}, HTTPStatus.NOT_FOUND)
            return None
        store = WireStore(self.config.paths.db_path)
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
        topic = self.config.find_topic(value)
        return topic.id if topic else value

    def _send_file(self, path: Path, content_type: str) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        self._send_bytes(body, content_type)

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
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)


def create_server(config: WireConfig, host: str = "127.0.0.1", port: int = 8790) -> ThreadingHTTPServer:
    handler = partial(DashboardHandler, config=config)
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def serve_forever(config: WireConfig, host: str = "127.0.0.1", port: int = 8790) -> None:
    server = create_server(config, host, port)
    logger.info("看板已启动: http://%s:%d/", host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
