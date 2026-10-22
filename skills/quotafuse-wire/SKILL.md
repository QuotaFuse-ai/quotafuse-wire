---
name: quotafuse-wire
description: 读取本地 QuotaFuse Wire 归档，按赛道给出每日资讯要点、事件多源报道、事件时间线与信源可信度；只读、本地、仅供信息参考。
---

# QuotaFuse Wire 资讯检索

用它是为了回答“某个赛道最近发生了什么、哪些信源在报道、可信度如何”，不是为了让模型编新闻。

## 能力边界

- 只读：四个工具都从本地归档取数，不触发采集，也不访问网络。
- 本地优先：数据来自本机 `QF_WIRE_DATA_DIR`（默认仓库下的 `data/`），敏感内容不出本机。
- 只提供信息：可以复述事实、标注信源与置信度，**不得给买卖建议、目标价、仓位或择时判断**。用户索要投资建议时，说明这里只提供资讯并建议其自行研判或咨询持牌专业人士。

## 何时使用

- 用户问某赛道“今天/某天有什么值得注意的消息” → 先取每日提炼。
- 用户给出关键词或事件线索，想确认“有几家在报、先后顺序如何” → 检索事件、取时间线。
- 用户质疑可信度或想知道“这条消息谁先发的” → 查信源评分与 `source_detail`。

## 前置条件

- 已安装 `qfw`（或可用 `python -m qf_wire`）。
- 本地已有归档：先执行过 `qfw run`；否则工具会返回“数据库尚未初始化”的参数错误。
- 二选一接入方式：
  - stdio：MCP 客户端配置 `qfw mcp stdio`（推荐，随用随起）。
  - http：执行 `qfw mcp http --port 8791`，客户端连 `http://127.0.0.1:8791/mcp`；默认只监听本机。

## 标准流程（SOP）

1. **读每日简报**
   调用 `wire_get_digest(topic, date?)`。`topic` 用赛道英文 slug（如 `semiconductor`），`date` 省略时取该赛道最新可用日期。
   先看 `payload.summary` 与 `payload.key_points`，判断当天有没有值得展开的事件。

2. **展开事件**
   有关键词时调用 `wire_search_events(keyword, window?, topic?)`，`window` 支持 `Nd` / `Nh`（默认 `7d`）。
   命中事件后调用 `wire_get_timeline(event_id)`，按发布时间升序还原“谁先报、谁跟进”。

3. **核对信源**
   调用 `wire_list_sources(topic?)`，结合 `score` 与 `status` 说明可信度；引用具体条目时同时给出 `source_detail` 中的信源 id。

回答时至少带上：`event_id`、`source_count`、`freshness`、`confidence`，让用户能自行复核。

## 解读返回

统一返回 `WireEnvelope` JSON 文本，字段与枚举见 `references/digest-format.md`。三个容易误读的字段：

- `freshness`：`archive` 表示取自历史归档（Wire 的常态），`cached` / `realtime` 表示更新鲜的数据。
- `confidence`：由信源数量与质量综合得出，`low` 时不要当作确定事实。
- `source_status`：`partial` / `degraded` 表示部分信源失败，结论覆盖度有限。

## 降级与错误

| 现象 | 含义 | 应对话术 |
|---|---|---|
| `payload` 为空且 `freshness=archive` | 该赛道/日期没有归档数据，或事件不存在 | 直接说没有找到记录，不要补写或推测 |
| `isError: true`，消息含“未知赛道” | `topic` 不在配置里 | 用消息中列出的合法赛道重试，或向用户确认 |
| `isError: true`，消息含“数据库尚未初始化” | 本地还没跑过采集 | 提示用户先执行 `qfw run`，不要伪造结果 |
| `isError: true`，消息为“查询失败：Wire 内部错误” | 服务端异常已脱敏 | 告知暂时无法查询，建议查看服务端日志 |

参数错误会以 `isError: true` 返回并列出合法取值；不要循环重试同一个错误参数。

## 参考

- 字段与最小示例：`references/digest-format.md`
- 一次完整的每日简报流程：`examples/read-daily-brief.md`
