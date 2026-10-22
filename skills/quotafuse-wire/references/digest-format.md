# WireEnvelope 返回格式

四个 MCP 工具与 `WireProvider` 的四个方法共用同一个信封结构，字段定义在 `src/qf_wire/core/models.py` 的 `WireEnvelope`，与本文件、`docs/PROVIDER_INTEGRATION.md` 的映射表保持一致。信封之外的任何字段都会被直接拒绝（`extra="forbid"`）。

## 信封字段（11 个）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `domain` | 枚举 | 是 | `news` / `policy` / `industry`；资讯类工具固定 `news` |
| `topic` | 字符串 | 是 | 赛道 slug；跨赛道结果允许空串 `""` |
| `event_id` | 字符串或 `null` | 否 | 事件维度才有；非事件工具为 `null` |
| `data_as_of` | 日期 `YYYY-MM-DD` | 是 | 数据截止日期，用于新鲜度判断 |
| `payload` | 对象 | 否 | 工具特有内容，见下文；无数据时为 `{}` |
| `source` | 字符串 | 否 | 固定 `wire` |
| `source_detail` | 字符串 | 否 | 原始信源 id，逗号分隔，用于溯源 |
| `fetched_at` | ISO8601 时间 | 是 | 采集/落库时间，**必须带时区**，naive 时间会被拒绝 |
| `freshness` | 枚举 | 否 | `realtime` / `cached` / `archive`，默认 `realtime`；本地归档固定 `archive` |
| `confidence` | 枚举 | 否 | `high` / `medium` / `low`，默认 `medium` |
| `source_status` | 枚举 | 否 | `ok` / `degraded` / `partial`，默认 `ok` |

## 枚举语义

- `freshness`：`archive` 表示历史归档（常态），`cached` 表示进程内缓存，`realtime` 表示实时计算。
- `confidence`：由命中信源数量与质量综合得出；单源或无关结果为 `low`，多源印证为 `high`。
- `source_status`：`degraded` 表示部分信源降级，`partial` 表示提炼缺失、只有采集结果。

## payload 结构

| 工具 | payload |
|---|---|
| `wire_get_digest` | `{topic, date, summary, key_points[], items[], generated_at, provider, model, partial, status, error, fallback}` |
| `wire_search_events` | `{query, events[{event_id, topic, title, first_seen, last_seen, source_count, sources[], confidence, items[]}]}` |
| `wire_get_timeline` | `{event, timeline[{published_at, source, title, url, zh}]}` |
| `wire_list_sources` | `{sources[{id, name, topic, type, weight, score, accuracy, timeliness, duplication, status}]}` |

无数据时 `payload` 为 `{}`（`wire_search_events` 例外，保留 `{"query": ..., "events": []}`），`freshness=archive`、`confidence=low`，不抛异常。

## 最小示例

```json
{
  "domain": "news",
  "topic": "semi",
  "event_id": null,
  "data_as_of": "2026-10-22",
  "payload": {
    "topic": "semi",
    "date": "2026-10-22",
    "summary": "两家信源确认扩产与设备订单。",
    "key_points": [
      {
        "text": "晶圆厂扩产带动设备订单",
        "sources": ["feed_a", "feed_b"],
        "confidence": "high",
        "event_id": "evt_20261022_1a2b3c"
      }
    ],
    "items": [
      {
        "title": "晶圆厂宣布扩产",
        "url": "https://example.com/news/a",
        "source": "feed_a",
        "published_at": "2026-10-22T06:00:00Z",
        "zh": "晶圆厂宣布扩产",
        "summary": "产能继续扩张",
        "event_id": "evt_20261022_1a2b3c"
      }
    ]
  },
  "source": "wire",
  "source_detail": "feed_a,feed_b",
  "fetched_at": "2026-10-22T07:10:00+08:00",
  "freshness": "archive",
  "confidence": "high",
  "source_status": "ok"
}
```

## 与 DataEnvelope 的对应

`to_data_envelope()` 把上面的信封压成 10 个键：`topic` / `event_id` 收进 `scope`，其余字段同名直传。`from_data_envelope()` 反向还原，缺失 `data_as_of` 或 `fetched_at` 会明确报错。
