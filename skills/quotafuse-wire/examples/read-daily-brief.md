# 示例：读取一份每日简报

场景：用户问“半导体最近有什么值得注意的消息”。一次完整的回答要经过 **读日报 → 展开事件 → 核对信源** 三步，CLI 与 MCP 两条路径任选其一，返回的数据同源。

示例数据：赛道 `semiconductor`，2026-10-22 归档两条资讯，聚合成一个双源事件 `evt_20261022_1a2b3c`。

## 前置条件

本地已有归档；没有就先生成一次：

```bash
qfw run --topic semiconductor
```

## 路径 A：CLI

### 1. 读日报

```bash
qfw --output json digest --topic semiconductor --date 2026-10-22
```

`--output` 是全局参数，要写在子命令前。输出按赛道分组，`semiconductor` 下就是一份 `TopicDigest`：

```json
{
  "date": "2026-10-22",
  "digests": {
    "semiconductor": {
      "topic": "semiconductor",
      "date": "2026-10-22",
      "summary": "两家信源确认芯片扩产与设备订单，产能与设备端同步走强。",
      "key_points": [
        {
          "text": "晶圆厂扩产带动设备商新增订单",
          "sources": ["feed_a", "feed_b"],
          "confidence": "high",
          "event_id": "evt_20261022_1a2b3c"
        }
      ],
      "items": [
        {
          "title": "设备商确认新增订单",
          "url": "https://example.com/news/b",
          "source": "feed_b",
          "published_at": "2026-10-22T23:22:03+08:00",
          "event_id": "evt_20261022_1a2b3c"
        },
        {
          "title": "晶圆厂宣布扩产",
          "url": "https://example.com/news/a",
          "source": "feed_a",
          "published_at": "2026-10-22T22:22:03+08:00",
          "event_id": "evt_20261022_1a2b3c"
        }
      ],
      "provider": "gateway",
      "model": "demo-model",
      "partial": false,
      "status": "ok",
      "error": null,
      "fallback": false
    }
  }
}
```

要点全指向同一个 `event_id`，说明它们来自一次多源聚合，可以继续展开。

### 2. 展开事件与时间线

```bash
qfw --output json event --topic semiconductor --date 2026-10-22
qfw --output json event show evt_20261022_1a2b3c
```

第一条列出当日事件；第二条给出事件详情与按时间升序的 `timeline`：

```json
{
  "event": {
    "event_id": "evt_20261022_1a2b3c",
    "topic": "semiconductor",
    "title": "晶圆厂扩产带动芯片设备订单",
    "sources": ["feed_a", "feed_b"],
    "source_count": 2,
    "confidence": "high",
    "first_seen": "2026-10-22T22:22:03+08:00",
    "last_seen": "2026-10-22T23:22:03+08:00"
  },
  "timeline": [
    {
      "published_at": "2026-10-22T22:22:03+08:00",
      "source_id": "feed_a",
      "title": "晶圆厂宣布扩产",
      "url": "https://example.com/news/a"
    },
    {
      "published_at": "2026-10-22T23:22:03+08:00",
      "source_id": "feed_b",
      "title": "设备商确认新增订单",
      "url": "https://example.com/news/b"
    }
  ]
}
```

`source_count` 为 2，`first_seen` 早于 `last_seen`，说明 `feed_a` 先发、`feed_b` 跟进。

### 3. 核对信源

```bash
qfw --output json sources list --topic semiconductor
```

上一步的 `source_id` 与这里列出的 `id` 一一对应，可据此判断报道方是否稳定、是否只有单一来源。

## 路径 B：MCP

### 启动

```bash
# stdio：由客户端拉起，推荐
qfw mcp stdio

# 或常驻本机 http
qfw mcp http --port 8791
# 客户端连接 http://127.0.0.1:8791/mcp
```

### 1. `wire_get_digest`：读日报

```json
{ "topic": "semiconductor", "date": "2026-10-22" }
```

返回 `WireEnvelope`，`payload` 即上面的 `TopicDigest`（省略 `items`）：

```json
{
  "domain": "news",
  "topic": "semiconductor",
  "event_id": null,
  "data_as_of": "2026-10-22",
  "payload": {
    "topic": "semiconductor",
    "date": "2026-10-22",
    "summary": "两家信源确认芯片扩产与设备订单，产能与设备端同步走强。",
    "key_points": [
      {
        "text": "晶圆厂扩产带动设备商新增订单",
        "sources": ["feed_a", "feed_b"],
        "confidence": "high",
        "event_id": "evt_20261022_1a2b3c"
      }
    ],
    "items": ["…"],
    "provider": "gateway",
    "model": "demo-model",
    "partial": false,
    "status": "ok",
    "error": null,
    "fallback": false
  },
  "source": "wire",
  "source_detail": "feed_a,feed_b",
  "fetched_at": "2026-10-23T00:25:29+08:00",
  "freshness": "archive",
  "confidence": "high",
  "source_status": "ok"
}
```

`date` 省略时取该赛道最新可用日期。`freshness=archive` 是常态：数据来自本地归档，不是实时行情。

### 2. `wire_search_events`：确认有几家在报

```json
{ "keyword": "芯片", "window": "7d", "topic": "semiconductor" }
```

```json
{
  "payload": {
    "query": "芯片",
    "events": [
      {
        "event_id": "evt_20261022_1a2b3c",
        "topic": "semiconductor",
        "title": "晶圆厂扩产带动芯片设备订单",
        "first_seen": "2026-10-22T22:22:03+08:00",
        "last_seen": "2026-10-22T23:22:03+08:00",
        "source_count": 2,
        "sources": ["feed_a", "feed_b"],
        "confidence": "high",
        "items": ["…"]
      }
    ]
  },
  "freshness": "archive",
  "confidence": "high",
  "source_status": "ok"
}
```

`window` 支持 `Nd` / `Nh`，默认 `7d`；关键词匹配标题、摘要与实体名，大小写不敏感。

### 3. `wire_get_timeline`：还原先后顺序

```json
{ "event_id": "evt_20261022_1a2b3c" }
```

```json
{
  "domain": "news",
  "topic": "semiconductor",
  "event_id": "evt_20261022_1a2b3c",
  "data_as_of": "2026-10-22",
  "payload": {
    "event": {
      "event_id": "evt_20261022_1a2b3c",
      "title": "晶圆厂扩产带动芯片设备订单",
      "source_count": 2,
      "sources": ["feed_a", "feed_b"],
      "confidence": "high"
    },
    "timeline": [
      {
        "published_at": "2026-10-22T22:22:03+08:00",
        "source": "feed_a",
        "title": "晶圆厂宣布扩产",
        "url": "https://example.com/news/a",
        "zh": "晶圆厂宣布扩产"
      },
      {
        "published_at": "2026-10-22T23:22:03+08:00",
        "source": "feed_b",
        "title": "设备商确认新增订单",
        "url": "https://example.com/news/b",
        "zh": "设备商确认新增订单"
      }
    ]
  },
  "source_detail": "feed_a,feed_b",
  "freshness": "archive",
  "confidence": "high",
  "source_status": "ok"
}
```

### 4. `wire_list_sources`：核对可信度

```json
{ "topic": "semiconductor" }
```

```json
{
  "payload": {
    "sources": [
      {
        "id": "feed_a",
        "name": "Feed A",
        "topic": "semiconductor",
        "type": "rss",
        "weight": 1.0,
        "score": 0.82,
        "accuracy": 0.86,
        "timeliness": 0.79,
        "duplication": 0.18,
        "status": "ok"
      }
    ]
  },
  "freshness": "archive",
  "confidence": "low",
  "source_status": "ok"
}
```

`score` 是 0–1 的综合分；`status` 为 `ok` / `degraded` / `unknown`。信源列表本身的 `confidence` 固定为 `low`，不要把它当成资讯结论的可信度。

## 如何引用

回答时把可复核的标识一并给出，读者才能自行验证：

| 字段 | 用法 |
| --- | --- |
| `event_id` | 标记“这是同一事件的多源报道”，便于追问时间线 |
| `source_count` | 说明有几家信源在报；`1` 表示单一来源，需谨慎 |
| `freshness` | `archive` 为历史归档，`cached` / `realtime` 更新鲜 |
| `confidence` | `high` / `medium` / `low`，`low` 时不要当作确定事实 |
| `source_detail` | 具体信源 id，如 `feed_a,feed_b` |
| `source_status` | `partial` / `degraded` 表示部分信源失败，覆盖度有限 |

示例答法：

> 2026-10-22 半导体有两条值得注意的消息，指向同一事件 `evt_20261022_1a2b3c`（晶圆厂扩产带动芯片设备订单）。`source_count=2`，`feed_a` 先发、`feed_b` 约一小时后跟进，`confidence=high`。数据取自本地归档（`freshness=archive`）。以上为资讯整理，不构成投资建议。

## 降级与边界

| 现象 | 说明 | 做法 |
| --- | --- | --- |
| `payload` 为空、`freshness=archive` | 该赛道/日期没有归档，或事件不存在 | 直接说没找到，不补写、不推测 |
| `partial=true` / `status=partial` | 模型不可用，只保留采集结果 | 只复述 `items` 里的事实，说明未生成要点 |
| `source_status=partial` / `degraded` | 部分信源失败 | 提示覆盖度有限 |
| `isError: true` + “未知赛道” | `topic` 不在配置中 | 用报错列出的合法赛道重试 |
| `isError: true` + “数据库尚未初始化” | 本地还没跑过采集 | 提示先执行 `qfw run` |

参数错误不要循环重试；`prompts/` 与技能都禁止输出买卖建议、目标价或仓位判断。
