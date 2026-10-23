"""安全 PoC 3：输入校验与解压边界。

复现：
1. Authorization 头含非 ASCII 字符时，secrets.compare_digest 抛 TypeError，连接被直接断开。
2. 同步抓取路径只限制压缩字节数，gzip 解压无上限（压缩炸弹）。
3. RSS/API 条目 URL 不做协议白名单，javascript: 链接可进入数据并写入前端 href。
4. 超大 window 数值带 d/h 后缀时抛 OverflowError，MCP 工具只捕获 ValueError。
5. DEBUG 日志会打印完整查询串（与部署文档的描述不一致）。

运行：python tests/security/poc_input_and_bomb.py
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from _harness import Dashboard, GzipBombServer, check, clean_env, finish, request

from qf_wire.core.models import Source
from qf_wire.mcp.tools import WireTools
from qf_wire.provider.wire_provider import parse_window
from qf_wire.sources.api import APIAdapter
from qf_wire.sources.base import MAX_BYTES
from qf_wire.sources.rss import RSSAdapter

RSS_WITH_JS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>poc</title>
<item><title>poc item</title><link>javascript:alert(document.domain)</link></item>
</channel></rss>
"""


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="qf-poc-input-") as raw_tmp:
        tmp = Path(raw_tmp)
        with clean_env(tmp / ".env.local"), Dashboard(tmp) as dash:
            import os

            os.environ["QF_WIRE_API_TOKEN"] = "poc-token-not-a-real-secret"
            os.environ["QF_WIRE_API_REQUIRE_TOKEN"] = "1"

            try:
                status, _, _ = request(
                    dash.base,
                    "/api/settings",
                    headers={"Authorization": "Bearer \u00ff"},
                )
            except Exception as exc:  # 服务端未返回响应即断开
                check(True, f"非 ASCII Authorization 使连接异常中断（{type(exc).__name__}）")
            else:
                check(status >= 500, f"非 ASCII Authorization 返回 {status}（应为 500/断开）")

            status, _, _ = request(
                dash.base,
                "/api/settings",
                headers={"Authorization": "Bearer poc-token-not-a-real-secret"},
            )
            check(status == 200, "对照：ASCII token 可正常通过鉴权")

            source = Source(id="poc_bomb", name="poc bomb", topic="semi", type="rss", url="http://127.0.0.1/")
            with GzipBombServer(decompressed_bytes=16 * 1024 * 1024) as bomb:
                adapter = RSSAdapter(
                    Source(id="poc_bomb", name="poc bomb", topic="semi", type="rss", url=bomb.url)
                )
                raw = adapter._get()
            check(
                len(raw) > MAX_BYTES,
                f"压缩响应仅限制压缩后大小；解压后 {len(raw)} 字节 > MAX_BYTES={MAX_BYTES}",
            )

            js_items = RSSAdapter(source).parse(RSS_WITH_JS)
            check(
                any(item.url.lower().startswith("javascript:") for item in js_items),
                "RSS 条目 javascript: 链接原样保留",
            )
            api_items = APIAdapter(source).parse(
                b'{"items":[{"title":"poc","url":"javascript:alert(1)"}]}'
            )
            check(
                api_items[0].url.lower().startswith("javascript:"),
                "API 条目 javascript: 链接经 urljoin 后原样保留",
            )

            try:
                parse_window("999999999999999999d")
            except OverflowError as exc:
                check(True, f"超大 window 后缀数值抛 OverflowError（MCP 未捕获）: {exc}")
            except ValueError:
                check(False, "超大 window 仅抛 ValueError（与预期不符）")

            tools = WireTools(config=dash.config)
            try:
                tools.wire_search_events("poc", window="999999999999999999d")
            except OverflowError:
                check(True, "MCP 工具 wire_search_events 直接抛出 OverflowError")
            except Exception as exc:
                check(False, f"MCP 工具返回了其他异常：{type(exc).__name__}")
            finally:
                tools.close()

            logger = logging.getLogger("qf_wire.web.server")
            logger.setLevel(logging.DEBUG)
            records: list[str] = []

            class Capture(logging.Handler):
                def emit(self, record: logging.LogRecord) -> None:
                    records.append(record.getMessage())

            handler = Capture()
            logger.addHandler(handler)
            try:
                request(dash.base, "/api/health?api_key=poc-query-canary")
            finally:
                logger.removeHandler(handler)
            check(
                any("poc-query-canary" in line for line in records),
                "DEBUG 日志记录完整查询串（api_key 金丝雀出现在日志中）",
            )

    finish("poc_input_and_bomb")


if __name__ == "__main__":
    main()
