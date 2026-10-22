# 功能规格：采集与分析管道（M2）

版本：M2（2026-10-22）。本文件描述当前生效的行为，M1 的契约保持兼容。

## 1. 采集

- 输入：`config/sources.yaml` 中 `enabled: true` 且被选中赛道引用的信源；
- 并发：`--max-workers` > `QF_WIRE_FETCH_CONCURRENCY` > 默认 24，范围 1..64；
- 单源：`timeout_sec` 默认 15s，`retries` 默认 2；重试退避 0.2s、0.4s、… 上限 1.0s；
- 输出：`FetchResult`，`status ∈ {ok, degraded, unavailable}`，附 `attempts`、`elapsed_ms`、`error`；
- 隔离：任一源失败不抛出到编排层，其余源继续；全部失败时整轮 `unavailable`。

## 2. 事件聚类

- 输入：每个赛道清洗、去重后的 `SourceItem` 列表；
- 分组依据：规范 URL 或标题指纹相同；或 7 天窗口内标题 bigram 余弦 ≥0.56；或 SimHash ≥0.86 且余弦 ≥0.30；
- 门控：双方都识别出机构且无交集时不合并；
- 输出：`Event(event_id, topic, title, items, sources, source_count, confidence, first_seen, last_seen)`；
- `event_id` 由赛道 + 标题指纹 / 规范 URL 稳定哈希，重建不变；
- 时间线：同一事件的报道按 `published_at` 升序；缺失时间的条目排在末尾。

## 3. 信源评分

- 每轮根据事件统计累加计数，写入 `source_scores`；
- 分项与权重见 `docs/decisions/0003-source-scoring.md`；
- 无样本时三项与综合分均为 0.5；
- 综合分 <0.45 且要点仅有低分来源支撑时降级置信度。

## 4. 提炼

- `digest.yaml` 的 `default` 与赛道条目合并，赛道可覆盖 `prompt_file` / `model` / `output_schema`；
- `TopicDigest`：摘要 + 要点 + 条目；`BriefDigest`：摘要 + 要点，条目由本地条目补齐；
- 无可用条目时 `status=skipped`；模型失败时 `status=partial` 且 `fallback=true`，不丢弃采集数据；
- provider：`claude-cli`（本机已登录）或 `api`（OpenAI 兼容，key 从环境变量读取）。

## 5. CLI

| 命令 | 输出 | 退出码 |
| --- | --- | --- |
| `qfw run [--topic] [--sources-only] [--max-workers N]` | 运行摘要 | 0 / 2 / 3 / 4 / 8 |
| `qfw event list [--topic] [--date]` | 事件列表 | 0 / 2 / 3 |
| `qfw event show <event_id>` | 事件详情 + 时间线 | 0 / 2 / 6 |
| `qfw event timeline <event_id>` | 时间线（支持 `--output csv`） | 0 / 2 / 6 |
| `qfw history [--topic] [--days]` | 每日条目 / 多源事件 / 事件增量 | 0 / 2 |

`--output` 全局支持 `json|table|csv`；6 表示对象不存在。

## 6. 看板与只读 API

- `qfw serve` 默认 `127.0.0.1:8790`；
- `data.js` 的每个赛道包含 `summary`、`key_points`、`items`；条目带 `event_id`、`source_count`、`confidence`；
- 顶层 `sourceStatus`、`sourceNotice`、`sourceScores` 分别驱动信源状态表、不可用提示与评分徽标；
- 同一 `event_id` 的条目在看板折叠为一张卡片，显示“多源 N”并可展开时间线；
- 只读 API：`/api/events`、`/api/event?id=`、`/api/sources`、`/api/history`、`/api/digest`、`/api/health`。

## 7. 兼容性

- `WireEnvelope` 顶层 12 字段与含义不变，M2 仅扩展 `payload` 内容；
- `topics.yaml` / `sources.yaml` 的 M1 字段不变；`digest.yaml` 新增赛道级 `model`，默认值保持原行为；
- SQLite 通过 `schema_migrations` 增量迁移，旧库可直接打开。
