"""通用 HTML 适配器：从页面锚点提取标题与链接。

站点级复杂结构在 M2 通过 `sources/adapters/` 定制；M1 保持无配置可用。
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from qf_wire.core.models import SourceItem
from qf_wire.sources.base import SourceAdapter, SourceError

MAX_ITEMS = 50
MIN_TITLE_LEN = 8
_SKIP_PREFIXES = ("javascript:", "mailto:", "tel:", "#")


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            text = re.sub(r"\s+", " ", "".join(self._text)).strip()
            self.anchors.append((self._href, text))
            self._href = None
            self._text = []


class HTMLAdapter(SourceAdapter):
    source_type = "html"

    def fetch(self, timeout_sec: float | None = None) -> list[SourceItem]:
        raw = self._get(timeout_sec=timeout_sec, accept="text/html, */*")
        text = self._decode(raw)
        if not text.strip():
            raise SourceError("空响应")

        parser = _AnchorParser()
        try:
            parser.feed(text)
            parser.close()
        except Exception as exc:  # noqa: BLE001 - html.parser 容错优先
            raise SourceError(f"HTML 解析失败: {exc}") from exc

        host = urlsplit(self.source.url).netloc
        seen: set[str] = set()
        items: list[SourceItem] = []
        for href, title in parser.anchors:
            if not href or href.lower().startswith(_SKIP_PREFIXES):
                continue
            absolute = urljoin(self.source.url, href)
            if not absolute.startswith(("http://", "https://")):
                continue
            if urlsplit(absolute).netloc != host and len(title) < 20:
                continue
            key = absolute.split("#", 1)[0]
            if key in seen or len(title) < MIN_TITLE_LEN:
                continue
            seen.add(key)
            items.append(
                SourceItem(
                    title=title,
                    url=absolute,
                    source_id=self.source.id,
                    topic=self.source.topic or "",
                    sources=[self.source.id],
                )
            )
            if len(items) >= MAX_ITEMS:
                break

        if not items:
            raise SourceError("未从页面提取到可用链接")
        return items
