# MCP 工具契约

Wire 暴露四个只读资讯工具，任何支持 MCP 的客户端（Claude Desktop、Cursor、Council Agent）都可以直接调用。

- [启动方式](#启动方式)
- [通用返回结构](#通用返回结构)
- [wire_get_digest](#wire_get_digest)
- [wire_search_events](#wire_search_events)
- [wire_get_timeline](#wire_get_timeline)
- [wire_list_sources](#wire_list_sources)
- [错误约定](#错误约定)
- [stdio 协议纯净性](#stdio-协议纯净性)

## 启动方式

```bash
qfw mcp stdio              # 由 MCP 客户端拉起的标准方式
qfw mcp http --port 8791   # 常驻 http 传输，默认仅 127.0.0.1
```

stdio 模式下 **stdout 只输出 MCP 协议报文**，所有日志走 stderr。任何 `print()` 到 stdout 都会破坏协议流，实现时必须把日志 handler 全部挂在 stderr。

客户端配置示例（stdio）：

```json
{
  "mcpServers": {
    "quota-fuse-wire": {
      "command": "qfw",
      "args": ["mcp", "stdio"]
    }
  }
}
```

## 通用返回结构

工具返回 JSON 文本内容（`content[0].type == "text"`），解析后统一是 `WireEnvelope` 信封，至少包含：

| 字段 | 说明 |
|---|---|
| `domain` | `news` / `policy` / `industry` |
| `topic` | 赛道 id |
| `event_id` | 事件 id，非事件类工具为 `null` |
| `data_as_of` | 数据对应日期 `YYYY-MM-DD` |
| `payload` | 工具特有内容 |
| `source` | 固定 `wire` |
| `source_detail` | 原始信源 id 列表（逗号分隔或数组） |
| `fetched_at` | 采集时间 ISO8601 |
| `freshness` | `realtime` / `cached` / `archive` |
| `confidence` | `high` / `medium` / `low` |
| `source_status` | `ok` / `degraded` / `partial` |

## wire_get_digest

取某赛道某日的要点。

```json
{ "topic": "semiconductor", "date": "2026-10-22" }
```

- `date` 省略时取该赛道最新可用日期。
- `topic` 必须是 `config/topics.yaml` 中存在的 id 或其 `legacy_key`。
- 命中归档时 `freshness = archive`；当日内存缓存命中为 `cached`；实时算出的为 `realtime`。
- `payload` 为 `TopicDigest`：`{topic, date, summary, key_points[], items[]}`。

## wire_search_events

按关键词在时间窗口内检索事件的多源报道。

```json
{ "keyword": "光刻机", "window": "7d" }
```

- `window` 支持 `Nd`（天数）/`Nh`（小时）；缺省 `7d`。
- 可选 `topic` 用于缩小范围。
- `payload` 为 `{"query": ..., "events": [{event_id, title, first_seen, last_seen, source_count, sources, items}]}`。
- 关键词匹配标题、摘要、实体名，大小写不敏感。

## wire_get_timeline

取单个事件的时间线。

```json
{ "event_id": "evt_20261022_1a2b3c" }
```

- `payload` 为 `{"event": {...}, "timeline": [{published_at, source, title, url, zh}]}`，按时间升序。
- 事件不存在时返回 `isError: true` 并给出可读原因。
- `freshness = archive`。

## wire_list_sources

列出信源及其质量评分，供 Agent 判断可信度。

```json
{ "topic": "semiconductor" }   // 可选，省略则全量
```

- `payload` 为 `{"sources": [{id, name, topic, type, weight, score, accuracy, timeliness, duplication, status}]}`。
- `score` 为 0–1 的综合分；`status` 为 `ok` / `degraded` / `unknown`。

## 错误约定

| 情况 | 表现 |
|---|---|
| 参数校验失败 | `isError: true`，消息说明合法取值（如可用 topic 列表） |
| 无该日数据 | 不报错，`payload` 为空集合，`freshness = archive` |
| 数据库未初始化 | `isError: true`，提示先执行 `qfw run` |
| 内部异常 | `isError: true`，消息脱敏，不暴露绝对路径与密钥 |

## stdio 协议纯净性

- 不得在工具实现里使用 `print`；统一用 `logging` 且 handler 指向 stderr。
- 第三方库的启动横幅必须被抑制（`logging` 级别调到 WARNING）。
- 集成测试需要真实跑一次 stdio 握手：`initialize` → `tools/list` → `tools/call`，断言 stdout 每行都是合法 JSON-RPC。
