"""RSS 2.0 / Atom 适配器，仅依赖标准库。"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from qf_wire.core.cleaner import parse_datetime
from qf_wire.core.models import SourceItem
from qf_wire.sources.base import SourceAdapter, SourceError

MAX_ITEMS = 80
_XML_DECL_RE = re.compile(r"^\s*<\?xml[^>]*\?>", re.IGNORECASE)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(element: ET.Element, *names: str) -> str:
    wanted = {name.lower() for name in names}
    for child in element:
        if _local(child.tag) in wanted:
            text = "".join(child.itertext()).strip()
            if text:
                return text
    return ""


def _link(element: ET.Element) -> str:
    for child in element:
        if _local(child.tag) != "link":
            continue
        href = child.attrib.get("href")
        rel = child.attrib.get("rel", "alternate")
        if href and rel in ("alternate", ""):
            return href.strip()
        text = "".join(child.itertext()).strip()
        if text:
            return text
    return _child_text(element, "guid", "id")


class RSSAdapter(SourceAdapter):
    source_type = "rss"

    def fetch(self, timeout_sec: float | None = None) -> list[SourceItem]:
        raw = self._get(
            timeout_sec=timeout_sec,
            accept="application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        )
        text = self._decode(raw).strip()
        if not text:
            raise SourceError("空响应")

        root = self._parse(raw, text)
        items: list[SourceItem] = []
        for element in root.iter():
            if _local(element.tag) not in ("item", "entry"):
                continue
            title = _child_text(element, "title")
            link = _link(element)
            if not title or not link:
                continue
            published = parse_datetime(
                _child_text(element, "pubdate", "published", "updated", "date", "created")
            )
            summary = _child_text(
                element, "description", "summary", "encoded", "content", "subtitle"
            )
            items.append(
                SourceItem(
                    title=title,
                    url=link,
                    source_id=self.source.id,
                    topic=self.source.topic or "",
                    summary=summary,
                    published_at=published,
                    sources=[self.source.id],
                )
            )
            if len(items) >= MAX_ITEMS:
                break

        if not items:
            raise SourceError("解析成功但没有可用条目")
        return items

    def _parse(self, raw: bytes, text: str) -> ET.Element:
        head = text[:8192].upper()
        if "<!DOCTYPE" in head or "<!ENTITY" in head:
            raise SourceError("拒绝含 DTD/实体声明的 XML")
        try:
            return ET.fromstring(raw)
        except ET.ParseError:
            pass
        sanitized = _XML_DECL_RE.sub("", text).strip()
        sanitized = sanitized.replace("\x00", "")
        try:
            return ET.fromstring(sanitized)
        except ET.ParseError as exc:
            raise SourceError(f"XML 解析失败: {exc}") from exc


def make_item(source_id: str, topic: str, title: str, url: str, **kwargs: object) -> SourceItem:
    payload = {
        "title": title,
        "url": url,
        "source_id": source_id,
        "topic": topic,
        "published_at": kwargs.get("published_at") or datetime.now(timezone.utc),
        "sources": [source_id],
    }
    payload.update({key: value for key, value in kwargs.items() if key != "published_at"})
    return SourceItem(**payload)  # type: ignore[arg-type]
